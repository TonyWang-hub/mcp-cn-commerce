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

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer

from servers.doudian.client import ConfigError, DouDianAPIError, DouDianClient
from servers.doudian.schema import (
    ORDER_DETAIL,
    ORDER_LIST,
    REFUND_LIST,
    list_params,
    project_order,
    project_refund,
    validate_read_response,
)
from shared.cn_commerce_base import (
    SensitiveDataFilter,
    register_common_tools,
)

logger = logging.getLogger(__name__)
logger.addFilter(SensitiveDataFilter())


@asynccontextmanager
async def _lifespan(_server):
    try:
        yield {}
    finally:
        client = _client
        if client is not None:
            await client.close()


server = MCPServer("mcp-cn-doudian", lifespan=_lifespan)

# ── Exceptions ──────────────────────────────────────────────


# ── HTTP Client ─────────────────────────────────────────────


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
    time_type: str = "create",
) -> dict:
    """按创建或更新时间查询近90天创建的店铺订单。

    日期使用北京时间或秒时间戳；page从0起、page_size为1至100。状态：1待支付、105已支付、
    2备货中、101部分发货、3已发货、4取消、5完成。amount为平台支付金额（分，含支付优惠），
    buyer_paid_amount另行扣除支付优惠；缺少优惠字段时保持未知。单页不是完整日报。
    """
    try:
        params = list_params(ORDER_LIST, start_time, end_time, page, page_size, time_type=time_type)
        if order_status:
            codes = [int(value.strip()) for value in order_status.split(",")]
            if any(value not in {1, 105, 2, 101, 3, 4, 5} for value in codes):
                raise ValueError("Unsupported official order_status")
            params["combine_status"] = [{"order_status": ",".join(str(code) for code in codes)}]
        data = await _get_client().request(ORDER_LIST, params)
        validate_read_response(ORDER_LIST, data)
        orders = [project_order(item) for item in data["shop_order_list"]]
        return {
            "total": data["total"],
            "page": page,
            "page_size": page_size,
            "orders": orders,
            "has_more": (page + 1) * page_size < data["total"],
            "time_type": time_type,
            "history_scope": "orders_created_within_last_90_days",
        }
    except DouDianAPIError as exc:
        return {"error": str(exc), "code": exc.code, "orders": []}
    except (ConfigError, ValueError) as exc:
        return {"error": str(exc), "orders": []}


@server.tool()
async def get_order_detail(order_id: str = "", shop_order_id: str = "") -> dict:
    """查询抖店店铺父订单详情；order_id为shop_order_id的兼容别名，二者不能冲突。"""
    try:
        if not order_id and not shop_order_id:
            raise ValueError("Please provide either order_id or shop_order_id")
        if order_id and shop_order_id and order_id != shop_order_id:
            raise ValueError("order_id and shop_order_id must identify the same platform shop order")
        data = await _get_client().request(ORDER_DETAIL, {"shop_order_id": shop_order_id or order_id})
        validate_read_response(ORDER_DETAIL, data)
        return {"order": project_order(data["shop_order_detail"])}
    except DouDianAPIError as exc:
        return {"error": str(exc), "code": exc.code, "order": None}
    except (ConfigError, ValueError) as exc:
        return {"error": str(exc), "order": None}


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
    time_type: str = "create",
) -> dict:
    """按申请/更新时间查询售后列表，0页起，每页最多100条，最多翻页至page*size=50000。

    refund_type为售后类型：0退货退款、1已发货退款、2未发货退款、3换货、6价保、7补寄、8维修。
    列表只返回申请金额；实际退款金额和成功时间必须通过SDK get_refund_detail查询，不能用更新时间替代。
    """
    try:
        params = list_params(REFUND_LIST, start_time, end_time, page, page_size, time_type=time_type)
        if refund_type:
            kind = int(refund_type)
            if kind not in {0, 1, 2, 3, 6, 7, 8}:
                raise ValueError("Unsupported official aftersale_type")
            params["aftersale_type"] = kind
        data = await _get_client().request(REFUND_LIST, params)
        validate_read_response(REFUND_LIST, data)
        return {
            "total": data["total"],
            "page": page,
            "page_size": page_size,
            "refunds": [project_refund(item) for item in data["items"]],
            "has_more": data["has_more"],
            "time_type": time_type,
        }
    except DouDianAPIError as exc:
        return {"error": str(exc), "code": exc.code, "refunds": []}
    except (ConfigError, ValueError) as exc:
        return {"error": str(exc), "refunds": []}


