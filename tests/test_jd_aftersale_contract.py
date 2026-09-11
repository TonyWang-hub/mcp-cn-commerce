"""Official POP aftersale reads remain separate from full refund collection."""

import asyncio
import hashlib
import json
from copy import deepcopy
from urllib.parse import parse_qs

import httpx
import pytest

from shared.cn_commerce_base import CommerceAPIError
from shared.platform_clients import create_platform_client, operation_catalog

METHODS = {
    "get_aftersale_list": "jingdong.asc.serviceAndRefund.view",
    "get_aftersale_refund_detail": "jingdong.b2c.shop.aftersales.refund.get",
}


def query(operation):
    if operation == "get_aftersale_refund_detail":
        return {"afsServiceId": 123}
    return {
        "applyTimeBegin": "2026-09-01 00:00:00",
        "applyTimeEnd": "2026-09-08 00:00:00",
        "pageNumber": 1,
        "pageSize": 2,
    }


def payload(operation, *, estimate=False):
    if operation == "get_aftersale_list":
        result = {
            "success": True,
            "code": "00000",
            "totalCount": 1,
            "pageNumber": 1,
            "pageSize": 2,
            "data": [
                {
                    "afsRefundId": "456",
                    "status": 13,
                    "completeTime": "2026-09-10 12:00:00",
                    "refoundAmount": "12.30",
                    "sameOrderServiceBill": {"serviceId": 123, "orderId": 789},
                }
            ],
        }
        field = "pageResult"
    else:
        result = {
            "success": "true",
            "errorCode": "200",
            "data": {
                "orderId": 789,
                **(
                    {"afsEstimateRefundDetail": {"maxRefundAmount": "15.00"}}
                    if estimate
                    else {"afsActualRefundDetail": {"actualRefundAmount": "12.30"}}
                ),
            },
        }
        field = "result"
    return {METHODS[operation].replace(".", "_") + "_responce": {field: result}}


async def invoke(operation, params, reply):
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: (requests.append(request), httpx.Response(200, json=reply))[1])
    ) as http:
        async with create_platform_client(
            "jd", {"app_key": "app", "app_secret": "secret", "access_token": "token"}, http_client=http
        ) as client:
            result = await client.call(operation, params)
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", METHODS)
async def test_aftersale_sdk_signed_native_leaf_fields_and_distinct_capabilities(operation):
    expected = payload(operation)
    result, requests = await invoke(operation, query(operation), expected)
    assert result == expected and len(requests) == 1
    request = requests[0]
    form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
    assert request.method == "POST" and str(request.url) == "https://api.jd.com/routerjson"
    assert form["method"] == METHODS[operation]
    assert json.loads(form["360buy_param_json"]) == query(operation)
    unsigned = "secret" + "".join(k + v for k, v in sorted(form.items()) if k != "sign") + "secret"
    assert form["sign"] == hashlib.md5(unsigned.encode()).hexdigest().upper()
    contract = operation_catalog("jd")[operation]
    assert contract.supported and contract.contract_status == "documented" and not contract.live_verified
    assert not operation_catalog("jd")["get_refund_list"].supported
    assert not operation_catalog("jd")["get_refund_detail"].supported


@pytest.mark.asyncio
async def test_aftersale_estimate_branch_is_not_relabelled_actual_refund():
    result, _ = await invoke(
        "get_aftersale_refund_detail",
        {"afsServiceId": 123, "skuNum": 2},
        payload("get_aftersale_refund_detail", estimate=True),
    )
    assert "actualRefundAmount" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"orderId": 789, "pageNumber": 1, "pageSize": 50},
        {
            "approveTimeBegin": "2026-09-01 00:00:00",
            "approveTimeEnd": "2026-09-11 00:00:00",
            "pageNumber": 1,
            "pageSize": 2,
        },
    ],
)
async def test_aftersale_order_and_ten_day_approval_queries(params):
    _, requests = await invoke("get_aftersale_list", params, payload("get_aftersale_list"))
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,change",
    [
        ("get_aftersale_list", {"pageNumber": 0}),
        ("get_aftersale_list", {"pageNumber": True}),
        ("get_aftersale_list", {"pageNumber": "1"}),
        ("get_aftersale_list", {"pageSize": 51}),
        ("get_aftersale_list", {"pageSize": 1.0}),
        ("get_aftersale_list", {"applyTimeBegin": None}),
        ("get_aftersale_list", {"applyTimeEnd": "2026-09-08 00:00:01"}),
        ("get_aftersale_list", {"applyTimeEnd": "2026-09-01 00:00:00"}),
        ("get_aftersale_list", {"applyTimeBegin": "2026-9-1 00:00:00"}),
        ("get_aftersale_list", {"approveTimeBegin": "2026-09-01 00:00:00"}),
        ("get_aftersale_list", {"approveTimeBegin": "2026-09-01 00:00:00", "approveTimeEnd": "2026-09-11 00:00:01"}),
        ("get_aftersale_list", {"orderId": 0}),
        ("get_aftersale_list", {"buId": "456"}),
        ("get_aftersale_list", {"venderId": 456}),
        ("get_aftersale_list", {"pin": "private"}),
        ("get_aftersale_list", {"serviceBaseQuery": {}}),
        ("get_aftersale_list", {"extJsonStr": "{}"}),
        ("get_aftersale_refund_detail", {"afsServiceId": True}),
        ("get_aftersale_refund_detail", {"afsServiceId": 2**63}),
        ("get_aftersale_refund_detail", {"afsServiceId": "123"}),
        ("get_aftersale_refund_detail", {"skuNum": 0}),
        ("get_aftersale_refund_detail", {"param": {"data": {"afsServiceId": 123}}}),
        ("get_aftersale_refund_detail", {"operatorRemark": "private"}),
    ],
)
async def test_bad_aftersale_fields_fail_without_network(operation, change):
    def network(_):
        pytest.fail("invalid query sent to merchant endpoint")

    async with httpx.AsyncClient(transport=httpx.MockTransport(network)) as http:
        async with create_platform_client(
            "jd", {"app_key": "app", "app_secret": "secret", "access_token": "token"}, http_client=http
        ) as client:
            with pytest.raises(ValueError):
                await client.call(operation, {**query(operation), **change})


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{}, {"pageNumber": 1, "pageSize": 2}, {"afsServiceId": 123, "skuNum": None}])
async def test_aftersale_requires_a_bounded_query(params):
    operation = "get_aftersale_refund_detail" if "afsServiceId" in params else "get_aftersale_list"
    with pytest.raises(ValueError):
        await invoke(operation, params, payload(operation))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", METHODS)
