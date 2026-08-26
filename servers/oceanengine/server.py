"""MCP Server for Ocean Engine (巨量引擎) advertising platform.

Provides read-only access to advertiser accounts.
Uses OAuth 2.0 for authentication via open.oceanengine.com.

FR-015（工具下架）状态：本 server 原有 18 个平台工具，官方文档清单比对后只有 2 个
endpoint 真实存在且在维护（`2/advertiser/info/`、`2/advertiser/fund/get/`）。其余 16 个
的 `@server.tool()` 装饰器已移除 —— 函数体与 docstring 原样保留（作为按真实接口重建时
的意图记录），但 MCP server 不再对外暴露它们，以免继续声明不存在的能力。

每个被下架函数上方的注释写明原因（`已下线` 附公告日期 / `查无此接口`）与已验证的官方
替代。逐条清单见 `docs/platforms.md`「下架工具清单（FR-015）」；重建工作另立 mission，
研究成果在 `kitty-specs/api-contract-conformance-01M0ZHQN/deferred/WP03-*.md`。

注意：`register_common_tools()` 注册的 4 个通用运维工具不依赖平台 endpoint，未受影响。
"""

from __future__ import annotations

import json
import os

from mcp.server.mcpserver import MCPServer

from shared.cn_commerce_base import (
    CommerceMCPBase,
    ConfigValidationError,
    handle_tool_errors,
    register_common_tools,
)

# ── Ocean Engine API Client ──────────────────────────────


class OceanEngine(CommerceMCPBase):
    """Ocean Engine (巨量引擎) API client using MD5 signing."""

    BASE_URL: str = "https://ad.oceanengine.com/open_api/"
    sign_method: str = "md5"


def _get_client() -> OceanEngine:
    """Create an OceanEngine client from OCEANENGINE_* environment variables."""
    try:
        return OceanEngine.from_env("OCEANENGINE", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
    except ConfigValidationError:
        # Fallback to direct instantiation for backward compatibility
        return OceanEngine(
            app_key=os.environ.get("OCEANENGINE_APP_KEY", ""),
            app_secret=os.environ.get("OCEANENGINE_APP_SECRET", ""),
            access_token=os.environ.get("OCEANENGINE_ACCESS_TOKEN", ""),
        )


# ── MCP Server ───────────────────────────────────────────


server = MCPServer("mcp-cn-oceanengine")


# ── Helpers ──────────────────────────────────────────────


def _safe_int_list(comma_separated: str) -> list[int]:
    """Parse a comma-separated string into a list of integers, ignoring empty entries."""
    return [int(x.strip()) for x in comma_separated.split(",") if x.strip()]


# ── Tools: Advertiser ────────────────────────────────────


@server.tool()
@handle_tool_errors
async def get_advertiser_info(advertiser_ids: str) -> dict:
    """Get basic advertiser account information including name, balance, and status.

    Args:
        advertiser_ids: Comma-separated string of advertiser IDs (e.g. "123456,789012").
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/advertiser/info/",
        params={"advertiser_ids": _safe_int_list(advertiser_ids)},
    )


# 保留注册：`2/advertiser/fund/get/` 官方存在且在维护。
# 但官方已公告自 2026 年 6 月中上旬起**不再接受旧工作台的 `bp_id` 参数**
# （changelog 1862437581755404）—— 已核对：本函数只发 `advertiser_id`，从未发过
# `bp_id`，故无需改动；后续重建时也不要把它加回来。
@server.tool()
@handle_tool_errors
async def get_account_balance(advertiser_id: str) -> dict:
    """Get the account balance for an advertiser.

    Args:
        advertiser_id: The advertiser account ID.
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/advertiser/fund/get/",
        params={"advertiser_id": int(advertiser_id)},
    )


# ── Tools: Campaign Reports ──────────────────────────────


# 下架（FR-015）：`2/report/advertiser/get/` 于 2025-08-31 官方下线（公告未指定替代）。
# 替代：`v3.0/report/custom/get/`（配 `v3.0/report/custom/config/get/` 查可用维度指标）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_campaign_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Get campaign-level advertising report with impressions, clicks, cost, conversions, CTR, CPC, etc.

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/report/advertiser/get/",
        params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# 下架（FR-015）：`2/report/ad/get/` 于 2024-05-06 官方下线（公告未指定替代）。
# 替代：`v3.0/report/custom/get/`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_ad_detail_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Get ad-level detail report with per-ad performance metrics (impressions, clicks, cost, conversions).

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/report/ad/get/",
        params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# ── Tools: Campaign Management ───────────────────────────


# 下架（FR-015）：`2/campaign/get/` 于 2024-05-06 官方下线（公告未指定替代）。
# 替代：`v3.0/project/list/`（原版「计划组」对标升级版「项目」）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def list_campaigns(
    advertiser_id: str,
    page: int = 1,
    page_size: int = 20,
    filtering: str = "",
) -> dict:
    """List campaigns under an advertiser account with optional status filtering.

    Args:
        advertiser_id: The advertiser account ID.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
        filtering: Optional JSON string for filtering (e.g. '{"status": "CAMPAIGN_STATUS_ENABLE"}').
    """
    client = _get_client()
    params: dict = {
        "advertiser_id": int(advertiser_id),
        "page": page,
        "page_size": min(page_size, 100),
    }
    if filtering:
        params["filtering"] = json.loads(filtering)
    return await client._request("GET", "2/campaign/get/", params=params)


