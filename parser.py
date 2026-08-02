"""纯逻辑函数：无副作用、无 astrbot 依赖（仅 logger 用于告警），可独立测试。

这些函数接收显式参数，由 main.py 的实例方法读取配置后调用。
"""

import datetime
import hashlib
import os

from astrbot.api import logger


def safe_anime_id(raw) -> str:
    """把任意输入规范化为安全的缓存文件名片段。

    Args:
        raw: 原始 anime_id（通常为 int，但配置/API 数据不可信）。

    Returns:
        str: 合法整数转为十进制字符串；否则取 SHA1 摘要前 12 位十六进制。
    """
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        return hashlib.sha1(str(raw).encode()).hexdigest()[:12]


def parse_push_time(raw) -> tuple[int, int]:
    """解析推送时间，支持 H:MM 或 HH:MM 格式，无效回退到默认 07:00。

    Args:
        raw: 配置项 push_time 的原始值。

    Returns:
        tuple[int, int]: (小时, 分钟)；解析失败或越界时回退 (7, 0)。
    """
    try:
        parts = str(raw).strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
        raise ValueError
    except (ValueError, IndexError):
        logger.warning(f"[Bangumi日历] push_time 格式无效: '{raw}'，使用默认 07:00")
        return 7, 0


def sort_items(items: list, sort_by: str, sort_order: str) -> list:
    """按指定字段与方向对番剧列表原地排序。

    Args:
        items: 番剧条目列表（原地修改后返回同一对象）。
        sort_by: 排序字段，``doing`` 按在看数，其余按评分。
        sort_order: 排序方向，非 ``asc`` 一律按降序处理。

    Returns:
        list: 排序后的原列表对象。
    """
    reverse = sort_order != "asc"
    if sort_by == "doing":
        items.sort(key=lambda a: (a.get("collection") or {}).get("doing", 0), reverse=reverse)
    else:
        items.sort(key=lambda a: (a.get("rating") or {}).get("score", 0), reverse=reverse)
    return items


def get_today_items(calendar: list, today_weekday: int) -> list:
    """从日历数据中提取指定星期（ISO 编号）的番剧条目。

    Args:
        calendar: Bangumi /calendar 返回的每周条目列表。
        today_weekday: 今天 isoweekday()，1=周一，7=周日。

    Returns:
        list: 当日条目；未匹配到时返回空列表。
    """
    for day in calendar:
        if day.get("weekday", {}).get("id") == today_weekday:
            return day.get("items", [])
    return []


def calculate_sleep_time(now: datetime.datetime, hour: int, minute: int) -> float:
    """计算从 now 到下一个 (hour, minute) 时刻的秒数。

    Args:
        now: 当前时刻（由调用方传入，便于注入固定时钟）。
        hour: 推送小时。
        minute: 推送分钟。

    Returns:
        float: 距离下次推送的秒数；今日时刻已过则跨到次日。
    """
    next_push = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_push <= now:
        next_push += datetime.timedelta(days=1)
    return (next_push - now).total_seconds()


def get_proxy(proxy_config) -> str | None:
    """获取代理地址：配置优先，环境变量回退，均无则直连。

    Args:
        proxy_config: 配置项 proxy 的原始值。

    Returns:
        str | None: 代理地址；无可用代理时返回 None。
    """
    proxy = str(proxy_config).strip()
    if proxy:
        return proxy
    return os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or None


def clean_umos(raw) -> list[str]:
    """清洗推送目标 UMO 列表：去空白、过滤空串。

    Args:
        raw: 配置项 umos 的原始值（可迭代）。

    Returns:
        list[str]: 清洗后的目标列表，不去重。
    """
    return [str(u).strip() for u in raw if str(u).strip()]
