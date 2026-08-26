"""Tests for the cross-platform common tools wired onto every server.

Item 3B verifies that ``register_common_tools`` (defined in
``shared.cn_commerce_base``) is correctly hooked into all eight platform
servers, exposing the four operational tools ``get_metrics``, ``get_traces``,
``get_alerts`` and ``export_data`` on each one.

All eight servers expose an MCPServer instance (named ``mcp`` on six of them,
``server`` on doudian/oceanengine) whose registered tools are introspectable
via ``await <instance>.list_tools()``.
"""

from __future__ import annotations

import json
import os

import pytest
from mcp.types import TextContent

# ── Environment: every server reads credentials at import time (the six
# MCPServer servers build their client eagerly). Set placeholder creds for all
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

# All servers expose an MCPServer instance; the attribute is ``mcp`` on six of
# them and ``server`` on doudian/oceanengine.
MCP_SERVERS = [
    pytest.param(jd_server, id="jd"),
    pytest.param(kuaishou_server, id="kuaishou"),
    pytest.param(pinduoduo_server, id="pinduoduo"),
    pytest.param(taobao_server, id="taobao"),
    pytest.param(weixin_store_server, id="weixin_store"),
    pytest.param(xiaohongshu_server, id="xiaohongshu"),
    pytest.param(doudian_server, id="doudian"),
    pytest.param(oceanengine_server, id="oceanengine"),
]


def _mcp_server(module):
    """Return the module's MCPServer instance regardless of its attribute name."""
    return getattr(module, "mcp", None) or module.server


# ── MCPServer servers: introspect via list_tools() ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("module", MCP_SERVERS)
async def test_mcpserver_registers_common_tools(module):
    """Each MCPServer exposes all four common operational tools."""
    tools = await _mcp_server(module).list_tools()
    names = {t.name for t in tools}
    missing = COMMON_TOOLS - names
    assert not missing, f"{module.__name__} missing common tools: {sorted(missing)}"


# FR-015 下架了指向不存在 / 已下线 endpoint 的工具。抖店（0/20 可用）与京东
# （0/15，`jd.pop.*` 命名空间不存在）因此**一个平台工具都不剩**，只保留 4 个不依赖平台
# endpoint 的通用运维工具。逐条清单见 docs/platforms.md「下架工具清单（FR-015）」。
_NO_PLATFORM_TOOLS = {"doudian", "jd"}


@pytest.mark.parametrize("module", MCP_SERVERS)
def test_mcpserver_keeps_platform_tools(module, request):
    """Wiring common tools must not drop a server's existing platform tools."""
    registered = set(_mcp_server(module)._tool_manager._tools.keys())
    if request.node.callspec.id in _NO_PLATFORM_TOOLS:
        # Nothing to keep: every endpoint this server used was fabricated or
        # retired, so the four common tools are the whole surface.
        assert registered == COMMON_TOOLS
    else:
        # Every other server has more than just the four common tools.
        assert len(registered - COMMON_TOOLS) > 0


# ── End-to-end: invoke the registered MCPServer tools against a real client ────


async def _call_tool_text(server, name, args=None):
    """Invoke a registered tool through the public API and return its text payload.

    ``MCPServer.call_tool()`` answers with a ``CallToolResult``; every tool in
    this project returns a JSON string, so the payload is its text content.
    """
    result = await server.call_tool(name, args or {})
    assert not result.is_error, f"{name} returned an error: {result.content}"
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


@pytest.mark.asyncio
async def test_get_metrics_tool_returns_metrics_summary():
    """Calling the registered get_metrics tool yields a JSON metrics summary."""
    tool = jd_server.mcp._tool_manager.get_tool("get_metrics")
    assert tool is not None
    payload = json.loads(await _call_tool_text(jd_server.mcp, "get_metrics"))
    # Shape produced by CommerceMCPBase.get_metrics_summary().
    assert "global" in payload
    assert "endpoints" in payload
    assert "total_requests" in payload["global"]


@pytest.mark.asyncio
async def test_export_data_tool_returns_serialized_records():
    """Calling export_data with one record returns a non-empty string carrying it."""
    raw = await _call_tool_text(jd_server.mcp, "export_data", {"records_json": json.dumps([{"a": 1}])})
    assert isinstance(raw, str)
    assert raw.strip()
    # The single record's field name and value must both survive the round-trip,
    # regardless of whether the exporter emitted CSV or JSON.
    assert "a" in raw
    assert "1" in raw


@pytest.mark.asyncio
async def test_get_alerts_and_traces_tools_return_json():
    """get_alerts / get_traces tools return JSON with their documented shape."""
    alerts = json.loads(await _call_tool_text(jd_server.mcp, "get_alerts"))
    assert "firing" in alerts
    assert "stats" in alerts

    traces = json.loads(await _call_tool_text(jd_server.mcp, "get_traces"))
    assert isinstance(traces, dict)


# ── End-to-end at the registration boundary: callable client (lazy getter) ───


@pytest.mark.asyncio
async def test_register_common_tools_with_callable_client():
    """register_common_tools accepts a zero-arg callable (the lazy-getter form).

    doudian / oceanengine pass ``_get_client`` (a callable) rather than an
    instance; exercise that resolution path end-to-end on a fresh MCPServer.
    """
    from mcp.server.mcpserver import MCPServer

    from shared.cn_commerce_base import register_common_tools

    client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
    mcp = MCPServer("probe")
    register_common_tools(mcp, lambda: client)

    names = {t.name for t in await mcp.list_tools()}
    assert COMMON_TOOLS <= names

    assert "global" in json.loads(await _call_tool_text(mcp, "get_metrics"))

    export_raw = await _call_tool_text(mcp, "export_data", {"records_json": json.dumps([{"a": 1}])})
    assert isinstance(export_raw, str) and export_raw.strip()
