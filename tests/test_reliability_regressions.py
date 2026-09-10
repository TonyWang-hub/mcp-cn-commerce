"""Regression evidence for transport, concurrency, and diagnostic boundaries.

Transport tests use real httpx MockTransport (no network); the MCP SDK wire
contract is exercised separately by the platform/package integration tests.
"""

import asyncio
import csv
import io
import json
import logging
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from shared.cn_commerce_base import (
    BatchRequestItem,
    CommerceAPIError,
    CommerceMCPBase,
    ConfigurableRateLimiter,
    DataExporter,
    DebugLogger,
    ExportConfig,
    ExportFormat,
    FailoverConfig,
    FailoverManager,
    LoadBalancer,
    RateLimitConfig,
    RateLimiter,
    RequestRecorder,
    RequestTracer,
    RetryConfig,
    RetryQueueConfig,
    RetryRequestQueue,
    SensitiveDataFilter,
    format_error_response,
    handle_tool_errors,
    mask_dict_sensitive_keys,
    mask_log_message,
    validate_api_param,
)


def make_client(handler):
    client = CommerceMCPBase(app_key="synthetic-app", app_secret="synthetic-secret")
    client.BASE_URL = "https://commerce.test"
    client.configurable_limiter.config.enabled = False
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_http_failure_retries_and_is_not_success(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"message": "temporary failure"})

    client = make_client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client._request("GET", "/orders", retry_config=RetryConfig(max_retries=2, base_delay=0, jitter=False))
        assert len(calls) == 3
        metrics = client.get_metrics_summary()["global"]
        assert metrics["total_errors"] == 3
        assert metrics["total_requests"] == 3
        assert not client._tracer.get_active_spans()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_business_parser_failure_recorded_before_success():
    client = make_client(lambda request: httpx.Response(200, json={"code": 42}))

    def parse(payload):
        raise CommerceAPIError(payload["code"], "permission denied")

    try:
        with pytest.raises(CommerceAPIError):
            await client._send_request("GET", "https://commerce.test/orders", parse_response=parse)
        assert client.get_metrics_summary()["global"]["total_errors"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_json_remains_parse_error_and_write_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"not JSON")

    client = make_client(handler)
    try:
        with pytest.raises(json.JSONDecodeError):
            await client._send_request("POST", "https://commerce.test/mutation", json_body={"id": 1})
        assert len(calls) == 1
        assert client.get_metrics_summary()["global"]["total_errors"] == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_signature_covers_exact_nested_and_get_data_wire_values():
    captured = []

    def handler(request):
        captured.append(dict(request.url.params))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    try:
        await client._request("GET", "/orders", params={"filter": {"b": 2, "a": 1}}, data={"active": True})
        wire = captured[0]
        assert wire["active"] == "true"
        assert wire["filter"] == '{"a":1,"b":2}'
        assert wire["sign"] == client._sign(wire)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cancellation_finishes_request_span():
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    client = make_client(handler)
    task = asyncio.create_task(client._request("GET", "/orders"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client._tracer.get_active_spans()
    assert client.get_trace_summary()["status"] == "cancelled"
    await client.close()


@pytest.mark.asyncio
async def test_limiter_concurrent_admissions_are_spaced():
    limiter = RateLimiter(100)
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(20)))
    assert time.monotonic() - started >= 0.17


@pytest.mark.asyncio
async def test_platform_limit_covers_different_endpoints():
    limiter = ConfigurableRateLimiter(RateLimitConfig(default_requests_per_second=100))
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire("SHOP", f"/orders/{i}") for i in range(20)))
    assert time.monotonic() - started >= 0.17
    assert limiter.stats.total_requests == 20


@pytest.mark.asyncio
async def test_ordinary_request_honors_configured_limit():
    client = make_client(lambda request: httpx.Response(200, json={"ok": True}))
    client.configurable_limiter.config.enabled = True
    client.configurable_limiter.set_platform_rps(client.platform_name, 20)
    started = time.monotonic()
    try:
        await asyncio.gather(client._request("GET", "/one"), client._request("GET", "/two"))
        assert time.monotonic() - started >= 0.04
        assert client.configurable_limiter.stats.total_requests == 2
    finally:
        await client.close()


def test_csv_union_and_formula_safety_preserve_numeric_values():
    output = DataExporter.export_to_string(
        [{"id": "001", "title": '=HYPERLINK("https://invalid")', "amount": -12}, {"id": "002", "refund": 4}],
        format=ExportFormat.CSV,
    )
    rows = list(csv.DictReader(io.StringIO(output)))
    assert rows[0]["id"] == "001"
    assert rows[0]["title"].startswith("'=")
    assert rows[0]["amount"] == "-12"
    assert rows[1]["refund"] == "4"