# 下架（FR-015）：`2/campaign/read/` 官方文档查无此接口（零命中，非下线）。
# 最近似：`v3.0/promotion/list/` 配 `filtering.ids`（≤20 个）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_campaign_detail(advertiser_id: str, campaign_id: str) -> dict:
    """广告计划详情 (Campaign detail).

    Get detailed information about a specific advertising campaign
    including budget, targeting, status, and creative settings.

    Args:
        advertiser_id: The advertiser account ID.
        campaign_id: The campaign ID to query.
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/campaign/read/",
        params={
            "advertiser_id": int(advertiser_id),
            "campaign_ids": [int(campaign_id)],
        },
    )


# 下架（FR-015）：`2/ad/get/` 于 2024-05-06 官方下线。注意本函数 docstring 标错：该接口实为
# 「广告计划」列表而非创意列表。无 1:1 替代，需 join `v3.0/project/list/` +
# `v3.0/promotion/list/`（预算/出价/定向分散在两层）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def list_ads(
    advertiser_id: str,
    campaign_id: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """广告创意列表 (Ad creative list).

    List ad creatives under an advertiser account, optionally filtered by campaign.

    Args:
        advertiser_id: The advertiser account ID.
        campaign_id: Optional campaign ID to filter ads by campaign.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    params: dict = {
        "advertiser_id": int(advertiser_id),
        "page": page,
        "page_size": min(page_size, 100),
    }
    if campaign_id:
        params["campaign_id"] = int(campaign_id)
    return await client._request("GET", "2/ad/get/", params=params)


# 下架（FR-015）：`2/ad/read/` 官方文档查无此接口（零命中）。
# 最近似：`v3.0/promotion/list/` 配 `filtering.ids`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_ad_detail(advertiser_id: str, ad_id: str) -> dict:
    """广告创意详情 (Ad creative detail).

    Get detailed information about a specific ad creative
    including creative content, delivery status, and performance settings.

    Args:
        advertiser_id: The advertiser account ID.
        ad_id: The ad creative ID to query.
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/ad/read/",
        params={
            "advertiser_id": int(advertiser_id),
            "ad_ids": [int(ad_id)],
        },
    )


# ── Tools: 千川 (Qianchuan Ecommerce Ads) ────────────────


# 下架（FR-015）：`2/qianchuan/report/ad/get/` 官方文档查无此接口（版本段错误）。
# 替代：`v1.0/qianchuan/report/ad/get/` —— 千川用 `v1.0`，文档 host 为
# `ad.oceanengine.com`；必填 `advertiser_id`/`start_date`/`end_date`/`fields[]`/`filtering`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_qianchuan_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """千川电商广告报表 (Qianchuan ecommerce ad report).

    Get advertising performance report for Qianchuan (千川) ecommerce ads
    including impressions, clicks, cost, conversions, GMV, ROI, etc.

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/qianchuan/report/ad/get/",
        params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# 下架（FR-015）：`2/qianchuan/campaign/list/get/` 官方文档查无此接口（版本段与路径均错）。
# 替代：`v1.0/qianchuan/campaign_list/get/` —— 千川用 `v1.0`，文档 host 为
# `ad.oceanengine.com`；`advertiser_id` 与 `filter` 均必填。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_qianchuan_campaign_list(
    advertiser_id: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """千川广告计划列表 (Qianchuan campaign list).

    List Qianchuan (千川) ecommerce ad campaigns under an advertiser account.

    Args:
        advertiser_id: The advertiser account ID.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/qianchuan/campaign/list/get/",
        params={
            "advertiser_id": int(advertiser_id),
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# ── Tools: 星图 (Star/Influencer Marketing) ──────────────


# 下架（FR-015）：`2/star/report/` 官方文档查无此接口 —— 它是**路径前缀而非接口**。
# 真实接口在其下一级：`2/star/report/order_overview/get/`、
# `2/star/report/order_user_distribution/get/`、`2/star/report/custom_data_topic_report/` 等。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_star_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """星图达人投放报表 (Star influencer marketing report).

    Get performance report for Star (星图) influencer marketing campaigns
    including reach, engagement, conversions, cost per engagement, and ROI.

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/star/report/",
        params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# 下架（FR-015）：`2/star/task/list/` 官方文档查无此接口（零命中）。
