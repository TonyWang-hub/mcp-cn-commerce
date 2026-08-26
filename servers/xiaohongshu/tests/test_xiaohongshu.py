"""Tests for Xiaohongshu MCP server tools.

重写自旧版：旧测试断言 ``_call("GET", "/api/order/list", ...)``，那三样（HTTP 动词、
REST path、参数名）在官方契约里都不存在。现在断言的是官方 method 名与官方业务参数名。

注意本文件 mock 在 ``xhs._call`` 层，所以覆盖不到系统参数与签名 —— 那部分由
``tests/contract/test_wire_xiaohongshu.py`` 在 wire 层断言（旧实现的系统参数缺陷正是
因为所有测试都 mock 在 ``_call`` 之上才长期无人发现）。
"""

from __future__ import annotations

import json

# Must patch env BEFORE importing the server module (it reads env at import time)
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("XHS_CLIENT_ID", "test_client_id")
os.environ.setdefault("XHS_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("XHS_ACCESS_TOKEN", "test_access_token")

from servers.xiaohongshu.server import (
    API_VERSION,
    CONTENT_TYPE,
    GATEWAY_165_2804,
    GATEWAY_URL,
    METHOD_GATEWAY,
    SIGNED_PARAMS,
    XiaohongshuMCP,
    get_account_records,
    get_expense_settlements,
    get_inventory,
    get_logistics_tracking,
    get_monthly_statement_url,
    get_order_detail,
    get_order_list,
    get_product_detail,
    get_product_list,
    get_refund_detail,
    get_refund_list,
    get_settlement_transactions,
)
from shared.cn_commerce_base import CommerceAPIError

# ── Fixtures ─────────────────────────────────────────────────────────────────────


def _live_client():
    """当前模块绑定的客户端实例。

    刻意每次动态取而不是 import 时抓一份：``tests/test_api_compatibility.py`` 会
    ``importlib.reload`` 本 server 模块，reload 会在同一个模块字典里把 ``xhs``
    重新绑定成新实例。工具函数在调用时读模块全局，所以只有 patch「当前」那个实例
    才有效；抓陈旧引用会让本文件在全量跑（含那个 reload 测试）时整片变红。
    """
    import servers.xiaohongshu.server as mod

    return mod.xhs


@pytest.fixture
def mock_call():
    """Patch the live client's ``_call`` with an AsyncMock, reset after each test."""
    with patch.object(_live_client(), "_call", new_callable=AsyncMock) as mock:
        mock.return_value = {}
        yield mock


def _sent(mock_call) -> tuple[str, dict]:
    """Return (api_method, biz_params) of the single recorded ``_call``."""
    args = mock_call.call_args[0]
    return args[0], args[1]


# ═══════════════════════════════════════════════════════════════════════════════════
# 契约常量
# ═══════════════════════════════════════════════════════════════════════════════════


def test_single_gateway_url_is_ark_not_open():
    """网关是 ark.xiaohongshu.com 的 common_controller，不是 open. 文档站。"""
    assert GATEWAY_URL == "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"
    assert "open.xiaohongshu.com" not in GATEWAY_URL
    assert XiaohongshuMCP.BASE_URL == GATEWAY_URL


def test_contract_constants():
    assert API_VERSION == "2.0"
    assert CONTENT_TYPE == "application/json;charset=utf-8"
    assert SIGNED_PARAMS == {"method", "appId", "timestamp", "version"}


def test_no_rest_paths_remain():
    """曾经虚构的 REST path 一个都不许再出现在 method 表里。"""
    for method in METHOD_GATEWAY:
        assert not method.startswith("/"), method
        assert "." in method, f"官方 method 形如 domain.action，得到 {method}"


def test_method_gateway_covers_every_tool_method():
    """每个工具用的 method 都必须登记网关版本族（含混排的 165/2804）。"""
    assert METHOD_GATEWAY["order.getOrderList"] == "103/1661"
    assert METHOD_GATEWAY["bill.downloadStatement"] == "103/1661"
    assert METHOD_GATEWAY["afterSale.listAfterSaleInfos"] == GATEWAY_165_2804
    assert METHOD_GATEWAY["finance.pageQueryTransaction"] == GATEWAY_165_2804
    assert METHOD_GATEWAY["inventory.getSkuStockV2"] == GATEWAY_165_2804


@pytest.mark.asyncio
async def test_unregistered_method_is_rejected():
    """未登记的 method 直接拒绝，避免再打到不存在的接口上。"""
    client = XiaohongshuMCP(app_key="k", app_secret="s", access_token="t")
    with pytest.raises(ValueError, match="未登记的 method"):
        await client._call("order.thisDoesNotExist", {})


# ═══════════════════════════════════════════════════════════════════════════════════
# 删除的 4 个工具
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "removed",
    ["get_review_list", "get_shop_info", "list_promotions", "list_coupons"],
)
def test_platform_unsupported_tools_are_gone(removed):
    """平台不提供这四类能力，改名救不了，必须删除而不是打到假接口上。"""
    import servers.xiaohongshu.server as mod

    assert not hasattr(mod, removed), f"{removed} 应已删除（小红书开放平台无对应 method）"


