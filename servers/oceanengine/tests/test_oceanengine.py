"""Pytest tests for the Ocean Engine (巨量引擎) MCP server tools.

Tests each tool function directly by mocking the underlying HTTP client.
Does not require the MCP stdio transport.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set up import paths so the server module and shared base can be imported.
# Mirrors the logic in server.py but adjusted for the test file's location
# (tests/ is one level shallower than src/mcp_oceanengine/).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_DIR = _REPO_ROOT / "shared"
_SRC_DIR = _REPO_ROOT / "servers" / "oceanengine" / "src"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from cn_commerce_base import CommerceAPIError  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mock_request():
    """An AsyncMock standing in for OceanEngine._request."""
    return AsyncMock()


@pytest.fixture
def mock_client(mock_request):
    """A mock OceanEngine client whose _request is an AsyncMock."""
    client = MagicMock()
    client._request = mock_request
    return client


# Skips that run when credentials are not available (we mock _request
# so credentials are never used, but just in case someone runs with
# --no-mock we keep the option to skip real-network tests).
requires_creds = pytest.mark.skipif(
    not all(
        [
            _REPO_ROOT.joinpath(".env").exists(),
        ]
    ),
    reason="No .env file; all tests run against mocks anyway.",
)


# ── Helper: build a unified patcher ─────────────────────────


def _patch_get_client(mock_client):
    """Context manager that patches _get_client to return *mock_client*."""
    return patch("mcp_oceanengine.server._get_client", return_value=mock_client)


# ── Unit tests for pure helpers ─────────────────────────────


class TestSafeIntList:
    """Tests for the _safe_int_list helper."""

    def test_normal_comma_separated(self):
        from mcp_oceanengine.server import _safe_int_list

        assert _safe_int_list("123,456,789") == [123, 456, 789]

    def test_single_value(self):
        from mcp_oceanengine.server import _safe_int_list

        assert _safe_int_list("42") == [42]

    def test_empty_string(self):
        from mcp_oceanengine.server import _safe_int_list

        assert _safe_int_list("") == []

    def test_with_spaces(self):
        from mcp_oceanengine.server import _safe_int_list

        assert _safe_int_list(" 123 , 456 ") == [123, 456]

    def test_trailing_comma(self):
        from mcp_oceanengine.server import _safe_int_list

        assert _safe_int_list("123,") == [123]


class TestFormatHelpers:
    def test_format_response_pretty_json(self):
        from mcp_oceanengine.server import _format_response

        result = json.loads(
            _format_response({"code": 0, "data": {"name": "测试"}})
        )
        assert result["code"] == 0
        assert result["data"]["name"] == "测试"

    def test_format_error_structure(self):
        from mcp_oceanengine.server import _format_error

        err = CommerceAPIError(40001, "Invalid parameters")
        result = json.loads(_format_error(err))
        assert result["error"]["code"] == 40001
        assert result["error"]["message"] == "Invalid parameters"


# ── Tool function tests ─────────────────────────────────────


class TestGetAdvertiserInfo:
    """Tests for get_advertiser_info."""

    @pytest.mark.asyncio
    async def test_returns_advertiser_list(self, mock_client, mock_request):
        """Normal call returns parsed advertiser data."""
        mock_request.return_value = {
            "code": 0,
            "message": "success",
            "data": {
                "list": [
                    {
                        "advertiser_id": 123456,
                        "advertiser_name": "测试广告主",
                        "status": "STATUS_ENABLE",
                    },
                    {
                        "advertiser_id": 789012,
                        "advertiser_name": "Another Advertiser",
                        "status": "STATUS_DISABLE",
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_advertiser_info

            result = await get_advertiser_info(advertiser_ids="123456,789012")

        data = json.loads(result)
        assert data["code"] == 0
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["advertiser_id"] == 123456
        assert data["data"]["list"][0]["advertiser_name"] == "测试广告主"

    @pytest.mark.asyncio
    async def test_empty_advertiser_ids_returns_error_gracefully(
        self, mock_client, mock_request
    ):
        """When advertiser_ids is an empty string the function does not crash
        and returns a JSON error string when the API rejects the request."""
        mock_request.side_effect = CommerceAPIError(40001, "advertiser_ids is required")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_advertiser_info

            result = await get_advertiser_info(advertiser_ids="")

        data = json.loads(result)
        assert "error" in data
        assert data["error"]["code"] == 40001
        assert "advertiser_ids" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """A CommerceAPIError raised by _request is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(50001, "Internal server error")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_advertiser_info

            result = await get_advertiser_info(advertiser_ids="123")

        data = json.loads(result)
        assert data["error"]["code"] == 50001
        assert data["error"]["message"] == "Internal server error"


