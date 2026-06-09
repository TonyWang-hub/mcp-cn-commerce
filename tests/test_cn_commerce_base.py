"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

# Add the shared directory to the path
_shared_dir = Path(__file__).resolve().parents[1] / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from cn_commerce_base import (
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    RateLimiter,
    SignMethod,
    WebhookDeliveryError,
    WebhookDeliveryResult,
    WebhookEvent,
    WebhookEventType,
    WebhookManager,
    WebhookSignatureVerifier,
    WebhookSubscription,
    format_error_response,
)

# ── SignMethod Tests ──────────────────────────────────────


class TestSignMethod:
    """Tests for SignMethod constants."""

    def test_md5_constant(self):
        assert SignMethod.MD5 == "md5"

    def test_hmac_sha256_constant(self):
        assert SignMethod.HMAC_SHA256 == "hmac_sha256"

    def test_hmac_md5_constant(self):
        assert SignMethod.HMAC_MD5 == "hmac_md5"


# ── ConfigValidationError Tests ───────────────────────────


class TestConfigValidationError:
    """Tests for ConfigValidationError."""

    def test_single_missing_var(self):
        err = ConfigValidationError("TEST", ["APP_KEY"])
        assert err.platform == "TEST"
        assert err.missing_vars == ["APP_KEY"]
        assert "APP_KEY" in str(err)

    def test_multiple_missing_vars(self):
        err = ConfigValidationError("TEST", ["APP_KEY", "APP_SECRET"])
        assert err.platform == "TEST"
        assert err.missing_vars == ["APP_KEY", "APP_SECRET"]
        assert "APP_KEY" in str(err)
        assert "APP_SECRET" in str(err)

    def test_is_exception(self):
        err = ConfigValidationError("TEST", ["VAR"])
        assert isinstance(err, Exception)


# ── CommerceAPIError Tests ────────────────────────────────


class TestCommerceAPIError:
    """Tests for CommerceAPIError."""

    def test_error_attributes(self):
        err = CommerceAPIError(40001, "Invalid parameters")
        assert err.code == 40001
        assert err.msg == "Invalid parameters"

    def test_error_message_format(self):
        err = CommerceAPIError(40001, "Invalid parameters")
        assert "[40001] Invalid parameters" in str(err)

    def test_is_exception(self):
        err = CommerceAPIError(1, "test")
        assert isinstance(err, Exception)


# ── RateLimiter Tests ─────────────────────────────────────


class TestRateLimiter:
    """Tests for RateLimiter."""

    def test_default_rate(self):
        limiter = RateLimiter()
        assert limiter.requests_per_second == 10.0

    def test_custom_rate(self):
        limiter = RateLimiter(requests_per_second=5.0)
        assert limiter.requests_per_second == 5.0

    def test_min_interval(self):
        limiter = RateLimiter(requests_per_second=10.0)
        assert limiter.min_interval == 0.1

    @pytest.mark.asyncio
    async def test_acquire_first_call(self):
        limiter = RateLimiter()
        # First call should not wait
        await limiter.acquire()
        assert limiter.last_request_time > 0

    @pytest.mark.asyncio
    async def test_acquire_respects_rate_limit(self):
        limiter = RateLimiter(requests_per_second=100.0)
        # First call
        await limiter.acquire()
        # Second call should wait
        await limiter.acquire()
        # Both calls should complete without error


# ── format_error_response Tests ───────────────────────────


class TestFormatErrorResponse:
    """Tests for format_error_response."""

    def test_commerce_api_error(self):
        err = CommerceAPIError(40001, "Invalid parameters")
        result = json.loads(format_error_response(err))
        assert result["error"]["code"] == 40001
        assert result["error"]["message"] == "Invalid parameters"

    def test_generic_exception(self):
        err = ValueError("Something went wrong")
        result = json.loads(format_error_response(err))
        assert result["error"]["message"] == "Something went wrong"

    def test_returns_valid_json(self):
        err = CommerceAPIError(1, "test")
        result = format_error_response(err)
        # Should not raise
        json.loads(result)


# ── CommerceMCPBase Tests ─────────────────────────────────