# ═══════════════════════════════════════════════════════════════════════════════════
# 订单
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_order_list_uses_official_method_and_params(mock_call):
    mock_call.return_value = {"total": 1, "maxPageNo": 1, "orderList": [{"orderId": "P1"}]}

    result = json.loads(await get_order_list(start_time=1612518379, end_time=1612518380))

    assert result["orderList"][0]["orderId"] == "P1"
    method, biz = _sent(mock_call)
    assert method == "order.getOrderList"
    assert biz == {
        "startTime": 1612518379,
        "endTime": 1612518380,
        "timeType": 1,
        "orderType": 0,
        "orderStatus": 0,
        "pageNo": 1,
        "pageSize": 50,
    }


@pytest.mark.asyncio
async def test_get_order_list_time_params_are_seconds_not_millis(mock_call):
    """业务入参是秒：10 位。旧实现发的是 13 位毫秒。"""
    await get_order_list(start_time=1612518379, end_time=1612518380)
    _, biz = _sent(mock_call)
    assert len(str(biz["startTime"])) == 10
    assert len(str(biz["endTime"])) == 10


@pytest.mark.asyncio
async def test_get_order_list_rejects_window_over_24h_for_create_time(mock_call):
    with pytest.raises(ValueError, match="24 小时"):
        await get_order_list(start_time=0, end_time=24 * 3600 + 1, time_type=1)
    mock_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_rejects_window_over_30min_for_update_time(mock_call):
    with pytest.raises(ValueError, match="30 分钟"):
        await get_order_list(start_time=0, end_time=30 * 60 + 1, time_type=2)
    mock_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_order_list_rejects_paging_beyond_official_caps(mock_call):
    with pytest.raises(ValueError, match="上限均为 100"):
        await get_order_list(start_time=0, end_time=10, page_no=101)
    with pytest.raises(ValueError, match="上限均为 100"):
        await get_order_list(start_time=0, end_time=10, page_size=101)


@pytest.mark.asyncio
async def test_get_order_list_docstring_records_reverse_paging_requirement():
    """timeType=2 必须从 maxPageNo 倒着翻，否则增量同步漏单 —— docstring 必须写出来。"""
    doc = get_order_list.__doc__ or ""
    assert "maxPageNo" in doc
    assert "漏单" in doc
    assert "10000" in doc


@pytest.mark.asyncio
async def test_get_order_detail_sends_camel_case_order_id(mock_call):
    mock_call.return_value = {"orderId": "P1", "createdTime": 1612518379000}
    await get_order_detail(order_id="P1")
    assert _sent(mock_call) == ("order.getOrderDetail", {"orderId": "P1"})


