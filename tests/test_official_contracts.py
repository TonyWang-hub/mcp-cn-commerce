"""Public official examples and HTTPX wire contracts; no merchant credentials."""

import hashlib
import json
import re

import httpx
import pytest

from servers.taobao.server import TaobaoMCP
from servers.weixin_store import server as wx


def test_top_published_md5_vector():
    client = TaobaoMCP(app_key="12345678", app_secret="helloworld", access_token="test")
    params = dict(
        method="taobao.item.seller.get",
        app_key="12345678",
        session="test",
        timestamp="2016-01-01 12:00:00",
        format="json",
        v="2.0",
        sign_method="md5",
        fields="num_iid,title,nick,price,num",
        num_iid="11223344",
    )
    assert client._sign(params) == "66987CB115214E59E6EC978214934FB8"


@pytest.mark.asyncio
async def test_top_session_timestamp_and_signature_on_wire():
    requests = []
    client = TaobaoMCP(app_key="k", app_secret="s", access_token="t")

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"trades_sold_get_response": {"total_results": 0, "trades": {"trade": []}}})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await client._call("taobao.trades.sold.get", {"fields": "tid,payment"})
        request = requests[0]
        params = dict(request.url.params)
        assert params["session"] == "t"
        assert "access_token" not in params
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", params["timestamp"])
        assert params["sign_method"] == "md5"
        raw = "s" + "".join(k + v for k, v in sorted(params.items()) if k != "sign") + "s"
        assert params["sign"] == hashlib.md5(raw.encode()).hexdigest().upper()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_weixin_order_cursor_and_seconds(monkeypatch):
    requests = []
    client = wx.WeixinStoreMCP(access_token="fixture-token")

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"errcode": 0, "order_id_list": ["42"], "has_more": False})

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(wx, "_wx", client)
    try:
        await wx.get_order_list("2026-09-10 00:00:00", "2026-09-10 01:00:00", next_key="cursor")
        body = json.loads(requests[0].content)
        assert body == {
            "create_time_range": {"start_time": 1788969600, "end_time": 1788973200},
            "page_size": 20,
            "next_key": "cursor",
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_weixin_order_rejects_unrepresentable_page_and_window():
    with pytest.raises(ValueError, match="next_key"):
        await wx.get_order_list("2026-09-01", "2026-09-02", page=2)
    with pytest.raises(ValueError, match="7 days"):
        await wx.get_order_list("2026-09-01", "2026-09-10")


def test_weixin_official_order_statuses():
    from shared.normalizer import normalize_order_status

    assert normalize_order_status(100, "weixin") == "completed"
    assert normalize_order_status(250, "weixin") == "cancelled"
    assert normalize_order_status(50, "weixin") == "unknown"


def test_xhs_completed_refund_without_actual_time_is_incomplete():
    from shared.aggregation import build_daily_report
    from shared.normalizer import Normalizer

    raw = {
        "returnsId": "r",
        "orderId": "o",
        "status": 4,
        "expectedRefundAmountYuan": 12.5,
        "applyTime": 1788969600000,
        "updatedAt": 1788969600000,
    }
    refund = Normalizer().normalize_refund(raw, "xiaohongshu")
    assert refund.refund_id == "r"
    assert refund.status == "completed"
    assert refund.amount is None
    assert refund.completed_at is None
    report = build_daily_report(
        "2026-09-10",
        [
            {
                "platform": "xiaohongshu",
                "shop_id": "s",
                "input_format": "raw",
                "orders": [],
                "refunds": [raw],
                "coverage": {
                    "2026-09-10": {"orders": True, "refunds": True},
                    "2026-09-09": {"orders": True, "refunds": True},
                },
            }
        ],
        timezone="Asia/Shanghai",
    )
    assert report["complete"] is False
    assert report["total_summary"]["refund_amount"] is None


@pytest.mark.asyncio
async def test_sdk_default_http_logging_redacts_query_credentials(caplog):
    import logging

    # Importing the actual server configures SDK logging and common tools.
    client = wx.WeixinStoreMCP(access_token="fixture-query-secret-value")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    try:
        with caplog.at_level(logging.INFO, logger="httpx"):
            await client._request("GET", "/channels/ec/order/get")
        assert "HTTP Request" in caplog.text
        assert "fixture-query-secret-value" not in caplog.text
        assert "****" in caplog.text
    finally:
        await client.close()


def test_xhs_official_order_state_mapping():
    from shared.normalizer import normalize_order_status

    assert normalize_order_status(1, "xiaohongshu") == "pending"
    assert normalize_order_status(4, "xiaohongshu") == "paid"
    assert normalize_order_status(5, "xiaohongshu") == "paid"
    assert normalize_order_status(7, "xiaohongshu") == "completed"
    assert normalize_order_status(9, "xiaohongshu") == "cancelled"
