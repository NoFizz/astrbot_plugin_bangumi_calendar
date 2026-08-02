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


class _FakeResponse:
    """模拟封面下载的 HTTP 200 响应。"""

    status_code = 200

    def __init__(self, content=b"", content_type="image/jpeg"):
        """初始化。

        Args:
            content: 响应体字节。
            content_type: content-type 响应头。
        """
        self.content = content
        self.headers = {"content-type": content_type}


class TestCoverCache:
    """``download_covers`` 的 MIME 感知缓存：命中/损坏/原子写入。"""

    @staticmethod
    def _install_fake_client(monkeypatch, resp):
        """用固定响应的假客户端替换 ``httpx.AsyncClient``，记录请求 URL。

        Args:
            monkeypatch: pytest 的 monkeypatch fixture。
            resp: 固定响应对象。

        Returns:
            list: 记录的请求 URL。
        """
        calls = []

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                calls.append(url)
                return resp

        monkeypatch.setattr(service_mod.httpx, "AsyncClient", FakeClient)
        return calls

    @staticmethod
    def _item(anime_id, url):
        """构造一条带封面 URL 的番剧条目。

        Args:
            anime_id: Bangumi 条目 ID。
            url: 封面 URL。

        Returns:
            dict: 番剧条目。
        """
        return {"id": anime_id, "images": {"large": url}}

    def test_png_cache_hit(self, monkeypatch, tmp_path):
        """Given 已有 .png 种子缓存，When 下载，Then 命中并返回 data:image/png。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        Path(tmp_path, "42.png").write_bytes(png_bytes)
        result = asyncio.run(service_mod.download_covers([self._item(42, "http://x/42.png")], None))
        expected = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        assert result == {"http://x/42.png": expected}

    def test_webp_download_stores_webp_ext(self, monkeypatch, tmp_path):
        """Given 响应 content-type 为 image/webp，When 下载，Then 缓存文件为 {id}.webp。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))
        content = b"\x00" * 200
        resp = _FakeResponse(content=content, content_type="image/webp; charset=utf-8")
        self._install_fake_client(monkeypatch, resp)
        result = asyncio.run(service_mod.download_covers([self._item(7, "http://x/7.webp")], None))
        assert Path(tmp_path, "7.webp").is_file()
        assert result["http://x/7.webp"].startswith("data:image/webp;base64,")

    def test_legacy_no_ext_cache_hit(self, monkeypatch, tmp_path):
        """Given 存在无扩展名的旧缓存文件，When 下载，Then 按 image/jpeg 命中。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))
        content = b"\x00" * 100
        Path(tmp_path, "5").write_bytes(content)
        result = asyncio.run(service_mod.download_covers([self._item(5, "http://x/5")], None))
        assert result == {"http://x/5": f"data:image/jpeg;base64,{base64.b64encode(content).decode()}"}

    def test_corrupt_cache_redownloads(self, monkeypatch, tmp_path):
        """Given 缓存文件损坏（读取抛 OSError），When 下载，Then 删除损坏文件并重新下载。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))
        Path(tmp_path, "9.jpg").write_bytes(b"corrupt")

        def boom(path, mime):
            raise OSError("corrupt cache")

        monkeypatch.setattr(service_mod, "_load_cover_file", boom)
        removed = []
        real_remove = os.remove

        def record_remove(path):
            removed.append(path)
            real_remove(path)

        monkeypatch.setattr(service_mod.os, "remove", record_remove)
        content = b"\x00" * 200
        calls = self._install_fake_client(monkeypatch, _FakeResponse(content=content))
        result = asyncio.run(service_mod.download_covers([self._item(9, "http://x/9.jpg")], None))
        assert calls == ["http://x/9.jpg"]  # 缓存未命中，重新下载
        assert removed == [str(Path(tmp_path, "9.jpg"))]  # 损坏文件被删除
        assert result["http://x/9.jpg"].startswith("data:image/jpeg;base64,")

    def test_replace_failure_cleans_tmp(self, monkeypatch, tmp_path):
        """Given os.replace 抛异常，When 下载，Then 不崩溃、tmp 文件被清理、结果不含该 URL。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(service_mod.os, "replace", boom)
        self._install_fake_client(monkeypatch, _FakeResponse(content=b"\x00" * 200))
        result = asyncio.run(service_mod.download_covers([self._item(3, "http://x/3.jpg")], None))
        assert result == {}
        assert list(tmp_path.glob("*.tmp")) == []


class TestSafeAnimeId:
    """``safe_anime_id``：合法整数原样返回，非法输入回退为 SHA1 摘要前 12 位。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("123", "123"),
            (123, "123"),
            ("abc", hashlib.sha1(b"abc").hexdigest()[:12]),
            ("../evil", hashlib.sha1(b"../evil").hexdigest()[:12]),
            ("", hashlib.sha1(b"").hexdigest()[:12]),
        ],
    )
    def test_safe_anime_id(self, raw, expected):
        """Given 任意输入，When 安全化，Then 返回合法整数或摘要片段。"""
        assert parser_mod.safe_anime_id(raw) == expected

    def test_get_cache_path_sanitized(self, make_plugin):
        """Given 恶意 anime_id 含路径分隔符，When 取缓存路径，Then 不出现 `..` 且路径安全。"""
        plugin = make_plugin()
        path = plugin._get_cache_path("../evil")
        assert os.path.dirname(path) == plugin_main._COVERS_DIR
        assert os.path.basename(path) == parser_mod.safe_anime_id("../evil") + ".jpg"
        assert ".." not in os.path.basename(path)