@pytest.mark.parametrize(
    "change", [{"success": False}, {"success": 1}, {"success": None}, {"success": "TRUE"}, {"success": "false"}]
)
async def test_aftersale_success_is_explicit_and_errors_are_sanitized(operation, change):
    data = payload(operation)
    result = next(iter(next(iter(data.values())).values()))
    result.update(change)
    result["errorMsg"] = "PRIVATE_BUYER TOKEN"
    with pytest.raises((CommerceAPIError, ValueError)) as error:
        await invoke(operation, query(operation), data)
    assert "PRIVATE" not in str(error.value) and "TOKEN" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem", ["rows", "total", "short_total", "page", "size", "missing_success", "code", "id", "date"]
)
async def test_aftersale_list_rejects_invalid_envelopes_and_records(problem):
    data = payload("get_aftersale_list")
    result = data["jingdong_asc_serviceAndRefund_view_responce"]["pageResult"]
    if problem == "rows":
        result["data"] = {}
    if problem == "total":
        result["totalCount"] = True
    if problem == "short_total":
        result["totalCount"] = 0
    if problem == "page":
        result["pageNumber"] = 0
    if problem == "size":
        result["pageSize"] = 51
    if problem == "missing_success":
        result.pop("success")
    if problem == "code":
        result["code"] = "200"
    if problem == "id":
        result["data"][0]["sameOrderServiceBill"]["orderId"] = 0
    if problem == "date":
        result["data"][0]["completeTime"] = "PRIVATE_DATE"
    with pytest.raises((CommerceAPIError, ValueError)):
        await invoke("get_aftersale_list", query("get_aftersale_list"), data)


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["both", "neither", "amount", "infinite", "negative", "empty", "order", "code"])
async def test_refund_detail_requires_one_documented_amount_branch(problem):
    data = payload("get_aftersale_refund_detail")
    result = data["jingdong_b2c_shop_aftersales_refund_get_responce"]["result"]
    body = result["data"]
    if problem == "both":
        body["afsEstimateRefundDetail"] = {"maxRefundAmount": "20.00"}
    if problem == "neither":
        body.pop("afsActualRefundDetail")
    if problem in {"amount", "infinite", "negative"}:
        body["afsActualRefundDetail"]["actualRefundAmount"] = {
            "amount": True,
            "infinite": "Infinity",
            "negative": "-1",
        }[problem]
    if problem == "empty":
        body["afsActualRefundDetail"] = {}
    if problem == "order":
        body["orderId"] = ""
    if problem == "code":
        result["errorCode"] = "0"
    with pytest.raises((CommerceAPIError, ValueError)):
        await invoke("get_aftersale_refund_detail", query("get_aftersale_refund_detail"), data)


@pytest.mark.asyncio
async def test_two_authorizations_and_native_pages_keep_distinct_tokens():
    captured = []

    async def wire(request):
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        params = json.loads(form["360buy_param_json"])
        captured.append((form["access_token"], params))
        await asyncio.sleep(0)
        result = deepcopy(payload("get_aftersale_list"))
        body = result["jingdong_asc_serviceAndRefund_view_responce"]["pageResult"]
        body.update(pageNumber=params["pageNumber"], totalCount=2, pageSize=1)
        return httpx.Response(200, json=result)

    async with httpx.AsyncClient(transport=httpx.MockTransport(wire)) as http:

        async def run(token):
            async with create_platform_client(
                "jd", {"app_key": "app", "app_secret": "secret", "access_token": token}, http_client=http
            ) as client:
                for page in (1, 2):
                    await client.call(
                        "get_aftersale_list", {**query("get_aftersale_list"), "pageNumber": page, "pageSize": 1}
                    )

        await asyncio.gather(run("one"), run("two"))
    assert {(token, params["pageNumber"]) for token, params in captured} == {
        (token, page) for token in ("one", "two") for page in (1, 2)
    }
