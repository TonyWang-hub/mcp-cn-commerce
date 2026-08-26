"""Kuaishou (快手小店) MCP server — read-only merchant tools for orders,
products, after-sale, reviews, coupons and shop info.

Auth via env vars: ``KUAISHOU_APP_KEY``, ``KUAISHOU_APP_SECRET``,
``KUAISHOU_SIGN_SECRET``, ``KUAISHOU_ACCESS_TOKEN``.

Gateway: ``https://openapi.kwaixiaodian.com`` (backup ``open.kwaixiaodian.com``).

Contract summary (full declaration with sources: ``docs/api-contracts/kuaishou.md``):

* **Path** is derived mechanically from the official ``method`` name by replacing
  dots with slashes — ``open.order.cursor.list`` → ``/open/order/cursor/list``.
  There is no ``/api/`` segment on this gateway.
* **System params are flat**: ``appkey`` (all lowercase), ``method`` (dotted),
  ``version=1``, ``access_token`` (snake_case), ``timestamp`` (epoch **millis**),
  ``signMethod`` (camelCase), ``sign``.
* **Business params are NOT flattened**: they are serialized into a *single*
  JSON string carried in the ``param`` field, with **camelCase** keys.
* **Signing** uses the dedicated ``signSecret`` credential (``app_secret`` is for
  OAuth only): sort every param except ``sign`` by name, join ``k=v`` with
  ``&``, append the literal ``&signSecret=<signSecret>``, then MD5 →
  **lowercase** hex (or HMAC-SHA256 → **Base64**).  Signing happens on raw
  values; URL encoding is applied afterwards, at send time, by httpx.
* **Error detection** is ``result == 1`` for success with the payload under
  ``data`` — *not* the ``error_response`` envelope used by Taobao/Pinduoduo.
* **Pagination differs per endpoint** — cursor, pcursor+currentPage, pageNumber,
  offset/limit and pageNo all appear.  See each tool's docstring.

Request assembly is deliberately implemented here instead of reusing
``CommerceMCPBase._request``: the base class assembles ``app_key`` /
``sign_method`` / flattened business params and detects errors via
``error_response``, all of which are wrong for this gateway.  See
``docs/api-contracts/kuaishou.md`` §7 for the list of base-class capabilities
that are consequently re-implemented here versus bypassed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
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
    canonicalize_sign_value,
    register_common_tools,
)

logger = logging.getLogger("mcp-cn-commerce.kuaishou")

# ── Contract constants ────────────────────────────────────────────────────────

#: Kuaishou's ``signMethod`` values are camelCase-named but uppercase-valued.
SIGN_METHOD_MD5 = "MD5"
SIGN_METHOD_HMAC_SHA256 = "HMAC_SHA256"

#: The platform runs on GMT+8.  Naive datetime strings are interpreted in that
#: zone explicitly rather than via the process timezone, so a container running
#: UTC does not silently shift every query window by 8 hours.
_PLATFORM_TZ = timezone(timedelta(hours=8))

_NAIVE_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)

#: ``open.order.cursor.list`` returns this sentinel in place of a cursor once the
#: result set is exhausted.
CURSOR_EXHAUSTED = "nomore"

#: Documented ``orderViewStatus`` enum (the parameter is mandatory).
ORDER_VIEW_STATUS = {
    "1": "全部",
    "2": "待付款",
    "3": "待发货",
    "4": "待收货",
    "5": "已收货",
    "6": "交易成功",
    "7": "已关闭",
}


def _to_epoch_millis(value: str | int | float, *, field: str) -> int:
    """Convert a caller-supplied time into epoch milliseconds.

    Accepts epoch millis, epoch seconds, and the human formats the MCP tools
    advertise (``YYYY-MM-DD HH:MM:SS`` / ``YYYY-MM-DD`` / ISO 8601).  Naive
    values are read as GMT+8, the platform's timezone.
    """
    if isinstance(value, (int, float)):
        raw = str(int(value))
    else:
        raw = str(value).strip()

    if raw.isdigit():
        number = int(raw)
        # 13 digits is already millis; 10 digits is seconds.
        return number if len(raw) >= 13 else number * 1000

    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in _NAIVE_TIME_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        raise ValueError(f"{field}: cannot parse {value!r} as a time. Use epoch millis or " "'YYYY-MM-DD HH:MM:SS'.")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_PLATFORM_TZ)
    return int(parsed.timestamp() * 1000)


def _clamp(value: int, low: int, high: int, *, field: str) -> int:
    """Clamp a paging value into the platform's documented range, loudly."""
    if value < low or value > high:
        logger.warning(f"{field}={value} outside documented range [{low}, {high}]; clamping")
    return max(low, min(high, value))