@pytest.mark.asyncio
async def test_get_logistics_tracking_uses_order_tracking_method(mock_call):
    mock_call.return_value = {"orderTrackInfos": []}
    await get_logistics_tracking(order_id="P1")
    assert _sent(mock_call) == ("order.getOrderTracking", {"orderId": "P1"})


# ═══════════════════════════════════════════════════════════════════════════════════
# 商品
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_product_list_uses_item_granularity(mock_call):
    """粒度决策：ITEM（searchItemList），与 getItemInfo 的 ID 空间一致。"""
    mock_call.return_value = {"total": 0}
    await get_product_list()
    method, biz = _sent(mock_call)
    assert method == "product.searchItemList"
    assert biz == {"pageNo": 1, "pageSize": 50, "searchParam": {}}


@pytest.mark.asyncio
async def test_get_product_list_filters_go_into_search_param(mock_call):
    await get_product_list(page_no=2, page_size=10, keyword="连衣裙", last_id="i9")
    _, biz = _sent(mock_call)
    assert biz["searchParam"] == {"keyword": "连衣裙", "lastId": "i9"}
    assert biz["pageNo"] == 2 and biz["pageSize"] == 10


@pytest.mark.asyncio
async def test_get_product_detail_uses_item_id(mock_call):
    mock_call.return_value = {"itemInfo": {}, "skuInfos": []}
    await get_product_detail(item_id="6501")
    assert _sent(mock_call) == (
        "product.getItemInfo",
        {"itemId": "6501", "pageNo": 1, "pageSize": 50},
    )


# ═══════════════════════════════════════════════════════════════════════════════════
# 售后
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_refund_list_by_order_id_omits_unset_filters(mock_call):
    mock_call.return_value = {"afterSaleBasicInfos": []}
    await get_refund_list(order_id="P1")
    method, biz = _sent(mock_call)
    assert method == "afterSale.listAfterSaleInfos"
    assert biz == {"pageNo": 1, "pageSize": 50, "orderId": "P1"}


@pytest.mark.asyncio
async def test_get_refund_list_return_types_and_statuses_are_int_arrays(mock_call):
    await get_refund_list(order_id="P1", return_types="4,5", statuses="1,9001")
    _, biz = _sent(mock_call)
    assert biz["returnTypes"] == [4, 5]
    assert biz["statuses"] == [1, 9001]


@pytest.mark.asyncio
async def test_get_refund_list_time_params_are_millis(mock_call):
    """售后接口入参时间是毫秒（与订单列表的秒不同单位）。"""
    start = 1612518379000
    await get_refund_list(start_time=start, end_time=start + 1000, time_type=1)
    _, biz = _sent(mock_call)
    assert biz["startTime"] == start
    assert len(str(biz["startTime"])) == 13


@pytest.mark.asyncio
async def test_get_refund_list_requires_order_id_or_time_type(mock_call):
    with pytest.raises(ValueError, match="至少传一个"):
        await get_refund_list()
    mock_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_refund_list_enforces_window_and_paging_caps(mock_call):
    with pytest.raises(ValueError, match="24 小时"):
        await get_refund_list(start_time=1, end_time=24 * 3600 * 1000 + 2, time_type=1)
    with pytest.raises(ValueError, match="30 分钟"):
        await get_refund_list(start_time=1, end_time=30 * 60 * 1000 + 2, time_type=2)
    with pytest.raises(ValueError, match="必传"):
        await get_refund_list(time_type=1)
    with pytest.raises(ValueError, match="≤100"):
        await get_refund_list(order_id="P1", page_size=101)
    with pytest.raises(ValueError, match="50000"):
        await get_refund_list(order_id="P1", page_no=600, page_size=100)


