# Copyright 2026 NoFizz
# SPDX-License-Identifier: AGPL-3.0-or-later

"""i18n 回复文案测试：英文命令返回英文文案，中文命令保持中文文案（逐字节）。

覆盖 6 个公开 handler（中/英两套）的回复文案与 ``_t`` 辅助方法本身。
英文文案先于实现写入，作为 TDD 的 RED 用例；中文文案与 test_handlers.py
的既有断言逐字节一致，防止语言机制引入时破坏中文行为。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import astrbot_plugin_bangumi_calendar.main as plugin_main


class _RecordingEvent:
    """记录事件替身：记录 ``plain_result`` 的文本用于断言。"""

    def __init__(self):
        """初始化：清空文本记录。"""
        self.plain_texts = []

    def plain_result(self, text):
        """记录并返回文本结果。

        Args:
            text: 文本内容。

        Returns:
            原样返回 text，模拟 AstrBot 结果对象。
        """
        self.plain_texts.append(text)
        return text


async def _collect(agen):
    """收集异步生成器的全部产出。

    Args:
        agen: 异步生成器。

    Returns:
        list: 生成器产出的结果列表。
    """
    return [item async for item in agen]


class TestTodayI18n:
    """``/新番 今日`` 与 ``/bangumi today``：失败文案按语言区分。"""

    @pytest.mark.parametrize(
        "handler_name,expected",
        [
            ("today_anime_cn", "获取新番信息失败，请稍后再试"),
            ("today_anime_en", "Failed to fetch anime info, please try again later"),
        ],
    )
    def test_failure_text_by_language(self, make_plugin, handler_name, expected):
        """Given _render_image 返回 None，When 调用 today handler，Then 产出对应语言文案（逐字节）。"""
        plugin = make_plugin()
        plugin._render_image = AsyncMock(return_value=None)
        event = _RecordingEvent()
        results = asyncio.run(_collect(getattr(plugin, handler_name)(event)))
        assert results == [expected]
        assert event.plain_texts == [expected]


class TestPushI18n:
    """``/新番 推送`` 与 ``/bangumi push``：推送数文案按语言区分。"""

    @pytest.mark.parametrize(
        "handler_name,expected",
        [
            ("manual_push_cn", "已向 3 个目标推送今日新番"),
            ("manual_push_en", "Pushed today's anime to 3 target(s)"),
        ],
    )
    def test_push_count_text_by_language(self, make_plugin, handler_name, expected):
        """Given _push_to_all_groups 返回 3，When 调用 push handler，Then 产出对应语言文案（逐字节）。"""
        plugin = make_plugin()
        plugin._push_to_all_groups = AsyncMock(return_value=3)
        event = _RecordingEvent()
        results = asyncio.run(_collect(getattr(plugin, handler_name)(event)))
        assert results == [expected]
        assert event.plain_texts == [expected]


class TestStatusI18n:
    """``/新番 状态`` 与 ``/bangumi status``：状态文本按语言切换标签。"""

    def test_status_text_en(self, make_plugin):
        """Given 配置了代理，When 以英文组装状态文本，Then 全英文且数值与中文版一致。"""
        plugin = make_plugin(push_time="07:00", umos=["a", "b"], proxy="http://127.0.0.1:7890")
        plugin._calculate_sleep_time = MagicMock(return_value=3661)
        expected = (
            "Bangumi Calendar Plugin\nPush time: 07:00\nTargets: 2\nProxy: http://127.0.0.1:7890\nNext push in 1h 1m"
        )
        assert plugin._build_status_text(lang="en") == expected

    def test_status_text_en_direct(self, make_plugin, monkeypatch):
        """Given 未配置代理且环境变量无代理，When 以英文组装状态文本，Then 代理行显示 Direct。"""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        plugin = make_plugin(push_time="07:00", umos=["a"], proxy="")
        plugin._calculate_sleep_time = MagicMock(return_value=3600)
        expected = "Bangumi Calendar Plugin\nPush time: 07:00\nTargets: 1\nProxy: Direct\nNext push in 1h 0m"
        assert plugin._build_status_text(lang="en") == expected

    def test_status_text_cn(self, make_plugin):
        """Given 配置了代理，When 以默认（中文）组装状态文本，Then 逐字节保持既有中文文案。"""
        plugin = make_plugin(push_time="07:00", umos=["a", "b"], proxy="http://127.0.0.1:7890")
        plugin._calculate_sleep_time = MagicMock(return_value=3661)
        expected = (
            "Bangumi新番日历插件\n推送时间: 07:00\n目标数: 2\n代理: http://127.0.0.1:7890\n距离下次推送: 1小时1分钟"
        )
        assert plugin._build_status_text() == expected


class TestTranslationHelper:
    """``_t`` 辅助方法：取文案、格式化占位符、缺失回退。"""

    def test_t_returns_zh_by_default(self, make_plugin):
        """Given 未指定语言，When 调用 _t，Then 返回中文文案。"""
        plugin = make_plugin()
        assert plugin._t("today_failed") == "获取新番信息失败，请稍后再试"

    def test_t_returns_en_when_lang_en(self, make_plugin):
        """Given 指定英文，When 调用 _t，Then 返回英文文案。"""
        plugin = make_plugin()
        assert plugin._t("today_failed", lang="en") == "Failed to fetch anime info, please try again later"

    def test_t_formats_placeholders(self, make_plugin):
        """Given 文案含 {count} 占位符，When 传入格式化参数，Then 占位符被替换。"""
        plugin = make_plugin()
        assert plugin._t("push_done", count=5) == "已向 5 个目标推送今日新番"
        assert plugin._t("push_done", lang="en", count=5) == "Pushed today's anime to 5 target(s)"

    def test_t_falls_back_to_zh_when_en_key_missing(self, make_plugin, monkeypatch):
        """Given 英文表缺失某键，When 请求英文文案，Then 回退中文文案。"""
        monkeypatch.delitem(plugin_main._REPLY_EN, "status_title")
        plugin = make_plugin()
        assert plugin._t("status_title", lang="en") == "Bangumi新番日历插件"
