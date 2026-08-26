"""Taobao (淘宝) MCP server — provides tools for reading merchant orders, products, shop info, and more.

Auth via env vars: TAOBAO_APP_KEY, TAOBAO_APP_SECRET, TAOBAO_ACCESS_TOKEN.
API endpoint: https://gw.api.taobao.com/router/rest
Sign method: MD5 (secret + sorted_kv_string + secret → MD5 → uppercase)

The documented contract, its official sources, and the base-class behaviours
deliberately bypassed here are recorded in ``docs/api-contracts/taobao.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    RetryConfig,
    SignMethod,
    canonicalize_sign_value,
    register_common_tools,
)

logger = logging.getLogger(__name__)

#: TOP timestamps are wall-clock time in Beijing time, not epoch and not UTC.
#: Pinned explicitly because containers commonly run with TZ=UTC, which would
#: otherwise put every request 8 hours outside the gateway's 10-minute window.
TOP_TIMEZONE = timezone(timedelta(hours=8))

#: ``strftime`` form of the documented ``yyyy-MM-dd HH:mm:ss``.
TOP_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


# ── Taobao client ───────────────────────────────────────────────────────────────


class TaobaoMCP(CommerceMCPBase):
    """Taobao Open Platform (TOP) client.

    Signs with MD5 (not HMAC-MD5): ``upper(md5(secret + Σ(key+value) + secret))``
    over every parameter except ``sign``, keys sorted by ASCII code point. All
    parameters (system + business) travel together in the query string of a POST
    to the single router endpoint.

    ``_request`` and ``_sign`` are both overridden because the base class encodes
    three assumptions TOP does not share — an ``access_token`` parameter, an
    epoch-millisecond ``timestamp``, and a ``sign_method`` that is sent but
    excluded from the signature. See ``docs/api-contracts/taobao.md``.
    """

    #: Main gateway from the official access guide.
    BASE_URL = "https://gw.api.taobao.com/router/rest"

    #: Also published officially (API detail pages). Kept for callers that were
    #: pinned to it; the relationship between the two hosts is undocumented, so
    #: neither is asserted to be an alias of the other.
    LEGACY_BASE_URL = "https://eco.taobao.com/router/rest"

    sign_method = SignMethod.MD5

    #: Endpoints for which the platform explicitly recommends the ``has_next``
    #: paging mode (announcement 25838). Kept as an allowlist rather than applied
    #: to every list call: ``use_has_next`` is only valid where the official
    #: parameter table declares it, and only the trade queries were verified.
    USE_HAS_NEXT_METHODS = frozenset(
        {
            "taobao.trades.sold.get",
            "taobao.trades.sold.increment.get",
        }
    )

    # ── Signing ───────────────────────────────────────────────────────────

    def _sign(self, params: dict[str, Any]) -> str:
        """Sign per TOP rules: everything except ``sign`` participates.

        Differences from ``CommerceMCPBase._sign``:

        * ``sign_method`` is **not** excluded. TOP's rule is "all parameters
          except ``sign`` and byte[] parameters", and the official worked
          example's concatenated string contains ``sign_method``.
        * A parameter is skipped when its key *or* its value is empty (enforced
          by the official SDK even though the prose does not say so).

        ``sorted()`` on ``str`` keys is an ASCII/code-point sort, which is what
        TOP requires — ``foo`` < ``foo_bar`` < ``foobar`` because ``_`` (0x5F)
        precedes ``b`` (0x62). No locale-aware collation, no case folding.
        """
        to_sign: dict[str, str] = {}
        for key, value in params.items():
            if key == "sign" or not key:
                continue
            canonical = canonicalize_sign_value(value)
            if canonical == "":
                continue
            to_sign[key] = canonical

        raw = self.app_secret + "".join(f"{k}{to_sign[k]}" for k in sorted(to_sign)) + self.app_secret

        if self.sign_method == SignMethod.MD5:
            return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
        raise ValueError(
            f"Unsupported TOP sign_method: {self.sign_method}. TOP also accepts "
            "'hmac' (HMAC-MD5) and 'hmac-sha256', whose digest inputs differ "
            "from md5's (no secret wrapping); neither is implemented here."
        )

    def _timestamp(self) -> str:
        """Current time as TOP wants it: ``yyyy-MM-dd HH:mm:ss`` in GMT+8."""
        return datetime.now(TOP_TIMEZONE).strftime(TOP_TIMESTAMP_FORMAT)

    def _system_params(self) -> dict[str, str]:
        """TOP public parameters that do not vary per attempt."""
        system: dict[str, str] = {}
        if self.app_key:
            system["app_key"] = self.app_key
        if self.access_token:
            # TOP's public-parameter table has no `access_token`; the credential
            # is named `session`.
            system["session"] = self.access_token
        return system

    # ── HTTP ──────────────────────────────────────────────────────────────

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return a pooled client, without the base class's connect probe.

        ``CommerceMCPBase._ensure_client`` sends ``HEAD`` to ``BASE_URL`` before
        handing the client back. For TOP that means probing ``/router/rest``,
        which is an API router rather than a documented health endpoint, so its
        response says nothing about whether the gateway will accept a signed
        call. Connection failures are already handled by ``retry_config`` in
        ``_request``.

        Connection pooling and the ``_ensure_client`` seam itself are kept.
        """
        client = self._client
        # getattr: a test double substituted for httpx.AsyncClient need not
        # implement is_closed.
        if client is None or getattr(client, "is_closed", False):
            client = self._client = httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30),
            )
        return client

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        retry_config: RetryConfig | None = None,
    ) -> dict[str, Any]:
        """Send a signed TOP request.

        Everything (system + business parameters) goes in the query string of a
        single request to the router endpoint; TOP has no JSON request body, so
        ``data`` is merged into the parameter set rather than serialized as one.

        ``sign_method`` is added *before* the signature is computed, which is the
        defect this override exists to fix.

        Empty-valued parameters are dropped rather than transmitted. TOP's
        signing rule skips them, so sending one would put a parameter on the
        wire that the signature does not cover — the gateway would then compute a
        different digest than we did.
        """
        merged: dict[str, Any] = {**(params or {}), **(data or {})}

        if self.validate_input:
            self._validate_params(merged)

        merged = {k: v for k, v in merged.items() if k and canonicalize_sign_value(v) != ""}

        system = self._system_params()
        url = f"{self.BASE_URL}{path}"
        max_attempts = (retry_config.max_retries + 1) if retry_config else 1
        span = self._tracer.start_span(f"{method} {path}", attributes={"method": method, "path": path})
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            attempt_start = time.time()
            try:
                if self.rate_limiter:
                    await self.rate_limiter.acquire()

                # Rebuilt per attempt: the timestamp moves, so the signature must
                # be recomputed over it.
                attempt_params: dict[str, Any] = {**merged, **system}
                attempt_params["timestamp"] = self._timestamp()
                attempt_params["sign_method"] = self.sign_method
                attempt_params["sign"] = self._sign(attempt_params)

                logger.debug(f"Request: {method} {url} (attempt {attempt + 1}/{max_attempts})")

                client = await self._ensure_client()
                if method == "GET":
                    resp = await client.get(url, params=attempt_params)
                else:
                    resp = await client.post(url, params=attempt_params)

                result = resp.json()
                if "error_response" in result:
                    error = result["error_response"]
                    code = error.get("code", -1)
                    msg = error.get("msg", "unknown")
                    logger.warning(f"API error: [{code}] {msg}")
                    raise CommerceAPIError(code=code, msg=msg)

                self.metrics.record_request(path, (time.time() - attempt_start) * 1000, success=True)
                self._tracer.finish_span(span, status="ok")
                return result

            except Exception as exc:
                last_exc = exc
                err_code = exc.code if isinstance(exc, CommerceAPIError) else 0
                self.metrics.record_request(
                    path,
                    (time.time() - attempt_start) * 1000,
                    success=False,
                    error_code=err_code,
                    error_msg=str(exc),
                )
                if not retry_config or not retry_config.should_retry_exception(exc):
                    self._tracer.finish_span(span, status="error")
                    raise
                if attempt == max_attempts - 1:
                    logger.error(f"Max retries ({retry_config.max_retries}) exhausted for {path}")
                    self._tracer.finish_span(span, status="error")
                    raise
                await asyncio.sleep(retry_config.compute_delay(attempt))

        if last_exc:  # pragma: no cover - loop always returns or raises
            raise last_exc
        return {}

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Make a Taobao API call.

        Merges system params (method, format, v) with business params and
        sends everything through _request as query-string parameters.

        Returns the API response dict, or an error_response dict on failure.
        """
        try:
            params: dict[str, str] = {
                "method": api_method,
                "format": "json",
                "v": "2.0",
            }
            if biz_params:
                params.update(biz_params)
            if api_method in self.USE_HAS_NEXT_METHODS:
                params.setdefault("use_has_next", "true")
            return await self._request("POST", "", params=params)
        except CommerceAPIError as e:
            return {"error_response": {"code": e.code, "msg": e.msg}}
        except Exception as e:
            return {"error_response": {"code": -1, "msg": str(e)}}


# ── Instantiate client from env ────────────────────────────────────────────────


def _create_taobao_client() -> TaobaoMCP:
    """Create Taobao client with configuration validation."""
    try:
        return TaobaoMCP.from_env("TAOBAO", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return TaobaoMCP(
            app_key=os.environ.get("TAOBAO_APP_KEY", ""),
            app_secret=os.environ.get("TAOBAO_APP_SECRET", ""),
            access_token=os.environ.get("TAOBAO_ACCESS_TOKEN", ""),
        )


taobao = _create_taobao_client()


# ── MCP server ─────────────────────────────────────────────────────────────────

mcp = MCPServer("mcp-cn-taobao")


# ═══════════════════════════════════════════════════════════════════════════════════
# 订单 (Orders)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_order_list(
    start_time: str,
    end_time: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query order list by time range and optional status.

    Platform constraints (see docs/api-contracts/taobao.md):
        - The query window cannot exceed 3 months. Older orders need
          taobao.trades.sold.history.get, which this server does not expose.
        - ``receiver_address`` is fully masked by the platform from 2026-08-31;
          do not promise a usable street address from this data.
        - Sent with ``use_has_next=true`` as the platform recommends, so the
          response reports ``has_next`` instead of ``total_results``.

    Args:
        start_time: Order start time, e.g. "2024-01-01 00:00:00"
        end_time: Order end time, e.g. "2024-01-31 23:59:59"
        status: Order status filter. Common values:
            WAIT_BUYER_PAY (waiting for payment),
            WAIT_SELLER_SEND_GOODS (waiting for shipment),
            WAIT_BUYER_CONFIRM_GOODS (shipped, waiting confirm),
            TRADE_FINISHED (completed),
            TRADE_CLOSED (closed).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    biz_params: dict[str, str] = {
        "start_created": start_time,
        "end_created": end_time,
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.trades.sold.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(tid: str) -> str:
    """Get full details of a single order.

    ``receiver_address`` is fully masked by the platform from 2026-08-31
    (announcement 25845), so do not promise a usable street address.

    Args:
        tid: The Taobao trade ID (e.g. "123456789012345678").
    """
    biz_params = {"tid": tid}
    result = await taobao._call("taobao.trade.fullinfo.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_increment_orders(
    start_time: str,
    end_time: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query incrementally modified orders by time range.

    Useful for syncing order changes (status updates, modifications).

    Sent with ``use_has_next=true`` as the platform recommends, so the response
    reports ``has_next`` instead of ``total_results``.

    Args:
        start_time: Modification start time, e.g. "2024-01-01 00:00:00"
        end_time: Modification end time, e.g. "2024-01-31 23:59:59"
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    biz_params: dict[str, str] = {
        "start_modified": start_time,
        "end_modified": end_time,
        "page_no": str(page),
        "page_size": str(page_size),
    }

    result = await taobao._call("taobao.trades.sold.increment.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
    status: str = "",
) -> str:
    """Get on-sale product (item) list with stock and price info.

    Args:
        page: Page number, starting from 1.
        page_size: Number of products per page (max 200).
        status: Product status filter. Empty for all.
            Common values: "onsale" (on sale), "instock" (in stock/off shelf).
    """
    biz_params: dict[str, str] = {
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.items.onsale.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(num_iid: str) -> str:
    """Get full details of a single product by item ID.

    Args:
        num_iid: The Taobao item ID (num_iid, e.g. "12345678901").
    """
    biz_params = {"num_iid": num_iid}
    # taobao.item.get was retired 2018-01-22; the official replacement is
    # taobao.item.seller.get.
    result = await taobao._call("taobao.item.seller.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    start_time: str,
    end_time: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query refund/return list by time range and optional status.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        status: Refund status filter. Common values:
            WAIT_SELLER_AGREE (waiting for seller approval),
            WAIT_BUYER_RETURN_GOODS (waiting for buyer to return goods),
            WAIT_SELLER_CONFIRM_GOODS (waiting for seller to confirm receipt),
            SUCCESS (completed),
            CLOSED (closed).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params: dict[str, str] = {
        "start_modified": start_time,
        "end_modified": end_time,
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.refunds.receive.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Get full details of a single refund/return record.

    Args:
        refund_id: The refund record ID (e.g. "RF12345678901").
    """
    biz_params = {"refund_id": refund_id}
    result = await taobao._call("taobao.refund.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_logistics_tracking(tid: str) -> str:
    """Get logistics tracking information for an order.

    Args:
        tid: The Taobao trade ID (e.g. "123456789012345678").
    """
    biz_params = {"tid": tid}
    result = await taobao._call("taobao.logistics.trace.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 评价 (Reviews)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_review_list(
    num_iid: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query product review (rate/comment) list.

    Args:
        num_iid: The Taobao item ID (e.g. "12345678901").
        page: Page number, starting from 1.
        page_size: Number of reviews per page (max 200).
    """
    biz_params = {
        "num_iid": num_iid,
        "page_no": str(page),
        "page_size": str(page_size),
    }

    result = await taobao._call("taobao.traderates.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info(nick: str = "") -> str:
    """Get shop basic information.

    Args:
        nick: Taobao seller nick (shop identifier). Leave empty to use the authenticated seller's shop.
    """
    biz_params: dict[str, str] = {}
    if nick:
        biz_params["nick"] = nick

    # taobao.shop.get was retired 2019-04-08; the official replacement is
    # taobao.shop.seller.get.
    result = await taobao._call("taobao.shop.seller.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_seller_info() -> str:
    """Get authenticated seller (user) information including seller credit and profile."""
    result = await taobao._call("taobao.user.seller.get", {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_promotions(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List promotion activities.

    Args:
        status: Promotion status filter. Common values:
            "1" (ongoing), "2" (ended), "3" (not started).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params: dict[str, str] = {
        "page_no": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await taobao._call("taobao.promotionmisc.activity.range.list.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════════
# 类目 (Categories)
# ═══════════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_categories(parent_cid: str = "0") -> str:
    """List product categories under a given parent category.

    Args:
        parent_cid: Parent category ID. Use "0" (default) to list top-level categories.
    """
    biz_params = {"parent_cid": parent_cid}

    result = await taobao._call("taobao.itemcats.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, taobao)


# ═══════════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-taobao' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
