"""JD (京东) MCP server — provides tools for reading merchant orders, products, and shop info.

Auth via env vars: JD_APP_KEY, JD_APP_SECRET, JD_ACCESS_TOKEN.
API endpoint: https://api.jd.com/routerjson
Sign method: HMAC-MD5
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Let the server find the shared base class at <repo-root>/shared/
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.cn_commerce_base import CommerceMCPBase, CommerceAPIError, SignMethod


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
        to_sign = {
            k: v
            for k, v in params.items()
            if k not in ("sign", "sign_method") and v != ""
        }
        sorted_keys = sorted(to_sign.keys())
        raw = self.app_secret + "".join(f"{k}{to_sign[k]}" for k in sorted_keys) + self.app_secret
        return (
            hmac.new(self.app_secret.encode(), raw.encode(), hashlib.md5)
            .hexdigest()
            .upper()
        )

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

jd = JDMCP(
    app_key=os.environ.get("JD_APP_KEY", ""),
    app_secret=os.environ.get("JD_APP_SECRET", ""),
    access_token=os.environ.get("JD_ACCESS_TOKEN", ""),
)


# ── MCP server ─────────────────────────────────────────────────────────────

mcp = FastMCP("mcp-cn-jd")


@mcp.tool()
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


@mcp.tool()
async def get_order_detail(order_id: str) -> str:
    """Get full details of a single order.

    Args:
        order_id: The JD order ID (e.g. "3000000000001").
    """
    biz_params = {"order_id": order_id}
    result = await jd._call("jd.pop.order.get", biz_params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
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


@mcp.tool()
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


def main() -> None:
    """Entry point for 'mcp-cn-jd' console script."""
    mcp.run()


if __name__ == "__main__":
    main()
