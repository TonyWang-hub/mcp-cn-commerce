"""MCP discovery and execution must share the SDK capability boundary."""

from __future__ import annotations

import inspect
import os

import pytest
from mcp.server.mcpserver.exceptions import ToolError

_ENV = {
    "JD_APP_KEY": "test_key",
    "JD_APP_SECRET": "test_secret",
    "JD_ACCESS_TOKEN": "test_token",
    "KUAISHOU_APP_KEY": "test_key",
    "KUAISHOU_APP_SECRET": "test_secret",
    "KUAISHOU_SIGN_SECRET": "test_sign_secret",
    "KUAISHOU_ACCESS_TOKEN": "test_token",
    "PINDUODUO_CLIENT_ID": "test_client_id",
    "PINDUODUO_CLIENT_SECRET": "test_secret",
    "PINDUODUO_ACCESS_TOKEN": "test_token",
    "TAOBAO_APP_KEY": "test_key",
    "TAOBAO_APP_SECRET": "test_secret",
    "TAOBAO_ACCESS_TOKEN": "test_token",
    "WX_ACCESS_TOKEN": "test_token",
    "XHS_CLIENT_ID": "test_client_id",
    "XHS_CLIENT_SECRET": "test_secret",
    "XHS_ACCESS_TOKEN": "test_token",
}
for _name, _value in _ENV.items():
    os.environ.setdefault(_name, _value)


import servers.doudian.server as doudian_server  # noqa: E402
import servers.jd.server as jd_server  # noqa: E402
import servers.kuaishou.server as kuaishou_server  # noqa: E402
import servers.oceanengine.server as oceanengine_server  # noqa: E402
import servers.pinduoduo.server as pinduoduo_server  # noqa: E402
import servers.taobao.server as taobao_server  # noqa: E402
import servers.weixin_store.server as weixin_store_server  # noqa: E402
import servers.xiaohongshu.server as xiaohongshu_server  # noqa: E402

COMMON_TOOLS = {"get_metrics", "get_traces", "get_alerts", "export_data", "build_daily_report"}
SERVERS = {
    "doudian": doudian_server.server,
    "jd": jd_server.mcp,
    "kuaishou": kuaishou_server.mcp,
    "oceanengine": oceanengine_server.server,
    "pinduoduo": pinduoduo_server.mcp,
    "taobao": taobao_server.mcp,
    "weixin_store": weixin_store_server.mcp,
    "xiaohongshu": xiaohongshu_server.mcp,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["get_campaign_report", "get_ad_detail_report", "get_qianchuan_report"])
async def test_oceanengine_unmigrated_reports_reject_before_client_creation(monkeypatch, name):
    monkeypatch.setattr(
        oceanengine_server,
        "_get_client",
        lambda: pytest.fail("unsupported operation created an OceanEngine client"),
    )
    tool = getattr(oceanengine_server, name)
    arguments = {
        "advertiser_id": "123",
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
    }
    with pytest.raises(ToolError, match="migration"):
        await tool(**arguments)


@pytest.mark.asyncio
async def test_every_business_tool_discloses_contract_and_live_verification_status():
    for platform, server in SERVERS.items():
        for tool in await server.list_tools():
            if tool.name in COMMON_TOOLS:
                assert not (tool.description or "").startswith("[Capability: ")
                continue
            description = tool.description or ""
            assert description.startswith("[Capability: "), f"{platform}.{tool.name} lacks capability metadata"
            assert "contract_status=" in description, f"{platform}.{tool.name} lacks contract status"
            assert "live_verified=false" in description, f"{platform}.{tool.name} overstates live verification"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,name,expected",
    [
        ("doudian", "get_order_list", "contract_status=documented; supported=true"),
        ("doudian", "get_shop_info", "contract_status=unverified; supported=false"),
        ("jd", "get_order_list", "contract_status=documented; supported=true"),
        ("jd", "get_after_sale_list", "contract_status=partial; supported=false"),
        ("kuaishou", "get_order_list", "contract_status=documented; supported=true"),
        ("oceanengine", "get_advertiser_info", "contract_status=documented; supported=true"),
        ("oceanengine", "get_campaign_report", "contract_status=partial; supported=false"),
        ("oceanengine", "list_campaigns", "contract_status=unverified; supported=true"),
        ("taobao", "get_shop_info", "contract_status=transport_only; supported=true"),
        ("pinduoduo", "get_order_list", "contract_status=partial; supported=false"),
        ("pinduoduo", "get_product_list", "contract_status=unverified; supported=true"),
        ("weixin_store", "get_order_list", "contract_status=documented; supported=true"),
        ("xiaohongshu", "get_order_list", "contract_status=documented; supported=true"),
        ("xiaohongshu", "get_review_list", "contract_status=unverified; supported=false"),
        ("xiaohongshu", "list_promotions", "contract_status=unverified; supported=false"),
        ("xiaohongshu", "get_product_list", "contract_status=unverified; supported=true"),
    ],
)
async def test_discovery_uses_shared_catalogue_and_marks_legacy_tools_unverified(platform, name, expected):
    tools = {tool.name: tool for tool in await SERVERS[platform].list_tools()}
    assert expected in (tools[name].description or "")


def test_capability_wrappers_preserve_public_function_signatures():
    assert str(inspect.signature(oceanengine_server.get_campaign_report)) == (
        "(advertiser_id: 'str', start_date: 'str', end_date: 'str', page: 'int' = 1, page_size: 'int' = 20) -> 'str'"
    )
    assert (
        str(inspect.signature(pinduoduo_server.get_product_list)) == "(page: 'int' = 1, page_size: 'int' = 20) -> 'str'"
    )
