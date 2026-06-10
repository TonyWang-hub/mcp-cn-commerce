"""Tests for the cross-platform common tools wired onto every server.

Item 3B verifies that ``register_common_tools`` (defined in
``shared.cn_commerce_base``) is correctly hooked into all eight platform
servers, exposing the four operational tools ``get_metrics``, ``get_traces``,
``get_alerts`` and ``export_data`` on each one.

All eight servers expose a FastMCP instance (named ``mcp`` on six of them,
``server`` on doudian/oceanengine) whose registered tools are introspectable
via ``await <instance>.list_tools()``.
"""

from __future__ import annotations

import json
import os

import pytest

# ── Environment: every server reads credentials at import time (the six
# FastMCP servers build their client eagerly). Set placeholder creds for all
# platforms up front so importing any server module never raises. ───────────

_ENV = {
    "JD_APP_KEY": "test_key",
    "JD_APP_SECRET": "test_secret",
    "JD_ACCESS_TOKEN": "test_token",
    "KUAISHOU_APP_KEY": "test_key",
    "KUAISHOU_APP_SECRET": "test_secret",
    "KUAISHOU_SIGN_SECRET": "test_sign_secret",
    "KUAISHOU_ACCESS_TOKEN": "test_token",
    "PINDUODUO_CLIENT_ID": "test_client_id",
    "PINDUODUO_CLIENT_SECRET": "test_client_secret",
    "PINDUODUO_ACCESS_TOKEN": "test_token",
    "TAOBAO_APP_KEY": "test_key",
    "TAOBAO_APP_SECRET": "test_secret",
    "TAOBAO_ACCESS_TOKEN": "test_token",
    "WX_APP_ID": "test_app_id",
    "WX_APP_SECRET": "test_secret",
    "WX_ACCESS_TOKEN": "test_token_123456",
    "XHS_CLIENT_ID": "test_client_id",
    "XHS_CLIENT_SECRET": "test_client_secret",
    "XHS_ACCESS_TOKEN": "test_token",
    "OCEANENGINE_APP_KEY": "test_key",
    "OCEANENGINE_APP_SECRET": "test_secret",
    "OCEANENGINE_ACCESS_TOKEN": "test_token",
    "DOUDIAN_APP_KEY": "test_key",
    "DOUDIAN_APP_SECRET": "test_secret",
    "DOUDIAN_SHOP_ID": "test_shop_id",
    "DOUDIAN_ACCESS_TOKEN": "test_token",
}
for _k, _v in _ENV.items():
    os.environ.setdefault(_k, _v)


# ── Import every server module (after env is in place) ───────────────────────

import servers.doudian.server as doudian_server  # noqa: E402
import servers.jd.server as jd_server  # noqa: E402
import servers.kuaishou.server as kuaishou_server  # noqa: E402
import servers.oceanengine.server as oceanengine_server  # noqa: E402
import servers.pinduoduo.server as pinduoduo_server  # noqa: E402
import servers.taobao.server as taobao_server  # noqa: E402
import servers.weixin_store.server as weixin_store_server  # noqa: E402
import servers.xiaohongshu.server as xiaohongshu_server  # noqa: E402
from shared.cn_commerce_base import CommerceMCPBase  # noqa: E402

COMMON_TOOLS = {"get_metrics", "get_traces", "get_alerts", "export_data"}

# All servers expose a FastMCP instance; the attribute is ``mcp`` on six of
# them and ``server`` on doudian/oceanengine.
FASTMCP_SERVERS = [
    pytest.param(jd_server, id="jd"),
    pytest.param(kuaishou_server, id="kuaishou"),
    pytest.param(pinduoduo_server, id="pinduoduo"),
    pytest.param(taobao_server, id="taobao"),
    pytest.param(weixin_store_server, id="weixin_store"),
    pytest.param(xiaohongshu_server, id="xiaohongshu"),
    pytest.param(doudian_server, id="doudian"),
    pytest.param(oceanengine_server, id="oceanengine"),
]


def _fastmcp(module):
    """Return the module's FastMCP instance regardless of its attribute name."""
    return getattr(module, "mcp", None) or module.server


# ── FastMCP servers: introspect via list_tools() ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module", FASTMCP_SERVERS)
async def test_fastmcp_server_registers_common_tools(module):
    """Each FastMCP server exposes all four common operational tools."""
    tools = await _fastmcp(module).list_tools()
    names = {t.name for t in tools}
    missing = COMMON_TOOLS - names
    assert not missing, f"{module.__name__} missing common tools: {sorted(missing)}"


@pytest.mark.parametrize("module", FASTMCP_SERVERS)
def test_fastmcp_server_keeps_platform_tools(module):
    """Wiring common tools must not drop a server's existing platform tools."""
    registered = set(_fastmcp(module)._tool_manager._tools.keys())
    # Every server has more than just the four common tools.
    assert len(registered - COMMON_TOOLS) > 0


# ── End-to-end: invoke the registered FastMCP tools against a real client ────


@pytest.mark.asyncio
async def test_get_metrics_tool_returns_metrics_summary():
    """Calling the registered get_metrics tool yields a JSON metrics summary."""
    tool = jd_server.mcp._tool_manager.get_tool("get_metrics")
    assert tool is not None
    raw = await jd_server.mcp._tool_manager.call_tool("get_metrics", {})
    payload = json.loads(raw)
    # Shape produced by CommerceMCPBase.get_metrics_summary().
    assert "global" in payload
    assert "endpoints" in payload
    assert "total_requests" in payload["global"]


@pytest.mark.asyncio
async def test_export_data_tool_returns_serialized_records():
    """Calling export_data with one record returns a non-empty string carrying it."""
    raw = await jd_server.mcp._tool_manager.call_tool("export_data", {"records_json": json.dumps([{"a": 1}])})
    assert isinstance(raw, str)
    assert raw.strip()
    # The single record's field name and value must both survive the round-trip,
    # regardless of whether the exporter emitted CSV or JSON.
    assert "a" in raw
    assert "1" in raw


@pytest.mark.asyncio
async def test_get_alerts_and_traces_tools_return_json():
    """get_alerts / get_traces tools return JSON with their documented shape."""
    alerts_raw = await jd_server.mcp._tool_manager.call_tool("get_alerts", {})
    alerts = json.loads(alerts_raw)
    assert "firing" in alerts
    assert "stats" in alerts

    traces_raw = await jd_server.mcp._tool_manager.call_tool("get_traces", {})
    traces = json.loads(traces_raw)
    assert isinstance(traces, dict)


# ── End-to-end at the registration boundary: callable client (lazy getter) ───


@pytest.mark.asyncio
async def test_register_common_tools_with_callable_client():
    """register_common_tools accepts a zero-arg callable (the lazy-getter form).

    doudian / oceanengine pass ``_get_client`` (a callable) rather than an
    instance; exercise that resolution path end-to-end on a fresh FastMCP.
    """
    from mcp.server.fastmcp import FastMCP

    from shared.cn_commerce_base import register_common_tools

    client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
    mcp = FastMCP("probe")
    register_common_tools(mcp, lambda: client)

    names = {t.name for t in await mcp.list_tools()}
    assert COMMON_TOOLS <= names

    raw = await mcp._tool_manager.call_tool("get_metrics", {})
    assert "global" in json.loads(raw)

    export_raw = await mcp._tool_manager.call_tool("export_data", {"records_json": json.dumps([{"a": 1}])})
    assert isinstance(export_raw, str) and export_raw.strip()
