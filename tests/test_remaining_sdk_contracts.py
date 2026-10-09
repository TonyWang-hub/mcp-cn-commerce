"""Official R16 sources distinguish executable adapters from pending migrations."""

import httpx
import pytest

from shared.platform_clients import create_platform_client, operation_catalog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,operation",
    [("oceanengine", name) for name in ("get_campaign_report", "get_ad_detail_report", "get_qianchuan_report")],
)
async def test_unmigrated_reads_refuse_before_http(platform, operation):
    requests = []
    credentials = {"access_token": "token"}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: (requests.append(r), httpx.Response(200, json={}))[1])
    ) as http:
        client = create_platform_client(platform, credentials, http_client=http)
        with pytest.raises(ValueError, match="migration"):
            await client.call(operation, {})
        assert not requests
        await client.close()
    metadata = operation_catalog(platform)[operation]
    assert metadata.supported is False
    assert metadata.live_verified is False
    assert metadata.contract_status == "partial"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params,path",
    [
        ("get_advertiser_info", {"advertiser_ids": [1, 2]}, "2/advertiser/info/"),
        ("get_account_balance", {"advertiser_id": 1}, "2/advertiser/fund/get/"),
    ],
)
async def test_documented_advertiser_reads_use_current_official_origin(operation, params, path):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: (requests.append(r), httpx.Response(200, json={"code": 0, "data": {}}))[1]
        )
    ) as http:
        client = create_platform_client("oceanengine", {"access_token": "advertiser-token"}, http_client=http)
        assert await client.call(operation, params) == {"code": 0, "data": {}}
        request = requests[0]
        assert str(request.url).startswith("https://ad.oceanengine.com/open_api/" + path)
        assert request.method == "GET"
        assert request.headers["Access-Token"] == "advertiser-token"
        assert not request.content
        assert client.operations[operation].contract_status == "documented"
        assert client.operations[operation].live_verified is False
        await client.close()