class TestCommerceMCPBase:
    """Tests for CommerceMCPBase."""

    def test_init_default_values(self):
        client = CommerceMCPBase()
        assert client.app_key == ""
        assert client.app_secret == ""
        assert client.access_token == ""

    def test_init_with_values(self):
        client = CommerceMCPBase(
            app_key="test_key",
            app_secret="test_secret",
            access_token="test_token",
        )
        assert client.app_key == "test_key"
        assert client.app_secret == "test_secret"
        assert client.access_token == "test_token"

    def test_has_rate_limiter(self):
        client = CommerceMCPBase()
        assert client.rate_limiter is not None
        assert isinstance(client.rate_limiter, RateLimiter)

    def test_from_env_success(self):
        with patch.dict(
            os.environ,
            {
                "TEST_APP_KEY": "key",
                "TEST_APP_SECRET": "secret",
                "TEST_ACCESS_TOKEN": "token",
            },
        ):
            client = CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
            assert client.app_key == "key"
            assert client.app_secret == "secret"
            assert client.access_token == "token"

    def test_from_env_missing_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET"])
            assert "TEST" in str(exc_info.value)
            assert "TEST_APP_KEY" in str(exc_info.value)
            assert "TEST_APP_SECRET" in str(exc_info.value)

    def test_from_env_partial_vars(self):
        with patch.dict(os.environ, {"TEST_APP_KEY": "key"}, clear=True):
            with pytest.raises(ConfigValidationError):
                CommerceMCPBase.from_env("TEST", ["APP_KEY", "APP_SECRET"])

    def test_sign_md5(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "test", "timestamp": "1234567890"}
        result = client._sign(params)
        assert isinstance(result, str)
        assert len(result) == 32  # MD5 hex length

    def test_sign_hmac_sha256(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.HMAC_SHA256
        params = {"app_key": "test", "timestamp": "1234567890"}
        result = client._sign(params)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex length

    def test_sign_excludes_sign_params(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {
            "app_key": "test",
            "timestamp": "1234567890",
            "sign": "should_be_excluded",
            "sign_method": "should_be_excluded",
        }
        result = client._sign(params)
        assert isinstance(result, str)

    def test_sign_empty_values_excluded(self):
        client = CommerceMCPBase(app_secret="test_secret")
        client.sign_method = SignMethod.MD5
        params = {"app_key": "test", "empty_param": ""}
        result = client._sign(params)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_paginate_single_page(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"result": [{"id": 1}, {"id": 2}]})
        result = await client._paginate(mock_fetch, page_size=10)
        assert len(result) == 2
        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_paginate_multiple_pages(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(
            side_effect=[
                {"result": [{"id": 1}, {"id": 2}]},
                {"result": [{"id": 3}]},
            ]
        )
        result = await client._paginate(mock_fetch, page_size=2)
        assert len(result) == 3
        assert mock_fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_paginate_empty_result(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"result": []})
        result = await client._paginate(mock_fetch)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_paginate_uses_list_key(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"list": [{"id": 1}]})
        result = await client._paginate(mock_fetch)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_paginate_max_pages(self):
        client = CommerceMCPBase()
        mock_fetch = AsyncMock(return_value={"result": [{"id": 1}]})
        result = await client._paginate(mock_fetch, page_size=1, max_pages=3)
        assert len(result) == 3
        assert mock_fetch.call_count == 3


# ── Webhook Tests ───────────────────────────────────────────


class TestWebhookEventType:
    """Tests for WebhookEventType enum."""

    def test_order_update_value(self):
        assert WebhookEventType.ORDER_UPDATE == "order_update"

    def test_inventory_change_value(self):
        assert WebhookEventType.INVENTORY_CHANGE == "inventory_change"

    def test_product_update_value(self):
        assert WebhookEventType.PRODUCT_UPDATE == "product_update"

    def test_refund_request_value(self):
        assert WebhookEventType.REFUND_REQUEST == "refund_request"

    def test_payment_received_value(self):
        assert WebhookEventType.PAYMENT_RECEIVED == "payment_received"

    def test_shipping_update_value(self):
        assert WebhookEventType.SHIPPING_UPDATE == "shipping_update"

    def test_review_submitted_value(self):
        assert WebhookEventType.REVIEW_SUBMITTED == "review_submitted"

    def test_coupon_used_value(self):
        assert WebhookEventType.COUPON_USED == "coupon_used"

    def test_custom_value(self):
        assert WebhookEventType.CUSTOM == "custom"

    def test_all_event_types_count(self):
        assert len(WebhookEventType) == 9

    def test_is_string_enum(self):
        assert isinstance(WebhookEventType.ORDER_UPDATE, str)