def _warn_window(begin_ms: int, end_ms: int, *, max_span: timedelta, endpoint: str) -> None:
    """Warn when a query window exceeds the documented maximum.

    Advisory rather than fatal on purpose: the platform is the authority on the
    current limit (it is tightened during large sales events), so we surface the
    likely rejection without pre-empting a call that may still be accepted.
    """
    if end_ms < begin_ms:
        logger.warning(f"{endpoint}: endTime precedes beginTime ({end_ms} < {begin_ms})")
        return
    span = timedelta(milliseconds=end_ms - begin_ms)
    if span > max_span:
        logger.warning(
            f"{endpoint}: query window {span} exceeds the documented maximum "
            f"{max_span}; the gateway will likely reject it"
        )


def _warn_retention(begin_ms: int, *, max_age: timedelta, endpoint: str) -> None:
    """Warn when the window starts outside the endpoint's retention horizon."""
    age = timedelta(milliseconds=max(0, int(time.time() * 1000) - begin_ms))
    if age > max_age:
        logger.warning(
            f"{endpoint}: beginTime is {age} old but only the last {max_age} is "
            "queryable; the gateway will likely return nothing"
        )


# ── Kuaishou client ───────────────────────────────────────────────────────────


class KuaishouMCP(CommerceMCPBase):
    """Kuaishou Open Platform client.

    Overrides both signing and request assembly.  ``CommerceMCPBase._request``
    is not used because its system-parameter layout (``app_key``,
    ``sign_method``, flattened business params) and its ``error_response``
    envelope check are both wrong for this gateway.
    """

    BASE_URL = "https://openapi.kwaixiaodian.com"
    API_VERSION = "1"
    #: Wire value of the ``signMethod`` parameter.  MD5 and HMAC_SHA256 are both
    #: official; MD5 is the default because it is the variant with a published
    #: worked example.  Override with ``KUAISHOU_SIGN_METHOD=HMAC_SHA256``.
    sign_method = SIGN_METHOD_MD5
    #: Default ceiling for the refund window (documented as 1 day, tightened by
    #: the platform during sales events) — override via
    #: ``KUAISHOU_REFUND_WINDOW_HOURS``.
    REFUND_WINDOW_HOURS = 24

    def __init__(
        self,
        app_key: str = "",
        app_secret: str = "",
        sign_secret: str = "",
        access_token: str = "",
        sign_method: str = "",
        refund_window_hours: int | None = None,
    ):
        super().__init__(
            app_key=app_key,
            app_secret=app_secret,
            access_token=access_token,
        )
        self.sign_secret = sign_secret
        if sign_method:
            if sign_method not in (SIGN_METHOD_MD5, SIGN_METHOD_HMAC_SHA256):
                raise ValueError(f"Unsupported Kuaishou signMethod: {sign_method!r}")
            self.sign_method = sign_method
        if refund_window_hours is not None:
            self.REFUND_WINDOW_HOURS = refund_window_hours

    # ── Path / params ─────────────────────────────────────────────────────

    @staticmethod
    def path_for(api_method: str) -> str:
        """Derive the REST path from the official ``method`` name.

        The rule is purely mechanical (dots become slashes), so deriving it
        rather than hardcoding a second string makes a fabricated path
        impossible to introduce.
        """
        if not api_method or api_method.strip(".") != api_method or ".." in api_method:
            raise ValueError(f"Malformed Kuaishou method name: {api_method!r}")
        return "/" + api_method.replace(".", "/")

    @staticmethod
    def pack_param(biz_params: dict[str, Any] | None) -> str:
        """Serialize business params into the single ``param`` JSON string.

        Serialized exactly once per request and reused for both signing and
        sending, so the signed bytes and the sent bytes cannot diverge.
        Returns ``""`` when there are no business params, in which case
        ``param`` is omitted from the request entirely.

        Empty strings are kept: cursor-style params are documented as "empty on
        the first call", so the key has to survive.  Only ``None`` is dropped.
        """
        if not biz_params:
            return ""
        cleaned = {k: v for k, v in biz_params.items() if v is not None}
        if not cleaned:
            return ""
        return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def build_params(self, api_method: str, biz_params: dict[str, Any] | None = None) -> dict[str, str]:
        """Assemble the full signed parameter set for one request.

        Empty-valued system params are omitted rather than sent blank, which
        keeps the invariant "signed set == sent set − {sign}" true by
        construction.
        """
        param_json = self.pack_param(biz_params)

        params: dict[str, str] = {
            "appkey": self.app_key,
            "method": api_method,
            "version": self.API_VERSION,
            "access_token": self.access_token,
            "timestamp": str(int(time.time() * 1000)),
            "signMethod": self.sign_method,
        }
        if param_json:
            params["param"] = param_json

        params = {k: v for k, v in params.items() if v not in (None, "")}
        params["sign"] = self._sign(params)
        return params

    # ── Signing ───────────────────────────────────────────────────────────

    def sign_base_string(self, params: dict[str, Any]) -> str:
        """Build the exact string fed to the digest.

        Every param except ``sign`` participates, sorted by name, joined as
        ``k=v`` with ``&``, with the literal ``&signSecret=<signSecret>``
        appended.  Values are the **raw**, un-encoded ones: URL encoding is
        applied only when the request is put on the wire.  Doing it the other
        way round produces a signature the gateway cannot reproduce.
        """
        signable = {k: v for k, v in params.items() if k != "sign" and v not in (None, "")}
        joined = "&".join(f"{k}={canonicalize_sign_value(signable[k])}" for k in sorted(signable))
        return f"{joined}&signSecret={self.sign_secret}"

    def _sign(self, params: dict[str, Any]) -> str:
        """Sign with the dedicated ``signSecret`` credential.

        MD5 yields **lowercase** hex (the official SDK uses ``md5Hex``);
        HMAC-SHA256 yields **Base64**, not hex.
        """
        raw = self.sign_base_string(params)
        if self.sign_method == SIGN_METHOD_HMAC_SHA256:
            digest = hmac.new(self.sign_secret.encode(), raw.encode(), hashlib.sha256).digest()
            return base64.b64encode(digest).decode()
        return hashlib.md5(raw.encode()).hexdigest()

    # ── Transport ─────────────────────────────────────────────────────────

    async def _call(
        self,
        api_method: str,
        biz_params: dict[str, Any] | None = None,
        http_method: str = "GET",
    ) -> dict[str, Any]:
        """Make one signed call to the Kuaishou gateway.

        Args:
            api_method: Official dotted ``method`` name; the path is derived
                from it.
            biz_params: Business params with camelCase keys; packed into
                ``param``.
            http_method: ``GET`` or ``POST``.  Per-API, not global — all nine
                endpoints this server exposes are GET.

        Returns:
            The parsed response envelope (``result`` / ``data`` / ...).

        Raises:
            CommerceAPIError: When ``result != 1``, or on an HTTP error status.
        """
        biz_params = biz_params or {}
        if self.validate_input:
            self._validate_params(biz_params)

        path = self.path_for(api_method)
        params = self.build_params(api_method, biz_params)
        url = f"{self.BASE_URL}{path}"

        # Rate limiting and tracing are re-implemented here because bypassing
        # the base _request also bypasses its middleware.
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        span = self._tracer.start_span(
            f"{http_method} {path}",
            attributes={"method": http_method, "path": path, "api_method": api_method},
        )
        started = time.time()

        try:
            # httpx performs the URL/form encoding, i.e. strictly after signing:
            # `param`'s quotes and colons go out as %22/%3A while the signature
            # was computed over the raw JSON.
            async with httpx.AsyncClient(timeout=30) as client:
                if http_method.upper() == "GET":
                    resp = await client.get(url, params=params)
                else:
                    # POST: the official client keeps only `appkey` in the query
                    # string, removes it from the body, and sends the rest as
                    # form-urlencoded (the only Content-Type the gateway takes).
                    body = {k: v for k, v in params.items() if k != "appkey"}
                    resp = await client.post(
                        url,
                        params={"appkey": params["appkey"]},
                        data=body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )

            result = self._check_envelope(resp)
            self.metrics.record_request(path, (time.time() - started) * 1000, success=True)
            self._tracer.finish_span(span, status="ok")
            return result
        except Exception as exc:
            err_code = exc.code if isinstance(exc, CommerceAPIError) else 0
            self.metrics.record_request(
                path,
                (time.time() - started) * 1000,
                success=False,
                error_code=err_code,
                error_msg=str(exc),
            )
            self._tracer.finish_span(span, status="error")
            raise

    def _check_envelope(self, resp: Any) -> dict[str, Any]:
        """Apply Kuaishou's success rule: ``result == 1``, payload in ``data``.

        The base class looks for an ``error_response`` key, which this gateway
        never emits — so every Kuaishou failure used to be reported to the model
        as a successful response whose "data" was actually an error envelope.
        """
        status = getattr(resp, "status_code", 200)
        if isinstance(status, int) and status >= 400:
            raise CommerceAPIError(code=status, msg=f"HTTP {status}: {str(getattr(resp, 'text', ''))[:200]}")

        payload = resp.json()
        if not isinstance(payload, dict):
            raise CommerceAPIError(code=-1, msg=f"Unexpected response type: {type(payload).__name__}")

        if payload.get("result") != 1:
            code = payload.get("result")
            code = code if isinstance(code, int) else -1
            msg = payload.get("error_msg") or payload.get("errorMsg") or payload.get("msg") or "unknown"
            logger.warning(f"Kuaishou API error: [{code}] {msg}")
            raise CommerceAPIError(code=code, msg=str(msg))

        return payload


