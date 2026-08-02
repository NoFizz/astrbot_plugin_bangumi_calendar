"""健壮性回归测试：渲染重试、并发限流、原子缓存、异步 I/O 卸载、异常收窄等。

每项修复先在 ``tests/test_robustness.py`` 写失败测试（RED），再实现（GREEN）。
所有测试 hermetic：不发起真实网络请求、不依赖 AstrBot 运行时。
"""

import asyncio
import base64
import hashlib
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

import astrbot_plugin_bangumi_calendar.main as plugin_main
import astrbot_plugin_bangumi_calendar.parser as parser_mod
import astrbot_plugin_bangumi_calendar.service as service_mod


class TestRenderRetry:
    """``_render_image`` 的 html_render 失败重试：异常/返回 None 时最多重试 2 次。"""

    @staticmethod
    def _plugin(make_plugin, side_effect):
        """构造渲染路径上所有外部依赖均已打桩的插件。

        Args:
            make_plugin: conftest 提供的插件工厂。
            side_effect: html_render 的 side_effect（异常或返回 URL）。

        Returns:
            BangumiCalendarPlugin: 已打桩的插件实例。
        """
        plugin = make_plugin(max_items=0)
        plugin._fetch_calendar = AsyncMock(
            return_value=[{"weekday": {"id": 1}, "items": [{"id": 1, "name": "A"}]}]
        )
        plugin._get_today_items = lambda calendar: calendar[0]["items"]
        plugin._download_covers = AsyncMock(return_value={})
        plugin.html_render = AsyncMock(side_effect=side_effect)
        return plugin

    def test_exception_then_success_retries(self, make_plugin, monkeypatch):
        """Given html_render 首次抛异常第二次成功，When 渲染，Then 重试后返回 URL。"""
        plugin = self._plugin(make_plugin, [RuntimeError("boom"), "https://example.com/card.png"])
        sleeps = []
        monkeypatch.setattr(
            plugin_main.asyncio, "sleep", AsyncMock(side_effect=lambda s: sleeps.append(s))
        )
        url = asyncio.run(plugin._render_image())
        assert url == "https://example.com/card.png"
        assert plugin.html_render.call_count == 2
        assert sleeps == [1]

    def test_none_then_success_retries(self, make_plugin, monkeypatch):
        """Given html_render 首次返回 None 第二次成功，When 渲染，Then 重试后返回 URL。"""
        plugin = self._plugin(make_plugin, [None, "https://example.com/card.png"])
        monkeypatch.setattr(plugin_main.asyncio, "sleep", AsyncMock())
        url = asyncio.run(plugin._render_image())
        assert url == "https://example.com/card.png"
        assert plugin.html_render.call_count == 2

    def test_all_failures_return_none(self, make_plugin, monkeypatch):
        """Given html_render 三次均返回 None，When 渲染，Then 重试耗尽返回 None。"""
        plugin = self._plugin(make_plugin, [None, None, None])
        monkeypatch.setattr(plugin_main.asyncio, "sleep", AsyncMock())
        assert asyncio.run(plugin._render_image()) is None
        assert plugin.html_render.call_count == 3

    def test_exceptions_exhaust_retries(self, make_plugin, monkeypatch):
        """Given html_render 三次均抛异常，When 渲染，Then 重试耗尽返回 None 不崩溃。"""
        plugin = self._plugin(make_plugin, [RuntimeError("boom")] * 3)
        monkeypatch.setattr(plugin_main.asyncio, "sleep", AsyncMock())
        assert asyncio.run(plugin._render_image()) is None
        assert plugin.html_render.call_count == 3
