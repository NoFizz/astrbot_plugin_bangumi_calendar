"""模块级常量：Bangumi 日历 URL、请求头、星期名、封面缓存目录与过期天数。

所有模块从这里取常量，避免散落的魔法值。
"""

# Copyright 2026 NoFizz
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

BANGUMI_CALENDAR_URL = "https://api.bgm.tv/calendar"
BANGUMI_SUBJECTS_URL = "https://api.bgm.tv/v0/subjects"
BANGUMI_HEADERS = {
    "User-Agent": "astrbot_plugin_bangumi_calendar/1.1.1 (https://github.com/AstrBotDevs/AstrBot)",
    "Accept": "application/json",
}
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
# 以 models.py 自身所在目录（插件根）计算，保证路径仍指向插件根/covers
_COVERS_DIR = os.path.join(os.path.dirname(__file__), "covers")
_CACHE_EXPIRE_DAYS = 30
# 封面并发下载的信号量上限，防止瞬时打满连接与磁盘 IO
_DOWNLOAD_SEM_LIMIT = 5
