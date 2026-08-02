"""service.fetch_ranks 单元测试：并发获取 Bangumi 全站排名的正确性与降级。

所有测试 hermetic：通过替换 ``httpx.AsyncClient`` 为假客户端，不发起真实网络请求。
"""

import asyncio

import httpx

import astrbot_plugin_bangumi_calendar.service as service_mod

_SUBJECTS_URL = "https://api.bgm.tv/v0/subjects"


class _RankResponse:
    """模拟 ``/v0/subjects/{id}`` 的 JSON 响应。"""

    def __init__(self, status_code=200, json_body=None):
        """初始化。

        Args:
            status_code: HTTP 状态码。
            json_body: ``json()`` 返回的响应体。
        """
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {"rating": {"rank": None}}

    def json(self):
        """返回固定响应体。

        Returns:
            dict: 响应体。
        """
        return self._json_body


def _item(anime_id):
    """构造含整数 id 的番剧条目。

    Args:
        anime_id: Bangumi 条目 ID。

    Returns:
        dict: 最小番剧条目。
    """
    return {"id": anime_id}


class TestFetchRanks:
    """``fetch_ranks``：成功提取、0/缺失视为未上榜、失败降级为 None。"""

    @staticmethod
    def _install_fake_client(monkeypatch, responses=None, exc_by_url=None):
        """替换 ``httpx.AsyncClient`` 并记录请求，按 URL 返回固定响应或抛异常。

        Args:
            monkeypatch: pytest 的 monkeypatch fixture。
            responses: URL 到响应对象的映射。
            exc_by_url: URL 到异常实例的映射（该 URL 的请求直接抛异常）。

        Returns:
            dict: 记录 ``calls``（请求 URL 列表）、``instances``（客户端实例数）
            与 ``kwargs``（首次实例化的构造参数）。
        """
        state = {"calls": [], "instances": 0, "kwargs": None}
        responses = responses or {}
        exc_by_url = exc_by_url or {}

        class FakeClient:
            def __init__(self, **kwargs):
                state["instances"] += 1
                state["kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, **kwargs):
                state["calls"].append(url)
                if url in exc_by_url:
                    raise exc_by_url[url]
                return responses[url]

        monkeypatch.setattr(service_mod.httpx, "AsyncClient", FakeClient)
        return state

    def test_returns_rank_for_each_subject(self, monkeypatch):
        """Given 两个条目各有排名，When 并发获取，Then 返回 id → rank 映射且走 v0/subjects。"""
        responses = {
            f"{_SUBJECTS_URL}/42": _RankResponse(json_body={"rating": {"rank": 9565}}),
            f"{_SUBJECTS_URL}/7": _RankResponse(json_body={"rating": {"rank": 1234}}),
        }
        state = self._install_fake_client(monkeypatch, responses)
        result = asyncio.run(service_mod.fetch_ranks([_item(42), _item(7)], None))
        assert result == {42: 9565, 7: 1234}
        assert set(state["calls"]) == {f"{_SUBJECTS_URL}/42", f"{_SUBJECTS_URL}/7"}

    def test_rank_zero_becomes_none(self, monkeypatch):
        """Given rank 为 0（未上榜），When 获取，Then 映射为 None。"""
        state = self._install_fake_client(
            monkeypatch, {f"{_SUBJECTS_URL}/42": _RankResponse(json_body={"rating": {"rank": 0}})}
        )
        assert asyncio.run(service_mod.fetch_ranks([_item(42)], None)) == {42: None}
        assert state["calls"] == [f"{_SUBJECTS_URL}/42"]

    def test_missing_rating_becomes_none(self, monkeypatch):
        """Given 响应无 rating 或无 rank 字段，When 获取，Then 映射为 None。"""
        responses = {
            f"{_SUBJECTS_URL}/1": _RankResponse(json_body={"rating": {}}),
            f"{_SUBJECTS_URL}/2": _RankResponse(json_body={}),
        }
        self._install_fake_client(monkeypatch, responses)
        assert asyncio.run(service_mod.fetch_ranks([_item(1), _item(2)], None)) == {1: None, 2: None}

    def test_non_200_returns_none(self, monkeypatch):
        """Given 接口返回 404，When 获取，Then 该项为 None。"""
        responses = {f"{_SUBJECTS_URL}/42": _RankResponse(status_code=404)}
        self._install_fake_client(monkeypatch, responses)
        assert asyncio.run(service_mod.fetch_ranks([_item(42)], None)) == {42: None}

    def test_request_error_degrades_to_none(self, monkeypatch):
        """Given 某个条目请求抛 ConnectError，When 获取，Then 该项 None 且整体不崩。"""
        responses = {f"{_SUBJECTS_URL}/7": _RankResponse(json_body={"rating": {"rank": 1234}})}
        exc_by_url = {f"{_SUBJECTS_URL}/42": httpx.ConnectError("refused")}
        self._install_fake_client(monkeypatch, responses, exc_by_url)
        result = asyncio.run(service_mod.fetch_ranks([_item(42), _item(7)], None))
        assert result == {42: None, 7: 1234}

    def test_client_instantiated_once(self, monkeypatch):
        """Given 多个条目，When 并发获取，Then AsyncClient 只实例化一次。"""
        responses = {f"{_SUBJECTS_URL}/{i}": _RankResponse(json_body={"rating": {"rank": i}}) for i in range(5)}
        state = self._install_fake_client(monkeypatch, responses)
        asyncio.run(service_mod.fetch_ranks([_item(i) for i in range(5)], None))
        assert state["instances"] == 1

    def test_sends_user_agent_header(self, monkeypatch):
        """Given 正常调用，When 创建客户端，Then 携带 Bangumi 请求头。"""
        state = self._install_fake_client(
            monkeypatch, {f"{_SUBJECTS_URL}/42": _RankResponse(json_body={"rating": {"rank": 1}})}
        )
        asyncio.run(service_mod.fetch_ranks([_item(42)], None))
        assert "User-Agent" in state["kwargs"]["headers"]
        assert state["kwargs"]["headers"]["User-Agent"]

    def test_max_concurrency_capped(self, monkeypatch):
        """Given 12 个条目且请求耗时，When 并发获取，Then 最大并发等于信号量限制。"""
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
                return _RankResponse(json_body={"rating": {"rank": 1}})

        monkeypatch.setattr(service_mod.httpx, "AsyncClient", FakeClient)
        result = asyncio.run(service_mod.fetch_ranks([_item(i) for i in range(12)], None))
        assert len(result) == 12
        assert state["max"] == 5  # 信号量将并发钳制在限制值
