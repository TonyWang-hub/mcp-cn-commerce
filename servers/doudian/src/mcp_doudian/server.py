"""MCP Server for 抖店 (Douyin Shop / Doudian) e-commerce platform.

Read-only tools for AI agents to query merchant business data:
orders, products, refunds, and shop info.

Authentication via environment variables:
  DOUDIAN_APP_KEY       — App Key from Douyin Open Platform
  DOUDIAN_APP_SECRET    — App Secret
  DOUDIAN_SHOP_ID       — Shop ID
  DOUDIAN_ACCESS_TOKEN  — OAuth access token

Usage:
  mcp-cn-doudian
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)

BASE_URL = "https://openapi-fxg.jinritemai.com/"

server = Server("mcp-cn-doudian")

# ── Exceptions ──────────────────────────────────────────────


class DouDianAPIError(Exception):
    """Normalized API error for Douyin shop."""

    def __init__(self, code: int, msg: str, sub_code: str = "", sub_msg: str = ""):
        self.code = code
        self.msg = msg
        self.sub_code = sub_code
        self.sub_msg = sub_msg
        detail = f"[{code}] {msg}"
        if sub_code:
            detail += f" (sub: [{sub_code}] {sub_msg})"
        super().__init__(detail)


class ConfigError(Exception):
    """Missing required configuration."""


# ── HTTP Client ─────────────────────────────────────────────


class DouDianClient:
    """HTTP client for the Doudian Open API.

    Implements Douyin-shop-specific MD5 signing:

    1. Sort business params alphabetically by key.
    2. Serialize to compact JSON (no spaces).
    3. Compute MD5(app_key + param_json + app_secret).
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        access_token: str,
        shop_id: str = "",
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.shop_id = shop_id

    # ── Signing ─────────────────────────────────────────

    def _sign(self, params: dict) -> str:
        """Generate Doudian MD5 signature.

        Filters out None/empty values, sorts alphabetically, serializes
        to compact JSON, then signs with MD5.
        """
        # Remove empty values so they don't affect the signature
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        # Sort by key alphabetically
        sorted_params = dict(sorted(clean.items()))
        # Compact JSON (no spaces, no ASCII escaping)
        param_json = json.dumps(
            sorted_params, separators=(",", ":"), ensure_ascii=False
        )
        # Build the sign string: app_key + JSON + app_secret
        sign_str = f"{self.app_key}{param_json}{self.app_secret}"
        return hashlib.md5(sign_str.encode()).hexdigest()

    # ── Request ─────────────────────────────────────────

    async def request(
        self,
        method: str,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make a signed POST request to Doudian Open API.

        Args:
            method: API method name, e.g. "order/list".
            params: Business parameters (placed in POST body as JSON).

        Returns:
            Parsed response data dict.

        Raises:
            DouDianAPIError: When the API returns a non-success code.
        """
        params = params or {}

        url = f"{BASE_URL.rstrip('/')}/{method.lstrip('/')}"

        # Common params go in the query string
        common = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            "v": "2",
            "sign_method": "md5",
            "access_token": self.access_token,
        }

        # Sign only the business params
        common["sign"] = self._sign(params)

        logger.debug("Request: %s %s", method, params)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, params=common, json=params)

        logger.debug("Response status: %s", resp.status_code)

        try:
            result = resp.json()
        except json.JSONDecodeError:
            raise DouDianAPIError(
                code=-1,
                msg=f"Invalid JSON response (HTTP {resp.status_code}): {resp.text[:500]}",
            )

        error_code = result.get("code", 10000)
        if error_code != 10000:
            raise DouDianAPIError(
                code=error_code,
                msg=result.get("msg", "unknown error"),
                sub_code=str(result.get("sub_code", "")),
                sub_msg=result.get("sub_msg", ""),
            )

        return result.get("data", result)


# ── Client singleton ────────────────────────────────────────

_client: DouDianClient | None = None


def _get_client() -> DouDianClient:
    """Lazily create and cache the DouDianClient from env vars."""
    global _client
    if _client is not None:
        return _client

    app_key = os.environ.get("DOUDIAN_APP_KEY", "")
    app_secret = os.environ.get("DOUDIAN_APP_SECRET", "")
    shop_id = os.environ.get("DOUDIAN_SHOP_ID", "")
    access_token = os.environ.get("DOUDIAN_ACCESS_TOKEN", "")

    missing = []
    if not app_key:
        missing.append("DOUDIAN_APP_KEY")
    if not app_secret:
        missing.append("DOUDIAN_APP_SECRET")
    if not shop_id:
        missing.append("DOUDIAN_SHOP_ID")
    if not access_token:
        missing.append("DOUDIAN_ACCESS_TOKEN")

    if missing:
        raise ConfigError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    _client = DouDianClient(
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_token,
        shop_id=shop_id,
    )
    return _client


# ── Helper: safe extraction ─────────────────────────────────


def _safe_get(d: dict, *keys: str, default: Any = "") -> Any:
    """Safely extract a nested value from a dict."""
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key, {})
        else:
            return default
    return d if d != {} else default


# ═══════════════════════════════════════════════════════════════
#  MCP Tools  (read-only)
# ═══════════════════════════════════════════════════════════════


@server.tool()
async def get_order_list(
    start_time: str = "",
    end_time: str = "",
    order_status: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """获取抖店订单列表。

    Args:
        start_time: 订单开始时间，格式如 '2024-01-01 00:00:00'
        end_time: 订单结束时间
        order_status: 订单状态筛选 (1:待确认, 2:备货中, 3:已发货, 4:已收货, 5:已完成, 101:已取消)
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含订单列表的字典，每个订单含 order_id, status, amount, product_info, buyer_info
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if order_status:
            params["order_status"] = str(order_status)

        data = await client.request("order/list", params)

        raw_orders = data.get("list", data.get("data", []))
        if not isinstance(raw_orders, list):
            raw_orders = []

        orders = [
            {
                "order_id": _safe_get(o, "order_id"),
                "shop_order_id": _safe_get(o, "shop_order_id"),
                "status": _safe_get(o, "order_status"),
                "status_desc": _safe_get(o, "order_status_desc"),
                "amount": _safe_get(o, "pay_amount"),
                "post_amount": _safe_get(o, "post_amount"),
                "create_time": _safe_get(o, "create_time"),
                "pay_time": _safe_get(o, "pay_time"),
                "product_info": [
                    {
                        "product_id": _safe_get(p, "product_id"),
                        "product_name": _safe_get(p, "product_name"),
                        "price": _safe_get(p, "price"),
                        "quantity": _safe_get(p, "combo_num"),
                        "spec_desc": _safe_get(p, "spec_desc"),
                    }
                    for p in _safe_get(o, "product_info", "list", default=[])
                ],
                "buyer_info": {
                    "buyer_name": _safe_get(o, "buyer_info", "name"),
                    "buyer_phone": _safe_get(o, "buyer_info", "phone"),
                    "buyer_words": _safe_get(o, "buyer_words"),
                },
            }
            for o in raw_orders
        ]

        return {
            "total": data.get("total", sum(data.get(k, 0) for k in ("total", "total_count", "count"))),
            "page": page,
            "page_size": page_size,
            "orders": orders,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "orders": []}
    except ConfigError as e:
        return {"error": str(e), "orders": []}
    except Exception as e:
        logger.exception("Unexpected error in get_order_list")
        return {"error": f"Unexpected error: {e}", "orders": []}


@server.tool()
async def get_order_detail(
    order_id: str = "",
    shop_order_id: str = "",
) -> dict:
    """获取抖店单个订单详情。

    包括物流信息、售后/退款状态、商品详情、买家信息等完整字段。

    Args:
        order_id: 订单号 (与 shop_order_id 二选一)
        shop_order_id: 商户订单号 (与 order_id 二选一)

    Returns:
        包含订单完整信息的字典
    """
    try:
        client = _get_client()

        if not order_id and not shop_order_id:
            return {
                "error": "Please provide either order_id or shop_order_id",
                "order": None,
            }

        params: dict[str, Any] = {}
        if order_id:
            params["order_id"] = order_id
        if shop_order_id:
            params["shop_order_id"] = shop_order_id

        data = await client.request("order/detail", params)

        raw = data.get("detail", data.get("order_info", data))

        order = {
            # Basic info
            "order_id": _safe_get(raw, "order_id"),
            "shop_order_id": _safe_get(raw, "shop_order_id"),
            "status": _safe_get(raw, "order_status"),
            "status_desc": _safe_get(raw, "order_status_desc"),
            "create_time": _safe_get(raw, "create_time"),
            "pay_time": _safe_get(raw, "pay_time"),
            "pay_type": _safe_get(raw, "pay_type"),
            "pay_amount": _safe_get(raw, "pay_amount"),
            "post_amount": _safe_get(raw, "post_amount"),
            "post_insurance_amount": _safe_get(raw, "post_insurance_amount"),
            "coupon_amount": _safe_get(raw, "coupon_amount"),
            "shop_coupon_amount": _safe_get(raw, "shop_coupon_amount"),
            "total_amount": _safe_get(raw, "total_amount"),
            "cancel_reason": _safe_get(raw, "cancel_reason"),
            "buyer_words": _safe_get(raw, "buyer_words"),
            "seller_words": _safe_get(raw, "seller_words"),
            "is_comment": _safe_get(raw, "is_comment"),

            # Logistics
            "logistics": {
                "company": _safe_get(raw, "logistics_info", "company"),
                "code": _safe_get(raw, "logistics_info", "code"),
                "receiver_name": _safe_get(raw, "logistics_info", "receiver_name"),
                "receiver_phone": _safe_get(raw, "logistics_info", "receiver_phone"),
                "receiver_address": _safe_get(raw, "logistics_info", "receiver_address"),
                "ship_time": _safe_get(raw, "logistics_info", "ship_time"),
                "delivery_time": _safe_get(raw, "logistics_info", "delivery_time"),
            },

            # Refund / after-sale
            "refund_status": _safe_get(raw, "refund_status"),
            "refund_amount": _safe_get(raw, "refund_amount"),
            "refund_type": _safe_get(raw, "refund_type"),
            "after_sale_id": _safe_get(raw, "after_sale_id"),

            # Products
            "products": [
                {
                    "product_id": _safe_get(p, "product_id"),
                    "product_name": _safe_get(p, "product_name"),
                    "price": _safe_get(p, "price"),
                    "quantity": _safe_get(p, "combo_num"),
                    "spec_desc": _safe_get(p, "spec_desc"),
                    "outer_sku_id": _safe_get(p, "outer_sku_id"),
                    "sku_id": _safe_get(p, "sku_id"),
                }
                for p in _safe_get(raw, "product_info", "list", default=[])
            ],

            # Buyer
            "buyer": {
                "name": _safe_get(raw, "buyer_info", "name"),
                "phone": _safe_get(raw, "buyer_info", "phone"),
                "post_addr": _safe_get(raw, "buyer_info", "post_addr"),
                "post_code": _safe_get(raw, "buyer_info", "post_code"),
                "province": _safe_get(raw, "buyer_info", "province", "name"),
                "city": _safe_get(raw, "buyer_info", "city", "name"),
                "town": _safe_get(raw, "buyer_info", "town", "name"),
                "street": _safe_get(raw, "buyer_info", "street", "name"),
            },

            # Additional
            "order_tags": _safe_get(raw, "order_tags"),
            "appointment_delivery_time": _safe_get(raw, "appointment_delivery_time"),
            "main_status": _safe_get(raw, "main_status"),
            "main_status_desc": _safe_get(raw, "main_status_desc"),
            "shop_id": _safe_get(raw, "shop_id"),
        }

        return {"order": order}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "order": None}
    except ConfigError as e:
        return {"error": str(e), "order": None}
    except Exception as e:
        logger.exception("Unexpected error in get_order_detail")
        return {"error": f"Unexpected error: {e}", "order": None}