class TestGetCampaignReport:
    """Tests for get_campaign_report."""

    @pytest.mark.asyncio
    async def test_returns_report_with_correct_fields(
        self, mock_client, mock_request
    ):
        """Report response includes impressions, clicks, cost, and CTR."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "campaign_id": 1001,
                        "campaign_name": "春节促销",
                        "show_cnt": 152000,
                        "click_cnt": 3800,
                        "stat_cost": 12500.50,
                        "ctr": 2.5,
                        "convert_cnt": 120,
                        "cpc": 3.29,
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total": 1},
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_campaign_report

            result = await get_campaign_report(
                advertiser_id="123456",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        data = json.loads(result)
        report = data["data"]["list"][0]

        # Verify the key metric fields mentioned in the docstring
        assert "show_cnt" in report  # impressions
        assert "click_cnt" in report  # clicks
        assert "stat_cost" in report  # cost
        assert "ctr" in report  # CTR
        assert "cpc" in report
        assert report["campaign_id"] == 1001

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """When page_size > 100 is passed it is capped to 100 via min()."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_campaign_report

            await get_campaign_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
                page_size=200,
            )

        # _request was called; extract the params it received.
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """A CommerceAPIError is caught and returned as error JSON."""
        mock_request.side_effect = CommerceAPIError(40100, "Advertiser not found")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_campaign_report

            result = await get_campaign_report(
                advertiser_id="999",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "not found" in data["error"]["message"]


class TestGetAdDetailReport:
    """Tests for get_ad_detail_report."""

    @pytest.mark.asyncio
    async def test_returns_ad_level_data(self, mock_client, mock_request):
        """Response includes per-ad performance metrics."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "ad_id": 50001,
                        "ad_name": "信息流广告-A",
                        "show_cnt": 88000,
                        "click_cnt": 2200,
                        "stat_cost": 6400.00,
                        "ctr": 2.5,
                        "convert_cnt": 85,
                    },
                    {
                        "ad_id": 50002,
                        "ad_name": "开屏广告-B",
                        "show_cnt": 120000,
                        "click_cnt": 3600,
                        "stat_cost": 9800.00,
                        "ctr": 3.0,
                        "convert_cnt": 140,
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_ad_detail_report

            result = await get_ad_detail_report(
                advertiser_id="123456",
                start_date="2024-02-01",
                end_date="2024-02-15",
            )

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["ad_id"] == 50001
        assert data["data"]["list"][1]["ad_name"] == "开屏广告-B"

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is silently reduced to 100."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_ad_detail_report

            await get_ad_detail_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
                page_size=500,
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is formatted as error JSON."""
        mock_request.side_effect = CommerceAPIError(40100, "Date range too wide")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_ad_detail_report

            result = await get_ad_detail_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert data["error"]["message"] == "Date range too wide"


class TestListCampaigns:
    """Tests for list_campaigns."""

    @pytest.mark.asyncio
    async def test_returns_campaign_list_with_status(
        self, mock_client, mock_request
    ):
        """Normal call returns campaigns including their status field."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "campaign_id": 1,
                        "campaign_name": "品牌推广计划",
                        "status": "CAMPAIGN_STATUS_ENABLE",
                        "budget": 50000.0,
                    },
                    {
                        "campaign_id": 2,
                        "campaign_name": "暂停计划",
                        "status": "CAMPAIGN_STATUS_DISABLE",
                        "budget": 20000.0,
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_campaigns

            result = await list_campaigns(advertiser_id="123")

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        campaign0 = data["data"]["list"][0]
        assert "campaign_name" in campaign0
        assert "status" in campaign0
        assert campaign0["status"] == "CAMPAIGN_STATUS_ENABLE"
        assert campaign0["budget"] == 50000.0

    @pytest.mark.asyncio
    async def test_with_valid_filtering_json(self, mock_client, mock_request):
        """A valid filtering JSON string is parsed and forwarded."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "campaign_id": 3,
                        "campaign_name": "投放中",
                        "status": "CAMPAIGN_STATUS_ENABLE",
                    }
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_campaigns

            filtering = '{"status": "CAMPAIGN_STATUS_ENABLE"}'
            await list_campaigns(advertiser_id="123", filtering=filtering)

        # The filtering JSON should have been decoded and passed to _request.
        call_kwargs = mock_request.call_args[1]
        assert "filtering" in call_kwargs["params"]
        assert call_kwargs["params"]["filtering"] == {
            "status": "CAMPAIGN_STATUS_ENABLE"
        }

    @pytest.mark.asyncio
    async def test_invalid_filter_json_returns_graceful_error(
        self, mock_client, mock_request
    ):
        """Malformed filtering JSON is caught (JSONDecodeError) and returned
        as a structured error string — no exception propagates."""
        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_campaigns

            result = await list_campaigns(
                advertiser_id="123", filtering='{"status": BROKEN'
            )

        # _request should NOT have been called because JSON parsing failed.
        mock_request.assert_not_called()

        data = json.loads(result)
        assert "error" in data
        assert "Invalid filtering JSON" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped via min() for list_campaigns too."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_campaigns

            await list_campaigns(advertiser_id="123", page_size=999)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_no_filtering_param_when_empty_string(
        self, mock_client, mock_request
    ):
        """When filtering is an empty string it is NOT added to the params."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_campaigns

            await list_campaigns(advertiser_id="123", filtering="")

        call_kwargs = mock_request.call_args[1]
        assert "filtering" not in call_kwargs["params"]

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted for list_campaigns."""
        mock_request.side_effect = CommerceAPIError(40001, "Invalid advertiser_id")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_campaigns

            result = await list_campaigns(advertiser_id="0")

        data = json.loads(result)
        assert data["error"]["code"] == 40001
        assert data["error"]["message"] == "Invalid advertiser_id"


