"""异步网络与封面缓存：抓取日历、下载封面（本地缓存 + 并发）、清理过期缓存。

依赖 models 的常量；无 astrbot 依赖（仅 logger 用于日志）。
"""

import asyncio
import base64
import os
import time

import httpx

from astrbot.api import logger

from .models import BANGUMI_CALENDAR_URL, BANGUMI_HEADERS, _COVERS_DIR


def _cache_path(anime_id: int) -> str:
    """封面缓存文件路径。

    Args:
        anime_id: Bangumi 条目 ID。

    Returns:
        str: covers 目录下的 jpg 缓存路径。
    """
    return os.path.join(_COVERS_DIR, f"{anime_id}.jpg")


async def fetch_calendar(config_retries: int, proxy: str | None) -> list | None:
    """获取 Bangumi 每周放送日历（自动重试）。

    Args:
        config_retries: 配置的 max_retries；小于 1 时按 1 处理。
        proxy: 代理地址，None 表示直连。

    Returns:
        list | None: 日历数据；重试耗尽后返回 None。
    """
    max_retries = config_retries
    if max_retries < 1:
        max_retries = 1
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(
                headers=BANGUMI_HEADERS, timeout=20, follow_redirects=True, proxy=proxy
            ) as client:
                resp = await client.get(BANGUMI_CALENDAR_URL)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(f"[Bangumi日历] API返回状态码: {resp.status_code} (第{attempt + 1}次)")
        except Exception as e:
            logger.warning(f"[Bangumi日历] 请求异常: {type(e).__name__}: {e} (第{attempt + 1}次)")
        if attempt < max_retries - 1:
            await asyncio.sleep(3 * (attempt + 1))
    logger.error(f"[Bangumi日历] 重试{max_retries}次后仍然失败")
    return None


async def download_covers(items: list[dict], proxy: str | None) -> dict[str, str]:
    """下载封面图，支持本地缓存。返回 {原始URL: data URI} 映射。

    Args:
        items: 番剧条目列表。
        proxy: 代理地址，None 表示直连。

    Returns:
        dict[str, str]: 原始封面 URL 到 base64 data URI 的映射。
    """
    result = {}

    # 第一步：检查缓存，优先使用已有的高清图
    need_download = []
    for item in items:
        anime_id = item.get("id")
        images = item.get("images") or {}
        cover_url = images.get("large") or images.get("common") or images.get("medium")
        if not cover_url or not anime_id:
            continue
        cache_path = _cache_path(anime_id)
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
                    with open(_cache_path(anime_id), "wb") as f:
                        f.write(resp.content)
                    ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                    b64 = base64.b64encode(resp.content).decode()
                    return url, f"data:{ct};base64,{b64}"
            except Exception as e:
                logger.warning(f"[Bangumi日历] 下载封面失败 {url}: {e}")
            return url, None

        async with httpx.AsyncClient(timeout=15, follow_redirects=True, proxy=proxy) as client:
            tasks = [_fetch(client, it) for it in need_download]
            for url, data_uri in await asyncio.gather(*tasks):
                if data_uri:
                    result[url] = data_uri

    return result


def cleanup_old_covers(covers_dir: str, expire_days: int) -> int:
    """删除超过 expire_days 天未使用的缓存封面。

    Args:
        covers_dir: 封面缓存目录。
        expire_days: 过期天数（按 atime 判断）。

    Returns:
        int: 清理的封面数量。
    """
    now = time.time()
    expire = expire_days * 86400
    count = 0
    for f in os.listdir(covers_dir):
        path = os.path.join(covers_dir, f)
        if os.path.isfile(path) and now - os.path.getatime(path) > expire:
            try:
                os.remove(path)
                count += 1
            except OSError:
                pass
    if count:
        logger.info(f"[Bangumi日历] 清理了 {count} 张过期缓存封面")
    return count
