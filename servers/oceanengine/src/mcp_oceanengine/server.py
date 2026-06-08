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

from cn_commerce_base import CommerceAPIError, CommerceMCPBase  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402


# ── Ocean Engine API Client ──────────────────────────────


class OceanEngine(CommerceMCPBase):
    """Ocean Engine (巨量引擎) API client using MD5 signing."""

    BASE_URL: str = "https://ad.oceanengine.com/open_api/"
    sign_method: str = "md5"


def _get_client() -> OceanEngine:
    """Create an OceanEngine client from OCEANENGINE_* environment variables."""
    return OceanEngine(
        app_key=os.environ.get("OCEANENGINE_APP_KEY", ""),
        app_secret=os.environ.get("OCEANENGINE_APP_SECRET", ""),
        access_token=os.environ.get("OCEANENGINE_ACCESS_TOKEN", ""),
    )


# ── MCP Server ───────────────────────────────────────────


server = Server("mcp-cn-oceanengine")


# ── Helpers ──────────────────────────────────────────────


def _format_response(result: dict) -> str:
    """Format a successful API response as a pretty-printed JSON string."""
    return json.dumps(result, ensure_ascii=False, indent=2)


def _format_error(err: CommerceAPIError) -> str:
    """Format a CommerceAPIError as an error JSON string."""
    return json.dumps({"error": {"code": err.code, "message": err.msg}}, ensure_ascii=False)


def _safe_int_list(comma_separated: str) -> list[int]:
    """Parse a comma-separated string into a list of integers, ignoring empty entries."""
    return [int(x.strip()) for x in comma_separated.split(",") if x.strip()]


# ── Tools ────────────────────────────────────────────────


@server.tool()
async def get_advertiser_info(advertiser_ids: str) -> str:
    """Get basic advertiser account information including name, balance, and status.

    Args:
        advertiser_ids: Comma-separated string of advertiser IDs (e.g. "123456,789012").
    """
    client = _get_client()
    try:
        result = await client._request(
            "GET",
            "2/advertiser/info/",
            params={"advertiser_ids": _safe_int_list(advertiser_ids)},
        )
        return _format_response(result)
    except CommerceAPIError as e:
        return _format_error(e)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, ensure_ascii=False)


@server.tool()
async def get_campaign_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Get campaign-level advertising report with impressions, clicks, cost, conversions, CTR, CPC, etc.

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    try:
        result = await client._request(
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
        return _format_response(result)
    except CommerceAPIError as e:
        return _format_error(e)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, ensure_ascii=False)


@server.tool()
async def get_ad_detail_report(
    advertiser_id: str,
    start_date: str,
    end_date: str,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """Get ad-level detail report with per-ad performance metrics (impressions, clicks, cost, conversions).

    Args:
        advertiser_id: The advertiser account ID.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
    """
    client = _get_client()
    try:
        result = await client._request(
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
        return _format_response(result)
    except CommerceAPIError as e:
        return _format_error(e)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, ensure_ascii=False)


@server.tool()
async def list_campaigns(
    advertiser_id: str,
    page: int = 1,
    page_size: int = 20,
    filtering: str = "",
) -> str:
    """List campaigns under an advertiser account with optional status filtering.

    Args:
        advertiser_id: The advertiser account ID.
        page: Page number for pagination (default 1).
        page_size: Number of records per page (default 20, max 100).
        filtering: Optional JSON string for filtering (e.g. '{"status": "CAMPAIGN_STATUS_ENABLE"}').
    """
    client = _get_client()
    try:
        params: dict = {
            "advertiser_id": int(advertiser_id),
            "page": page,
            "page_size": min(page_size, 100),
        }
        if filtering:
            params["filtering"] = json.loads(filtering)
        result = await client._request("GET", "2/campaign/get/", params=params)
        return _format_response(result)
    except CommerceAPIError as e:
        return _format_error(e)
    except json.JSONDecodeError as e:
        return json.dumps(
            {"error": {"message": f"Invalid filtering JSON: {e}"}}, ensure_ascii=False
        )
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, ensure_ascii=False)


@server.tool()
async def get_account_balance(advertiser_id: str) -> str:
    """Get the account balance for an advertiser.

    Args:
        advertiser_id: The advertiser account ID.
    """
    client = _get_client()
    try:
        result = await client._request(
            "GET",
            "2/advertiser/fund/get/",
            params={"advertiser_id": int(advertiser_id)},
        )
        return _format_response(result)
    except CommerceAPIError as e:
        return _format_error(e)
    except Exception as e:
        return json.dumps({"error": {"message": str(e)}}, ensure_ascii=False)


# ── Entry Point ──────────────────────────────────────────


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