# 最近似：`2/star/demand/list/`（星图客户任务列表）、
# `2/star/star_ad_unite_task/list/`、`v3.0/tools/ebp/star_task/list/`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def list_star_tasks(
    advertiser_id: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """星图任务列表 (Star task list).

    List Star (星图) influencer marketing tasks under an advertiser account,
    optionally filtered by task status.

    Args:
        advertiser_id: The advertiser account ID.
        status: Optional status filter (e.g. "IN_PROGRESS", "COMPLETED", "CANCELLED").
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    params: dict = {
        "advertiser_id": int(advertiser_id),
        "page": page,
        "page_size": min(page_size, 100),
    }
    if status:
        params["status"] = status
    return await client._request("GET", "2/star/task/list/", params=params)


# ── Tools: 素材 (Creative/Materials) ─────────────────────


# 下架（FR-015）：`2/report/creative/get/` 于 2024-05-06 官方下线（公告未指定替代）。
# 替代：`v3.0/report/custom/get/`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_creative_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """素材/创意报表 (Creative/materials report).

    Get creative-level performance report including impressions, clicks,
    CTR, conversions, and cost per creative.

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/report/creative/get/",
        params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# 下架（FR-015）：`2/material/list/` 官方文档查无此接口（零命中）。
# 按意图选替代：`2/file/material/list/`（素材标签列表）/ `2/file/video/get/`
# （视频素材）/ `v3.0/tools/ebp/material/list/`（组织级）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def list_materials(
    advertiser_id: str,
    page: int = 1,
    page_size: int = 20,
    material_type: str = "",
) -> dict:
    """素材库列表 (Material library list).

    List materials in the creative library under an advertiser account,
    optionally filtered by material type.

    Args:
        advertiser_id: The advertiser account ID.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
        material_type: Optional material type filter (e.g. "IMAGE", "VIDEO", "TITLE").
    """
    client = _get_client()
    params: dict = {
        "advertiser_id": int(advertiser_id),
        "page": page,
        "page_size": min(page_size, 100),
    }
    if material_type:
        params["material_type"] = material_type
    return await client._request("GET", "2/material/list/", params=params)


# ── Tools: 人群 (Audience/DMP) ───────────────────────────


# 下架（FR-015）：`2/dmp/audience/list/` 官方文档查无此接口（零命中）。
# 替代：`2/dmp/custom_audience/select/`（人群包列表）。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def list_audience_packages(
    advertiser_id: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """DMP 人群包列表 (DMP audience package list).

    List DMP (Data Management Platform) audience packages under an advertiser
    account, including audience size, type, and status.

    Args:
        advertiser_id: The advertiser account ID.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/dmp/audience/list/",
        params={
            "advertiser_id": int(advertiser_id),
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# 下架（FR-015）：`2/report/audience/` 于 2024-05-06 官方下线（整组下线，公告未指定替代）。
# 替代：`v3.0/report/custom/get/`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_audience_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """人群分析报表 (Audience analysis report).

    Get audience analysis report including demographic breakdown, interest
    tags, device distribution, and geographic distribution.

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/report/audience/",
        params={
            "advertiser_id": int(advertiser_id),
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": min(page_size, 100),
        },
    )


# ── Tools: 优化建议 (Optimization Suggestions) ───────────


# 下架（FR-015）：`2/tools/bid_suggest/` 官方文档查无此接口（零命中）。
# 替代：`v3.0/tools/bids/suggest/`。注意 `2/tools/bid/suggest/`（斜杠形式）虽能探测
# 通但官方无文档，不要用。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_bid_suggestion(advertiser_id: str, campaign_id: str) -> dict:
    """出价建议 (Bid suggestion).

    Get bid optimization suggestions for a campaign, including recommended bid
    range based on historical performance and competition analysis.

    Args:
        advertiser_id: The advertiser account ID.
        campaign_id: The campaign ID to get bid suggestions for.
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/tools/bid_suggest/",
        params={
            "advertiser_id": int(advertiser_id),
            "campaign_id": int(campaign_id),
        },
    )


# 下架（FR-015）：`2/tools/diagnosis/` 官方文档查无此接口 —— 它是**路径前缀而非接口**。
# 真实接口：`v3.0/tools/diagnosis/suggestion/get/`、
# `v3.0/tools/promotion_diagnosis/suggestion/get/`、
# `v3.0/tools/advertiser_diagnosis/suggestion/get/`、
# `v3.0/tools/project_diagnosis/suggestion/list/`。
# 保留函数体仅为记录重建意图，不再注册为 MCP 工具；详见 docs/platforms.md。
@handle_tool_errors
async def get_diagnosis(advertiser_id: str, campaign_id: str) -> dict:
    """广告诊断 (Ad diagnosis).

    Get diagnostic analysis for a campaign, identifying delivery issues,
    budget constraints, audience saturation, and optimization recommendations.

    Args:
        advertiser_id: The advertiser account ID.
        campaign_id: The campaign ID to diagnose.
    """
    client = _get_client()
    return await client._request(
        "GET",
        "2/tools/diagnosis/",
        params={
            "advertiser_id": int(advertiser_id),
            "campaign_id": int(campaign_id),
        },
    )


# ── Cross-platform operational tools ─────────────────────
# (get_metrics/get_traces/get_alerts/export_data)

register_common_tools(server, _get_client)


# ── Entry Point ──────────────────────────────────────────


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    server.run()


if __name__ == "__main__":
    main()