class TestDownloadConcurrency:
    """``download_covers`` 的并发限流：最大并发不超过 ``_DOWNLOAD_SEM_LIMIT``。"""

    def test_max_concurrency_capped(self, monkeypatch, tmp_path):
        """Given 12 个待下载条目且下载耗时，When 并发下载，Then 最大并发恰好等于限制值。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))
        state = {"active": 0, "max": 0}

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
                await asyncio.sleep(0.02)
                state["active"] -= 1
                return _FakeResponse(content=b"\x00" * 200)

        monkeypatch.setattr(service_mod.httpx, "AsyncClient", FakeClient)
        items = [
            {"id": i, "images": {"large": f"http://x/{i}.jpg"}} for i in range(12)
        ]
        result = asyncio.run(service_mod.download_covers(items, None))
        assert len(result) == 12
        assert state["max"] == 5  # 信号量将并发钳制在限制值


class TestFileIOOffload:
    """文件操作（缓存读/写/utime）必须通过 ``asyncio.to_thread`` 执行，避免阻塞事件循环。"""

    def test_cache_io_goes_through_to_thread(self, monkeypatch, tmp_path):
        """Given 同时有缓存命中与需要下载的条目，When 下载，Then 读写均走线程。"""
        monkeypatch.setattr(service_mod, "_COVERS_DIR", str(tmp_path))
        calls = []
        real_to_thread = asyncio.to_thread

        async def fake_to_thread(fn, *args):
            calls.append(fn.__name__)
            return await real_to_thread(fn, *args)

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        Path(tmp_path, "1.png").write_bytes(png_bytes)
        resp = _FakeResponse(content=b"\x00" * 200)
        TestCoverCache._install_fake_client(monkeypatch, resp)
        items = [TestCoverCache._item(1, "http://x/1.png"), TestCoverCache._item(2, "http://x/2.jpg")]
        result = asyncio.run(service_mod.download_covers(items, None))
        assert "http://x/1.png" in result  # 命中缓存
        assert "http://x/2.jpg" in result  # 走下载
        assert "_read_cached_cover" in calls
        assert "_store_cached_cover" in calls


class _ErrorClient:
    """每次请求都抛指定异常的假客户端，并记录实例化次数。"""

    instances = 0

    def __init__(self, exc):
        """初始化。

        Args:
            exc: 每次 get 抛出的异常实例。
        """
        self.exc = exc
        type(self).instances += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise self.exc


class TestFetchCalendarNarrow:
    """``fetch_calendar`` 只捕获 httpx.HTTPError 与 json.JSONDecodeError。"""

    @pytest.fixture(autouse=True)
    def _reset_instances(self):
        """每个用例前重置实例计数。"""
        _ErrorClient.instances = 0
        yield

    def test_connect_error_retries_then_none(self, monkeypatch):
        """Given 每次请求抛 httpx.ConnectError 且 retries=3，When 抓取，Then 重试耗尽返回 None。"""
        sleeps = []
        monkeypatch.setattr(
            asyncio, "sleep", AsyncMock(side_effect=lambda s: sleeps.append(s))
        )
        monkeypatch.setattr(
            service_mod.httpx, "AsyncClient", lambda **kw: _ErrorClient(httpx.ConnectError("refused"))
        )
        assert asyncio.run(service_mod.fetch_calendar(3, None)) is None
        assert sleeps == [3, 6]

    def test_runtime_error_propagates(self, monkeypatch):
        """Given 请求抛 RuntimeError，When 抓取，Then 异常直接传播（pytest.raises）。"""
        monkeypatch.setattr(
            service_mod.httpx, "AsyncClient", lambda **kw: _ErrorClient(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError):
            asyncio.run(service_mod.fetch_calendar(2, None))


class TestAsyncClientReuse:
    """``fetch_calendar`` 复用单个 AsyncClient：重试循环外创建一次。"""

    @pytest.fixture(autouse=True)
    def _reset_instances(self):
        """每个用例前重置实例计数。"""
        _ErrorClient.instances = 0
        yield

    def test_client_instantiated_once_across_retries(self, monkeypatch):
        """Given 多次重试，When 抓取，Then AsyncClient 只实例化一次。"""
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(
            service_mod.httpx, "AsyncClient", lambda **kw: _ErrorClient(httpx.ConnectError("refused"))
        )
        assert asyncio.run(service_mod.fetch_calendar(5, None)) is None
        assert _ErrorClient.instances == 1


class TestCleanUmosDedup:
    """``clean_umos`` 保持顺序去重，避免同一目标被重复推送。"""

    def test_deduplicates_keeping_order(self, make_plugin):
        """Given 含重复项的目标列表，When 清洗，Then 按首次出现顺序去重。"""
        plugin = make_plugin(umos=["a", "b", "a", "c", "b"])
        assert plugin._get_target_umos() == ["a", "b", "c"]

    def test_dedup_after_strip(self, make_plugin):
        """Given 重复项仅空白不同，When 清洗，Then 去空白后视为同一目标。"""
        plugin = make_plugin(umos=["a", " a ", "a"])
        assert plugin._get_target_umos() == ["a"]