@pytest.mark.asyncio
async def test_get_refund_detail_uses_returns_id(mock_call):
    mock_call.return_value = {"afterSaleInfo": {}}
    await get_refund_detail(returns_id="R1")
    method, biz = _sent(mock_call)
    assert method == "afterSale.getAfterSaleInfo"
    assert biz == {"returnsId": "R1", "needNegotiateRecord": False}
    # requestHeader 语义不明，官方描述为空 ⇒ 不发送
    assert "requestHeader" not in biz


# ═══════════════════════════════════════════════════════════════════════════════════
# 库存
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_inventory_uses_sku_stock_v2(mock_call):
    mock_call.return_value = {"skuStockInfo": {}}
    await get_inventory(sku_id="67064f2b980e2f00016052bc")
    method, biz = _sent(mock_call)
    assert method == "inventory.getSkuStockV2"
    assert biz == {"skuId": "67064f2b980e2f00016052bc"}


@pytest.mark.asyncio
async def test_get_inventory_omits_undocumented_inventory_type_by_default(mock_call):
    await get_inventory(sku_id="s1")
    _, biz = _sent(mock_call)
    assert "inventoryType" not in biz

    mock_call.reset_mock()
    await get_inventory(sku_id="s1", inventory_type="0")
    _, biz = _sent(mock_call)
    assert biz["inventoryType"] == 0


# ═══════════════════════════════════════════════════════════════════════════════════
# 财务 —— 原 get_bill_list 拆成 4 个
# ═══════════════════════════════════════════════════════════════════════════════════


def test_bill_list_tool_was_split_into_four():
    import servers.xiaohongshu.server as mod

    assert not hasattr(mod, "get_bill_list")
    for name in (
        "get_settlement_transactions",
        "get_account_records",
        "get_expense_settlements",
        "get_monthly_statement_url",
    ):
        assert hasattr(mod, name)


@pytest.mark.asyncio
async def test_get_settlement_transactions_params(mock_call):
    mock_call.return_value = {"transactions": []}
    start = 1612518379000
    await get_settlement_transactions(
        start_time=start,
        end_time=start + 1000,
        settle_biz_type="0",
        settle_status="1",
        account_type="2",
    )
    method, biz = _sent(mock_call)
    assert method == "finance.pageQueryTransaction"
    # 官方分页字段名是 pageNum（不是 order 域的 pageNo）
    assert biz["pageNum"] == 1 and biz["pageSize"] == 50
    assert biz["settleBizType"] == 0  # 0 是有效枚举值，不能被当成"不传"
    assert biz["commonSettleStatus"] == 1
    assert biz["erqingType"] == 2
    assert biz["shouldLoadGoodsInfo"] is False


@pytest.mark.asyncio
async def test_get_settlement_transactions_rejects_window_over_one_day(mock_call):
    with pytest.raises(ValueError, match="一天"):
        await get_settlement_transactions(start_time=0, end_time=24 * 3600 * 1000 + 1)
    mock_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_account_records_params(mock_call):
    mock_call.return_value = {}
    await get_account_records(
        start_time=1,
        end_time=2,
        debit_type="IN",
        trade_types="RECHARGE,STATEMENT_IN",
        fund_type="0",
    )
    method, biz = _sent(mock_call)
    assert method == "finance.querySellerAccountRecords"
    assert biz["debitType"] == "IN"
    assert biz["tradeTypes"] == ["RECHARGE", "STATEMENT_IN"]
    assert biz["fundType"] == 0
    assert "businessNo" not in biz


@pytest.mark.asyncio
async def test_get_expense_settlements_params(mock_call):
    mock_call.return_value = {}
    await get_expense_settlements(start_time=1, end_time=2, base_biz_type="4")
    method, biz = _sent(mock_call)
    assert method == "finance.pageQueryExpense"
    assert biz["baseBizType"] == 4
    assert "settleStatus" not in biz


@pytest.mark.asyncio
async def test_get_monthly_statement_url_params(mock_call):
    mock_call.return_value = {"downloadUrl": "https://example.invalid/x.xlsx"}
    result = json.loads(await get_monthly_statement_url(month="2024-01"))
    assert result["downloadUrl"].endswith(".xlsx")
    assert _sent(mock_call) == ("bill.downloadStatement", {"month": "2024-01"})


