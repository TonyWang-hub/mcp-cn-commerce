"""MCP Server for Ocean Engine (巨量引擎) advertising platform.

Provides read-only access to advertiser accounts, campaigns, and reports.
Uses OAuth 2.0 for authentication via open.oceanengine.com.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure the shared base module is importable from ../../shared/
_SHARED_DIR = Path(__file__).resolve().parents[4] / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    format_error_response,
    handle_tool_errors,
)  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

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


server = Server("mcp-cn-oceanengine")


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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


@server.tool()
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


# ── Entry Point ──────────────────────────────────────────


def main() -> None:
    """Entry point: run the MCP server over stdio."""

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
