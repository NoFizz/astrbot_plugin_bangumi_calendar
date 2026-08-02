# Copyright 2026 NoFizz
# SPDX-License-Identifier: AGPL-3.0-or-later

import asyncio
import datetime
import html as html_mod
import os
from collections.abc import AsyncGenerator

# 测试通过 plugin_main.httpx.AsyncClient 做 monkeypatch（httpx 是共享模块对象，
# service.py 中的属性查找同样生效），故在此保留导入并在 __all__ 中再导出。
import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

from .card import HTML_TMPL
from .models import WEEKDAY_NAMES, _CACHE_EXPIRE_DAYS, _COVERS_DIR
from .parser import (
    calculate_sleep_time,
    clean_umos,
    filter_items_by_limits,
    get_proxy,
    get_today_items,
    parse_push_time,
    safe_anime_id,
    select_tags,
    sort_items,
)
from .service import cleanup_old_covers, download_covers, fetch_calendar, fetch_subject_details

__all__ = ["httpx"]


# 用户可见文案表：_t() 按语言取模板并格式化，键为文案标识。
# 英文表缺失的键回退中文表；两表都缺失时原样返回键名（仅编程错误时出现）。
_REPLY_CN = {
    "today_failed": "获取新番信息失败，请稍后再试",
    "push_done": "已向 {count} 个目标推送今日新番",
    "status_title": "Bangumi新番日历插件",
    "status_push_time": "推送时间",
    "status_targets": "目标数",
    "status_proxy": "代理",
    "status_direct": "直连",
    "status_next_push": "距离下次推送: {hours}小时{minutes}分钟",
}

_REPLY_EN = {
    "today_failed": "Failed to fetch anime info, please try again later",
    "push_done": "Pushed today's anime to {count} target(s)",
    "status_title": "Bangumi Calendar Plugin",
    "status_push_time": "Push time",
    "status_targets": "Targets",
    "status_proxy": "Proxy",
    "status_direct": "Direct",
    "status_next_push": "Next push in {hours}h {minutes}m",
}