# ═══════════════════════════════════════════════════════════════════════════════════
# 签名
# ═══════════════════════════════════════════════════════════════════════════════════


def _client() -> XiaohongshuMCP:
    return XiaohongshuMCP(app_key="21d6748be8de0", app_secret="429aa3aee9ef9e4a858210", access_token="tok")


def test_sign_source_matches_official_shape():
    """官方《签名算法》：method?appId=xxx&timestamp=xxx&version=xxx（无空格）。"""
    source = _client()._sign_source("product.createItem", "1612518379")
    assert source == "product.createItem?appId=21d6748be8de0&timestamp=1612518379&version=2.0"
    assert " " not in source  # 官方正文的空格是排版，"实际中不存在"


def test_sign_source_orders_kv_naturally_with_method_outside():
    """三个 k=v 段按自然序 appId < timestamp < version；method 在 ? 之前不参与排序。"""
    source = _client()._sign_source("order.getOrderList", "1612518379")
    head, _, query = source.partition("?")
    assert head == "order.getOrderList"
    keys = [seg.split("=", 1)[0] for seg in query.split("&")]
    assert keys == sorted(keys) == ["appId", "timestamp", "version"]


def test_sign_is_lowercase_md5_hex_of_source_plus_secret():
    import hashlib

    client = _client()
    expected = hashlib.md5(
        (client._sign_source("order.getOrderList", "1612518379") + client.app_secret).encode("utf-8")
    ).hexdigest()
    sign = client._sign_request("order.getOrderList", "1612518379")
    assert sign == expected
    assert len(sign) == 32
    assert sign == sign.lower()


def test_sign_excludes_access_token_and_business_params():
    """accessToken 与业务参数都不参与签名（官方两处明文）。"""
    a = XiaohongshuMCP(app_key="k", app_secret="s", access_token="tokenA")
    b = XiaohongshuMCP(app_key="k", app_secret="s", access_token="tokenB")
    assert a._sign_request("order.getOrderList", "1") == b._sign_request("order.getOrderList", "1")


def test_sign_is_not_the_shared_base_algorithm():
    """基类 _sign（secret+sorted_kv+secret → 大写）对小红书不成立，不得复用。"""
    client = _client()
    base_style = client._sign({"appId": client.app_key, "timestamp": "1612518379"})
    assert base_style != client._sign_request("order.getOrderList", "1612518379")
    assert base_style == base_style.upper()


# ═══════════════════════════════════════════════════════════════════════════════════
# 判错 / 解包
# ═══════════════════════════════════════════════════════════════════════════════════


def test_success_envelope_is_unwrapped_one_layer():
    payload = {"error_code": 0, "error_msg": "", "success": True, "data": {"total": 3}}
    got = XiaohongshuMCP._unwrap_envelope(payload, api_method="order.getOrderList", gateway="103/1661")
    assert got == {"total": 3}


def test_negative_error_code_raises():
    payload = {"error_code": -2000400, "error_msg": "请求参数错误", "success": False}
    with pytest.raises(CommerceAPIError) as exc:
        XiaohongshuMCP._unwrap_envelope(payload, api_method="order.getOrderList", gateway="103/1661")
    assert exc.value.code == -2000400
    assert "请求参数错误" in exc.value.msg


def test_success_false_with_zero_code_still_raises():
    payload = {"error_code": 0, "success": False, "data": {"total": 1}}
    with pytest.raises(CommerceAPIError):
        XiaohongshuMCP._unwrap_envelope(payload, api_method="order.getOrderList", gateway="103/1661")