@server.tool()
async def get_product_list(
    page: int = 0,
    page_size: int = 10,
    status: str = "",
) -> dict:
    """获取抖店商品列表。

    Args:
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100
        status: 商品状态筛选 (on_sale: 在售, off_sale: 下架, 不填则返回全部)

    Returns:
        包含商品列表的字典，每个商品含 product_id, name, price, stock, sales 等信息
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if status:
            params["status"] = status

        data = await client.request("product/list", params)

        raw_products = data.get("list", data.get("data", data.get("products", [])))
        if not isinstance(raw_products, list):
            raw_products = []

        products = [
            {
                "product_id": _safe_get(p, "product_id"),
                "product_id_str": _safe_get(p, "product_id_str"),
                "name": _safe_get(p, "name", default=_safe_get(p, "product_name")),
                "price": _safe_get(p, "price"),
                "market_price": _safe_get(p, "market_price"),
                "stock": _safe_get(p, "stock", default=_safe_get(p, "inventory")),
                "sales": _safe_get(p, "sales", default=_safe_get(p, "sell_num")),
                "status": _safe_get(p, "status"),
                "status_desc": _safe_get(p, "status_desc"),
                "category_id": _safe_get(p, "category_id"),
                "category_name": _safe_get(p, "category_name"),
                "image": _safe_get(p, "img", default=_safe_get(p, "main_image")),
                "create_time": _safe_get(p, "create_time"),
                "update_time": _safe_get(p, "update_time"),
                "spec_count": _safe_get(p, "spec_count"),
                "min_price": _safe_get(p, "min_price"),
                "max_price": _safe_get(p, "max_price"),
                "description": _safe_get(p, "description"),
                "outer_product_id": _safe_get(p, "outer_product_id"),
            }
            for p in raw_products
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "products": products,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "products": []}
    except ConfigError as e:
        return {"error": str(e), "products": []}
    except Exception as e:
        logger.exception("Unexpected error in get_product_list")
        return {"error": f"Unexpected error: {e}", "products": []}


@server.tool()
async def get_refund_list(
    start_time: str = "",
    end_time: str = "",
    refund_type: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """获取抖店售后/退款单列表。

    Args:
        start_time: 开始时间，格式如 '2024-01-01 00:00:00'
        end_time: 结束时间
        refund_type: 售后类型 (0:仅退款, 1:退货退款, 2:换货, 3:维修)
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含退款单列表的字典，每个退款单含 refund_id, order_id, amount, status, reason 等
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if refund_type:
            params["type"] = refund_type

        data = await client.request("refund/listSearch", params)

        raw_refunds = data.get("list", data.get("data", []))
        if not isinstance(raw_refunds, list):
            raw_refunds = []

        refunds = [
            {
                "refund_id": _safe_get(r, "refund_id"),
                "order_id": _safe_get(r, "order_id"),
                "refund_type": _safe_get(r, "refund_type"),
                "refund_type_desc": _safe_get(r, "refund_type_desc"),
                "amount": _safe_get(r, "refund_amount"),
                "status": _safe_get(r, "status"),
                "status_desc": _safe_get(r, "status_desc"),
                "reason": _safe_get(r, "reason"),
                "reason_desc": _safe_get(r, "reason_desc"),
                "create_time": _safe_get(r, "create_time"),
                "update_time": _safe_get(r, "update_time"),
                "refund_phase": _safe_get(r, "refund_phase"),
                "pay_amount": _safe_get(r, "pay_amount"),
                "logistics_code": _safe_get(r, "logistics_code"),
                "logistics_company": _safe_get(r, "logistics_company"),
                "product_name": _safe_get(r, "product_name"),
                "product_id": _safe_get(r, "product_id"),
                "buyer_name": _safe_get(r, "buyer_name"),
                "arbitrate_status": _safe_get(r, "arbitrate_status"),
            }
            for r in raw_refunds
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "refunds": refunds,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "refunds": []}
    except ConfigError as e:
        return {"error": str(e), "refunds": []}
    except Exception as e:
        logger.exception("Unexpected error in get_refund_list")
        return {"error": f"Unexpected error: {e}", "refunds": []}


