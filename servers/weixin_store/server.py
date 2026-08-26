"""WeChat Store (微信小店) MCP server — provides read-only tools for merchant
orders, products, after-sale, logistics, shop info, marketing, supply chain,
and categories.

Auth: an ``access_token`` passed as a **query-string** parameter
(``?access_token=...``). Users can provide ``WX_ACCESS_TOKEN`` directly, or let
the server mint one from ``WX_APP_ID`` + ``WX_APP_SECRET`` via
``POST /cgi-bin/stable_token``.

API endpoint: https://api.weixin.qq.com

Every contract claim below is sourced in ``docs/api-contracts/weixin_store.md``,
which also marks which claims are official text and which are inferences. Three
points are worth repeating here:

* **No per-request signing.** This is an *inference*, not official text: WeChat
  never says "no signature" anywhere. It follows from the endpoint pages'
  parameter tables and auth columns being exhaustive and containing no ``sign``
  field. Treated as inference per spec §8.
* **``/cgi-bin/stable_token`` and ``/cgi-bin/token`` mint isolated
  credentials.** They do not invalidate one another, so their tokens must never
  share a cache slot. This module uses ``stable_token`` exclusively.
* **HTTP 403 carries no ``errcode``.** An IP that is not on the app's allowlist
  is rejected at the gateway with a bare 403, so status must be inspected before
  the body.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    register_common_tools,
)

# ── Documented contract constants ─────────────────────────────────────────────

#: Order status enum for ``/channels/ec/order/list/get``.
ORDER_STATUS: dict[int, str] = {
    10: "待付款",
    12: "礼物待收下",
    13: "一起买待成团",
    20: "待发货",
    21: "部分发货",
    30: "待收货",
    100: "完成",
    250: "订单取消",
}

#: Product status enum for ``/channels/ec/product/list/get``. There is no "all"
#: member — omit the field entirely to get every status.
PRODUCT_STATUS: dict[int, str] = {
    0: "初始值",
    5: "上架",
    6: "回收站",
    11: "下架",
}

#: Coupon status enum for ``/channels/ec/coupon/get_list``. The field is
#: mandatory and ``0`` is not a member, so there is no "all" query.
COUPON_STATUS: dict[int, str] = {
    1: "编辑中",
    2: "已生效",
    3: "已过期",
    4: "已作废",
    5: "已删除",
    200: "过期或作废",
}

#: ``data_type`` on ``/channels/ec/product/get``.
PRODUCT_DATA_TYPE: dict[int, str] = {1: "线上", 2: "草稿", 3: "两者"}

#: Order list time-range span cap.
ORDER_TIME_SPAN_MAX_SECONDS = 7 * 24 * 60 * 60

#: After-sale list time-range span cap — 24 hours, *not* the order list's 7 days.
AFTERSALE_TIME_SPAN_MAX_SECONDS = 24 * 60 * 60

ORDER_PAGE_SIZE_MAX = 100
PRODUCT_PAGE_SIZE_MAX = 30
PRODUCT_PAGE_SIZE_DEFAULT = 10
COUPON_PAGE_SIZE_MAX = 200

#: Consecutive coupon requests may not skip more than 10 pages.
COUPON_PAGE_STRIDE_MAX = 10

#: Which time range each list endpoint accepts, keyed by the tool's
#: ``time_field`` argument.
ORDER_TIME_RANGE_KEYS = {
    "create_time": "create_time_range",
    "update_time": "update_time_range",
}
AFTERSALE_TIME_FIELD_KEYS = {
    "create_time": ("begin_create_time", "end_create_time"),
    "update_time": ("begin_update_time", "end_update_time"),
}

#: Any epoch value beyond this is milliseconds, not the seconds WeChat wants.
_EPOCH_SECONDS_CEILING = 10**11


# ── Validation helpers ────────────────────────────────────────────────────────


def _check_enum(name: str, value: int, allowed: dict[int, str]) -> int:
    if value not in allowed:
        members = ", ".join(f"{k} ({v})" for k, v in allowed.items())
        raise ValueError(f"{name}={value!r} is not a documented value. Allowed: {members}")
    return value


def _check_epoch_seconds(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer epoch timestamp in seconds, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{name} must be a positive epoch timestamp in seconds, got {value}")
    if value >= _EPOCH_SECONDS_CEILING:
        raise ValueError(f"{name}={value} looks like milliseconds; WeChat Store expects seconds")
    return value


def _check_time_span(start: int, end: int, max_seconds: int, label: str) -> None:
    if end <= start:
        raise ValueError(f"{label}: end_time ({end}) must be greater than start_time ({start})")
    if end - start > max_seconds:
        raise ValueError(
            f"{label}: the span {end - start}s exceeds the documented maximum of "
            f"{max_seconds}s ({max_seconds // 3600}h)"
        )


def _check_bounds(name: str, value: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    if not low <= value <= high:
        raise ValueError(f"{name}={value} is out of range [{low}, {high}]")
    return value


def _check_choice(name: str, value: str, allowed: dict[str, Any]) -> str:
    if value not in allowed:
        raise ValueError(f"{name}={value!r} must be one of {sorted(allowed)}")
    return value


# ── WeChat Store client ───────────────────────────────────────────────────────


class WeixinStoreMCP(CommerceMCPBase):
    """WeChat Store (微信小店) client.

    The credential is an ``access_token`` on the query string of every request;
    there is no per-request signature (an inference — see module docstring).

    If ``WX_ACCESS_TOKEN`` is set it is used as-is, since an externally supplied
    token carries no ``expires_in`` for us to reason about. Otherwise
    ``WX_APP_ID`` + ``WX_APP_SECRET`` mint one via
    ``POST /cgi-bin/stable_token``, cached for exactly the ``expires_in`` the
    response reports.
    """

    BASE_URL = "https://api.weixin.qq.com"
    sign_method = ""  # No signing for WeChat Store — see module docstring.

    #: Official token endpoint. WeChat: "此接口和 getAccessToken 互相隔离，且比
    #: 其更加稳定，推荐使用此接口替代". Deliberately *not* ``/cgi-bin/token``:
    #: the two mint independent credentials and must not share a cache slot.
    TOKEN_PATH = "/cgi-bin/stable_token"

    #: Refresh this many seconds before the reported expiry. Capped at half the
    #: reported TTL so a short ``expires_in`` (the endpoint returns the *previous*
    #: token plus its remaining life, e.g. 345s) is still usable.
    TOKEN_REFRESH_BUFFER = 300.0

    #: ``force_refresh=true`` invalidates the previous token. WeChat caps it at
    #: 20 calls/day with at least 30s between calls, and labels it "慎用".
    FORCE_REFRESH_MIN_INTERVAL = 30.0
    FORCE_REFRESH_DAILY_LIMIT = 20

    #: The only errcodes for which a forced refresh is justified.
    TOKEN_ERRCODES = frozenset({40001, 42001, 40014})

    #: IP allowlist rejection. Returned at the gateway with no ``errcode`` and
    #: not necessarily a JSON body.
    IP_ALLOWLIST_STATUS = 403

    def __init__(self, app_key: str = "", app_secret: str = "", access_token: str = ""):
        super().__init__(app_key=app_key, app_secret=app_secret, access_token=access_token)
        # Cache slot dedicated to /cgi-bin/stable_token. Never populate it from
        # /cgi-bin/token: the two credentials are mutually isolated.
        self._stable_access_token: str = self.access_token or ""
        self._token_expires_at: float = 0.0
        self._token_ttl: float = 0.0
        self._force_refresh_log: list[float] = []
        # Coupon paging: WeChat forbids skipping more than
        # COUPON_PAGE_STRIDE_MAX pages between consecutive requests.
        self._coupon_page_cursor: int | None = None

    # ── Token ────────────────────────────────────────────────────────────────

    def _force_refresh_budget_error(self) -> str:
        """Return why a forced refresh is not allowed right now, or ""."""
        now = time.time()
        self._force_refresh_log = [t for t in self._force_refresh_log if now - t < 86400]
        if self._force_refresh_log and now - self._force_refresh_log[-1] < (self.FORCE_REFRESH_MIN_INTERVAL):
            waited = now - self._force_refresh_log[-1]
            return (
                f"stable_token force_refresh needs {self.FORCE_REFRESH_MIN_INTERVAL:.0f}s "
                f"between calls; only {waited:.0f}s have passed"
            )
        if len(self._force_refresh_log) >= self.FORCE_REFRESH_DAILY_LIMIT:
            return (
                f"stable_token force_refresh is capped at {self.FORCE_REFRESH_DAILY_LIMIT} "
                "calls per day and that budget is spent"
            )
        return ""

    def _can_force_refresh(self) -> bool:
        if not (self.app_key and self.app_secret):
            return False
        return not self._force_refresh_budget_error()

    async def _ensure_token(self, *, force_refresh: bool = False) -> str:
        """Return a usable access_token, minting one when necessary."""
        if not force_refresh and self._stable_access_token:
            if self._token_ttl == 0.0:
                # Externally supplied WX_ACCESS_TOKEN: there is no expires_in to
                # honour, and inventing one would be a guess. Use it until the
                # platform tells us it is dead (40001/42001/40014).
                return self._stable_access_token
            buffer = min(self.TOKEN_REFRESH_BUFFER, max(self._token_ttl, 0.0) / 2)
            if time.time() < self._token_expires_at - buffer:
                return self._stable_access_token

        if not self.app_key or not self.app_secret:
            raise CommerceAPIError(
                code=-1,
                msg=(
                    "WX_ACCESS_TOKEN not set and no WX_APP_ID / WX_APP_SECRET "
                    "available to fetch one. Set at least one pair of env vars."
                ),
            )

        if force_refresh:
            blocked = self._force_refresh_budget_error()
            if blocked:
                raise CommerceAPIError(code=-1, msg=blocked)

        body = {
            "grant_type": "client_credential",
            "appid": self.app_key,
            "secret": self.app_secret,
            "force_refresh": force_refresh,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.BASE_URL}{self.TOKEN_PATH}", json=body)
        data = self._decode(resp)

        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise CommerceAPIError(
                code=int(data.get("errcode", -1) or -1) if isinstance(data, dict) else -1,
                msg=(
                    data.get("errmsg", "stable_token returned no access_token")
                    if isinstance(data, dict)
                    else "stable_token returned no access_token"
                ),
            )

        expires_in = data.get("expires_in")
        self._stable_access_token = token
        if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
            # Always the reported TTL — never a hardcoded 7200. In non-forced
            # mode WeChat may hand back the *previous* token with only its
            # remaining life left (e.g. expires_in: 345).
            self._token_ttl = float(expires_in)
            self._token_expires_at = time.time() + float(expires_in)
        else:
            # No TTL reported and none to invent (spec §8): use the token for
            # this call and ask again next time.
            self._token_ttl = -1.0
            self._token_expires_at = 0.0
        if force_refresh:
            self._force_refresh_log.append(time.time())
        return token

    # ── Transport ────────────────────────────────────────────────────────────

    def _decode(self, resp: Any) -> dict[str, Any]:
        """Turn an HTTP response into a payload dict.

        Handles the failure shape that does *not* go through ``errcode``: an IP
        that is not on the app's allowlist is rejected with a bare HTTP 403, so
        the status code has to be inspected before the body is parsed.
        """
        status = getattr(resp, "status_code", 200)
        if status == self.IP_ALLOWLIST_STATUS:
            raise CommerceAPIError(
                code=self.IP_ALLOWLIST_STATUS,
                msg=(
                    "HTTP 403 from api.weixin.qq.com — the calling IP is not in this "
                    "app's IP allowlist. This rejection carries no errcode. Add the "
                    "egress IP in 微信小店后台 (allowlist holds up to 200 entries; "
                    "CIDR masks /8, /16 and /24 only)."
                ),
            )
        try:
            data = resp.json()
        except ValueError as exc:  # non-JSON body, e.g. a gateway error page
            text = getattr(resp, "text", "")
            raise CommerceAPIError(
                code=-1,
                msg=f"non-JSON response from WeChat Store (HTTP {status}): {text[:200]!r}",
            ) from exc
        if not isinstance(data, dict):
            raise CommerceAPIError(
                code=-1,
                msg=f"unexpected response type from WeChat Store: {type(data).__name__}",
            )
        return data

    async def _call(
        self,
        method: str,
        path: str,
        token: str,
        params: dict | None,
        data: dict | None,
    ) -> dict[str, Any]:
        """One HTTP round trip with ``access_token`` on the query string."""
        url = f"{self.BASE_URL}{path}"
        query_params: dict[str, str] = {"access_token": token}
        if params:
            query_params.update(params)

        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                # GET endpoints take no body at all — sending one earns 43001.
                resp = await client.get(url, params=query_params)
            else:
                resp = await client.post(url, params=query_params, json=(data or {}))
        return self._decode(resp)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        *,
        retry_on_token_error: bool = True,
    ) -> dict[str, Any]:
        """Make an API request with access_token in the query string.

        Overrides the base-class ``_request``, which does MD5/HMAC signing that
        WeChat Store has no use for.
        """
        token = await self._ensure_token()
        result = await self._call(method, path, token, params, data)

        errcode = result.get("errcode")
        if errcode in self.TOKEN_ERRCODES and retry_on_token_error and self._can_force_refresh():
            # Only these three errcodes justify burning force_refresh budget.
            token = await self._ensure_token(force_refresh=True)
            result = await self._call(method, path, token, params, data)
            errcode = result.get("errcode")

        # WeChat errors use "errcode" (0 = success)
        if errcode is not None and errcode != 0:
            raise CommerceAPIError(code=errcode, msg=result.get("errmsg", "unknown"))
        return result


# ── Instantiate client from env ────────────────────────────────────────────


def _create_weixin_store_client() -> WeixinStoreMCP:
    """Create weixin-store client with configuration validation."""
    # Check required vars
    required = ["WX_APP_ID", "WX_APP_SECRET"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise ConfigValidationError("WX", missing)

    return WeixinStoreMCP(
        app_key=os.environ.get("WX_APP_ID", ""),
        app_secret=os.environ.get("WX_APP_SECRET", ""),
        access_token=os.environ.get("WX_ACCESS_TOKEN", ""),
    )


_wx = _create_weixin_store_client()


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = MCPServer("mcp-cn-weixin-store")


# ═══════════════════════════════════════════════════════════════════════════════
# 订单 (Orders)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_order_list(
    start_time: int,
    end_time: int,
    order_status: str = "",
    page_size: int = 20,
    next_key: str = "",
    time_field: str = "create_time",
) -> str:
    """Query WeChat Store order list by time range and optional status.

    Args:
        start_time: Range start as an **epoch timestamp in seconds** (not a
            date string — a string earns errcode 40097).
        end_time: Range end, epoch seconds. The span must not exceed 7 days.
        order_status: Status filter, as a string; empty means no filter.
            10 待付款 / 12 礼物待收下 / 13 一起买待成团 / 20 待发货 /
            21 部分发货 / 30 待收货 / 100 完成 / 250 订单取消.
        page_size: Orders per page, 1–100.
        next_key: Cursor taken verbatim from the previous page's ``next_key``.
            Leave empty for the first page; every other parameter must stay
            identical across a cursor walk or WeChat returns 606006.
        time_field: Which range to filter on, "create_time" or "update_time".
            WeChat requires at least one of the two; this tool sends exactly one.

    Returns ``order_id_list`` plus ``has_more`` and ``next_key``. Errcode 31042
    means the range matched too many orders — narrow it.
    """
    _check_choice("time_field", time_field, ORDER_TIME_RANGE_KEYS)
    start = _check_epoch_seconds("start_time", start_time)
    end = _check_epoch_seconds("end_time", end_time)
    _check_time_span(start, end, ORDER_TIME_SPAN_MAX_SECONDS, "order list time range")
    _check_bounds("page_size", page_size, 1, ORDER_PAGE_SIZE_MAX)

    data: dict = {
        ORDER_TIME_RANGE_KEYS[time_field]: {"start_time": start, "end_time": end},
        "page_size": page_size,
    }
    if order_status:
        data["status"] = _check_enum("order_status", int(order_status), ORDER_STATUS)
    if next_key:
        data["next_key"] = next_key

    result = await _wx._request("POST", "/channels/ec/order/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single WeChat Store order.

    Args:
        order_id: The WeChat Store order ID (e.g. "3705115058471207000").
    """
    data = {"order_id": order_id}
    result = await _wx._request("POST", "/channels/ec/order/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 商品 (Products)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_product_list(
    status: str = "",
    page_size: int = PRODUCT_PAGE_SIZE_DEFAULT,
    next_key: str = "",
) -> str:
    """Get product (商品) list with basic info.

    Args:
        status: Status filter, as a string. 0 初始值 / 5 上架 / 6 回收站 /
            11 下架. There is no "all" member — leave this empty to get every
            status, since the field is then omitted from the request.
        page_size: Products per page, 1–30 (WeChat's cap is 30, not 200).
        next_key: Cursor from the previous page's ``next_key``; empty for the
            first page.

    Returns ``product_ids``, ``next_key`` and ``total_num``. There is no
    ``has_more`` on this endpoint — page against ``total_num``.
    """
    _check_bounds("page_size", page_size, 1, PRODUCT_PAGE_SIZE_MAX)
    data: dict = {"page_size": page_size}
    if status != "":
        data["status"] = _check_enum("status", int(status), PRODUCT_STATUS)
    if next_key:
        data["next_key"] = next_key
    result = await _wx._request("POST", "/channels/ec/product/list/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_product_detail(product_id: str, data_type: int = 1) -> str:
    """Get full details of a single product by product ID.

    Args:
        product_id: The WeChat Store product ID (e.g. "10000000000001").
        data_type: Which copy to read — 1 线上 (default), 2 草稿, 3 两者.
    """
    _check_enum("data_type", data_type, PRODUCT_DATA_TYPE)
    data = {"product_id": product_id, "data_type": data_type}
    result = await _wx._request("POST", "/channels/ec/product/get", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_refund_list(
    start_time: int,
    end_time: int,
    time_field: str = "create_time",
    next_key: str = "",
) -> str:
    """Query after-sale (售后) record list by time range.

    This endpoint's contract is *not* the order list's: the bounds are four flat
    fields rather than a nested range object, the span cap is 24 hours rather
    than 7 days, and there is no page size or page number at all.

    Args:
        start_time: Range start as an **epoch timestamp in seconds**.
        end_time: Range end, epoch seconds. The span must not exceed 24 hours.
        time_field: Which pair of bounds to send — "create_time" sends
            ``begin_create_time``/``end_create_time``, "update_time" sends
            ``begin_update_time``/``end_update_time``. The two members of a pair
            are always sent together; exactly one pair is required.
        next_key: Cursor from the previous page's ``next_key``; empty for the
            first page. Paging is cursor-only here.

    Returns ``after_sale_order_id_list`` plus ``has_more`` and ``next_key``.
    """
    _check_choice("time_field", time_field, AFTERSALE_TIME_FIELD_KEYS)
    start = _check_epoch_seconds("start_time", start_time)
    end = _check_epoch_seconds("end_time", end_time)
    _check_time_span(start, end, AFTERSALE_TIME_SPAN_MAX_SECONDS, "after-sale list time range")

    begin_field, end_field = AFTERSALE_TIME_FIELD_KEYS[time_field]
    data: dict = {begin_field: start, end_field: end}
    if next_key:
        data["next_key"] = next_key
    result = await _wx._request("POST", "/channels/ec/aftersale/getaftersalelist", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_refund_detail(after_sale_order_id: str) -> str:
    """Get full details of a single after-sale (refund) record.

    Args:
        after_sale_order_id: The after-sale order ID (e.g. "3705115058471207000").
    """
    data = {"after_sale_order_id": after_sale_order_id}
    result = await _wx._request("POST", "/channels/ec/aftersale/getaftersaleorder", data=data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════

#: Where the logistics payload actually lives. WeChat Store publishes no
#: logistics *pull* endpoint — the whole platform offers only a write
#: ("修改物流信息") API — so the data is read out of the order detail.
LOGISTICS_SOURCE_ENDPOINT = "/channels/ec/order/get"
LOGISTICS_SOURCE_FIELD = "order.order_detail.delivery_info"


@mcp.tool()
async def get_logistics_tracking(order_id: str) -> str:
    """Get logistics information for a WeChat Store order.

    WeChat Store has no logistics-pull endpoint, so this reads the
    ``delivery_info`` embedded in the order detail (``waybill_id``,
    ``delivery_id``, ``extra_logistics_info`` …). It is delivery *state*, not a
    carrier trace: there are no scan nodes to return.

    Args:
        order_id: The WeChat Store order ID (e.g. "3705115058471207000").
    """
    result = await _wx._request("POST", LOGISTICS_SOURCE_ENDPOINT, data={"order_id": order_id})
    order = result.get("order") or {}
    order_detail = order.get("order_detail") or {}
    payload = {
        "errcode": result.get("errcode", 0),
        "errmsg": result.get("errmsg", "ok"),
        "order_id": order_id,
        "delivery_info": order_detail.get("delivery_info"),
        "source": {
            "endpoint": LOGISTICS_SOURCE_ENDPOINT,
            "field": LOGISTICS_SOURCE_FIELD,
            "note": (
                "WeChat Store exposes no logistics-pull endpoint; this is the "
                "delivery_info embedded in the order detail."
            ),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺 (Shop)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def get_shop_info() -> str:
    """Get basic shop (店铺) information for the authenticated merchant.

    ``GET`` with no body; a POST to this path returns errcode 43001.
    """
    result = await _wx._request("GET", "/channels/ec/basics/info/get")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 营销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_coupons(
    status: int,
    page: int = 1,
    page_size: int = 20,
    page_ctx: str = "",
) -> str:
    """List coupon (优惠券) activities for the WeChat Store.

    All four request fields are mandatory, so ``status`` has no default: there
    is no "all statuses" query on this endpoint.

    Args:
        status: 1 编辑中 / 2 已生效 / 3 已过期 / 4 已作废 / 5 已删除 /
            200 过期或作废.
        page: Page number, 1-based. Consecutive calls may not skip more than 10
            pages.
        page_size: Records per page, 1–200.
        page_ctx: Paging context — empty string on the first request, then the
            value returned by the previous page.
    """
    _check_enum("status", status, COUPON_STATUS)
    _check_bounds("page", page, 1, 2**31 - 1)
    _check_bounds("page_size", page_size, 1, COUPON_PAGE_SIZE_MAX)

    previous = _wx._coupon_page_cursor
    if previous is not None and abs(page - previous) > COUPON_PAGE_STRIDE_MAX:
        raise ValueError(
            f"coupon paging may not jump more than {COUPON_PAGE_STRIDE_MAX} pages "
            f"between requests: last requested page was {previous}, this one is {page}"
        )

    data = {
        "status": status,
        "page": page,
        "page_size": page_size,
        "page_ctx": page_ctx,
    }
    result = await _wx._request("POST", "/channels/ec/coupon/get_list", data=data)
    _wx._coupon_page_cursor = page
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 供货 (Supply Chain)
# ═══════════════════════════════════════════════════════════════════════════════

#: We call the **shop side** of the dropship pair. See
#: ``docs/api-contracts/weixin_store.md`` for the decision and its reasoning:
#: this server authenticates as a 微信小店 merchant, and a shop token cannot
#: reach the supplier-side endpoint (``order/dropship/supplier/list``,
#: permission 192, which additionally requires a 「小店供货商」 account).
SUPPLY_ORDER_ENDPOINT = "/channels/ec/order/dropship/list"


@mcp.tool()
async def get_supply_order_list() -> str:
    """Query dropship order (供货订单) list from the shop side.

    Takes no arguments on purpose. The path is confirmed, but this endpoint's
    request-field contract is not in our verified corpus, and spec §8 forbids
    filling that gap by guessing — the previous version of this tool sent five
    invented fields to a path that did not exist. Until the official field list
    is confirmed, the request body is empty and filtering/paging is not exposed.
    """
    result = await _wx._request("POST", SUPPLY_ORDER_ENDPOINT, data={})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 类目 (Categories)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_categories() -> str:
    """List product categories (类目) on WeChat Store.

    ``GET`` with no body and no parameters — one call returns the whole tree, so
    there is nothing to walk level by level. Note the path prefix is
    ``/shop/ec/``, not ``/channels/ec/`` like the rest of this server. The
    current tree is in ``cats_v2``.
    """
    result = await _wx._request("GET", "/shop/ec/category/all")
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, _wx)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Entry point for 'mcp-cn-weixin-store' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
