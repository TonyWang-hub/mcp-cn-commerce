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


# ── Tool function tests: Original 5 tools ───────────────────


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


# ── Tool function tests: 千川 (Qianchuan) ───────────────────


class TestGetQianchuanReport:
    """Tests for get_qianchuan_report."""

    @pytest.mark.asyncio
    async def test_returns_qianchuan_report(self, mock_client, mock_request):
        """Returns Qianchuan ecommerce ad report with GMV and ROI fields."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "ad_id": 70001,
                        "ad_name": "千川直播引流",
                        "show_cnt": 320000,
                        "click_cnt": 9600,
                        "stat_cost": 28500.00,
                        "ctr": 3.0,
                        "convert_cnt": 580,
                        "gmv": 152000.00,
                        "roi": 5.33,
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total": 1},
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_qianchuan_report

            result = await get_qianchuan_report(
                advertiser_id="123",
                start_date="2024-03-01",
                end_date="2024-03-31",
            )

        data = json.loads(result)
        report = data["data"]["list"][0]
        assert report["ad_id"] == 70001
        assert "gmv" in report
        assert "roi" in report
        assert report["roi"] == 5.33

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_qianchuan_report

            await get_qianchuan_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
                page_size=500,
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Qianchuan report not available")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_qianchuan_report

            result = await get_qianchuan_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "Qianchuan" in data["error"]["message"]


class TestGetQianchuanCampaignList:
    """Tests for get_qianchuan_campaign_list."""

    @pytest.mark.asyncio
    async def test_returns_qianchuan_campaigns(self, mock_client, mock_request):
        """Returns list of Qianchuan campaigns with budget and status."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "campaign_id": 8001,
                        "campaign_name": "千川直播推广",
                        "status": "CAMPAIGN_STATUS_ENABLE",
                        "budget": 100000.00,
                        "budget_mode": "BUDGET_MODE_DAY",
                    },
                    {
                        "campaign_id": 8002,
                        "campaign_name": "千川短视频推广",
                        "status": "CAMPAIGN_STATUS_DISABLE",
                        "budget": 50000.00,
                        "budget_mode": "BUDGET_MODE_DAY",
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_qianchuan_campaign_list

            result = await get_qianchuan_campaign_list(advertiser_id="123")

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["campaign_name"] == "千川直播推广"
        assert data["data"]["list"][0]["budget"] == 100000.00

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_qianchuan_campaign_list

            await get_qianchuan_campaign_list(advertiser_id="123", page_size=999)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Advertiser not authorized for Qianchuan")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_qianchuan_campaign_list

            result = await get_qianchuan_campaign_list(advertiser_id="999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "Qianchuan" in data["error"]["message"]


# ── Tool function tests: 星图 (Star/Influencer) ─────────────


class TestGetStarReport:
    """Tests for get_star_report."""

    @pytest.mark.asyncio
    async def test_returns_star_report(self, mock_client, mock_request):
        """Returns Star influencer report with engagement and reach metrics."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "task_id": 9001,
                        "influencer_name": "达人张伟",
                        "fans_count": 520000,
                        "play_cnt": 1200000,
                        "like_cnt": 85000,
                        "comment_cnt": 3200,
                        "share_cnt": 1500,
                        "engage_rate": 7.5,
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total": 1},
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_star_report

            result = await get_star_report(
                advertiser_id="123",
                start_date="2024-04-01",
                end_date="2024-04-30",
            )

        data = json.loads(result)
        report = data["data"]["list"][0]
        assert report["task_id"] == 9001
        assert report["influencer_name"] == "达人张伟"
        assert "engage_rate" in report
        assert report["fans_count"] == 520000

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_star_report

            await get_star_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
                page_size=500,
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Star report unavailable")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_star_report

            result = await get_star_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "Star" in data["error"]["message"]


class TestListStarTasks:
    """Tests for list_star_tasks."""

    @pytest.mark.asyncio
    async def test_returns_star_tasks(self, mock_client, mock_request):
        """Returns list of Star influencer tasks."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "task_id": 9501,
                        "task_name": "美妆种草合作",
                        "influencer_name": "达人李娜",
                        "status": "IN_PROGRESS",
                        "budget": 30000.00,
                        "create_time": "2024-05-01 10:00:00",
                    },
                    {
                        "task_id": 9502,
                        "task_name": "品牌代言合作",
                        "influencer_name": "达人王强",
                        "status": "COMPLETED",
                        "budget": 50000.00,
                        "create_time": "2024-04-15 09:30:00",
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_star_tasks

            result = await list_star_tasks(advertiser_id="123")

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["status"] == "IN_PROGRESS"
        assert data["data"]["list"][1]["task_name"] == "品牌代言合作"

    @pytest.mark.asyncio
    async def test_with_status_filter(self, mock_client, mock_request):
        """Status filter is forwarded to the API."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "task_id": 9503,
                        "task_name": "已完成任务",
                        "status": "COMPLETED",
                    }
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_star_tasks

            await list_star_tasks(advertiser_id="123", status="COMPLETED")

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_no_status_param_when_empty(self, mock_client, mock_request):
        """When status is empty string, it is NOT added to params."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_star_tasks

            await list_star_tasks(advertiser_id="123", status="")

        call_kwargs = mock_request.call_args[1]
        assert "status" not in call_kwargs["params"]

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_star_tasks

            await list_star_tasks(advertiser_id="123", page_size=999)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Star tasks not found")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_star_tasks

            result = await list_star_tasks(advertiser_id="999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "not found" in data["error"]["message"]


# ── Tool function tests: 广告管理 (Ad Management) ───────────


class TestGetCampaignDetail:
    """Tests for get_campaign_detail."""

    @pytest.mark.asyncio
    async def test_returns_campaign_detail(self, mock_client, mock_request):
        """Returns detailed campaign info including budget, targeting, and status."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "campaign_id": 1001,
                "campaign_name": "品牌推广-春季",
                "status": "CAMPAIGN_STATUS_ENABLE",
                "budget": 200000.00,
                "budget_mode": "BUDGET_MODE_DAY",
                "delivery_mode": "DELIVERY_MODE_STANDARD",
                "targeting": {
                    "age": ["18-24", "25-34"],
                    "gender": "ALL",
                    "region": ["北京", "上海", "广州"],
                },
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_campaign_detail

            result = await get_campaign_detail(
                advertiser_id="123", campaign_id="1001"
            )

        data = json.loads(result)
        assert data["data"]["campaign_id"] == 1001
        assert data["data"]["campaign_name"] == "品牌推广-春季"
        assert "targeting" in data["data"]
        assert data["data"]["budget"] == 200000.00

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Campaign not found")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_campaign_detail

            result = await get_campaign_detail(
                advertiser_id="123", campaign_id="99999"
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "not found" in data["error"]["message"]


class TestListAds:
    """Tests for list_ads."""

    @pytest.mark.asyncio
    async def test_returns_ad_list(self, mock_client, mock_request):
        """Returns list of ad creatives with delivery status."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "ad_id": 50001,
                        "ad_name": "信息流广告A",
                        "campaign_id": 1001,
                        "status": "AD_STATUS_DELIVERING",
                        "creative_type": "IMAGE",
                    },
                    {
                        "ad_id": 50002,
                        "ad_name": "短视频广告B",
                        "campaign_id": 1001,
                        "status": "AD_STATUS_DELIVERING",
                        "creative_type": "VIDEO",
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_ads

            result = await list_ads(advertiser_id="123")

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["ad_name"] == "信息流广告A"
        assert data["data"]["list"][1]["creative_type"] == "VIDEO"

    @pytest.mark.asyncio
    async def test_with_campaign_filter(self, mock_client, mock_request):
        """Campaign ID filter is forwarded when provided."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "ad_id": 50003,
                        "ad_name": "指定计划广告",
                        "campaign_id": 2001,
                        "status": "AD_STATUS_DELIVERING",
                    }
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_ads

            await list_ads(advertiser_id="123", campaign_id="2001")

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["campaign_id"] == 2001

    @pytest.mark.asyncio
    async def test_no_campaign_param_when_empty(self, mock_client, mock_request):
        """When campaign_id is empty, it is NOT added to params."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_ads

            await list_ads(advertiser_id="123", campaign_id="")

        call_kwargs = mock_request.call_args[1]
        assert "campaign_id" not in call_kwargs["params"]

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_ads

            await list_ads(advertiser_id="123", page_size=500)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Ads not found")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_ads

            result = await list_ads(advertiser_id="999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "not found" in data["error"]["message"]


class TestGetAdDetail:
    """Tests for get_ad_detail."""

    @pytest.mark.asyncio
    async def test_returns_ad_detail(self, mock_client, mock_request):
        """Returns detailed ad creative info with creative content and settings."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "ad_id": 50001,
                "ad_name": "信息流广告素材A",
                "campaign_id": 1001,
                "status": "AD_STATUS_DELIVERING",
                "creative_type": "IMAGE",
                "creative_materials": [
                    {"image_url": "https://cdn.example.com/img/001.jpg"},
                    {"title": "限时优惠，不容错过"},
                ],
                "delivery_settings": {
                    "bid": 15.00,
                    "bid_type": "BID_TYPE_CPM",
                    "schedule_start": "2024-06-01",
                    "schedule_end": "2024-06-30",
                },
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_ad_detail

            result = await get_ad_detail(advertiser_id="123", ad_id="50001")

        data = json.loads(result)
        assert data["data"]["ad_id"] == 50001
        assert data["data"]["ad_name"] == "信息流广告素材A"
        assert "creative_materials" in data["data"]
        assert "delivery_settings" in data["data"]
        assert data["data"]["delivery_settings"]["bid"] == 15.00

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Ad not found")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_ad_detail

            result = await get_ad_detail(advertiser_id="123", ad_id="99999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "not found" in data["error"]["message"]


# ── Tool function tests: 素材 (Creative/Materials) ──────────


class TestGetCreativeReport:
    """Tests for get_creative_report."""

    @pytest.mark.asyncio
    async def test_returns_creative_report(self, mock_client, mock_request):
        """Returns creative-level performance data."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "creative_id": 60001,
                        "creative_name": "素材-夏日促销",
                        "show_cnt": 450000,
                        "click_cnt": 13500,
                        "stat_cost": 18000.00,
                        "ctr": 3.0,
                        "cpc": 1.33,
                        "convert_cnt": 450,
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total": 1},
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_creative_report

            result = await get_creative_report(
                advertiser_id="123",
                start_date="2024-05-01",
                end_date="2024-05-31",
            )

        data = json.loads(result)
        report = data["data"]["list"][0]
        assert report["creative_id"] == 60001
        assert "ctr" in report
        assert "cpc" in report
        assert report["convert_cnt"] == 450

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_creative_report

            await get_creative_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
                page_size=500,
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Creative report unavailable")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_creative_report

            result = await get_creative_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "Creative" in data["error"]["message"]


class TestListMaterials:
    """Tests for list_materials."""

    @pytest.mark.asyncio
    async def test_returns_material_list(self, mock_client, mock_request):
        """Returns list of creative materials."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "material_id": "mat_001",
                        "material_name": "夏日促销banner",
                        "material_type": "IMAGE",
                        "width": 1200,
                        "height": 628,
                        "file_size": 204800,
                        "create_time": "2024-05-10 14:30:00",
                    },
                    {
                        "material_id": "mat_002",
                        "material_name": "产品介绍视频",
                        "material_type": "VIDEO",
                        "duration": 15,
                        "file_size": 5242880,
                        "create_time": "2024-05-12 09:00:00",
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_materials

            result = await list_materials(advertiser_id="123")

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["material_type"] == "IMAGE"
        assert data["data"]["list"][1]["material_type"] == "VIDEO"

    @pytest.mark.asyncio
    async def test_with_material_type_filter(self, mock_client, mock_request):
        """Material type filter is forwarded to the API."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "material_id": "mat_003",
                        "material_name": "视频素材",
                        "material_type": "VIDEO",
                    }
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_materials

            await list_materials(advertiser_id="123", material_type="VIDEO")

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["material_type"] == "VIDEO"

    @pytest.mark.asyncio
    async def test_no_material_type_param_when_empty(self, mock_client, mock_request):
        """When material_type is empty, it is NOT added to params."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_materials

            await list_materials(advertiser_id="123", material_type="")

        call_kwargs = mock_request.call_args[1]
        assert "material_type" not in call_kwargs["params"]

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_materials

            await list_materials(advertiser_id="123", page_size=500)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Material library access denied")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_materials

            result = await list_materials(advertiser_id="999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "denied" in data["error"]["message"]


# ── Tool function tests: 人群 (Audience/DMP) ─────────────


class TestListAudiencePackages:
    """Tests for list_audience_packages."""

    @pytest.mark.asyncio
    async def test_returns_audience_packages(self, mock_client, mock_request):
        """Returns list of DMP audience packages with size and status."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "audience_id": "aud_1001",
                        "audience_name": "高消费女性用户",
                        "audience_size": 2800000,
                        "audience_type": "CUSTOM",
                        "status": "ACTIVE",
                        "create_time": "2024-04-01 10:00:00",
                    },
                    {
                        "audience_id": "aud_1002",
                        "audience_name": "一线城市白领",
                        "audience_size": 1500000,
                        "audience_type": "LOOKALIKE",
                        "status": "ACTIVE",
                        "create_time": "2024-04-15 14:00:00",
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_audience_packages

            result = await list_audience_packages(advertiser_id="123")

        data = json.loads(result)
        assert len(data["data"]["list"]) == 2
        assert data["data"]["list"][0]["audience_name"] == "高消费女性用户"
        assert data["data"]["list"][0]["audience_size"] == 2800000
        assert data["data"]["list"][1]["audience_type"] == "LOOKALIKE"

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_audience_packages

            await list_audience_packages(advertiser_id="123", page_size=999)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "DMP access not authorized")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import list_audience_packages

            result = await list_audience_packages(advertiser_id="999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "authorized" in data["error"]["message"]


class TestGetAudienceReport:
    """Tests for get_audience_report."""

    @pytest.mark.asyncio
    async def test_returns_audience_analysis(self, mock_client, mock_request):
        """Returns audience analysis with demographic and interest breakdown."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "dimension": "age",
                        "items": [
                            {"label": "18-24", "ratio": 0.35},
                            {"label": "25-34", "ratio": 0.45},
                            {"label": "35-44", "ratio": 0.15},
                            {"label": "45+", "ratio": 0.05},
                        ],
                    },
                    {
                        "dimension": "gender",
                        "items": [
                            {"label": "男", "ratio": 0.55},
                            {"label": "女", "ratio": 0.45},
                        ],
                    },
                ]
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_audience_report

            result = await get_audience_report(
                advertiser_id="123",
                start_date="2024-05-01",
                end_date="2024-05-31",
            )

        data = json.loads(result)
        breakdown = data["data"]["list"]
        assert len(breakdown) == 2
        assert breakdown[0]["dimension"] == "age"
        assert len(breakdown[0]["items"]) == 4
        assert breakdown[1]["dimension"] == "gender"

    @pytest.mark.asyncio
    async def test_page_size_capped_at_100(self, mock_client, mock_request):
        """page_size > 100 is capped."""
        mock_request.return_value = {"code": 0, "data": {"list": []}}

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_audience_report

            await get_audience_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
                page_size=500,
            )

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["page_size"] == 100

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Audience report not available")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_audience_report

            result = await get_audience_report(
                advertiser_id="123",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "Audience" in data["error"]["message"]


# ── Tool function tests: 优化建议 (Optimization) ─────────────


class TestGetBidSuggestion:
    """Tests for get_bid_suggestion."""

    @pytest.mark.asyncio
    async def test_returns_bid_suggestions(self, mock_client, mock_request):
        """Returns bid suggestions with min, max, and recommended bid."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "campaign_id": 1001,
                "suggestions": {
                    "bid_min": 8.00,
                    "bid_max": 25.00,
                    "bid_recommended": 15.50,
                    "competition_level": "MEDIUM",
                    "estimated_impressions": 500000,
                },
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_bid_suggestion

            result = await get_bid_suggestion(
                advertiser_id="123", campaign_id="1001"
            )

        data = json.loads(result)
        assert data["data"]["campaign_id"] == 1001
        suggestions = data["data"]["suggestions"]
        assert suggestions["bid_min"] == 8.00
        assert suggestions["bid_max"] == 25.00
        assert suggestions["bid_recommended"] == 15.50
        assert "competition_level" in suggestions

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Campaign has no delivery data for bid suggestion")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_bid_suggestion

            result = await get_bid_suggestion(
                advertiser_id="123", campaign_id="99999"
            )

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "bid suggestion" in data["error"]["message"]


class TestGetDiagnosis:
    """Tests for get_diagnosis."""

    @pytest.mark.asyncio
    async def test_returns_diagnosis(self, mock_client, mock_request):
        """Returns campaign diagnosis with issues and recommendations."""
        mock_request.return_value = {
            "code": 0,
            "data": {
                "campaign_id": 1001,
                "diagnosis_score": 75,
                "issues": [
                    {
                        "type": "BUDGET_LIMIT",
                        "severity": "MEDIUM",
                        "description": "日预算多次消耗达到上限，建议提高预算",
                    },
                    {
                        "type": "AUDIENCE_SATURATION",
                        "severity": "LOW",
                        "description": "定向人群规模偏小，建议扩展兴趣标签",
                    },
                ],
                "recommendations": [
                    "将日预算从 5000 提高到 10000",
                    "添加相关兴趣标签扩大受众规模",
                ],
            },
        }

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_diagnosis

            result = await get_diagnosis(advertiser_id="123", campaign_id="1001")

        data = json.loads(result)
        assert data["data"]["campaign_id"] == 1001
        assert data["data"]["diagnosis_score"] == 75
        assert len(data["data"]["issues"]) == 2
        assert data["data"]["issues"][0]["type"] == "BUDGET_LIMIT"
        assert len(data["data"]["recommendations"]) == 2

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_client, mock_request):
        """CommerceAPIError is caught and formatted."""
        mock_request.side_effect = CommerceAPIError(40100, "Diagnosis not available for this campaign")

        with _patch_get_client(mock_client):
            from mcp_oceanengine.server import get_diagnosis

            result = await get_diagnosis(advertiser_id="123", campaign_id="99999")

        data = json.loads(result)
        assert data["error"]["code"] == 40100
        assert "Diagnosis" in data["error"]["message"]


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
            (
                "get_qianchuan_report",
                {"advertiser_id": "1", "start_date": "2024-01-01", "end_date": "2024-01-31", "page_size": 300},
            ),
            (
                "get_qianchuan_campaign_list",
                {"advertiser_id": "1", "page_size": 300},
            ),
            (
                "get_star_report",
                {"advertiser_id": "1", "start_date": "2024-01-01", "end_date": "2024-01-31", "page_size": 300},
            ),
            (
                "list_star_tasks",
                {"advertiser_id": "1", "page_size": 300},
            ),
            (
                "list_ads",
                {"advertiser_id": "1", "page_size": 300},
            ),
            (
                "get_creative_report",
                {"advertiser_id": "1", "start_date": "2024-01-01", "end_date": "2024-01-31", "page_size": 300},
            ),
            (
                "list_materials",
                {"advertiser_id": "1", "page_size": 300},
            ),
            (
                "list_audience_packages",
                {"advertiser_id": "1", "page_size": 300},
            ),
            (
                "get_audience_report",
                {"advertiser_id": "1", "start_date": "2024-01-01", "end_date": "2024-01-31", "page_size": 300},
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