@server.tool()
async def get_shop_info() -> dict:
    """暂不支持：当前官方目录没有已核实的通用抖店基础信息接口。"""
    return {
        "supported": False,
        "shop": None,
        "error": "Unsupported: no verified general Doudian shop-info API; no request was sent",
    }


# ── 物流 (logistics) ────────────────────────────────────────────


@server.tool()
async def get_logistics_tracking(
    order_id: str = "",
) -> dict:
    """物流轨迹追踪 — 查询订单的物流配送状态和轨迹。

    Args:
        order_id: 订单号 (必填)

    Returns:
        包含物流轨迹的字典，含 tracking_id, status, company, steps 等
    """
    try:
        client = _get_client()

        if not order_id:
            return {
                "error": "Please provide order_id",
                "tracking": None,
            }

        params: dict[str, Any] = {"order_id": order_id}
        data = await client.request("order/logisticsTrace", params)

        raw = data.get("logistics_trace", data.get("logistics_info", data))

        tracking = {
            "order_id": _safe_get(raw, "order_id"),
            "tracking_id": _safe_get(raw, "tracking_id", default=_safe_get(raw, "logistics_code")),
            "company": _safe_get(raw, "company", default=_safe_get(raw, "logistics_company")),
            "status": _safe_get(raw, "status", default=_safe_get(raw, "logistics_status")),
            "status_desc": _safe_get(raw, "status_desc"),
            "receiver_name": _safe_get(raw, "receiver_name"),
            "receiver_phone": _safe_get(raw, "receiver_phone"),
            "receiver_address": _safe_get(raw, "receiver_address"),
            "sender_name": _safe_get(raw, "sender_name"),
            "sender_phone": _safe_get(raw, "sender_phone"),
            "sender_address": _safe_get(raw, "sender_address"),
            "ship_time": _safe_get(raw, "ship_time"),
            "delivery_time": _safe_get(raw, "delivery_time"),
            "sign_time": _safe_get(raw, "sign_time"),
            "steps": [
                {
                    "time": _safe_get(s, "time"),
                    "status": _safe_get(s, "status"),
                    "desc": _safe_get(s, "desc", default=_safe_get(s, "description")),
                    "location": _safe_get(s, "location", default=_safe_get(s, "city")),
                }
                for s in _safe_get(raw, "trace_list", default=[])
            ],
        }

        return {"tracking": tracking}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "tracking": None}
    except ConfigError as e:
        return {"error": str(e), "tracking": None}
    except Exception as e:
        logger.exception("Unexpected error in get_logistics_tracking")
        return {"error": f"Unexpected error: {e}", "tracking": None}


@server.tool()
async def list_logistics_companies() -> dict:
    """物流公司列表 — 获取抖店支持的物流/快递公司列表。

    Returns:
        包含物流公司列表的字典，每项含 company_code, company_name
    """
    try:
        client = _get_client()

        data = await client.request("order/getLogisticsCompanyList", {})

        raw_companies = data.get("list", data.get("data", data.get("companies", [])))
        if not isinstance(raw_companies, list):
            raw_companies = []

        companies = [
            {
                "company_code": _safe_get(c, "company_code", default=_safe_get(c, "code")),
                "company_name": _safe_get(c, "company_name", default=_safe_get(c, "name")),
                "short_name": _safe_get(c, "short_name"),
                "website": _safe_get(c, "website"),
                "phone": _safe_get(c, "phone"),
            }
            for c in raw_companies
        ]

        return {
            "total": len(companies),
            "companies": companies,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "companies": []}
    except ConfigError as e:
        return {"error": str(e), "companies": []}
    except Exception as e:
        logger.exception("Unexpected error in list_logistics_companies")
        return {"error": f"Unexpected error: {e}", "companies": []}


# ── 评价 (reviews) ─────────────────────────────────────────────


