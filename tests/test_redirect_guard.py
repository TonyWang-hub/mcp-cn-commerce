"""Credential-bearing platform requests never follow HTTP redirects."""

import httpx
import pytest

from shared.platform_clients import create_platform_client


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["jd", "weixin_store"])
@pytest.mark.parametrize("status", [301, 302, 307, 308])
async def test_injected_redirecting_client_cannot_replace_shop_identity(platform, status):
    seen = []

    def wire(request):
        seen.append(request)
        if request.url.host != "untrusted.example":
            return httpx.Response(status, headers={"Location": "https://untrusted.example/fake-shop"})
        body = (
            {"errcode": 0, "info": {"username": "intended-shop"}}
            if platform == "weixin_store"
            else {
                "jingdong_vender_shop_query_responce": {
                    "shop_jos_result": {"shop_id": "123", "vender_id": "456"},
                }
            }
        )
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire), follow_redirects=True) as http:
        async with create_platform_client(
            platform,
            {
                "app_key": "app",
                "app_secret": "secret",
                "access_token": "token",
            },
            http_client=http,
        ) as client:
            with pytest.raises(httpx.HTTPStatusError) as failure:
                await client.call("get_shop_info", {})
            assert failure.value.response.status_code == status
            assert len(seen) == 1 and seen[0].url.host != "untrusted.example"
        assert not http.is_closed