class TestWebhookSubscription:
    """Tests for WebhookSubscription dataclass."""

    def test_basic_creation(self):
        sub = WebhookSubscription(
            subscription_id="sub-1",
            url="https://example.com/webhook",
            event_types=["order_update"],
            secret="test_secret",
        )
        assert sub.subscription_id == "sub-1"
        assert sub.url == "https://example.com/webhook"
        assert sub.event_types == ["order_update"]
        assert sub.secret == "test_secret"
        assert sub.is_active is True

    def test_auto_generated_fields(self):
        sub = WebhookSubscription(
            subscription_id="",
            url="https://example.com/webhook",
            event_types=["order_update"],
            secret="",
        )
        assert sub.subscription_id != ""
        assert sub.created_at != ""
        assert sub.secret != ""

    def test_default_metadata(self):
        a = WebhookSubscription(
            subscription_id="a", url="https://a.com", event_types=["order_update"], secret="s"
        )
        b = WebhookSubscription(
            subscription_id="b", url="https://b.com", event_types=["order_update"], secret="s"
        )
        a.metadata["key"] = "val"
        assert "key" not in b.metadata


class TestWebhookEvent:
    """Tests for WebhookEvent dataclass."""

    def test_basic_creation(self):
        event = WebhookEvent(
            event_type="order_update",
            platform="TAOBAO",
            payload={"order_id": "123"},
        )
        assert event.event_type == "order_update"
        assert event.platform == "TAOBAO"
        assert event.payload == {"order_id": "123"}

    def test_auto_generated_fields(self):
        event = WebhookEvent(event_type="order_update")
        assert event.event_id != ""
        assert event.timestamp != ""

    def test_to_dict(self):
        event = WebhookEvent(
            event_id="evt-1",
            event_type="order_update",
            platform="TAOBAO",
            payload={"order_id": "123"},
            timestamp="2026-06-09T00:00:00Z",
            source="order_123",
            version="1.0",
        )
        result = event.to_dict()
        assert result["event_id"] == "evt-1"
        assert result["event_type"] == "order_update"
        assert result["platform"] == "TAOBAO"
        assert result["payload"] == {"order_id": "123"}
        assert result["source"] == "order_123"

    def test_default_version(self):
        event = WebhookEvent(event_type="test")
        assert event.version == "1.0"


class TestWebhookSignatureVerifier:
    """Tests for WebhookSignatureVerifier."""

    def test_sign_returns_hex(self):
        verifier = WebhookSignatureVerifier(secret="test_secret")
        signature = verifier.sign(b"test payload")
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex length

    def test_sign_consistent(self):
        verifier = WebhookSignatureVerifier(secret="test_secret")
        sig1 = verifier.sign(b"test payload")
        sig2 = verifier.sign(b"test payload")
        assert sig1 == sig2

    def test_sign_different_secrets(self):
        v1 = WebhookSignatureVerifier(secret="secret1")
        v2 = WebhookSignatureVerifier(secret="secret2")
        sig1 = v1.sign(b"test payload")
        sig2 = v2.sign(b"test payload")
        assert sig1 != sig2

    def test_verify_valid_signature(self):
        verifier = WebhookSignatureVerifier(secret="test_secret")
        payload = b"test payload"
        signature = verifier.sign(payload)
        assert verifier.verify(payload, signature) is True

    def test_verify_invalid_signature(self):
        verifier = WebhookSignatureVerifier(secret="test_secret")
        assert verifier.verify(b"test payload", "invalid_signature") is False

    def test_verify_empty_signature(self):
        verifier = WebhookSignatureVerifier(secret="test_secret")
        assert verifier.verify(b"test payload", "") is False

    def test_verify_tampered_payload(self):
        verifier = WebhookSignatureVerifier(secret="test_secret")
        signature = verifier.sign(b"original payload")
        assert verifier.verify(b"tampered payload", signature) is False

    def test_extract_signature_with_prefix(self):
        result = WebhookSignatureVerifier.extract_signature("sha256=abc123", prefix="sha256=")
        assert result == "abc123"

    def test_extract_signature_without_prefix(self):
        result = WebhookSignatureVerifier.extract_signature("abc123")
        assert result == "abc123"

    def test_extract_signature_wrong_prefix(self):
        result = WebhookSignatureVerifier.extract_signature("md5=abc123", prefix="sha256=")
        assert result == "md5=abc123"


