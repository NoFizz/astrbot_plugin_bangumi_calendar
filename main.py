import asyncio
import base64
import datetime
import html as html_mod
import os
import time

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

BANGUMI_CALENDAR_URL = "https://api.bgm.tv/calendar"
BANGUMI_HEADERS = {
    "User-Agent": "astrbot_plugin_bangumi_calendar/1.0.0 (https://github.com/AstrBotDevs/AstrBot)",
    "Accept": "application/json",
}
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_COVERS_DIR = os.path.join(os.path.dirname(__file__), "covers")
_CACHE_EXPIRE_DAYS = 30

HTML_TMPL = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=660, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: sans-serif; }
    html, body { background: #fff0f3; color: #222; width: 660px; min-width: 660px; max-width: 660px; margin: 0; padding: 0; min-height: 100%; overflow-x: hidden; }
    .header {
      text-align: center; padding: 28px 0 22px;
      background: #fb7299; width: 660px; position: relative;
      border-radius: 0;
    }
    .container {
      width: 660px; margin: 0; padding: 0;
      background: #fff0f3; overflow: hidden;
      border-radius: 0 0 16px 16px;
      box-shadow: 0 4px 12px rgba(251, 114, 153, 0.15);
    }
    .header h1 { font-size: 38px; font-weight: 700; color: #fff; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .header .date { font-size: 20px; color: #ffd6e0; }
    .header::after {
      content: ""; position: absolute; bottom: 0; left: 0; right: 0; height: 4px;
      background: linear-gradient(90deg, #fb7299, #ff99b1, #fb7299);
    }
    .body { display: block; width: 100%; padding: 24px 6px; }
    .anime-card {
      display: flex; background: #fff; border-radius: 12px;
      margin-bottom: 14px; overflow: hidden; border: 1px solid #e3e5e7;
      min-height: 210px; width: 100%; box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }
    .anime-card .cover { width: 150px; min-height: 210px; object-fit: cover; flex-shrink: 0; background: #e3e5e7; }
    .anime-card .info { padding: 20px; display: flex; flex-direction: column; justify-content: center; flex: 1; min-width: 0; }
    .anime-card .title { font-size: 26px; font-weight: 700; color: #18191c; margin-bottom: 4px; word-break: break-all; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .anime-card .title-jp { font-size: 17px; color: #9499a0; margin-bottom: 14px; word-break: break-all; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
    .anime-card .meta { font-size: 18px; color: #61666d; line-height: 1.6; }
    .anime-card .meta .score { color: #fb7299; font-weight: 700; font-size: 22px; }
    .anime-card .meta .doing { color: #00a1d6; font-weight: 700; }
    .footer { text-align: center; padding: 18px 0 22px; font-size: 14px; color: #9499a0; border-top: 1px solid #e3e5e7; width: 100%; background: #fff; }
    .no-cover .info { padding: 20px; }
    .cover-placeholder { width: 150px; min-height: 210px; flex-shrink: 0; background: #e3e5e7; display: flex; align-items: center; justify-content: center; font-size: 20px; color: #c9ccd0; }
  </style>
</head>
<body>
  <div class="header">
    <h1>新番日推</h1>
    <div class="date">{{ date }} {{ weekday }} · 共 {{ count }} 部</div>
  </div>
  <div class="container">
    <div class="body">
      {% for a in items %}
      <div class="anime-card">
        {% if a.cover %}
        <img class="cover" src="{{ a.cover }}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
        <div class="cover-placeholder" style="display:none">无图</div>
        {% else %}
        <div class="cover-placeholder">无图</div>
        {% endif %}
        <div class="info">
          <div class="title">{{ a.name_cn or a.name }}</div>
          {% if a.name_cn and a.name and a.name_cn != a.name %}
          <div class="title-jp">{{ a.name }}</div>
          {% endif %}
          <div class="meta">
            评分: <span class="score">{{ a.score }}</span>
            &nbsp;·&nbsp; 在看: <span class="doing">{{ a.doing }}</span>人
            &nbsp;·&nbsp; {{ a.air_date }}
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="footer">数据来源: Bangumi · bangumi.tv</div>
  </div>
</body>
</html>
'''


@register(
    "astrbot_plugin_bangumi_calendar",
    "NoFizz",
    "每日新番放送日历，定时推送卡片图至群聊",
    "1.0.0",
)
class BangumiCalendarPlugin(Star):
    """Bangumi 新番日历定时推送插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        os.makedirs(_COVERS_DIR, exist_ok=True)
        self._cleanup_old_covers()
        self._monitoring_task = asyncio.create_task(self._daily_task())
        logger.info(f"[Bangumi日历] 插件已加载, 推送时间: {self.config.get('push_time', '07:00')}")

    def _parse_push_time(self) -> tuple[int, int]:
        """解析推送时间，支持 H:MM 或 HH:MM 格式，无效回退到默认 07:00"""
        raw = self.config.get("push_time", "07:00")
        try:
            parts = str(raw).strip().split(":")
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
            raise ValueError
        except (ValueError, IndexError):
            logger.warning(f"[Bangumi日历] push_time 格式无效: '{raw}'，使用默认 07:00")
            return 7, 0

    def _get_target_umos(self) -> list[str]:
        """获取推送目标UMO列表"""
        raw = self.config.get("umos", [])
        return [str(u).strip() for u in raw if str(u).strip()]

    def _get_proxy(self) -> str | None:
        """获取代理地址：配置优先，环境变量回退，均无则直连"""
        proxy = str(self.config.get("proxy", "")).strip()
        if proxy:
            return proxy
        return os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or None

    def _sort_items(self, items: list) -> list:
        """根据配置的排序方式对番剧列表排序"""
        sort_by = self.config.get("sort_by", "score")
        sort_order = self.config.get("sort_order", "desc")
        reverse = sort_order != "asc"
        if sort_by == "doing":
            items.sort(key=lambda a: (a.get("collection") or {}).get("doing", 0), reverse=reverse)
        else:
            items.sort(key=lambda a: (a.get("rating") or {}).get("score", 0), reverse=reverse)
        return items

    def _get_cache_path(self, anime_id: int) -> str:
        return os.path.join(_COVERS_DIR, f"{anime_id}.jpg")

    def _cleanup_old_covers(self):
        """删除超过30天未使用的缓存封面"""
        now = time.time()
        expire = _CACHE_EXPIRE_DAYS * 86400
        count = 0
        for f in os.listdir(_COVERS_DIR):
            path = os.path.join(_COVERS_DIR, f)
            if os.path.isfile(path) and now - os.path.getatime(path) > expire:
                try:
                    os.remove(path)
                    count += 1
                except OSError:
                    pass
        if count:
            logger.info(f"[Bangumi日历] 清理了 {count} 张过期缓存封面")

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
        """查看今日更新的新番"""
        url = await self._render_image()
        if url:
            yield event.image_result(url)
        else:
            yield event.plain_result("获取新番信息失败，请稍后再试")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_cn.command("推送")
    async def manual_push_cn(self, event: AstrMessageEvent):
        """手动推送今日新番到所有目标"""
        count = await self._push_to_all_groups()
        yield event.plain_result(f"已向 {count} 个目标推送今日新番")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_cn.command("状态")
    async def check_status_cn(self, event: AstrMessageEvent):
        """查看插件运行状态"""
        yield event.plain_result(self._build_status_text())

    # ---- 英文指令 ----

    @bangumi_en.command("today")
    async def today_anime_en(self, event: AstrMessageEvent):
        """View today's anime schedule"""
        url = await self._render_image()
        if url:
            yield event.image_result(url)
        else:
            yield event.plain_result("获取新番信息失败，请稍后再试")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_en.command("push")
    async def manual_push_en(self, event: AstrMessageEvent):
        """Push today's anime to all targets"""
        count = await self._push_to_all_groups()
        yield event.plain_result(f"已向 {count} 个目标推送今日新番")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bangumi_en.command("status")
    async def check_status_en(self, event: AstrMessageEvent):
        """Check plugin status"""
        yield event.plain_result(self._build_status_text())

    def _build_status_text(self) -> str:
        """构建状态信息文本"""
        sleep_time = self._calculate_sleep_time()
        hours = int(sleep_time / 3600)
        minutes = int((sleep_time % 3600) / 60)
        umos = self._get_target_umos()
        proxy = self._get_proxy()
        return (
            f"Bangumi新番日历插件\n"
            f"推送时间: {self.config.get('push_time', '07:00')}\n"
            f"目标数: {len(umos)}\n"
            f"代理: {proxy or '直连'}\n"
            f"距离下次推送: {hours}小时{minutes}分钟"
        )

    async def terminate(self):
        """插件卸载时停止定时任务"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("[Bangumi日历] 插件已卸载")

    async def _fetch_calendar(self) -> list | None:
        """获取Bangumi每周放送日历（自动重试）"""
        max_retries = self.config.get("max_retries", 3)
        if max_retries < 1:
            max_retries = 1
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(headers=BANGUMI_HEADERS, timeout=20, follow_redirects=True, proxy=self._get_proxy()) as client:
                    resp = await client.get(BANGUMI_CALENDAR_URL)
                    if resp.status_code == 200:
                        return resp.json()
                    logger.warning(f"[Bangumi日历] API返回状态码: {resp.status_code} (第{attempt+1}次)")
            except Exception as e:
                logger.warning(f"[Bangumi日历] 请求异常: {type(e).__name__}: {e} (第{attempt+1}次)")
            if attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))
        logger.error(f"[Bangumi日历] 重试{max_retries}次后仍然失败")
        return None

    def _get_today_items(self, calendar: list) -> list:
        """从日历数据中提取今日番剧"""
        today_weekday = datetime.datetime.now().isoweekday()
        for day in calendar:
            if day.get("weekday", {}).get("id") == today_weekday:
                return day.get("items", [])
        return []

    async def _download_covers(self, items: list[dict]) -> dict[str, str]:
        """下载封面图，支持本地缓存。返回 {原始URL: data URI} 映射"""
        result = {}

        # 第一步：检查缓存，优先使用已有的高清图
        need_download = []
        for item in items:
            anime_id = item.get("id")
            images = item.get("images") or {}
            cover_url = images.get("large") or images.get("common") or images.get("medium")
            if not cover_url or not anime_id:
                continue
            cache_path = self._get_cache_path(anime_id)
            if os.path.isfile(cache_path):
                os.utime(cache_path)
                with open(cache_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                result[cover_url] = f"data:image/jpeg;base64,{b64}"
            else:
                need_download.append(item)

        # 第二步：下载缺失的封面
        if need_download:
            async def _fetch(client: httpx.AsyncClient, item: dict):
                anime_id = item.get("id")
                images = item.get("images") or {}
                url = images.get("large") or images.get("common") or images.get("medium")
                try:
                    resp = await client.get(url, timeout=10)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        # 保存到本地缓存
                        cache_path = self._get_cache_path(anime_id)
                        with open(cache_path, "wb") as f:
                            f.write(resp.content)
                        ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                        b64 = base64.b64encode(resp.content).decode()
                        return url, f"data:{ct};base64,{b64}"
                except Exception as e:
                    logger.warning(f"[Bangumi日历] 下载封面失败 {url}: {e}")
                return url, None

            async with httpx.AsyncClient(timeout=15, follow_redirects=True, proxy=self._get_proxy()) as client:
                tasks = [_fetch(client, it) for it in need_download]
                for url, data_uri in await asyncio.gather(*tasks):
                    if data_uri:
                        result[url] = data_uri

        return result

    async def _render_image(self) -> str | None:
        """获取数据并渲染为图片"""
        calendar = await self._fetch_calendar()
        if not calendar:
            return None

        items = self._get_today_items(calendar)
        if not items:
            return None

        items = self._sort_items(items)

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

        for anime in items:
            images = anime.get("images") or {}
            cover_url = images.get("large") or images.get("common") or images.get("medium")

            rating = anime.get("rating") or {}
            collection = anime.get("collection") or {}

            template_data["items"].append({
                "name": html_mod.unescape(anime.get("name", "")),
                "name_cn": html_mod.unescape(anime.get("name_cn", "")),
                "score": rating.get("score", "暂无"),
                "doing": collection.get("doing", 0),
                "air_date": anime.get("air_date", ""),
                "cover": cover_url,
            })

        # 下载封面图并转为 base64，避免 Playwright 加载外部图片超时
        try:
            cover_map = await self._download_covers(items)
            for item in template_data["items"]:
                if item["cover"] and item["cover"] in cover_map:
                    item["cover"] = cover_map[item["cover"]]
                else:
                    item["cover"] = ""

            options = {
                "type": "png",
                "full_page": True,
                "timeout": 60000,
                "viewport_width": 660,
                "viewport_height": 800,
                "device_scale_factor_level": "high",
            }
            url = await self.html_render(HTML_TMPL, template_data, options=options)
            if url:
                logger.info("[Bangumi日历] 图片渲染成功")
            else:
                logger.error("[Bangumi日历] html_render 返回空，渲染失败")
            return url
        except Exception as e:
            logger.error(f"[Bangumi日历] 图片渲染失败: {e}")
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
            except Exception as e:
                logger.error(f"[Bangumi日历] 推送至 {umo} 失败: {e}")
        return success

    def _calculate_sleep_time(self) -> float:
        """计算距离下次推送的秒数"""
        now = datetime.datetime.now()
        hour, minute = self._parse_push_time()
        next_push = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_push <= now:
            next_push += datetime.timedelta(days=1)
        return (next_push - now).total_seconds()

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
                else:
                    logger.info("[Bangumi日历] 未配置推送目标，跳过")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Bangumi日历] 定时任务异常: {e}")
                await asyncio.sleep(300)