@server.tool()
async def get_shop_info() -> dict:
    """获取抖店基本信息。

    返回店铺名称、Logo、评分、状态、认证信息等。

    Returns:
        包含店铺基本信息的字典
    """
    try:
        client = _get_client()

        data = await client.request("shop/basicInfo", {})

        raw = data.get("shop", data.get("shop_info", data))

        shop = {
            "shop_id": _safe_get(raw, "shop_id"),
            "shop_name": _safe_get(raw, "shop_name"),
            "logo": _safe_get(raw, "logo", default=_safe_get(raw, "shop_logo")),
            "rating": _safe_get(raw, "shop_score", default=_safe_get(raw, "rating")),
            "status": _safe_get(raw, "status", default=_safe_get(raw, "shop_status")),
            "status_desc": _safe_get(raw, "status_desc"),
            "shop_type": _safe_get(raw, "shop_type"),
            "main_product": _safe_get(raw, "main_product"),
            "open_time": _safe_get(raw, "open_time"),
            "province": _safe_get(raw, "province", "name"),
            "city": _safe_get(raw, "city", "name"),
            "certification_status": _safe_get(raw, "certification_status"),
            "brand_info": _safe_get(raw, "brand_info"),
            "goods_count": _safe_get(raw, "goods_count"),
            "order_count_30d": _safe_get(raw, "order_count_30d"),
            "refund_rate": _safe_get(raw, "refund_rate"),
            "dispute_rate": _safe_get(raw, "dispute_rate"),
        }

        return {"shop": shop}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "shop": None}
    except ConfigError as e:
        return {"error": str(e), "shop": None}
    except Exception as e:
        logger.exception("Unexpected error in get_shop_info")
        return {"error": f"Unexpected error: {e}", "shop": None}


# ═══════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """Run the Doudian MCP server via stdio transport."""
    import asyncio

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
