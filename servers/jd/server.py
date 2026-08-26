"""JD (京东) MCP server.

FR-015（工具下架）状态：**本 server 当前不暴露任何平台业务工具。** 从官方文档后端拉取
覆盖三个网关的完整目录（3514 个 API）后确认：`jd.pop.*` 命名空间在京东任何网关上都不
存在（命中数 **0**）。`jd.` 确是真前缀，但**只属于京东联盟** `jd.union.open.*`（90 个）；
商家 / POP / VC 接口一律是 `jingdong.*`（3147 个）。原有 15 个 method 全部编造。

因此全部 15 个工具的 `@mcp.tool()` 装饰器已移除 —— 函数体与 docstring 原样保留（作为按
真实接口重建时的意图记录），但 MCP server 不再对外暴露它们。每个函数上方的注释写明原因，
并区分两类：11 个有已验证的正确 `jingdong.*` method 名；4 个**京东无官方等价能力**
（店铺评分 / 单条评价详情 / 实时售价 / 订单级物流轨迹）。

⚠️ 重建前需先决定网关方向：官方《开放平台API对接指南》明文把本文件使用的
`https://api.jd.com/routerjson` 标为「**历史接口，逐步迁移至 SP-API**」，而
`https://api-cn.jd.com` 的 SP-API 标为「新一代标准化接口（推荐使用）」，POP 所需能力已
全覆盖。两者鉴权完全不同 —— SP-API 凭证走 `X-JOS-*` header，timestamp 为 epoch 毫秒，
签名 `upper(md5(secret + sorted_kv + secret))` 且 **header 名本身参与签名串**。选 SP-API
则下方 routerjson 的签名实现与契约细节全部作废。

逐条清单见 `docs/platforms.md`「下架工具清单（FR-015）」；重建工作另立 mission，研究成果
在 `kitty-specs/api-contract-conformance-01M0ZHQN/deferred/WP08-*.md`。

注意：`register_common_tools()` 注册的 4 个通用运维工具不依赖平台 endpoint，未受影响 ——
它们是本 server 目前唯一对外暴露的工具。

Auth via env vars: JD_APP_KEY, JD_APP_SECRET, JD_ACCESS_TOKEN.
API endpoint: https://api.jd.com/routerjson (官方标注为历史接口)
Sign method: HMAC-MD5
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    CommerceMCPBase,
    ConfigValidationError,
    SignMethod,
    canonicalize_sign_value,
    register_common_tools,
)

# ── JD client ───────────────────────────────────────────────────────────────


class JDMCP(CommerceMCPBase):
    """JD-specific client that overrides signing for HMAC-MD5."""

    BASE_URL = "https://api.jd.com/routerjson"
    sign_method = SignMethod.HMAC_MD5

    def _sign(self, params: dict) -> str:
        """JD HMAC-MD5 signing.

        Builds: app_secret + sorted_kv_string + app_secret
        Then HMAC-MD5 with app_secret as key.
        """
        to_sign = {k: v for k, v in params.items() if k not in ("sign", "sign_method") and v != ""}
        sorted_keys = sorted(to_sign.keys())
        raw = (
            self.app_secret
            + "".join(f"{k}{canonicalize_sign_value(to_sign[k])}" for k in sorted_keys)
            + self.app_secret
        )
        return hmac.new(self.app_secret.encode(), raw.encode(), hashlib.md5).hexdigest().upper()

    async def _call(self, api_method: str, biz_params: dict | None = None) -> dict:
        """Make a JD API call.

        system params (method, format, v, plus auth) go in query string;
        business params go in JSON body.
        """
        params = {
            "method": api_method,
            "format": "json",
            "v": "2.0",
        }
        return await self._request("POST", "", params=params, data=biz_params or {})


# ── Instantiate client from env ────────────────────────────────────────────


def _create_jd_client() -> JDMCP:
    """Create JD client with configuration validation."""
    try:
        return JDMCP.from_env("JD", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return JDMCP(
            app_key=os.environ.get("JD_APP_KEY", ""),
            app_secret=os.environ.get("JD_APP_SECRET", ""),
            access_token=os.environ.get("JD_ACCESS_TOKEN", ""),
        )


jd = _create_jd_client()


# ── MCP server ─────────────────────────────────────────────────────────────

mcp = MCPServer("mcp-cn-jd")


# 下架（FR-015）：`jd.pop.order.search` —— `jd.pop.*` 命名空间在京东任何网关上都不存在。
# 替代：`jingdong.pop.order.search`（apiId 4246，权限 R3）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_order_list(
    start_time: str,
    end_time: str,
    order_status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query order list by time range and optional status.

    Args:
        start_time: Order start time, e.g. "2024-01-01 00:00:00"
        end_time: Order end time, e.g. "2024-01-31 23:59:59"
        order_status: Status filter. Common values:
            WAIT_SELLER_STOCK_OUT (waiting to ship),
            WAIT_GOODS_RECEIVE_CONFIRM (shipped, waiting confirm),
            FINISHED_L (completed),
            TRADE_CANCELED (cancelled).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of orders per page (max 100).
    """
    biz_params = {
        "start_date": start_time,
        "end_date": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if order_status:
        biz_params["order_status"] = order_status

    result = await jd._call("jd.pop.order.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# 下架（FR-015）：`jd.pop.order.get` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.pop.order.get`（权限 R3）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single order.

    Args:
        order_id: The JD order ID (e.g. "3000000000001").
    """
    biz_params = {"order_id": order_id}
    result = await jd._call("jd.pop.order.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# 下架（FR-015）：`jd.pop.ware.search` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.ware.read.searchWare4Valid`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_product_list(
    page: int = 1,
    page_size: int = 20,
    ware_status: str = "",
) -> str:
    """Get product (ware) list with stock and price info.

    Args:
        page: Page number, starting from 1.
        page_size: Number of products per page (max 100).
        ware_status: Product status filter. Empty for all.
            Common values: "0" (draft), "1" (never-on-sale),
            "2" (on-sale), "3" (off-shelf).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if ware_status:
        biz_params["ware_status"] = ware_status

    result = await jd._call("jd.pop.ware.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# 下架（FR-015）：`jd.pop.shop.get` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.vender.shop.query`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_shop_info(shop_id: str = "") -> str:
    """Get shop basic information.

    Args:
        shop_id: JD shop ID. Leave empty to use the authenticated shop.
    """
    biz_params: dict = {}
    if shop_id:
        biz_params["shop_id"] = shop_id

    result = await jd._call("jd.pop.shop.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 售后 (After-Sale)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.afs.search` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.ServiceInfoProvider.queryServicePageSafe` 或
# `jingdong.afsservice.alltask.get`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_after_sale_list(
    start_time: str,
    end_time: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query after-sale (return/refund/exchange) list by time range and optional status.

    Args:
        start_time: Query start time, e.g. "2024-01-01 00:00:00"
        end_time: Query end time, e.g. "2024-01-31 23:59:59"
        status: After-sale status filter. Common values:
            WAIT_SELLER_AGREE (waiting for seller approval),
            WAIT_BUYER_RETURN_GOODS (waiting for buyer to return goods),
            WAIT_SELLER_RECEIVE_GOODS (waiting for seller to receive goods),
            COMPLETE (completed),
            CLOSED (closed).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "start_date": start_time,
        "end_date": end_time,
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await jd._call("jd.pop.afs.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# 下架（FR-015）：`jd.pop.afs.get` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.ServiceDetailProvider.findServiceDetail`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_after_sale_detail(after_sale_id: str) -> str:
    """Get full details of a single after-sale (return/refund/exchange) record.

    Args:
        after_sale_id: The after-sale record ID (e.g. "AS00000001").
    """
    biz_params = {"after_sale_id": after_sale_id}
    result = await jd._call("jd.pop.afs.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 物流 (Logistics)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.logistics.trace` —— `jd.pop.*` 命名空间不存在，且**京东无订单级等价能力**：
# `jingdong.ldop.receive.trace.get` 需青龙业主号 + 运单号，不是订单号入口。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_logistics_tracking(order_id: str) -> str:
    """Get logistics tracking information for an order.

    Args:
        order_id: The JD order ID (e.g. "3000000000001").
    """
    biz_params = {"order_id": order_id}
    result = await jd._call("jd.pop.logistics.trace", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 评价 (Reviews)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.comment.search` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.pop.PopCommentJsfService.getVenderCommentsForJos`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_review_list(
    product_id: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Query product review (comment) list.

    Args:
        product_id: The product/ware ID (e.g. "20000001").
        page: Page number, starting from 1.
        page_size: Number of reviews per page (max 100).
    """
    biz_params = {
        "ware_id": product_id,
        "page": str(page),
        "page_size": str(page_size),
    }

    result = await jd._call("jd.pop.comment.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# 下架（FR-015）：`jd.pop.comment.get` —— `jd.pop.*` 命名空间不存在，且**京东无官方等价能力**：
# 评价类 API 仅 6 个，均无单条评价详情。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_review_detail(review_id: str) -> str:
    """Get full details of a single review.

    Args:
        review_id: The review/comment ID (e.g. "C00000001").
    """
    biz_params = {"comment_id": review_id}
    result = await jd._call("jd.pop.comment.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 价格 (Pricing)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.price.get` —— `jd.pop.*` 命名空间不存在，且**京东无官方等价能力**：
# 没有 POP 实时售价读接口，价格随 `jingdong.ware.read.findWareById` 一并返回。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_price_info(sku_ids: str) -> str:
    """Get real-time price information for given SKUs, including promotion overlay.

    Args:
        sku_ids: Comma-separated SKU IDs, e.g. "10000001,10000002,10000003".
            Maximum 100 SKUs per request.
    """
    biz_params = {"sku_ids": sku_ids}

    result = await jd._call("jd.pop.price.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 库存 (Inventory)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.inventory.get` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.ware.stock.sku.query`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_inventory(ware_ids: str) -> str:
    """Query current inventory/stock levels for given ware IDs.

    Args:
        ware_ids: Comma-separated ware IDs, e.g. "20000001,20000002".
            Maximum 100 ware IDs per request.
    """
    biz_params = {"ware_ids": ware_ids}

    result = await jd._call("jd.pop.inventory.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 促销 (Marketing)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.promotion.search` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.seller.promotion.list`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
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
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await jd._call("jd.pop.promotion.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# 下架（FR-015）：`jd.pop.coupon.search` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.seller.coupon.read.getCouponList`（权限 R1）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def list_coupons(
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List coupon templates.

    Args:
        status: Coupon status filter. Common values:
            "1" (active), "2" (expired), "3" (not started).
            Empty string means all statuses.
        page: Page number, starting from 1.
        page_size: Number of records per page (max 100).
    """
    biz_params = {
        "page": str(page),
        "page_size": str(page_size),
    }
    if status:
        biz_params["status"] = status

    result = await jd._call("jd.pop.coupon.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 类目 (Categories)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.category.search` —— `jd.pop.*` 命名空间不存在。
# 替代：`jingdong.category.read.findByPId`（`parent_id` 对应其 `pid`）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def list_categories(parent_id: str = "0") -> str:
    """List product categories under a given parent category.

    Args:
        parent_id: Parent category ID. Use "0" (default) to list top-level categories.
    """
    biz_params = {"parent_id": parent_id}

    result = await jd._call("jd.pop.category.search", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# 店铺-扩展 (Shop extended)
# ═══════════════════════════════════════════════════════════════════════════════


# 下架（FR-015）：`jd.pop.shop.score.get` —— `jd.pop.*` 命名空间不存在，且**京东无官方等价能力**：
# 3514 个官方 API 中 DSR / 店铺评分 / 口碑 / 服务分零命中。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
async def get_shop_score() -> str:
    """Get shop DSR (Detail Seller Rating) scores including product description,
    service attitude, and delivery speed ratings.
    """
    result = await jd._call("jd.pop.shop.score.get", {})
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── Cross-platform operational tools (get_metrics/get_traces/get_alerts/export_data) ──
register_common_tools(mcp, jd)


def main() -> None:
    """Entry point for 'mcp-cn-jd' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