class TestGetAccountBalance:
    """Tests for get_account_balance."""

    @pytest.mark.asyncio
    async def test_returns_balance_info(self, mock_client, mock_request):
        """Normal call returns account balance data."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "advertiser_id": 123,
                "balance": 158000.00,
                "valid_balance": 150000.00,
                "cash": 100000.00,
                "grant": 50000.00,
                "return_goods_abs": 0.0,
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_account_balance

            result = await get_account_balance(advertiser_id="123")

        data = json.loads(result)
        assert data["data"]["advertiser_id"] == 123
        assert data["data"]["balance"] == 158000.00
        assert data["data"]["valid_balance"] == 150000.00
        assert "cash" in data["data"]
        assert "grant" in data["data"]

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError from get_account_balance is formatted as error JSON."""
        mock_request.side_effect = CommerceAPIError(40100, "Account not found")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_account_balance

            result = await get_account_balance(advertiser_id="999999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert data["error"]["message"] == "Account not found"


# ── Cross-tool pagination summary ───────────────────────────


class TestPaginationCapping:
    """Verify that *every* paginated tool caps page_size at 100."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name, call_kwargs",
        [
            (
                "get_campaign_report",
                {"advertiser_id": "1", "start_date": "2024-01-01", "end_date": "2024-01-31", "page_size": 300},
            ),
            (
                "get_ad_detail_report",
                {"advertiser_id": "1", "start_date": "2024-01-01", "end_date": "2024-01-31", "page_size": 300},
            ),
            (
                "list_campaigns",
                {"advertiser_id": "1", "page_size": 300},
            ),
        ],
    )
    async def test_page_size_always_capped(
        self, mock_client, mock_request, tool_name, call_kwargs
    ):
        """With page_size > 100, every tool passes min(page_size, 100) to _request."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        import importlib
        module = importlib.import_module("mcp_oceanengine.server")

        with _patch_get_client(mock_client):
            tool_fn = getattr(module, tool_name)
            await tool_fn(**call_kwargs)

        actual_page_size = mock_request.call_args[1]["params"]["page_size"]
        assert actual_page_size == 100, (
            f"{tool_name} passed page_size={actual_page_size}, expected 100"
        )
