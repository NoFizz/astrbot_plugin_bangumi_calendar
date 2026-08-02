"""异步网络与封面缓存：抓取日历、下载封面（本地缓存 + 并发）、清理过期缓存。

依赖 models 的常量；无 astrbot 依赖（仅 logger 用于日志）。
"""

import asyncio
import base64
import json
import os
import time

import httpx

from astrbot.api import logger

from .models import BANGUMI_CALENDAR_URL, BANGUMI_HEADERS, _COVERS_DIR, _DOWNLOAD_SEM_LIMIT
from .parser import safe_anime_id

# 缓存扩展名与 MIME 的映射：命中时按扩展名反查 MIME，写入时按 MIME 选扩展名
_MIME_BY_EXT = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_EXT_BY_MIME = {mime: ext for ext, mime in _MIME_BY_EXT.items()}


def _cache_path(anime_id, ext: str = ".jpg") -> str:
    """封面缓存文件路径。

    Args:
        anime_id: Bangumi 条目 ID（任意类型，写入前安全化）。
        ext: 文件扩展名，``""`` 表示无扩展名的旧式缓存文件。

    Returns:
        str: covers 目录下的缓存路径。
    """
    return os.path.join(_COVERS_DIR, f"{safe_anime_id(anime_id)}{ext}")


def _load_cover_file(path: str, mime: str) -> str:
    """读取缓存文件并转为 data URI；文件损坏时抛出 OSError/ValueError。

    Args:
        path: 缓存文件路径。
        mime: data URI 的 MIME 类型。

    Returns:
        str: ``data:{mime};base64,...``。
    """
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    os.utime(path)
    return f"data:{mime};base64,{b64}"


def _read_cached_cover(anime_id) -> str | None:
    """读取缓存封面为 data URI；缺失或损坏返回 None（损坏文件会被删除）。

    Args:
        anime_id: Bangumi 条目 ID。

    Returns:
        str | None: data URI；未命中或文件损坏时返回 None。
    """
    candidates = [(ext, mime) for ext, mime in _MIME_BY_EXT.items()]
    candidates.append(("", "image/jpeg"))  # 无扩展名的旧式缓存按 jpeg 处理
    for ext, mime in candidates:
        path = _cache_path(anime_id, ext)
        if os.path.isfile(path):
            try:
                return _load_cover_file(path, mime)
            except (OSError, ValueError):
                try:
                    os.remove(path)
                except OSError:
                    pass
                return None
    return None


def _store_cached_cover(anime_id, content: bytes, content_type: str) -> str:
    """原子写入缓存封面并返回 data URI；写入失败时清理临时文件并重抛。

    Args:
        anime_id: Bangumi 条目 ID。
        content: 图片字节。
        content_type: 响应 content-type（可能带 ``; charset=...`` 后缀）。

    Returns:
        str: ``data:{mime};base64,...``。

    Raises:
        OSError: 写入或原子替换失败。
    """
    mime = content_type.split(";")[0].strip()
    ext = _EXT_BY_MIME.get(mime, ".jpg")
    final_path = _cache_path(anime_id, ext)
    tmp_path = f"{final_path}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        os.replace(tmp_path, final_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


async def fetch_calendar(config_retries: int, proxy: str | None) -> list[dict] | None:
    """获取 Bangumi 每周放送日历（自动重试）。

    Args:
        config_retries: 配置的 max_retries；小于 1 时按 1 处理。
        proxy: 代理地址，None 表示直连。

    Returns:
        list[dict] | None: 日历数据；重试耗尽后返回 None。

    Raises:
        Exception: 非 httpx.HTTPError/json.JSONDecodeError 的意外异常直接传播，
        不做吞没（便于上层发现编程错误）。
    """
    max_retries = config_retries
    if max_retries < 1:
        max_retries = 1
    # AsyncClient 在重试循环外创建一次，循环内复用同一连接池
    async with httpx.AsyncClient(
        headers=BANGUMI_HEADERS, timeout=20, follow_redirects=True, proxy=proxy
    ) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.get(BANGUMI_CALENDAR_URL)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(f"[Bangumi日历] API返回状态码: {resp.status_code} (第{attempt + 1}次)")
            except (httpx.HTTPError, json.JSONDecodeError) as e:
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
        if not cover_url or anime_id is None:
            continue
        data_uri = await asyncio.to_thread(_read_cached_cover, anime_id)
        if data_uri is not None:
            result[cover_url] = data_uri
        else:
            need_download.append(item)

    # 第二步：下载缺失的封面（并发受信号量限制）
    if need_download:
        sem = asyncio.Semaphore(_DOWNLOAD_SEM_LIMIT)

        async def _fetch(client: httpx.AsyncClient, item: dict):
            anime_id = item.get("id")
            images = item.get("images") or {}
            url = images.get("large") or images.get("common") or images.get("medium")
            try:
                async with sem:
                    resp = await client.get(url, timeout=10)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                        data_uri = await asyncio.to_thread(_store_cached_cover, anime_id, resp.content, ct)
                        return url, data_uri
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
        expire_days: 过期天数（按 max(atime, mtime) 判断，Windows atime 不可靠）。

    Returns:
        int: 清理的封面数量。
    """
    now = time.time()
    expire = expire_days * 86400
    count = 0
    for f in os.listdir(covers_dir):
        path = os.path.join(covers_dir, f)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if os.path.isfile(path) and now - max(st.st_atime, st.st_mtime) > expire:
            try:
                os.remove(path)
                count += 1
            except OSError:
                pass
    if count:
        logger.info(f"[Bangumi日历] 清理了 {count} 张过期缓存封面")
    return count