@register(
    "astrbot_plugin_bangumi_calendar",
    "NoFizz",
    "每日新番放送日历，定时推送卡片图至群聊",
    "1.1.0",
)
class BangumiCalendarPlugin(Star):
    """Bangumi 新番日历定时推送插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化插件：创建封面目录、启动时清理过期缓存、启动每日定时任务。

        Args:
            context: AstrBot 插件上下文。
            config: 插件配置（AstrBot 自动注入）。
        """
        super().__init__(context)
        self.config = config
        os.makedirs(_COVERS_DIR, exist_ok=True)
        self._cleanup_old_covers()
        # 依赖插件加载时宿主的事件循环已在运行：create_task 必须在运行中的循环内调用
        self._monitoring_task = asyncio.create_task(self._daily_task())
        logger.info(f"[Bangumi日历] 插件已加载, 推送时间: {self.config.get('push_time', '07:00')}")

    def _parse_push_time(self) -> tuple[int, int]:
        """解析推送时间，支持 H:MM 或 HH:MM 格式，无效回退到默认 07:00"""
        return parse_push_time(self.config.get("push_time", "07:00"))

    def _get_target_umos(self) -> list[str]:
        """获取推送目标UMO列表"""
        return clean_umos(self.config.get("umos", []))

    def _get_proxy(self) -> str | None:
        """获取代理地址：配置优先，环境变量回退，均无则直连"""
        return get_proxy(self.config.get("proxy", ""))

    def _sort_items(self, items: list[dict]) -> list[dict]:
        """根据配置的排序方式对番剧列表排序"""
        return sort_items(
            items,
            self.config.get("sort_by", "score"),
            self.config.get("sort_order", "desc"),
        )

    def _filter_items(self, items: list[dict]) -> list[dict]:
        """根据配置的评分/在看人数下限过滤番剧列表（开关关闭时下限不生效）"""
        return filter_items_by_limits(
            items,
            self.config.get("enable_score_min", False),
            self.config.get("score_min", 0),
            self.config.get("enable_doing_min", False),
            self.config.get("doing_min", 0),
        )

    def _get_cache_path(self, anime_id) -> str:
        """计算封面缓存文件路径。

        Args:
            anime_id: Bangumi 条目 ID（任意类型，安全化后拼接）。

        Returns:
            str: covers 目录下的 jpg 缓存路径。
        """
        return os.path.join(_COVERS_DIR, f"{safe_anime_id(anime_id)}.jpg")

    def _cleanup_old_covers(self):
        """删除超过30天未使用的缓存封面"""
        cleanup_old_covers(_COVERS_DIR, _CACHE_EXPIRE_DAYS)

    def _t(self, key: str, lang: str = "zh", **fmt: object) -> str:
        """按语言取回复文案模板并格式化，缺失时回退中文。

        Args:
            key: 文案标识（_REPLY_CN/_REPLY_EN 的键）。
            lang: 回复语言，zh 中文、en 英文，其他值回退中文。
            **fmt: 模板格式化参数（如 push_done 的 count）。

        Returns:
            str: 格式化后的回复文案。
        """
        template = _REPLY_CN.get(key)
        if lang == "en":
            template = _REPLY_EN.get(key, template)
        if template is None:
            return key
        return template.format(**fmt)

    @filter.command_group("新番")
    def bangumi_cn(self):
        """新番日历命令组（中文）"""
        pass

    @filter.command_group("bangumi")
    def bangumi_en(self):
        """Bangumi calendar command group (English)"""
        pass

    # ---- 中文指令 ----

    @bangumi_cn.command("今日")
    async def today_anime_cn(self, event: AstrMessageEvent):
        """查看今日更新的新番。

        Args:
            event: AstrBot 消息事件。

        Returns:
            AsyncGenerator: 渲染成功时产出图片消息，失败时产出失败提示文本。
        """
        async for result in self._handle_today(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_cn.command("推送")
    async def manual_push_cn(self, event: AstrMessageEvent):
        """手动推送今日新番到所有目标。

        Args:
            event: AstrBot 消息事件。

        Returns:
            AsyncGenerator: 产出包含推送目标数的文本结果。
        """
        async for result in self._handle_push(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_cn.command("状态")
    async def check_status_cn(self, event: AstrMessageEvent):
        """查看插件运行状态。

        Args:
            event: AstrBot 消息事件。

        Returns:
            AsyncGenerator: 产出状态信息文本。
        """
        async for result in self._handle_status(event):
            yield result

    # ---- 英文指令 ----

    @bangumi_en.command("today")
    async def today_anime_en(self, event: AstrMessageEvent):
        """View today's anime schedule.

        Args:
            event: AstrBot message event.

        Returns:
            AsyncGenerator: image result on success, failure text otherwise.
        """
        async for result in self._handle_today(event, lang="en"):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_en.command("push")
    async def manual_push_en(self, event: AstrMessageEvent):
        """Push today's anime to all targets.

        Args:
            event: AstrBot message event.

        Returns:
            AsyncGenerator: text result with the pushed target count.
        """
        async for result in self._handle_push(event, lang="en"):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_en.command("status")
    async def check_status_en(self, event: AstrMessageEvent):
        """Check plugin status.

        Args:
            event: AstrBot message event.

        Returns:
            AsyncGenerator: status text result.
        """
        async for result in self._handle_status(event, lang="en"):
            yield result

    async def _handle_today(self, event: AstrMessageEvent, lang: str = "zh") -> AsyncGenerator:
        """中英文「今日」命令共享核心：渲染今日新番图，失败时返回对应语言提示文案。

        Args:
            event: AstrBot 消息事件。
            lang: 回复语言，zh 中文、en 英文，默认中文。

        Returns:
            AsyncGenerator: 渲染成功时产出图片消息，失败时产出失败提示文本。
        """
        url = await self._render_image()
        if url:
            yield event.image_result(url)
        else:
            yield event.plain_result(self._t("today_failed", lang))

    async def _handle_push(self, event: AstrMessageEvent, lang: str = "zh") -> AsyncGenerator:
        """中英文「推送」命令共享核心：推送今日新番并报告成功数。

        Args:
            event: AstrBot 消息事件。
            lang: 回复语言，zh 中文、en 英文，默认中文。

        Returns:
            AsyncGenerator: 产出包含推送目标数的文本结果。
        """
        count = await self._push_to_all_groups()
        yield event.plain_result(self._t("push_done", lang, count=count))

    async def _handle_status(self, event: AstrMessageEvent, lang: str = "zh") -> AsyncGenerator:
        """中英文「状态」命令共享核心：产出对应语言的状态信息文本。

        Args:
            event: AstrBot 消息事件。
            lang: 回复语言，zh 中文、en 英文，默认中文。

        Returns:
            AsyncGenerator: 产出状态信息文本。
        """
        yield event.plain_result(self._build_status_text(lang=lang))

    def _build_status_text(self, lang: str = "zh") -> str:
        """构建状态信息文本，标签文案按语言切换。

        Args:
            lang: 回复语言，zh 中文、en 英文，默认中文。

        Returns:
            str: 多行状态文本，数值与格式不随语言变化。
        """
        sleep_time = self._calculate_sleep_time()
        hours = int(sleep_time / 3600)
        minutes = int((sleep_time % 3600) / 60)
        umos = self._get_target_umos()
        proxy = self._get_proxy()
        return (
            f"{self._t('status_title', lang)}\n"
            f"{self._t('status_push_time', lang)}: {self.config.get('push_time', '07:00')}\n"
            f"{self._t('status_targets', lang)}: {len(umos)}\n"
            f"{self._t('status_proxy', lang)}: {proxy or self._t('status_direct', lang)}\n"
            f"{self._t('status_next_push', lang, hours=hours, minutes=minutes)}"
        )

    async def terminate(self):
        """插件卸载时停止定时任务。

        Returns:
            None: 取消定时任务并等待其退出。
        """
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("[Bangumi日历] 插件已卸载")

    async def _fetch_calendar(self) -> list | None:
        """获取Bangumi每周放送日历（自动重试）"""
        return await fetch_calendar(self.config.get("max_retries", 3), self._get_proxy())

    def _get_today_items(self, calendar: list[dict]) -> list[dict]:
        """从日历数据中提取今日番剧"""
        today_weekday = datetime.datetime.now().isoweekday()
        return get_today_items(calendar, today_weekday)

    async def _download_covers(self, items: list[dict]) -> dict[str, str]:
        """下载封面图，支持本地缓存。返回 {原始URL: data URI} 映射"""
        return await download_covers(items, self._get_proxy())

    async def _fetch_subject_details(self, items: list[dict]) -> dict[int, tuple[int | None, list[dict]]]:
        """并发获取番剧的 Bangumi 条目详情（全站排名 + 官方标签），结果按实例内存缓存。

        同一天内「今日」命令/定时推送/手动推送会多次渲染，缓存避免对同一批
        番剧重复请求（排名/标签变化不敏感，插件生命周期内有效即可，无需落盘）。

        Args:
            items: 番剧条目列表。

        Returns:
            dict[int, tuple[int | None, list[dict]]]: subject_id → (全站排名, 原始标签列表)；
            未上榜或获取失败为 (None, [])。
        """
        # 懒初始化：测试用 object.__new__ 绕过 __init__，该属性可能尚未创建
        cache = getattr(self, "_subject_cache", None)
        if cache is None:
            cache = self._subject_cache = {}
        missing = {it.get("id") for it in items if isinstance(it.get("id"), int)} - set(cache)
        if missing:
            fresh = await fetch_subject_details([{"id": aid} for aid in missing], self._get_proxy())
            cache.update(fresh)
        return cache

    async def _render_image(self) -> str | None:
        """获取数据并渲染为图片"""
        calendar = await self._fetch_calendar()
        if not calendar:
            return None

        items = self._get_today_items(calendar)
        if not items:
            return None

        # 先并发获取条目详情（rank + tags）：rank 是排序依据，必须在此注入
        # items 的 rating.rank 之后再排序；获取失败项已降级为 (None, [])
        subject_map = await self._fetch_subject_details(items)
        for anime in items:
            rank, _ = subject_map.get(anime.get("id"), (None, []))
            rating = anime.get("rating")
            if not isinstance(rating, dict):
                rating = anime["rating"] = {}
            rating["rank"] = rank

        items = self._sort_items(items)
        items = self._filter_items(items)

        max_items = self.config.get("max_items", 0)
        if max_items > 0:
            items = items[:max_items]

        today = datetime.datetime.now()
        template_data = {
            "date": today.strftime("%Y-%m-%d"),
            "weekday": WEEKDAY_NAMES[today.isoweekday() - 1],
            "count": len(items),
            "items": [],
        }

        for i, anime in enumerate(items):
            images = anime.get("images") or {}
            cover_url = images.get("large") or images.get("common") or images.get("medium")

            rating = anime.get("rating") or {}
            collection = anime.get("collection") or {}

            template_data["items"].append(
                {
                    "name": html_mod.unescape(anime.get("name", "")),
                    "name_cn": html_mod.unescape(anime.get("name_cn", "")),
                    "index": i + 1,
                    "score": rating.get("score", "暂无"),
                    "rank": rating.get("rank"),
                    "doing": collection.get("doing", 0),
                    "air_date": anime.get("air_date", ""),
                    "cover": cover_url,
                }
            )

        # 下载封面图并转为 base64，避免 Playwright 加载外部图片超时
        try:
            cover_map = await self._download_covers(items)
            for item in template_data["items"]:
                if item["cover"] and item["cover"] in cover_map:
                    item["cover"] = cover_map[item["cover"]]
                else:
                    item["cover"] = ""

            # 标签经 select_tags 筛选后写入（rank 已在排序前注入）
            for item, anime in zip(template_data["items"], items):
                _, tags = subject_map.get(anime.get("id"), (None, []))
                item["tags"] = select_tags(tags)

            options = {
                "type": "png",
                "full_page": True,
                "timeout": 60000,
                "viewport_width": 760,
                "viewport_height": 800,
                "device_scale_factor_level": "high",
            }
            # html_render 依赖 AstrBot 的浏览器服务，可能瞬时失败；最多重试 3 次（间隔 1s）
            for attempt in range(3):
                try:
                    url = await self.html_render(HTML_TMPL, template_data, options=options)
                    if url:
                        logger.info("[Bangumi日历] 图片渲染成功")
                        return url
                    logger.warning(f"[Bangumi日历] html_render 返回空，渲染失败 (第{attempt + 1}次)")
                except Exception as e:
                    logger.warning(f"[Bangumi日历] html_render 渲染异常: {type(e).__name__}: {e} (第{attempt + 1}次)")
                if attempt < 2:
                    await asyncio.sleep(1)
            logger.error("[Bangumi日历] html_render 渲染重试 3 次后仍然失败")
            return None
        except Exception:
            logger.exception("[Bangumi日历] 图片渲染失败")
            return None

    async def _push_to_all_groups(self) -> int:
        """向所有目标推送今日新番图片，返回成功数"""
        url = await self._render_image()
        if not url:
            logger.error("[Bangumi日历] 获取新番数据失败，跳过推送")
            return 0

        umos = self._get_target_umos()
        if not umos:
            logger.warning("[Bangumi日历] 无有效推送目标")
            return 0

        msg = MessageChain()
        msg.url_image(url)

        success = 0
        for umo in umos:
            try:
                await self.context.send_message(umo, msg)
                logger.info(f"[Bangumi日历] 已推送至 {umo}")
                success += 1
                await asyncio.sleep(2)
            except Exception:
                logger.exception(f"[Bangumi日历] 推送至 {umo} 失败")
        return success

    def _calculate_sleep_time(self) -> float:
        """计算距离下次推送的秒数"""
        now = datetime.datetime.now()
        hour, minute = self._parse_push_time()
        return calculate_sleep_time(now, hour, minute)

    async def _daily_task(self):
        """定时任务主循环"""
        while True:
            try:
                sleep_time = self._calculate_sleep_time()
                next_push = datetime.datetime.now() + datetime.timedelta(seconds=sleep_time)
                logger.info(f"[Bangumi日历] 下次推送: {next_push.strftime('%Y-%m-%d %H:%M')}")
                await asyncio.sleep(sleep_time)
                umos = self._get_target_umos()
                if umos:
                    await self._push_to_all_groups()
                    # 推送完成后清理过期缓存（文件 IO 卸载到线程，避免阻塞事件循环）
                    await asyncio.to_thread(cleanup_old_covers, _COVERS_DIR, _CACHE_EXPIRE_DAYS)
                else:
                    logger.info("[Bangumi日历] 未配置推送目标，跳过")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[Bangumi日历] 定时任务异常")
                await asyncio.sleep(300)