class TestWebhookDeliveryError:
    """Tests for WebhookDeliveryError."""

    def test_basic_creation(self):
        err = WebhookDeliveryError("sub-1", "https://example.com/webhook")
        assert err.subscription_id == "sub-1"
        assert err.url == "https://example.com/webhook"
        assert err.status_code == 0
        assert "https://example.com/webhook" in err.message

    def test_with_status_code(self):
        err = WebhookDeliveryError("sub-1", "https://example.com", status_code=500)
        assert err.status_code == 500

    def test_custom_message(self):
        err = WebhookDeliveryError("sub-1", "https://example.com", message="Custom error")
        assert err.message == "Custom error"

    def test_is_exception(self):
        err = WebhookDeliveryError("sub-1", "https://example.com")
        assert isinstance(err, Exception)


class TestWebhookDeliveryResult:
    """Tests for WebhookDeliveryResult dataclass."""

    def test_success_result(self):
        result = WebhookDeliveryResult(
            subscription_id="sub-1",
            event_id="evt-1",
            success=True,
            status_code=200,
            latency_ms=50.0,
        )
        assert result.success is True
        assert result.status_code == 200
        assert result.latency_ms == 50.0
        assert result.error == ""
        assert result.attempt == 1

    def test_failure_result(self):
        result = WebhookDeliveryResult(
            subscription_id="sub-1",
            event_id="evt-1",
            success=False,
            status_code=500,
            error="Internal server error",
            attempt=3,
        )
        assert result.success is False
        assert result.error == "Internal server error"
        assert result.attempt == 3


