"""BangumiCalendarPlugin 核心逻辑特征测试（hermetic）。

测试不发起任何网络请求、不依赖真实 AstrBot 运行时、不读取真实配置。
所有断言锁定 main.py 当前实现的实际行为（含回退逻辑）；
若某处与直觉不符，注释中以「实际行为」标注。
"""

import asyncio
import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

import astrbot_plugin_bangumi_calendar.main as plugin_main


class _FixedClock(datetime.datetime):
    """固定时刻的 datetime 子类，用于替换 ``datetime.datetime.now``。"""

    fixed = None

    @classmethod
    def now(cls, tz=None):
        """返回固定时刻。

        Args:
            tz: 忽略，仅匹配签名。

        Returns:
            datetime: ``fixed`` 中设定的固定时刻。
        """
        return cls.fixed


class _FakeResponse:
    """模拟 HTTP 200 响应。"""

    status_code = 200

    def json(self):
        """返回模拟的日历 JSON。"""
        return [{"weekday": {"id": 1}, "items": []}]


class TestParsePushTime:
    """``_parse_push_time``：合法值解析，非法值回退默认 07:00。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("7:00", (7, 0)),
            ("07:00", (7, 0)),
            ("23:59", (23, 59)),
            # 以下为回退场景：实际行为是任何解析失败/越界值一律回退 (7, 0)
            ("24:00", (7, 0)),
            ("7:99", (7, 0)),
            ("", (7, 0)),
            (None, (7, 0)),
            ("abc", (7, 0)),
        ],
    )
    def test_parse(self, make_plugin, raw, expected):
        """Given 配置 push_time，When 解析，Then 得到期望的 (小时, 分钟)。"""
        plugin = make_plugin(push_time=raw)
        assert plugin._parse_push_time() == expected

    def test_missing_config_uses_default(self, make_plugin):
        """Given 配置无 push_time，When 解析，Then 回退默认 (7, 0)。"""
        plugin = make_plugin()
        assert plugin._parse_push_time() == (7, 0)


class TestSortItems:
    """``_sort_items``：按配置排序；无效配置静默回退，不崩溃。"""

    @staticmethod
    def _items():
        # 每次返回新列表：sort 是原地操作
        return [
            {"name": "a", "rating": {"score": 3.0}, "collection": {"doing": 10}},
            {"name": "b", "rating": {"score": 9.5}, "collection": {"doing": 2}},
            {"name": "c", "rating": {"score": 5.0}, "collection": {"doing": 30}},
        ]

    @pytest.mark.parametrize(
        ("sort_by", "sort_order", "expected"),
        [
            ("score", "desc", ["b", "c", "a"]),
            ("score", "asc", ["a", "c", "b"]),
            ("doing", "desc", ["c", "a", "b"]),
            ("doing", "asc", ["b", "a", "c"]),
        ],
    )
    def test_sorted_by_config(self, make_plugin, sort_by, sort_order, expected):
        """Given 排序配置，When 排序，Then 按配置字段与方向排列。"""
        plugin = make_plugin(sort_by=sort_by, sort_order=sort_order)
        items = self._items()
        assert [item["name"] for item in plugin._sort_items(items)] == expected

    def test_invalid_sort_by_falls_back_to_score(self, make_plugin):
        """Given sort_by 为未知值，When 排序，Then 走 score 分支且不崩溃。"""
        plugin = make_plugin(sort_by="popularity", sort_order="desc")
        items = self._items()
        assert [item["name"] for item in plugin._sort_items(items)] == ["b", "c", "a"]

    def test_invalid_sort_order_treated_as_desc(self, make_plugin):
        """Given sort_order 非 asc，When 排序，Then 实际按降序处理。"""
        plugin = make_plugin(sort_by="score", sort_order="sideways")
        items = self._items()
        assert [item["name"] for item in plugin._sort_items(items)] == ["b", "c", "a"]

    def test_none_sort_config_falls_back_to_score(self, make_plugin):
        """Given sort_by/sort_order 为 None，When 排序，Then 走默认分支不崩溃。"""
        plugin = make_plugin(sort_by=None, sort_order=None)
        items = self._items()
        assert [item["name"] for item in plugin._sort_items(items)] == ["b", "c", "a"]

    def test_empty_list(self, make_plugin):
        """Given 空列表，When 排序，Then 返回空列表。"""
        plugin = make_plugin()
        assert plugin._sort_items([]) == []

    def test_missing_nested_fields_treated_as_zero(self, make_plugin):
        """Given 条目缺 rating/collection 字段，When 排序，Then 按 0 参与且不崩溃。"""
        plugin = make_plugin(sort_by="doing", sort_order="asc")
        items = [
            {"name": "no-field"},
            {"name": "null-collection", "collection": None},
            {"name": "with-doing", "collection": {"doing": 5}},
        ]
        assert [item["name"] for item in plugin._sort_items(items)] == [
            "no-field",
            "null-collection",
            "with-doing",
        ]


class TestGetTodayItems:
    """``_get_today_items``：按 ISO weekday（1=周一）提取当日番剧。"""

    @staticmethod
    def _calendar():
        """构造含全部 7 天条目的日历。

        Returns:
            tuple[list, int]: (日历, 今天的 isoweekday)。
        """
        today = datetime.datetime.now().isoweekday()
        calendar = [
            {"weekday": {"id": day_id}, "items": [{"name": f"day-{day_id}"}]}
            for day_id in range(1, 8)
        ]
        return calendar, today

    def test_matches_today_weekday(self, make_plugin):
        """Given 含全部 7 天条目的日历，When 提取，Then 仅返回当日条目。"""
        calendar, today = self._calendar()
        plugin = make_plugin()
        assert plugin._get_today_items(calendar) == [{"name": f"day-{today}"}]

    def test_other_days_only_returns_empty(self, make_plugin):
        """Given 日历仅含非当日条目，When 提取，Then 返回空列表。"""
        today = datetime.datetime.now().isoweekday()
        other = 1 if today != 1 else 2
        calendar = [{"weekday": {"id": other}, "items": [{"name": "x"}]}]
        plugin = make_plugin()
        assert plugin._get_today_items(calendar) == []

    def test_empty_calendar_returns_empty(self, make_plugin):
        """Given 空日历，When 提取，Then 返回空列表。"""
        plugin = make_plugin()
        assert plugin._get_today_items([]) == []

    def test_day_missing_weekday_field_is_skipped(self, make_plugin):
        """Given 条目缺 weekday 字段，When 提取，Then 该条目被跳过。"""
        today = datetime.datetime.now().isoweekday()
        other = 1 if today != 1 else 2
        calendar = [
            {"items": [{"name": "no-weekday"}]},
            {"weekday": {"id": other}, "items": [{"name": "other-day"}]},
        ]
        plugin = make_plugin()
        assert plugin._get_today_items(calendar) == []


class TestCalculateSleepTime:
    """``_calculate_sleep_time``：推送时刻前后分别得到当日/跨日秒数。"""

    @pytest.fixture
    def fixed_clock(self, monkeypatch):
        """把 ``datetime.datetime.now`` 固定为指定时刻。

        Returns:
            callable: 接收 (year, month, day, hour, minute, second) 六元组，
            设定固定时刻并替换 ``datetime.datetime``。
        """

        def _use(when):
            _FixedClock.fixed = _FixedClock(*when)
            monkeypatch.setattr(plugin_main.datetime, "datetime", _FixedClock)

        return _use

    def test_before_push_time_same_day(self, make_plugin, fixed_clock):
        """Given 当前 06:00 且推送 07:00，When 计算，Then 当日 1 小时（3600 秒）。"""
        fixed_clock((2026, 8, 2, 6, 0, 0))
        plugin = make_plugin(push_time="07:00")
        assert plugin._calculate_sleep_time() == 3600.0

    def test_after_push_time_rolls_to_next_day(self, make_plugin, fixed_clock):
        """Given 当前 08:00 已过推送 07:00，When 计算，Then 跨到次日（82800 秒）。"""
        fixed_clock((2026, 8, 2, 8, 0, 0))
        plugin = make_plugin(push_time="07:00")
        assert plugin._calculate_sleep_time() == 82800.0


class TestGetProxy:
    """``_get_proxy``：配置优先，环境变量回退，均无则 None（直连）。"""

    def test_config_proxy_wins(self, make_plugin, monkeypatch):
        """Given 配置 proxy，When 读取，Then 返回该地址。"""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        plugin = make_plugin(proxy="http://127.0.0.1:7890")
        assert plugin._get_proxy() == "http://127.0.0.1:7890"

    def test_empty_config_falls_back_to_env(self, make_plugin, monkeypatch):
        """Given 配置 proxy 为空且存在 HTTP_PROXY，When 读取，Then 返回环境变量值。"""
        monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
        plugin = make_plugin(proxy="")
        assert plugin._get_proxy() == "http://env-proxy:8080"

    def test_no_config_no_env_returns_none(self, make_plugin, monkeypatch):
        """Given 配置 proxy 为空且无环境变量，When 读取，Then 返回 None（直连）。"""
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        plugin = make_plugin(proxy="")
        assert plugin._get_proxy() is None


class TestGetTargetUmos:
    """``_get_target_umos``：清洗空串/空白；按实际实现不去重。"""

    def test_cleans_whitespace_and_filters_empties(self, make_plugin):
        """Given 含空白/空串的脏输入，When 清洗，Then 保留去空白后的非空项。"""
        plugin = make_plugin(
            umos=[" Bot1:GroupMessage:111 ", "", "   ", "Bot2:GroupMessage:222"]
        )
        assert plugin._get_target_umos() == [
            "Bot1:GroupMessage:111",
            "Bot2:GroupMessage:222",
        ]

    def test_keeps_duplicates(self, make_plugin):
        """Given 含重复项，When 清洗，Then 重复项保留（实际行为：不去重）。"""
        plugin = make_plugin(umos=["a", "a", "a"])
        assert plugin._get_target_umos() == ["a", "a", "a"]

    def test_missing_config_returns_empty(self, make_plugin):
        """Given 配置无 umos，When 清洗，Then 返回空列表。"""
        plugin = make_plugin()
        assert plugin._get_target_umos() == []

    def test_none_item_kept_as_string(self, make_plugin):
        """Given 含 None 项，When 清洗，Then 转为字符串 "None" 保留（实际行为）。"""
        plugin = make_plugin(umos=[None, "b"])
        assert plugin._get_target_umos() == ["None", "b"]


class TestBuildStatusText:
    """``_build_status_text``：渲染状态文本（固定内部依赖保证确定性）。"""

    @staticmethod
    def _plugin(make_plugin, **config):
        plugin = make_plugin(**config)
        plugin._calculate_sleep_time = lambda: 3600.0  # 固定为 1 小时
        return plugin

    def test_full_text(self, make_plugin):
        """Given 完整配置，When 渲染，Then 文本含推送时间/目标数/代理/倒计时。"""
        plugin = self._plugin(make_plugin, push_time="07:00", umos=["a", "b"])
        plugin._get_proxy = lambda: "http://127.0.0.1:7890"
        assert plugin._build_status_text() == (
            "Bangumi新番日历插件\n"
            "推送时间: 07:00\n"
            "目标数: 2\n"
            "代理: http://127.0.0.1:7890\n"
            "距离下次推送: 1小时0分钟"
        )

    def test_no_proxy_shows_direct_connection(self, make_plugin):
        """Given 无代理，When 渲染，Then 代理行显示「直连」。"""
        plugin = self._plugin(make_plugin, push_time="07:00")
        plugin._get_proxy = lambda: None
        assert plugin._build_status_text() == (
            "Bangumi新番日历插件\n"
            "推送时间: 07:00\n"
            "目标数: 0\n"
            "代理: 直连\n"
            "距离下次推送: 1小时0分钟"
        )


class TestFetchCalendar:
    """``_fetch_calendar``：proxy 传入 httpx.AsyncClient，失败返回 None。"""

    @staticmethod
    async def _ok_response(url):
        """模拟返回 HTTP 200 的日历响应。

        Args:
            url: 请求地址（忽略）。

        Returns:
            _FakeResponse: 模拟响应。
        """
        return _FakeResponse()

    @staticmethod
    def _install_fake_client(monkeypatch, get_impl):
        """用记录型假客户端替换 ``httpx.AsyncClient`` 并捕获构造参数。

        Args:
            monkeypatch: pytest 的 monkeypatch fixture。
            get_impl: 接收 url、返回模拟响应的异步函数。

        Returns:
            dict: 捕获到的 ``AsyncClient(**kwargs)`` 构造参数。
        """
        captured = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured["kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                captured["url"] = url
                return await get_impl(url)

        monkeypatch.setattr(plugin_main.httpx, "AsyncClient", FakeClient)
        return captured

    def test_proxy_passed_to_async_client(self, make_plugin, monkeypatch):
        """Given 配置了 proxy，When 抓取日历，Then proxy 参数传入 httpx.AsyncClient。"""
        captured = self._install_fake_client(monkeypatch, self._ok_response)
        plugin = make_plugin(proxy="http://127.0.0.1:7890")
        result = asyncio.run(plugin._fetch_calendar())
        assert captured["kwargs"]["proxy"] == "http://127.0.0.1:7890"
        assert result == [{"weekday": {"id": 1}, "items": []}]

    def test_no_proxy_passes_none(self, make_plugin, monkeypatch):
        """Given 未配置代理，When 抓取日历，Then proxy=None 传入 httpx.AsyncClient。"""
        captured = self._install_fake_client(monkeypatch, self._ok_response)
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        monkeypatch.delenv("HTTPS_PROXY", raising=False)
        plugin = make_plugin(proxy="")
        asyncio.run(plugin._fetch_calendar())
        assert captured["kwargs"]["proxy"] is None

    def test_failure_returns_none(self, make_plugin, monkeypatch):
        """Given 请求抛 httpx.HTTPError 且 max_retries=1，When 抓取，Then 返回 None 不崩溃。

        异常收窄后 ``fetch_calendar`` 只捕获 httpx.HTTPError 与 json.JSONDecodeError，
        故用 ``httpx.ConnectError`` 触发重试路径；RuntimeError 等未知异常会直接传播。
        """

        async def boom(url):
            raise httpx.ConnectError("connection refused")

        self._install_fake_client(monkeypatch, boom)
        plugin = make_plugin(proxy="", max_retries=1)
        assert asyncio.run(plugin._fetch_calendar()) is None


class TestRenderImage:
    """``_render_image``：排序后按 max_items 截断；无数据时返回 None。"""

    @staticmethod
    def _sample_items():
        """构造评分依次为 1/9/5 的 3 条番剧。"""
        return [
            {"id": 1, "name": "A", "rating": {"score": 1.0}},
            {"id": 2, "name": "B", "rating": {"score": 9.0}},
            {"id": 3, "name": "C", "rating": {"score": 5.0}},
        ]

    @staticmethod
    def _plugin(make_plugin, max_items=0):
        """构造渲染路径上所有外部依赖均已打桩的插件。

        Args:
            make_plugin: conftest 提供的插件工厂。
            max_items: max_items 配置值。

        Returns:
            BangumiCalendarPlugin: 已打桩的插件实例。
        """
        plugin = make_plugin(max_items=max_items)
        plugin._fetch_calendar = AsyncMock(
            return_value=[{"weekday": {"id": 1}, "items": TestRenderImage._sample_items()}]
        )
        plugin._get_today_items = lambda calendar: calendar[0]["items"]
        plugin._download_covers = AsyncMock(return_value={})
        plugin.html_render = AsyncMock(return_value="https://example.com/card.png")
        return plugin

    def test_max_items_truncates_after_sort(self, make_plugin):
        """Given max_items=2，When 渲染，Then 先按评分降序再截断前 2 部。"""
        plugin = self._plugin(make_plugin, max_items=2)
        url = asyncio.run(plugin._render_image())
        template_data = plugin.html_render.call_args.args[1]
        assert url == "https://example.com/card.png"
        assert template_data["count"] == 2
        assert [item["name"] for item in template_data["items"]] == ["B", "C"]

    def test_no_today_items_returns_none(self, make_plugin):
        """Given 当日无番剧，When 渲染，Then 返回 None。"""
        plugin = make_plugin()
        plugin._fetch_calendar = AsyncMock(
            return_value=[{"weekday": {"id": 1}, "items": []}]
        )
        assert asyncio.run(plugin._render_image()) is None

    def test_empty_calendar_returns_none(self, make_plugin):
        """Given 抓取结果为空，When 渲染，Then 返回 None。"""
        plugin = make_plugin()
        plugin._fetch_calendar = AsyncMock(return_value=None)
        assert asyncio.run(plugin._render_image()) is None