def test_excel_uses_xlsx_and_text_cells(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    result = DataExporter.export(
        [{"id": "0001", "title": "=1+1"}, {"id": "0002", "refund": 3}],
        ExportConfig(format=ExportFormat.EXCEL, output_dir=str(tmp_path)),
    )
    assert result["file_path"].endswith(".xlsx")
    workbook = openpyxl.load_workbook(result["file_path"])
    assert workbook.active["B2"].data_type == "s"
    assert workbook.active["A2"].value == "0001"
    assert "refund" in result["fields"]


def test_recursive_headers_query_and_interpolated_dict_are_redacted():
    secret = "sensitive0123456789"
    data = {"headers": {"Authorization": secret, "Access-Token": secret}, "nested": [[{"clientSecret": secret}]]}
    assert secret not in json.dumps(mask_dict_sensitive_keys(data))
    assert secret not in mask_log_message(f"failed https://shop.test/path?access_token={secret}&id=1")
    record = logging.LogRecord("test", logging.ERROR, "file", 1, "request: %s", (data,), None)
    SensitiveDataFilter().filter(record)
    assert secret not in record.getMessage()


def test_recorder_and_debug_logs_do_not_keep_credentials():
    secret = "sensitive0123456789"
    recorder = RequestRecorder()
    recorder.record(
        "GET", f"/orders?access_token={secret}", params={"access_token": secret}, response={"Authorization": secret}
    )
    assert secret not in recorder.export_json()
    debug = DebugLogger()
    debug.log("error", f"token={secret}", {"headers": {"Authorization": secret}})
    assert secret not in debug.export_json()


def test_traces_are_bounded_and_independent():
    tracer = RequestTracer(max_spans=10)
    first = tracer.start_span("failed")
    tracer.finish_span(first, "error")
    second = tracer.start_span("successful")
    tracer.finish_span(second)
    assert tracer.get_trace_summary()["trace_id"] == second.trace_id
    assert tracer.get_trace_summary()["status"] == "ok"
    assert tracer.get_trace_summary(first.trace_id)["status"] == "error"
    for _ in range(100):
        tracer.finish_span(tracer.start_span("another"))
    assert len(tracer.get_spans()) == 10
    assert not tracer.get_active_spans()


@pytest.mark.asyncio
async def test_retry_queue_restores_unfinished_jobs_on_cancel():
    queue = RetryRequestQueue(RetryQueueConfig(base_delay=0, jitter=False, dedup_window=0))
    await queue.enqueue("GET", "/one")
    await queue.enqueue("GET", "/two")
    entered = asyncio.Event()

    async def blocked(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(queue.process(blocked))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert queue.pending_count == 2
    assert queue.in_flight_count == 0
    assert all(item.retry_count == 0 for item in queue.peek())


@pytest.mark.asyncio
async def test_batch_fail_fast_skips_requests_waiting_for_slot():
    client = CommerceMCPBase()
    client._request = AsyncMock(side_effect=CommerceAPIError(42, "failed"))
    result = await client._batch_request(
        [BatchRequestItem(method="GET", path=f"/{i}", request_id=str(i)) for i in range(5)],
        max_concurrency=1,
        fail_fast=True,
    )
    assert client._request.await_count == 1
    assert result.total == 5
    assert result.failed == 5


def test_half_open_allows_one_probe_then_recovers():
    balancer = LoadBalancer()
    url = "https://shop.test"
    balancer.add_endpoint(url)
    manager = FailoverManager(balancer, FailoverConfig(circuit_breaker_reset_seconds=0))
    for _ in range(5):
        manager.report_failure(url)
    assert manager.get_healthy_endpoint().url == url
    assert manager.get_healthy_endpoint() is None
    manager.report_success(url)
    assert manager.get_healthy_endpoint().url == url


def test_half_open_failed_probe_reopens_circuit():
    balancer = LoadBalancer()
    url = "https://shop.test"
    balancer.add_endpoint(url)
    manager = FailoverManager(balancer, FailoverConfig(circuit_breaker_reset_seconds=0))
    for _ in range(5):
        manager.report_failure(url)
    assert manager.get_healthy_endpoint().url == url
    manager.config.circuit_breaker_reset_seconds = 60
    manager.report_failure(url)
    assert manager.get_healthy_endpoint() is None
    assert manager.is_circuit_open(url)


@pytest.mark.parametrize(
    "value", ["SELECT 防晒衣", "DROP shoulder tee", "CREATE design", "update edition", "cargo -- blue"]
)
def test_business_words_are_not_rejected(value):
    assert validate_api_param("keyword", value) == value


@pytest.mark.asyncio
async def test_structured_tool_return_annotation_matches_result():
    @handle_tool_errors
    async def tool() -> dict:
        return {"ok": True}

    assert await tool() == {"ok": True}
    assert tool.__annotations__["return"] is dict

    @handle_tool_errors
    async def error_tool() -> dict:
        raise CommerceAPIError(42, "denied")

    with pytest.raises(CommerceAPIError):
        await error_tool()


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after", ["600", "Wed, 01 Jan 2031 00:00:00 GMT"])
async def test_retry_after_exceeding_budget_preserves_error_without_early_retry(retry_after):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": retry_after}, json={"error": "throttled"})

    client = make_client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client._request("GET", "/orders", retry_config=RetryConfig(base_delay=0, max_delay=1))
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_pagination_uses_page_key_and_exposes_possible_truncation():
    client = CommerceMCPBase()
    fetch = AsyncMock(return_value={"list": []})
    assert await client._paginate(fetch, page_key="pageNo") == []
    fetch.assert_awaited_once_with(pageNo=1, page_size=50)
    full = AsyncMock(return_value={"list": [{"id": 1}]})
    with pytest.raises(RuntimeError, match="incomplete"):
        await client._paginate(full, page_size=1, max_pages=1)


@pytest.mark.parametrize(
    "key",
    ["secret", "accessToken", "appSecret", "refreshToken", "password", "receiver_tel", "buyer_name"],
)
def test_sensitive_aliases_redacted_in_urls_and_nested_data(key):
    secret = "synthetic-DO-NOT-LEAK-secret"
    url = f"https://shop.test/cgi-bin/token?appid=demo&{key}={secret}"
    assert secret not in mask_log_message(url)
    assert secret not in json.dumps(mask_dict_sensitive_keys({"params": {key: secret}}))
    assert secret not in format_error_response(RuntimeError(url))
    assert secret not in format_error_response(CommerceAPIError(42, url))


@pytest.mark.asyncio
async def test_tool_error_outputs_redact_weixin_token_secret():
    secret = "synthetic-DO-NOT-LEAK-secret"
    url = f"https://shop.test/cgi-bin/token?appid=demo&secret={secret}"

    @handle_tool_errors
    async def text_tool() -> str:
        raise RuntimeError(url)

    @handle_tool_errors
    async def structured_tool() -> dict:
        raise CommerceAPIError(42, url)

    @handle_tool_errors
    async def structured_http_tool() -> dict:
        response = httpx.Response(403, request=httpx.Request("GET", url))
        response.raise_for_status()
        return response.json()

    assert secret not in await text_tool()
    with pytest.raises(CommerceAPIError) as caught:
        await structured_tool()
    assert caught.value.code == 42
    assert secret not in str(caught.value)
    with pytest.raises(httpx.HTTPStatusError) as caught_http:
        await structured_http_tool()
    assert secret not in str(caught_http.value)


@pytest.mark.asyncio
async def test_dynamic_limit_change_recalculates_queued_and_sleeping_requests():
    limiter = ConfigurableRateLimiter(RateLimitConfig(default_requests_per_second=100))
    await limiter.acquire("SHOP", "/orders")
    times = [time.monotonic()]

    async def acquire():
        await limiter.acquire("SHOP", "/orders")
        times.append(time.monotonic())

    pending = [asyncio.create_task(acquire()) for _ in range(3)]
    await asyncio.sleep(0)
    limiter.set_platform_rps("SHOP", 5)
    await asyncio.gather(*pending)
    assert all(later - earlier >= 0.18 for earlier, later in zip(times, times[1:]))


@pytest.mark.asyncio
async def test_dynamic_speedup_wakes_existing_waiter():
    limiter = ConfigurableRateLimiter(RateLimitConfig(default_requests_per_second=1))
    await limiter.acquire("SHOP", "/orders")
    pending = asyncio.create_task(limiter.acquire("SHOP", "/orders"))
    await asyncio.sleep(0)
    limiter.set_platform_rps("SHOP", 100)
    await asyncio.wait_for(pending, timeout=0.3)


@pytest.mark.asyncio
async def test_transport_redacts_final_error_without_disrupting_http_retries():
    secret = "synthetic-DO-NOT-LEAK-secret"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"message": "temporary"})

    client = make_client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await client._send_request(
                "GET",
                "https://shop.test/cgi-bin/token",
                params={"secret": secret},
                retry_config=RetryConfig(max_retries=1, base_delay=0, jitter=False),
            )
        assert len(calls) == 2
        assert caught.value.response.status_code == 503
        assert secret not in str(caught.value)
        assert secret not in str(caught.value.request.url)
        assert secret not in str(caught.value.response.request.url)
        assert client.get_metrics_summary()["global"]["total_errors"] == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_weixin_managed_token_failure_redacted_without_tool_decorator():
    from servers.weixin_store.server import WeixinStoreMCP

    secret = "synthetic-DO-NOT-LEAK-secret"
    client = WeixinStoreMCP(app_key="demo", app_secret=secret, token_mode="managed")
    client.configurable_limiter.config.enabled = False
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"message": "denied"}))
    )
    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await client._request("POST", "/channels/ec/order/get", data={"order_id": "1"})
        assert caught.value.response.status_code == 403
        assert secret not in str(caught.value)
        assert secret not in str(caught.value.request.url)
        assert client.get_metrics_summary()["global"]["total_errors"] == 1
    finally:
        await client.close()