class TestWebhookManager:
    """Tests for WebhookManager."""

    def test_init(self):
        manager = WebhookManager()
        assert manager._max_delivery_retries == 3
        assert manager._delivery_timeout == 30.0
        assert manager._max_consecutive_failures == 10

    def test_subscribe_success(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/webhook",
            event_types=["order_update"],
        )
        assert sub.url == "https://example.com/webhook"
        assert sub.event_types == ["order_update"]
        assert sub.is_active is True
        assert sub.subscription_id != ""

    def test_subscribe_empty_url_raises(self):
        manager = WebhookManager()
        with pytest.raises(ValueError, match="URL cannot be empty"):
            manager.subscribe(url="", event_types=["order_update"])

    def test_subscribe_empty_event_types_raises(self):
        manager = WebhookManager()
        with pytest.raises(ValueError, match="event type must be specified"):
            manager.subscribe(url="https://example.com", event_types=[])

    def test_subscribe_invalid_event_type_raises(self):
        manager = WebhookManager()
        with pytest.raises(ValueError, match="Invalid event type"):
            manager.subscribe(url="https://example.com", event_types=["invalid_type"])

    def test_subscribe_with_secret(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/webhook",
            event_types=["order_update"],
            secret="custom_secret",
        )
        assert sub.secret == "custom_secret"

    def test_subscribe_with_platform(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/webhook",
            event_types=["order_update"],
            platform="TAOBAO",
        )
        assert sub.platform == "TAOBAO"

    def test_unsubscribe_success(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/webhook",
            event_types=["order_update"],
        )
        assert manager.unsubscribe(sub.subscription_id) is True
        assert manager.get_subscription(sub.subscription_id) is None

    def test_unsubscribe_not_found(self):
        manager = WebhookManager()
        assert manager.unsubscribe("nonexistent") is False

    def test_get_subscription(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com/webhook",
            event_types=["order_update"],
        )
        retrieved = manager.get_subscription(sub.subscription_id)
        assert retrieved is not None
        assert retrieved.subscription_id == sub.subscription_id

    def test_get_subscription_not_found(self):
        manager = WebhookManager()
        assert manager.get_subscription("nonexistent") is None

    def test_list_subscriptions_all(self):
        manager = WebhookManager()
        manager.subscribe(url="https://a.com", event_types=["order_update"])
        manager.subscribe(url="https://b.com", event_types=["inventory_change"])
        subs = manager.list_subscriptions()
        assert len(subs) == 2

    def test_list_subscriptions_by_event_type(self):
        manager = WebhookManager()
        manager.subscribe(url="https://a.com", event_types=["order_update"])
        manager.subscribe(url="https://b.com", event_types=["inventory_change"])
        subs = manager.list_subscriptions(event_type="order_update")
        assert len(subs) == 1
        assert subs[0].url == "https://a.com"

    def test_list_subscriptions_by_platform(self):
        manager = WebhookManager()
        manager.subscribe(url="https://a.com", event_types=["order_update"], platform="TAOBAO")
        manager.subscribe(url="https://b.com", event_types=["order_update"], platform="JD")
        subs = manager.list_subscriptions(platform="TAOBAO")
        assert len(subs) == 1
        assert subs[0].platform == "TAOBAO"

    def test_list_subscriptions_active_only(self):
        manager = WebhookManager()
        sub = manager.subscribe(url="https://a.com", event_types=["order_update"])
        manager.update_subscription(sub.subscription_id, is_active=False)
        subs = manager.list_subscriptions(active_only=True)
        assert len(subs) == 0
        subs = manager.list_subscriptions(active_only=False)
        assert len(subs) == 1

    def test_update_subscription_success(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://a.com", event_types=["order_update"]
        )
        updated = manager.update_subscription(
            sub.subscription_id,
            url="https://b.com",
            event_types=["inventory_change"],
        )
        assert updated is not None
        assert updated.url == "https://b.com"
        assert updated.event_types == ["inventory_change"]

    def test_update_subscription_not_found(self):
        manager = WebhookManager()
        result = manager.update_subscription("nonexistent", url="https://b.com")
        assert result is None

    def test_update_subscription_is_active(self):
        manager = WebhookManager()
        sub = manager.subscribe(url="https://a.com", event_types=["order_update"])
        manager.update_subscription(sub.subscription_id, is_active=False)
        updated = manager.get_subscription(sub.subscription_id)
        assert updated is not None
        assert updated.is_active is False

    def test_add_delivery_callback(self):
        manager = WebhookManager()
        callback = AsyncMock()
        manager.add_delivery_callback(callback)
        assert len(manager._delivery_callbacks) == 1

    def test_prepare_delivery(self):
        manager = WebhookManager()
        sub = WebhookSubscription(
            subscription_id="sub-1",
            url="https://example.com",
            event_types=["order_update"],
            secret="test_secret",
        )
        event = WebhookEvent(event_id="evt-1", event_type="order_update", payload={"key": "val"})
        payload_bytes, signature = manager._prepare_delivery(sub, event)
        assert isinstance(payload_bytes, bytes)
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex

    def test_verify_signature(self):
        manager = WebhookManager()
        payload = b"test payload"
        verifier = WebhookSignatureVerifier(secret="test_secret")
        signature = verifier.sign(payload)
        assert manager.verify_signature(payload, signature, "test_secret") is True
        assert manager.verify_signature(payload, "wrong", "test_secret") is False

    def test_get_delivery_stats_empty(self):
        manager = WebhookManager()
        stats = manager.get_delivery_stats()
        assert stats["total_deliveries"] == 0
        assert stats["succeeded"] == 0
        assert stats["failed"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["active_subscriptions"] == 0

    def test_clear_history(self):
        manager = WebhookManager()
        manager._event_history.append(WebhookEvent(event_type="test"))
        manager._delivery_results.append(
            WebhookDeliveryResult(subscription_id="s", event_id="e", success=True)
        )
        manager.clear_history()
        assert len(manager._event_history) == 0
        assert len(manager._delivery_results) == 0

    @pytest.mark.asyncio
    async def test_trigger_empty_event_type_raises(self):
        manager = WebhookManager()
        event = WebhookEvent(event_type="")
        with pytest.raises(ValueError, match="Event type cannot be empty"):
            await manager.trigger(event)

    @pytest.mark.asyncio
    async def test_trigger_no_matching_subscriptions(self):
        manager = WebhookManager()
        manager.subscribe(url="https://a.com", event_types=["order_update"])
        event = WebhookEvent(event_type="inventory_change")
        results = await manager.trigger(event)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_trigger_with_callback_success(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com",
            event_types=["order_update"],
        )

        async def success_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=True,
                status_code=200,
                latency_ms=10.0,
            )

        manager.add_delivery_callback(success_callback)
        event = WebhookEvent(event_type="order_update", payload={"order_id": "123"})
        results = await manager.trigger(event)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].status_code == 200

    @pytest.mark.asyncio
    async def test_trigger_with_callback_failure(self):
        manager = WebhookManager(max_delivery_retries=1)
        sub = manager.subscribe(
            url="https://example.com",
            event_types=["order_update"],
        )

        async def failure_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=False,
                status_code=500,
                error="Server error",
            )

        manager.add_delivery_callback(failure_callback)
        event = WebhookEvent(event_type="order_update")
        results = await manager.trigger(event)
        assert len(results) == 1
        assert results[0].success is False

    @pytest.mark.asyncio
    async def test_trigger_updates_last_triggered_at(self):
        manager = WebhookManager()
        sub = manager.subscribe(
            url="https://example.com",
            event_types=["order_update"],
        )

        async def success_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=True,
            )

        manager.add_delivery_callback(success_callback)
        assert sub.last_triggered_at == ""
        await manager.trigger(WebhookEvent(event_type="order_update"))
        assert sub.last_triggered_at != ""

    @pytest.mark.asyncio
    async def test_trigger_records_event_history(self):
        manager = WebhookManager()
        manager.subscribe(url="https://example.com", event_types=["order_update"])

        async def success_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=True,
            )

        manager.add_delivery_callback(success_callback)
        await manager.trigger(WebhookEvent(event_type="order_update"))
        assert len(manager._event_history) == 1

    @pytest.mark.asyncio
    async def test_trigger_multiple_subscriptions(self):
        manager = WebhookManager()
        manager.subscribe(url="https://a.com", event_types=["order_update"])
        manager.subscribe(url="https://b.com", event_types=["order_update"])

        async def success_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=True,
            )

        manager.add_delivery_callback(success_callback)
        results = await manager.trigger(WebhookEvent(event_type="order_update"))
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_trigger_increments_failure_count(self):
        manager = WebhookManager(max_delivery_retries=1)
        sub = manager.subscribe(
            url="https://example.com",
            event_types=["order_update"],
        )

        async def failure_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=False,
                error="Failed",
            )

        manager.add_delivery_callback(failure_callback)
        await manager.trigger(WebhookEvent(event_type="order_update"))
        updated_sub = manager.get_subscription(sub.subscription_id)
        assert updated_sub is not None
        assert updated_sub.failure_count == 1

    @pytest.mark.asyncio
    async def test_trigger_auto_disables_after_max_failures(self):
        manager = WebhookManager(max_delivery_retries=1, max_consecutive_failures=2)
        sub = manager.subscribe(
            url="https://example.com",
            event_types=["order_update"],
        )

        async def failure_callback(subscription, event, payload_bytes, signature):
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=False,
                error="Failed",
            )

        manager.add_delivery_callback(failure_callback)
        # Trigger twice to exceed max_consecutive_failures
        await manager.trigger(WebhookEvent(event_type="order_update"))
        await manager.trigger(WebhookEvent(event_type="order_update"))
        updated_sub = manager.get_subscription(sub.subscription_id)
        assert updated_sub is not None
        assert updated_sub.is_active is False

    @pytest.mark.asyncio
    async def test_trigger_resets_failure_count_on_success(self):
        manager = WebhookManager(max_delivery_retries=1)
        sub = manager.subscribe(
            url="https://example.com",
            event_types=["order_update"],
        )

        call_count = 0

        async def alternating_callback(subscription, event, payload_bytes, signature):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return WebhookDeliveryResult(
                    subscription_id=subscription.subscription_id,
                    event_id=event.event_id,
                    success=False,
                    error="Failed",
                )
            return WebhookDeliveryResult(
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                success=True,
            )

        manager.add_delivery_callback(alternating_callback)
        # First trigger fails
        await manager.trigger(WebhookEvent(event_type="order_update"))
        updated_sub = manager.get_subscription(sub.subscription_id)
        assert updated_sub is not None
        assert updated_sub.failure_count == 1
        # Second trigger succeeds
        await manager.trigger(WebhookEvent(event_type="order_update"))
        updated_sub = manager.get_subscription(sub.subscription_id)
        assert updated_sub is not None
        assert updated_sub.failure_count == 0