# ── Instantiate client from env ────────────────────────────────────────────


def _refund_window_hours_from_env() -> int | None:
    raw = os.environ.get("KUAISHOU_REFUND_WINDOW_HOURS", "")
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(f"Ignoring non-integer KUAISHOU_REFUND_WINDOW_HOURS={raw!r}")
        return None


def _create_kuaishou_client() -> KuaishouMCP:
    """Create kuaishou client with configuration validation."""
    sign_method = os.environ.get("KUAISHOU_SIGN_METHOD", "")
    refund_window = _refund_window_hours_from_env()
    try:
        KuaishouMCP.from_env("KUAISHOU", ["APP_KEY", "APP_SECRET", "SIGN_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        pass
    # from_env() does not know about sign_secret, so construct directly either
    # way; the call above is kept for its validation logging.
    return KuaishouMCP(
        app_key=os.environ.get("KUAISHOU_APP_KEY", ""),
        app_secret=os.environ.get("KUAISHOU_APP_SECRET", ""),
        sign_secret=os.environ.get("KUAISHOU_SIGN_SECRET", ""),
        access_token=os.environ.get("KUAISHOU_ACCESS_TOKEN", ""),
        sign_method=sign_method,
        refund_window_hours=refund_window,
    )


ks = _create_kuaishou_client()


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = MCPServer("mcp-cn-kuaishou")


# ═══════════════════════════════════════════════════════════════════════════════
# 订单 (Orders)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_order_list(
    start_time: str,
    end_time: str,
    order_view_status: str = "1",
    cursor: str = "",
    page_size: int = 50,
) -> str:
    """Query the order list (method ``open.order.cursor.list``).

    Pure cursor pagination — there is no page number.  Pass ``cursor=""`` for
    the first call, then feed back the ``cursor`` from the response; the
    platform returns ``"nomore"`` when the result set is exhausted.

    Platform limits: ``page_size`` ≤ 50, query window ≤ 7 days, and only the
    last 90 days are queryable.

    Args:
        start_time: Window start — epoch millis or "2024-01-01 00:00:00"
            (naive values are read as GMT+8).
        end_time: Window end, same formats.
        order_view_status: Required by the platform. 1 全部, 2 待付款,
            3 待发货, 4 待收货, 5 已收货, 6 交易成功, 7 已关闭.
        cursor: Opaque cursor from the previous page; "" for the first page.
        page_size: Orders per page, max 50.
    """
    if str(order_view_status) not in ORDER_VIEW_STATUS:
        raise ValueError(f"order_view_status must be one of {sorted(ORDER_VIEW_STATUS)}, got {order_view_status!r}")

    begin_ms = _to_epoch_millis(start_time, field="start_time")
    end_ms = _to_epoch_millis(end_time, field="end_time")
    _warn_window(begin_ms, end_ms, max_span=timedelta(days=7), endpoint="open.order.cursor.list")
    _warn_retention(begin_ms, max_age=timedelta(days=90), endpoint="open.order.cursor.list")

    biz: dict[str, Any] = {
        "orderViewStatus": int(order_view_status),
        "beginTime": begin_ms,
        "endTime": end_ms,
        "pageSize": _clamp(int(page_size), 1, 50, field="page_size"),
        # Documented as an empty string on the first call; "nomore" is the
        # end-of-results sentinel, never a cursor to send back.
        "cursor": "" if not cursor or cursor == CURSOR_EXHAUSTED else cursor,
    }

    result = await ks._call("open.order.cursor.list", biz)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single order (method ``open.order.detail``).

    Args:
        order_id: The Kuaishou order ID (``oid``).
    """
    result = await ks._call("open.order.detail", {"orderId": order_id})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Get the product (item) list (method ``open.item.list.get``).

    Real page-number pagination.  ``page_size`` must be 10–100; 20 is the
    platform's recommended value.

    Args:
        page: Page number (``pageNumber``), starting from 1.
        page_size: Items per page, 10–100.
    """
    biz = {
        "pageNumber": max(1, int(page)),
        "pageSize": _clamp(int(page_size), 10, 100, field="page_size"),
    }
    result = await ks._call("open.item.list.get", biz)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(item_id: str) -> str:
    """Get full details of a single product (method ``open.item.get``).

    Args:
        item_id: The Kuaishou item ID.
    """
    result = await ks._call("open.item.get", {"itemId": item_id})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    start_time: str,
    end_time: str,
    pcursor: str = "",
    current_page: int = 1,
    page_size: int = 20,
) -> str:
    """Query the refund (after-sale) list.

    Method ``open.seller.order.refund.pcursor.list``.  Pagination is **hybrid**:
    ``pcursor`` and ``currentPage`` are both required by the platform, so both
    are always sent.

    Platform limits: ``page_size`` ≤ 100 and a query window of ≤ 1 day.  The
    window ceiling is tightened during large sales events, so it is
    configurable via ``KUAISHOU_REFUND_WINDOW_HOURS``.

    Note: no status filter is exposed — the official parameter name for it
    could not be established from the sources in scope, and this repo does not
    fill contract gaps with guesses (spec §8).

    Args:
        start_time: Window start — epoch millis or "2024-01-01 00:00:00".
        end_time: Window end, same formats.
        pcursor: Opaque cursor from the previous page; "" for the first page.
        current_page: Page counter the platform requires alongside ``pcursor``.
        page_size: Records per page, max 100.
    """
    begin_ms = _to_epoch_millis(start_time, field="start_time")
    end_ms = _to_epoch_millis(end_time, field="end_time")
    _warn_window(
        begin_ms,
        end_ms,
        max_span=timedelta(hours=ks.REFUND_WINDOW_HOURS),
        endpoint="open.seller.order.refund.pcursor.list",
    )

    biz: dict[str, Any] = {
        "beginTime": begin_ms,
        "endTime": end_ms,
        "currentPage": max(1, int(current_page)),
        "pageSize": _clamp(int(page_size), 1, 100, field="page_size"),
        # Always present, empty on the first call: the platform requires both
        # halves of the hybrid scheme even when the cursor is not yet known.
        "pcursor": "" if not pcursor or pcursor == CURSOR_EXHAUSTED else pcursor,
    }

    result = await ks._call("open.seller.order.refund.pcursor.list", biz)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(refund_id: str) -> str:
    """Get full details of one refund record.

    Method ``open.seller.order.refund.detail``.

    Args:
        refund_id: The refund / after-sale record ID.
    """
    result = await ks._call("open.seller.order.refund.detail", {"refundId": refund_id})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 评价 (Reviews)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_review_list(
    item_id: str,
    offset: int = 0,
    limit: int = 20,
) -> str:
    """Query the product review (comment) list (method ``open.comment.list.get``).

    Offset/limit pagination, with ``limit`` capped at **20** — lower than every
    other list endpoint on this platform.

    Args:
        item_id: The Kuaishou item ID.
        offset: Zero-based record offset.
        limit: Reviews per page, max 20.
    """
    biz = {
        "itemId": item_id,
        "offset": max(0, int(offset)),
        "limit": _clamp(int(limit), 1, 20, field="limit"),
    }
    result = await ks._call("open.comment.list.get", biz)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info() -> str:
    """Get shop information for the authenticated merchant.

    Method ``open.shop.info.get``.  Takes no business params, so no ``param``
    field is sent at all.
    """
    result = await ks._call("open.shop.info.get")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing) — coupons only
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_coupons(
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List the shop's coupons (method ``open.promotion.coupon.page.list``).

    Page-number pagination via ``pageNo``, which starts at 1.

    Note: no status filter is exposed — the official parameter name for it
    could not be established from the sources in scope (spec §8).

    Args:
        page: Page number (``pageNo``), starting from 1.
        page_size: Records per page.
    """
    biz = {
        "pageNo": max(1, int(page)),
        "pageSize": max(1, int(page_size)),
    }
    result = await ks._call("open.promotion.coupon.page.list", biz)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, ks)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-kuaishou' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
