"""巨量引擎 Marketing API 的 wire 契约。

巨量是全仓唯一「凭证走 header 且完全不签名」的平台，与基类假设正面冲突 ——
本文件把这个差异钉住，防止有人"顺手统一"回基类那套。

官方依据（公开无鉴权，见 mission spec §2.3.1 的文档后端接口）：
- header 字段全语料只有 Access-Token / Content-Type / App-Access-Token 三种
- 全量 1053 篇官方文档中 sign_method 零命中，无「公共参数」章节
- 487 篇 v3.0 文档 100% 使用 api.oceanengine.com
- 判错为 body 的 code != 0，消息字段是 message
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

# 官方公共参数里不存在的字段 —— 出现任何一个就说明退回了基类那套
FORBIDDEN_PARAMS = {"sign", "sign_method", "app_key", "timestamp", "access_token", "secret"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OCEANENGINE_APP_KEY", "k")
    monkeypatch.setenv("OCEANENGINE_APP_SECRET", "s")
    monkeypatch.setenv("OCEANENGINE_ACCESS_TOKEN", "tok")
    from servers.oceanengine.server import OceanEngine

    return OceanEngine(app_key="k", app_secret="s", access_token="tok")


async def test_token_travels_in_a_header_not_the_query(client, wire):
    await client._request("GET", "2/advertiser/info/", params={"advertiser_ids": [1, 2]})

    assert len(wire) == 1
    req = wire[0]
    assert req.headers.get("Access-Token") == "tok"
    assert "access_token" not in req.query


async def test_nothing_is_signed(client, wire):
    """巨量不签名 —— 基类会加 5 个参数，这里一个都不该出现。"""
    await client._request("GET", "2/advertiser/fund/get/", params={"advertiser_id": 7})

    leaked = FORBIDDEN_PARAMS & set(wire[0].query)
    assert not leaked, f"发出了巨量不接受的参数：{sorted(leaked)}（说明退回了基类的签名路径）"


async def test_host_is_the_v3_documented_one(client, wire):
    await client._request("GET", "2/advertiser/info/", params={"advertiser_ids": [1]})

    assert wire[0].host == "api.oceanengine.com"
    # 另一个官方 host 保留可追溯，但不作为默认；不声明二者等价。
    from servers.oceanengine.server import OceanEngine

    assert OceanEngine.LEGACY_BASE_URL.startswith("https://ad.oceanengine.com/")


async def test_list_params_are_json_serialised(client, wire):
    await client._request("GET", "2/advertiser/info/", params={"advertiser_ids": [1, 2]})

    assert wire[0].query["advertiser_ids"] == "[1,2]"


async def test_failure_is_read_from_body_code_and_message(client, monkeypatch):
    """官方从未规定错误时的 HTTP 状态码 —— 必须以 body 的 code 为唯一判据。"""

    from shared.cn_commerce_base import CommerceAPIError

    class _Resp:
        status_code = 200  # 刻意为 200：证明我们不依赖 HTTP status

        @staticmethod
        def json():
            return {"code": 40105, "message": "access_token无效"}

    class _Client:
        async def get(self, *_, **__):
            return _Resp()

        async def post(self, *_, **__):
            return _Resp()

    monkeypatch.setattr(client, "_ensure_client", lambda: _make_awaitable(_Client()))

    with pytest.raises(CommerceAPIError) as exc:
        await client._request("GET", "2/advertiser/info/", params={"advertiser_ids": [1]})

    assert exc.value.code == 40105
    # 消息字段是 message 而非 msg —— 读错会让所有巨量报错退化成 "unknown"
    assert "access_token无效" in exc.value.msg


def _make_awaitable(value):
    async def _inner():
        return value

    return _inner()