@server.tool()
async def get_review_list(
    start_time: str = "",
    end_time: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """评价列表 — 获取抖店商品评价列表。

    Args:
        start_time: 评价开始时间，格式如 '2024-01-01 00:00:00'
        end_time: 评价结束时间
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含评价列表的字典，每项含 review_id, order_id, product_id, score, content 等
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

        data = await client.request("comment/list", params)

        raw_reviews = data.get("list", data.get("data", []))
        if not isinstance(raw_reviews, list):
            raw_reviews = []

        reviews = [
            {
                "review_id": _safe_get(r, "comment_id"),
                "order_id": _safe_get(r, "order_id"),
                "product_id": _safe_get(r, "product_id"),
                "product_name": _safe_get(r, "product_name"),
                "score": _safe_get(r, "comment_score"),
                "content": _safe_get(r, "content"),
                "images": _safe_get(r, "images", default=[]),
                "videos": _safe_get(r, "videos", default=[]),
                "reply": _safe_get(r, "seller_reply"),
                "reply_time": _safe_get(r, "seller_reply_time"),
                "create_time": _safe_get(r, "create_time"),
                "is_anonymous": _safe_get(r, "is_anonymous"),
                "buyer_name": _safe_get(r, "buyer_name"),
                "buyer_avatar": _safe_get(r, "buyer_avatar"),
                "spec_desc": _safe_get(r, "spec_desc"),
                "is_auto_comment": _safe_get(r, "is_auto_comment"),
                "score_product": _safe_get(r, "score_product"),
                "score_service": _safe_get(r, "score_service"),
                "score_logistics": _safe_get(r, "score_logistics"),
            }
            for r in raw_reviews
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "reviews": reviews,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "reviews": []}
    except ConfigError as e:
        return {"error": str(e), "reviews": []}
    except Exception as e:
        logger.exception("Unexpected error in get_review_list")
        return {"error": f"Unexpected error: {e}", "reviews": []}


@server.tool()
async def get_review_detail(
    review_id: str = "",
) -> dict:
    """评价详情 — 获取抖店单个评价的详细信息。

    Args:
        review_id: 评价ID (必填)

    Returns:
        包含评价完整信息的字典
    """
    try:
        client = _get_client()

        if not review_id:
            return {
                "error": "Please provide review_id",
                "review": None,
            }

        params: dict[str, Any] = {"comment_id": review_id}
        data = await client.request("comment/detail", params)

        raw = data.get("detail", data.get("comment_info", data))

        review = {
            "review_id": _safe_get(raw, "comment_id"),
            "order_id": _safe_get(raw, "order_id"),
            "product_id": _safe_get(raw, "product_id"),
            "product_name": _safe_get(raw, "product_name"),
            "product_image": _safe_get(raw, "product_image"),
            "score": _safe_get(raw, "comment_score"),
            "score_product": _safe_get(raw, "score_product"),
            "score_service": _safe_get(raw, "score_service"),
            "score_logistics": _safe_get(raw, "score_logistics"),
            "content": _safe_get(raw, "content"),
            "images": _safe_get(raw, "images", default=[]),
            "videos": _safe_get(raw, "videos", default=[]),
            "reply": _safe_get(raw, "seller_reply"),
            "reply_time": _safe_get(raw, "seller_reply_time"),
            "additional": _safe_get(raw, "additional_content"),
            "additional_time": _safe_get(raw, "additional_time"),
            "additional_reply": _safe_get(raw, "additional_reply"),
            "create_time": _safe_get(raw, "create_time"),
            "is_anonymous": _safe_get(raw, "is_anonymous"),
            "is_auto_comment": _safe_get(raw, "is_auto_comment"),
            "buyer_name": _safe_get(raw, "buyer_name"),
            "buyer_avatar": _safe_get(raw, "buyer_avatar"),
            "spec_desc": _safe_get(raw, "spec_desc"),
            "order_amount": _safe_get(raw, "order_amount"),
        }

        return {"review": review}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "review": None}
    except ConfigError as e:
        return {"error": str(e), "review": None}
    except Exception as e:
        logger.exception("Unexpected error in get_review_detail")
        return {"error": f"Unexpected error: {e}", "review": None}


# ── 客服 (customer service — 飞鸽) ────────────────────────────


@server.tool()
async def get_feige_messages(
    user_id: str = "",
    start_time: str = "",
    end_time: str = "",
    page: int = 0,
    page_size: int = 20,
) -> dict:
    """飞鸽客服消息列表 — 获取与指定用户的飞鸽客服聊天记录。

    Args:
        user_id: 用户ID (必填)
        start_time: 消息开始时间，格式如 '2024-01-01 00:00:00'
        end_time: 消息结束时间
        page: 页码，从 0 开始
        page_size: 每页数量，默认20，最大100

    Returns:
        包含消息列表的字典，每项含 message_id, content, from_role, time, msg_type 等
    """
    try:
        client = _get_client()

        if not user_id:
            return {
                "error": "Please provide user_id",
                "messages": [],
            }

        params: dict[str, Any] = {
            "user_id": user_id,
            "page": str(page),
            "size": str(page_size),
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        data = await client.request("im/getMessageList", params)

        raw_messages = data.get("list", data.get("data", data.get("messages", [])))
        if not isinstance(raw_messages, list):
            raw_messages = []

        messages = [
            {
                "message_id": _safe_get(m, "message_id"),
                "content": _safe_get(m, "content"),
                "content_type": _safe_get(m, "msg_type", default=_safe_get(m, "content_type")),
                "from_role": _safe_get(m, "from_role"),
                "from_user_id": _safe_get(m, "from_user_id"),
                "to_user_id": _safe_get(m, "to_user_id"),
                "time": _safe_get(m, "time", default=_safe_get(m, "create_time")),
                "conversation_id": _safe_get(m, "conversation_id"),
                "is_read": _safe_get(m, "is_read"),
                "media_url": _safe_get(m, "media_url"),
                "media_type": _safe_get(m, "media_type"),
            }
            for m in raw_messages
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "messages": messages,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "messages": []}
    except ConfigError as e:
        return {"error": str(e), "messages": []}
    except Exception as e:
        logger.exception("Unexpected error in get_feige_messages")
        return {"error": f"Unexpected error: {e}", "messages": []}


# ── 直播 (live streaming) ──────────────────────────────────────


@server.tool()
async def get_live_data(
    room_id: str = "",
    start_time: str = "",
    end_time: str = "",
) -> dict:
    """直播间数据 — 获取抖店单个直播间数据(观看/互动/成交)。

    Args:
        room_id: 直播间ID (必填)
        start_time: 开始时间，格式如 '2024-01-01 00:00:00'
        end_time: 结束时间

    Returns:
        包含直播间数据的字典，含观看人数、互动、成交金额、商品点击等
    """
    try:
        client = _get_client()

        if not room_id:
            return {
                "error": "Please provide room_id",
                "live_data": None,
            }

        params: dict[str, Any] = {"room_id": room_id}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        data = await client.request("live/getLiveRoomData", params)

        raw = data.get("live_data", data.get("data", data))

        live_data = {
            "room_id": _safe_get(raw, "room_id"),
            "room_title": _safe_get(raw, "title", default=_safe_get(raw, "room_title")),
            "status": _safe_get(raw, "status"),
            "status_desc": _safe_get(raw, "status_desc"),
            "start_time": _safe_get(raw, "start_time"),
            "end_time": _safe_get(raw, "end_time"),
            "duration": _safe_get(raw, "duration"),
            "cover_image": _safe_get(raw, "cover", default=_safe_get(raw, "cover_image")),
            "anchor_name": _safe_get(raw, "anchor_name"),
            "anchor_id": _safe_get(raw, "anchor_id"),
            # Viewership
            "total_viewers": _safe_get(raw, "total_viewers", default=_safe_get(raw, "uv")),
            "peak_viewers": _safe_get(raw, "peak_viewers", default=_safe_get(raw, "max_uv")),
            "avg_viewers": _safe_get(raw, "avg_viewers", default=_safe_get(raw, "avg_uv")),
            "watch_duration_avg": _safe_get(raw, "watch_duration_avg"),
            "new_followers": _safe_get(raw, "new_followers"),
            # Interaction
            "comments_count": _safe_get(raw, "comments_count", default=_safe_get(raw, "danmu_count")),
            "likes_count": _safe_get(raw, "likes_count"),
            "share_count": _safe_get(raw, "share_count"),
            # Conversion
            "pay_count": _safe_get(raw, "pay_count", default=_safe_get(raw, "order_count")),
            "pay_amount": _safe_get(raw, "pay_amount", default=_safe_get(raw, "gmv")),
            "pay_user_count": _safe_get(raw, "pay_user_count"),
            "product_click_count": _safe_get(raw, "product_click_count"),
            "conversion_rate": _safe_get(raw, "conversion_rate"),
        }

        return {"live_data": live_data}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "live_data": None}
    except ConfigError as e:
        return {"error": str(e), "live_data": None}
    except Exception as e:
        logger.exception("Unexpected error in get_live_data")
        return {"error": f"Unexpected error: {e}", "live_data": None}


@server.tool()
async def list_live_rooms(
    start_time: str = "",
    end_time: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """直播间列表 — 获取抖店直播场次列表。

    Args:
        start_time: 开始时间，格式如 '2024-01-01 00:00:00'
        end_time: 结束时间
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含直播场次列表的字典，每项含 room_id, title, status, duration, viewers 等
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

        data = await client.request("live/getLiveRoomList", params)

        raw_rooms = data.get("list", data.get("data", []))
        if not isinstance(raw_rooms, list):
            raw_rooms = []

        rooms = [
            {
                "room_id": _safe_get(r, "room_id"),
                "title": _safe_get(r, "title", default=_safe_get(r, "room_title")),
                "status": _safe_get(r, "status"),
                "status_desc": _safe_get(r, "status_desc"),
                "start_time": _safe_get(r, "start_time"),
                "end_time": _safe_get(r, "end_time"),
                "duration": _safe_get(r, "duration"),
                "cover_image": _safe_get(r, "cover", default=_safe_get(r, "cover_image")),
                "anchor_name": _safe_get(r, "anchor_name"),
                "anchor_id": _safe_get(r, "anchor_id"),
                "total_viewers": _safe_get(r, "total_viewers", default=_safe_get(r, "uv")),
                "peak_viewers": _safe_get(r, "peak_viewers", default=_safe_get(r, "max_uv")),
                "pay_amount": _safe_get(r, "pay_amount", default=_safe_get(r, "gmv")),
                "pay_count": _safe_get(r, "pay_count"),
                "new_followers": _safe_get(r, "new_followers"),
                "comments_count": _safe_get(r, "comments_count", default=_safe_get(r, "danmu_count")),
                "likes_count": _safe_get(r, "likes_count"),
            }
            for r in raw_rooms
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "rooms": rooms,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "rooms": []}
    except ConfigError as e:
        return {"error": str(e), "rooms": []}
    except Exception as e:
        logger.exception("Unexpected error in list_live_rooms")
        return {"error": f"Unexpected error: {e}", "rooms": []}


# ── 流量 (traffic) ─────────────────────────────────────────────


@server.tool()
async def get_traffic_data(
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """流量来源分析 — 获取抖店流量来源数据。

    Args:
        start_date: 开始日期，格式如 '2024-01-01'
        end_date: 结束日期，格式如 '2024-01-31'

    Returns:
        包含流量来源数据的字典，含总流量、各渠道来源数据
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        data = await client.request("shop/getTrafficData", params)

        raw = data.get("traffic_data", data.get("data", data))

        traffic = {
            "start_date": _safe_get(raw, "start_date", default=start_date),
            "end_date": _safe_get(raw, "end_date", default=end_date),
            "total_uv": _safe_get(raw, "total_uv"),
            "total_pv": _safe_get(raw, "total_pv"),
            "avg_stay_time": _safe_get(raw, "avg_stay_time"),
            "bounce_rate": _safe_get(raw, "bounce_rate"),
            "conversion_rate": _safe_get(raw, "conversion_rate"),
            "new_buyer_rate": _safe_get(raw, "new_buyer_rate"),
            "old_buyer_rate": _safe_get(raw, "old_buyer_rate"),
            "sources": [
                {
                    "source_name": _safe_get(s, "source_name"),
                    "source_type": _safe_get(s, "source_type"),
                    "uv": _safe_get(s, "uv"),
                    "pv": _safe_get(s, "pv"),
                    "uv_ratio": _safe_get(s, "uv_ratio"),
                    "pay_count": _safe_get(s, "pay_count"),
                    "pay_amount": _safe_get(s, "pay_amount"),
                    "conversion_rate": _safe_get(s, "conversion_rate"),
                }
                for s in _safe_get(raw, "source_list", default=[])
            ],
        }

        return {"traffic": traffic}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "traffic": None}
    except ConfigError as e:
        return {"error": str(e), "traffic": None}
    except Exception as e:
        logger.exception("Unexpected error in get_traffic_data")
        return {"error": f"Unexpected error: {e}", "traffic": None}


# ── 短视频 (short video) ───────────────────────────────────────


@server.tool()
async def get_short_video_data(
    video_id: str = "",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """短视频数据 — 获取抖店短视频的流量和转化数据。

    Args:
        video_id: 短视频ID (必填)
        start_date: 开始日期，格式如 '2024-01-01'
        end_date: 结束日期

    Returns:
        包含短视频数据的字典，含播放量、点赞、评论、分享、成交等
    """
    try:
        client = _get_client()

        if not video_id:
            return {
                "error": "Please provide video_id",
                "video_data": None,
            }

        params: dict[str, Any] = {"video_id": video_id}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        data = await client.request("video/getVideoData", params)

        raw = data.get("video_data", data.get("data", data))

        video_data = {
            "video_id": _safe_get(raw, "video_id"),
            "title": _safe_get(raw, "title"),
            "description": _safe_get(raw, "description"),
            "cover_url": _safe_get(raw, "cover_url"),
            "video_url": _safe_get(raw, "video_url"),
            "duration": _safe_get(raw, "duration"),
            "status": _safe_get(raw, "status"),
            "status_desc": _safe_get(raw, "status_desc"),
            "create_time": _safe_get(raw, "create_time"),
            # Traffic
            "play_count": _safe_get(raw, "play_count"),
            "like_count": _safe_get(raw, "like_count"),
            "comment_count": _safe_get(raw, "comment_count"),
            "share_count": _safe_get(raw, "share_count"),
            "collect_count": _safe_get(raw, "collect_count"),
            "download_count": _safe_get(raw, "download_count"),
            "finish_rate": _safe_get(raw, "finish_rate"),
            "avg_watch_duration": _safe_get(raw, "avg_watch_duration"),
            # Conversion
            "product_click_count": _safe_get(raw, "product_click_count"),
            "pay_count": _safe_get(raw, "pay_count"),
            "pay_amount": _safe_get(raw, "pay_amount", default=_safe_get(raw, "gmv")),
            "conversion_rate": _safe_get(raw, "conversion_rate"),
        }

        return {"video_data": video_data}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "video_data": None}
    except ConfigError as e:
        return {"error": str(e), "video_data": None}
    except Exception as e:
        logger.exception("Unexpected error in get_short_video_data")
        return {"error": f"Unexpected error: {e}", "video_data": None}


# ── 营销 (marketing) ──────────────────────────────────────────


@server.tool()
async def list_promotions(
    status: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """营销活动列表 — 获取抖店促销活动列表。

    Args:
        status: 活动状态筛选 (1:进行中, 2:未开始, 3:已结束, 4:已终止)
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含营销活动列表的字典，每项含 promotion_id, name, type, status, time 等
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if status:
            params["status"] = status

        data = await client.request("promotion/list", params)

        raw_promotions = data.get("list", data.get("data", []))
        if not isinstance(raw_promotions, list):
            raw_promotions = []

        promotions = [
            {
                "promotion_id": _safe_get(p, "promotion_id"),
                "name": _safe_get(p, "name", default=_safe_get(p, "promotion_name")),
                "type": _safe_get(p, "type", default=_safe_get(p, "promotion_type")),
                "type_desc": _safe_get(p, "type_desc", default=_safe_get(p, "promotion_type_desc")),
                "status": _safe_get(p, "status"),
                "status_desc": _safe_get(p, "status_desc"),
                "start_time": _safe_get(p, "start_time"),
                "end_time": _safe_get(p, "end_time"),
                "discount_rule": _safe_get(p, "discount_rule"),
                "product_count": _safe_get(p, "product_count"),
                "order_count": _safe_get(p, "order_count"),
                "pay_amount": _safe_get(p, "pay_amount", default=_safe_get(p, "gmv")),
                "create_time": _safe_get(p, "create_time"),
            }
            for p in raw_promotions
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "promotions": promotions,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "promotions": []}
    except ConfigError as e:
        return {"error": str(e), "promotions": []}
    except Exception as e:
        logger.exception("Unexpected error in list_promotions")
        return {"error": f"Unexpected error: {e}", "promotions": []}


@server.tool()
async def list_coupons(
    status: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """优惠券列表 — 获取抖店优惠券列表。

    Args:
        status: 优惠券状态筛选 (1:生效中, 2:已失效, 3:已过期)
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含优惠券列表的字典，每项含 coupon_id, name, type, discount, status, usage 等
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if status:
            params["status"] = status

        data = await client.request("coupon/list", params)

        raw_coupons = data.get("list", data.get("data", []))
        if not isinstance(raw_coupons, list):
            raw_coupons = []

        coupons = [
            {
                "coupon_id": _safe_get(c, "coupon_id"),
                "name": _safe_get(c, "name", default=_safe_get(c, "coupon_name")),
                "type": _safe_get(c, "type", default=_safe_get(c, "coupon_type")),
                "type_desc": _safe_get(c, "type_desc"),
                "discount_amount": _safe_get(c, "discount_amount"),
                "min_order_amount": _safe_get(c, "min_order_amount"),
                "total_count": _safe_get(c, "total_count"),
                "received_count": _safe_get(c, "received_count"),
                "used_count": _safe_get(c, "used_count"),
                "status": _safe_get(c, "status"),
                "status_desc": _safe_get(c, "status_desc"),
                "start_time": _safe_get(c, "start_time"),
                "end_time": _safe_get(c, "end_time"),
                "applicable_scope": _safe_get(c, "applicable_scope"),
                "usage_scope_desc": _safe_get(c, "usage_scope_desc"),
                "create_time": _safe_get(c, "create_time"),
            }
            for c in raw_coupons
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "coupons": coupons,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "coupons": []}
    except ConfigError as e:
        return {"error": str(e), "coupons": []}
    except Exception as e:
        logger.exception("Unexpected error in list_coupons")
        return {"error": f"Unexpected error: {e}", "coupons": []}


# ── 资金 (billing) ────────────────────────────────────────────


@server.tool()
async def get_bill_list(
    start_date: str = "",
    end_date: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """账单/资金流水 — 获取抖店资金流水列表。

    Args:
        start_date: 开始日期，格式如 '2024-01-01'
        end_date: 结束日期
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含账单列表的字典，每项含 bill_id, type, amount, balance, time, description 等
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        data = await client.request("finance/getBillList", params)

        raw_bills = data.get("list", data.get("data", []))
        if not isinstance(raw_bills, list):
            raw_bills = []

        bills = [
            {
                "bill_id": _safe_get(b, "bill_id"),
                "order_id": _safe_get(b, "order_id"),
                "type": _safe_get(b, "type", default=_safe_get(b, "bill_type")),
                "type_desc": _safe_get(b, "type_desc", default=_safe_get(b, "bill_type_desc")),
                "amount": _safe_get(b, "amount"),
                "balance_before": _safe_get(b, "balance_before"),
                "balance_after": _safe_get(b, "balance_after"),
                "time": _safe_get(b, "time", default=_safe_get(b, "create_time")),
                "description": _safe_get(b, "description", default=_safe_get(b, "remark")),
                "status": _safe_get(b, "status"),
                "status_desc": _safe_get(b, "status_desc"),
                "biz_type": _safe_get(b, "biz_type"),
                "biz_type_desc": _safe_get(b, "biz_type_desc"),
            }
            for b in raw_bills
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "bills": bills,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "bills": []}
    except ConfigError as e:
        return {"error": str(e), "bills": []}
    except Exception as e:
        logger.exception("Unexpected error in get_bill_list")
        return {"error": f"Unexpected error: {e}", "bills": []}


# ── 店铺 (shop extended) ──────────────────────────────────────


@server.tool()
async def get_shop_score() -> dict:
    """店铺评分详情 — 获取抖店DSR评分、商品体验、服务体验、物流体验等详细评分。

    Returns:
        包含店铺评分的字典，含 dsr_score, product_score, service_score, logistics_score 等
    """
    try:
        client = _get_client()

        data = await client.request("shop/getShopScore", {})

        raw = data.get("score_data", data.get("data", data))

        score = {
            "shop_id": _safe_get(raw, "shop_id"),
            # DSR summary
            "dsr_score": _safe_get(raw, "dsr_score", default=_safe_get(raw, "shop_score")),
            "dsr_rank": _safe_get(raw, "dsr_rank"),
            "dsr_rank_rate": _safe_get(raw, "dsr_rank_rate"),
            # Product experience
            "product_score": _safe_get(raw, "product_score"),
            "product_rank": _safe_get(raw, "product_rank"),
            "product_rank_rate": _safe_get(raw, "product_rank_rate"),
            "product_quality_return_rate": _safe_get(raw, "product_quality_return_rate"),
            "product_negative_review_rate": _safe_get(raw, "product_negative_review_rate"),
            # Service experience
            "service_score": _safe_get(raw, "service_score"),
            "service_rank": _safe_get(raw, "service_rank"),
            "service_rank_rate": _safe_get(raw, "service_rank_rate"),
            "complaint_rate": _safe_get(raw, "complaint_rate"),
            "dispute_resolution_rate": _safe_get(raw, "dispute_resolution_rate"),
            "im_response_rate": _safe_get(raw, "im_response_rate"),
            "im_avg_response_time": _safe_get(raw, "im_avg_response_time"),
            # Logistics experience
            "logistics_score": _safe_get(raw, "logistics_score"),
            "logistics_rank": _safe_get(raw, "logistics_rank"),
            "logistics_rank_rate": _safe_get(raw, "logistics_rank_rate"),
            "ship_time_avg": _safe_get(raw, "ship_time_avg"),
            "delivery_time_avg": _safe_get(raw, "delivery_time_avg"),
            "logistics_negative_rate": _safe_get(raw, "logistics_negative_rate"),
            # Timestamp
            "evaluate_time": _safe_get(raw, "evaluate_time"),
            "update_time": _safe_get(raw, "update_time"),
        }

        return {"shop_score": score}

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "shop_score": None}
    except ConfigError as e:
        return {"error": str(e), "shop_score": None}
    except Exception as e:
        logger.exception("Unexpected error in get_shop_score")
        return {"error": f"Unexpected error: {e}", "shop_score": None}


@server.tool()
async def list_categories(
    parent_id: str = "0",
) -> dict:
    """商品类目列表 — 获取抖店商品类目树。

    Args:
        parent_id: 父类目ID，默认 '0' 表示根类目

    Returns:
        包含类目列表的字典，每项含 category_id, name, parent_id, has_child 等
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {"parent_id": parent_id}
        data = await client.request("product/getCategoryList", params)

        raw_categories = data.get("list", data.get("data", data.get("categories", [])))
        if not isinstance(raw_categories, list):
            raw_categories = []

        categories = [
            {
                "category_id": _safe_get(c, "category_id"),
                "name": _safe_get(c, "name", default=_safe_get(c, "category_name")),
                "parent_id": _safe_get(c, "parent_id"),
                "level": _safe_get(c, "level"),
                "has_child": _safe_get(c, "has_child"),
                "is_leaf": _safe_get(c, "is_leaf"),
                "image": _safe_get(c, "image"),
                "status": _safe_get(c, "status"),
            }
            for c in raw_categories
        ]

        return {
            "total": len(categories),
            "parent_id": parent_id,
            "categories": categories,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "categories": []}
    except ConfigError as e:
        return {"error": str(e), "categories": []}
    except Exception as e:
        logger.exception("Unexpected error in list_categories")
        return {"error": f"Unexpected error: {e}", "categories": []}


@server.tool()
async def list_brands(
    category_id: str = "",
    page: int = 0,
    page_size: int = 10,
) -> dict:
    """品牌列表 — 获取抖店已入驻的品牌列表。

    Args:
        category_id: 按类目筛选品牌
        page: 页码，从 0 开始
        page_size: 每页数量，默认10，最大100

    Returns:
        包含品牌列表的字典，每项含 brand_id, name, logo, category 等
    """
    try:
        client = _get_client()

        params: dict[str, Any] = {
            "page": str(page),
            "size": str(page_size),
        }
        if category_id:
            params["category_id"] = category_id

        data = await client.request("product/getBrandList", params)

        raw_brands = data.get("list", data.get("data", data.get("brands", [])))
        if not isinstance(raw_brands, list):
            raw_brands = []

        brands = [
            {
                "brand_id": _safe_get(b, "brand_id"),
                "name": _safe_get(b, "name", default=_safe_get(b, "brand_name")),
                "name_en": _safe_get(b, "name_en", default=_safe_get(b, "brand_name_en")),
                "logo": _safe_get(b, "logo", default=_safe_get(b, "brand_logo")),
                "description": _safe_get(b, "description"),
                "category_id": _safe_get(b, "category_id"),
                "category_name": _safe_get(b, "category_name"),
                "status": _safe_get(b, "status"),
                "registered_capital": _safe_get(b, "registered_capital"),
                "registered_address": _safe_get(b, "registered_address"),
            }
            for b in raw_brands
        ]

        total = data.get("total", data.get("total_count", 0))

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "brands": brands,
        }

    except DouDianAPIError as e:
        return {"error": str(e), "code": e.code, "brands": []}
    except ConfigError as e:
        return {"error": str(e), "brands": []}
    except Exception as e:
        logger.exception("Unexpected error in list_brands")
        return {"error": f"Unexpected error: {e}", "brands": []}


# ═══════════════════════════════════════════════════════════════
#  Cross-platform operational tools
#  (get_metrics/get_traces/get_alerts/export_data)
# ═══════════════════════════════════════════════════════════════

register_common_tools(server, _get_client)


# ═══════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════


def main() -> None:
    """Run the Doudian MCP server via stdio transport."""
    server.run()


if __name__ == "__main__":
    main()
