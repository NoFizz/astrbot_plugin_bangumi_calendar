# Copyright 2026 NoFizz
# SPDX-License-Identifier: AGPL-3.0-or-later

"""命令处理器特征测试：6 个公开 handler（中/英两套）的回复文案与委托行为。

这些是特征测试（characterization test）：先于重构写入，锁定当前行为；
重构（提取共享核心 + 薄包装）前后均须全绿，证明回复文案逐字节未变。
所有测试 hermetic：不发起真实网络请求、不依赖 AstrBot 运行时。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


class _RecordingEvent:
    """记录事件替身：区分 ``image_result`` 与 ``plain_result`` 的调用。

    相比 conftest 的占位事件，额外记录调用参数，用于断言 handler
    产出的是图片消息还是文本消息。
    """

    def __init__(self):
        """初始化：清空两类结果记录。"""
        self.image_urls = []
        self.plain_texts = []

    def image_result(self, url):
        """记录并返回图片结果。

        Args:
            url: 图片地址。

        Returns:
            原样返回 url，模拟 AstrBot 结果对象。
        """
        self.image_urls.append(url)
        return url

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


class TestTodayHandlers:
    """``/新番 今日`` 与 ``/bangumi today``：委托 ``_render_image``，成功出图、失败出文案。"""

    @pytest.mark.parametrize("handler_name", ["today_anime_cn", "today_anime_en"])
    def test_success_yields_image(self, make_plugin, handler_name):
        """Given _render_image 返回 URL，When 调用 today handler，Then 仅产出图片且只渲染一次。"""
        plugin = make_plugin()
        plugin._render_image = AsyncMock(return_value="https://img.example.com/card.png")
        event = _RecordingEvent()
        results = asyncio.run(_collect(getattr(plugin, handler_name)(event)))
        assert results == ["https://img.example.com/card.png"]
        assert event.image_urls == ["https://img.example.com/card.png"]
        assert event.plain_texts == []
        plugin._render_image.assert_awaited_once_with()

    @pytest.mark.parametrize(
        "handler_name,expected",
        [
            ("today_anime_cn", "获取新番信息失败，请稍后再试"),
            ("today_anime_en", "Failed to fetch anime info, please try again later"),
        ],
    )
    def test_failure_yields_failure_text(self, make_plugin, handler_name, expected):
        """Given _render_image 返回 None，When 调用 today handler，Then 产出对应语言失败文案。"""
        plugin = make_plugin()
        plugin._render_image = AsyncMock(return_value=None)
        event = _RecordingEvent()
        results = asyncio.run(_collect(getattr(plugin, handler_name)(event)))
        assert results == [expected]
        assert event.image_urls == []
        assert event.plain_texts == [expected]
        plugin._render_image.assert_awaited_once_with()


class TestPushHandlers:
    """``/新番 推送`` 与 ``/bangumi push``：委托 ``_push_to_all_groups`` 并报告推送数。"""

    @pytest.mark.parametrize(
        "handler_name,expected",
        [
            ("manual_push_cn", "已向 3 个目标推送今日新番"),
            ("manual_push_en", "Pushed today's anime to 3 target(s)"),
        ],
    )
    def test_yields_push_count_text(self, make_plugin, handler_name, expected):
        """Given _push_to_all_groups 返回 3，When 调用 push handler，Then 产出对应语言推送数文案。"""
        plugin = make_plugin()
        plugin._push_to_all_groups = AsyncMock(return_value=3)
        event = _RecordingEvent()
        results = asyncio.run(_collect(getattr(plugin, handler_name)(event)))
        assert results == [expected]
        assert event.image_urls == []
        assert event.plain_texts == [expected]
        plugin._push_to_all_groups.assert_awaited_once_with()


class TestStatusHandlers:
    """``/新番 状态`` 与 ``/bangumi status``：委托 ``_build_status_text`` 并逐字节产出。"""

    @pytest.mark.parametrize(
        "handler_name,expected_lang",
        [("check_status_cn", "zh"), ("check_status_en", "en")],
    )
    def test_yields_status_text(self, make_plugin, handler_name, expected_lang):
        """Given _build_status_text 返回固定文本，When 调用 status handler，Then 原样产出并传对应语言。"""
        plugin = make_plugin()
        plugin._build_status_text = MagicMock(return_value="STATUS_TEXT")
        event = _RecordingEvent()
        results = asyncio.run(_collect(getattr(plugin, handler_name)(event)))
        assert results == ["STATUS_TEXT"]
        assert event.image_urls == []
        assert event.plain_texts == ["STATUS_TEXT"]
        plugin._build_status_text.assert_called_once_with(lang=expected_lang)

    def test_real_status_text_composition_with_proxy(self, make_plugin):
        """Given 配置了代理，When 组装状态文本，Then 文案逐字节符合预期。"""
        plugin = make_plugin(push_time="07:00", umos=["a", "b"], proxy="http://127.0.0.1:7890")
        plugin._calculate_sleep_time = MagicMock(return_value=3661)
        expected = (
            "Bangumi新番日历插件\n推送时间: 07:00\n目标数: 2\n代理: http://127.0.0.1:7890\n距离下次推送: 1小时1分钟"
        )
        assert plugin._build_status_text() == expected

    def test_real_status_text_composition_direct(self, make_plugin, monkeypatch):
        """Given 未配置代理且环境变量无代理，When 组装状态文本，Then 显示直连。"""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        plugin = make_plugin(push_time="07:00", umos=["a"], proxy="")
        plugin._calculate_sleep_time = MagicMock(return_value=3600)
        expected = "Bangumi新番日历插件\n推送时间: 07:00\n目标数: 1\n代理: 直连\n距离下次推送: 1小时0分钟"
        assert plugin._build_status_text() == expected
