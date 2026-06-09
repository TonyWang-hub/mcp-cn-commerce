#!/usr/bin/env python3
"""Observability demo for mcp-cn-commerce.

This script demonstrates the always-on observability that every
``CommerceMCPBase`` subclass (and therefore every platform MCP server) gets
for free, plus the cross-platform data-export helper:

  * Every ``_request()`` call is automatically *metered* (MetricsCollector)
    and *traced* (RequestTracer) -- no configuration required.
  * ``client.get_metrics_summary()`` returns per-endpoint latency / error
    counts (exposed to MCP clients as the ``get_metrics`` tool).
  * ``client.get_trace_summary()`` returns a span summary for the most recent
    request flow (exposed as the ``get_traces`` tool).
  * ``client.get_alerts()`` evaluates the built-in alert rules against current
    metrics (exposed as the ``get_alerts`` tool).
  * ``client.export_data(records, fmt=...)`` serialises a list of records to a
    CSV or JSON string (exposed as the ``export_data`` tool).

No real network calls are made: the HTTP layer is mocked so the script runs
anywhere, offline.

Run it with::

    python3 examples/best-practices/observability_demo.py

(Run from the repository root so that the ``shared`` package is importable.)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Make the repository root importable when run directly (so `shared` resolves).
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.cn_commerce_base import CommerceMCPBase  # noqa: E402


class DemoClient(CommerceMCPBase):
    """A minimal platform client.

    A real server subclass would set a live ``BASE_URL`` and the correct
    ``sign_method``; for this offline demo any value works because the HTTP
    call is mocked out below.
    """

    BASE_URL = "https://api.demo.example.com/"
    sign_method = "md5"


def _fake_http_response(payload: dict) -> object:
    """Build a stand-in for an ``httpx.Response`` exposing ``.json()``."""

    class _Resp:
        status_code = 200

        def json(self) -> dict:
            return payload

    return _Resp()


async def main() -> None:
    client = DemoClient(app_key="demo-key", app_secret="demo-secret", access_token="demo-token")

    # --- Mock the network so `_request` runs end-to-end without a real API. ---
    # `_request` calls `self._ensure_client()` then `client.get(...)` / `.post(...)`.
    # We hand it a fake httpx client whose GET/POST return canned JSON. One of
    # the responses is an API error so the metrics show a non-zero error rate.
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(
        side_effect=[
            _fake_http_response({"result": [{"id": 1, "name": "Widget"}]}),
            _fake_http_response({"result": [{"id": 2, "name": "Gadget"}]}),
            # An API-level error: `_request` raises CommerceAPIError, which the
            # metrics layer records as a failed request for this endpoint.
            _fake_http_response({"error_response": {"code": 42, "msg": "rate limited"}}),
        ]
    )
    fake_client.post = AsyncMock(return_value=_fake_http_response({"result": "ok"}))

    with patch.object(client, "_ensure_client", AsyncMock(return_value=fake_client)):
        # Two successful product reads + one read that the API rejects.
        await client._request("GET", "/api/product/get", params={"id": "1"})
        await client._request("GET", "/api/product/get", params={"id": "2"})
        try:
            await client._request("GET", "/api/order/search", params={"page": "1"})
        except Exception as exc:  # noqa: BLE001 -- expected demo error
            print(f"[expected] /api/order/search failed: {exc}\n")

    # --- 1. Metrics summary (the `get_metrics` MCP tool calls this) ----------
    print("=== get_metrics_summary() ===")
    metrics = client.get_metrics_summary()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print()

    # --- 2. Trace summary (the `get_traces` MCP tool calls this) -------------
    print("=== get_trace_summary() ===")
    print(json.dumps(client.get_trace_summary(), ensure_ascii=False, indent=2))
    print()

    # --- 3. Alerts (the `get_alerts` MCP tool calls this) --------------------
    # Evaluates the built-in default rules against the metrics above.
    print("=== get_alerts() ===")
    print(json.dumps(client.get_alerts(), ensure_ascii=False, indent=2))
    print()

    # --- 4. Data export (the `export_data` MCP tool calls this) --------------
    # `export_data(records, fmt=...)` serialises a list of dicts to a string.
    # `fmt="csv"` produces comma-separated rows with a header line.
    records = [
        {"id": 1, "name": "Widget", "price": 9.9},
        {"id": 2, "name": "Gadget", "price": 19.9},
    ]
    print("=== export_data(records, fmt='csv') ===")
    print(client.export_data(records, fmt="csv"))

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