def test_taobao_style_error_envelope_is_not_mistaken_for_data():
    """旧实现查的是淘宝/拼多多的 error_response ⇒ 小红书失败完全检测不到。

    现在任何认不出的信封都 fail-closed，不会把信封当业务数据交给模型。
    """
    payload = {"error_response": {"code": 10001, "msg": "order not found"}}
    with pytest.raises(CommerceAPIError, match="无法识别"):
        XiaohongshuMCP._unwrap_envelope(payload, api_method="order.getOrderDetail", gateway="103/1661")


def test_empty_body_fails_closed():
    with pytest.raises(CommerceAPIError):
        XiaohongshuMCP._unwrap_envelope({}, api_method="order.getOrderDetail", gateway="103/1661")


def test_non_dict_body_fails_closed():
    with pytest.raises(CommerceAPIError, match="不是 JSON object"):
        XiaohongshuMCP._unwrap_envelope("<html>502</html>", api_method="order.getOrderDetail", gateway="103/1661")


def test_165_2804_family_unwraps_the_extra_inner_envelope():
    """165/2804 族的官方响应 schema 自带 {code,msg,success,data} 一层。"""
    payload = {
        "error_code": 0,
        "success": True,
        "data": {"code": 0, "msg": "", "success": True, "data": {"afterSaleBasicInfos": []}},
    }
    got = XiaohongshuMCP._unwrap_envelope(payload, api_method="afterSale.listAfterSaleInfos", gateway=GATEWAY_165_2804)
    assert got == {"afterSaleBasicInfos": []}


def test_165_2804_inner_failure_raises():
    payload = {
        "error_code": 0,
        "success": True,
        "data": {"code": -1, "msg": "内层失败", "success": False},
    }
    with pytest.raises(CommerceAPIError, match="内层失败"):
        XiaohongshuMCP._unwrap_envelope(payload, api_method="afterSale.listAfterSaleInfos", gateway=GATEWAY_165_2804)


def test_103_1661_family_does_not_double_unwrap():
    """103/1661 族只有一层；业务体里恰好有 code/success 字段时不得再解一层。"""
    payload = {"error_code": 0, "success": True, "data": {"code": 0, "success": True, "x": 1}}
    got = XiaohongshuMCP._unwrap_envelope(payload, api_method="order.getOrderList", gateway="103/1661")
    assert got == {"code": 0, "success": True, "x": 1}


# ═══════════════════════════════════════════════════════════════════════════════════
# 错误传播 / 输出格式
# ═══════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_api_error_propagates(mock_call):
    mock_call.side_effect = CommerceAPIError(code=-2000101, msg="包裹不存在")

    with pytest.raises(CommerceAPIError) as exc_info:
        await get_order_detail(order_id="P404")

    assert exc_info.value.code == -2000101
    assert "包裹不存在" in exc_info.value.msg


@pytest.mark.asyncio
async def test_timeout_propagates(mock_call):
    mock_call.side_effect = TimeoutError("Connection timed out")

    with pytest.raises(TimeoutError, match="Connection timed out"):
        await get_product_list()


@pytest.mark.asyncio
async def test_output_is_valid_json_string(mock_call):
    mock_call.return_value = {"orderList": [], "total": 0, "maxPageNo": 0}

    result = await get_order_list(start_time=0, end_time=60)

    assert isinstance(result, str)
    assert json.loads(result)["total"] == 0


@pytest.mark.asyncio
async def test_business_params_keep_native_json_types(mock_call):
    """业务参数不做统一 str 化：官方业务参数表里是 integer/number/boolean。"""
    await get_order_list(start_time=0, end_time=60, page_no=2, page_size=10)
    _, biz = _sent(mock_call)
    assert isinstance(biz["pageNo"], int)
    assert isinstance(biz["startTime"], int)


@pytest.mark.asyncio
async def test_business_params_cannot_shadow_system_params():
    client = XiaohongshuMCP(app_key="k", app_secret="s", access_token="t")
    with pytest.raises(ValueError, match="撞名"):
        await client._call("order.getOrderList", {"method": "evil", "timestamp": "0"})
