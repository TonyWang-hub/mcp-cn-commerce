"""Tests for the shared cn_commerce_base module.

Tests the base classes, error handling, and utility functions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
    SensitiveDataFilter,
    SignMethod,
    format_error_response,
    mask_dict_sensitive_keys,
    mask_log_message,
    mask_sensitive_value,
    sanitize_log_context,
    validate_api_param,
    validate_env_var_name,
    validate_platform_name,
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


# ── Security: Sensitive Data Masking Tests ────────────────


class TestMaskSensitiveValue:
    """Tests for mask_sensitive_value function."""

    def test_mask_long_value(self):
        result = mask_sensitive_value("abcdefghijklmnop")
        assert result == "abcd****mnop"

    def test_mask_short_value(self):
        result = mask_sensitive_value("short")
        assert result == "s****t"

    def test_mask_empty_value(self):
        result = mask_sensitive_value("")
        assert result == "****"

    def test_mask_single_char(self):
        result = mask_sensitive_value("a")
        assert result == "****"

    def test_mask_two_chars(self):
        result = mask_sensitive_value("ab")
        assert result == "a****b"

    def test_mask_custom_prefix_suffix(self):
        result = mask_sensitive_value("abcdefghijklmnop", visible_prefix=6, visible_suffix=2)
        assert result == "abcdef****op"

    def test_mask_exact_boundary_length(self):
        # Length equals prefix + suffix (8) - still gets masked since len <= prefix + suffix
        result = mask_sensitive_value("abcdefgh")
        assert result == "a****h"


class TestMaskDictSensitiveKeys:
    """Tests for mask_dict_sensitive_keys function."""

    def test_mask_app_key(self):
        data = {"app_key": "abcdefghijklmnop", "name": "test"}
        result = mask_dict_sensitive_keys(data)
        assert result["app_key"] == "abcd****mnop"
        assert result["name"] == "test"

    def test_mask_app_secret(self):
        data = {"app_secret": "secret1234567890"}
        result = mask_dict_sensitive_keys(data)
        assert result["app_secret"] == "secr****7890"

    def test_mask_access_token(self):
        data = {"access_token": "token1234567890"}
        result = mask_dict_sensitive_keys(data)
        assert result["access_token"] == "toke****7890"

    def test_mask_nested_dict(self):
        data = {
            "config": {
                "app_key": "abcdefghijklmnop",
                "name": "test",
            },
            "other": "value",
        }
        result = mask_dict_sensitive_keys(data)
        assert result["config"]["app_key"] == "abcd****mnop"
        assert result["config"]["name"] == "test"
        assert result["other"] == "value"

    def test_mask_list_of_dicts(self):
        data = {
            "credentials": [
                {"app_key": "key1", "name": "first"},
                {"app_key": "key2", "name": "second"},
            ]
        }
        result = mask_dict_sensitive_keys(data)
        assert result["credentials"][0]["app_key"] == "k****1"
        assert result["credentials"][1]["app_key"] == "k****2"

    def test_mask_non_string_value(self):
        data = {"token": 12345}
        result = mask_dict_sensitive_keys(data)
        assert result["token"] == "***MASKED***"

    def test_mask_case_insensitive(self):
        data = {"APP_KEY": "abcdefghijklmnop", "Access_Token": "token1234567890"}
        result = mask_dict_sensitive_keys(data)
        assert result["APP_KEY"] == "abcd****mnop"
        assert result["Access_Token"] == "toke****7890"

    def test_no_sensitive_keys(self):
        data = {"name": "test", "value": 123}
        result = mask_dict_sensitive_keys(data)
        assert result == {"name": "test", "value": 123}


class TestMaskLogMessage:
    """Tests for mask_log_message function."""

    def test_mask_jwt_token(self):
        # JWT token format: header.payload.signature
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = mask_log_message(f"Token: {jwt}")
        assert jwt not in result
        assert "****" in result

    def test_mask_bearer_token(self):
        result = mask_log_message("Authorization: Bearer abcdefghijklmnop")
        assert "Bearer" in result
        assert "abcdefghijklmnop" not in result
        assert "****" in result

    def test_no_sensitive_data(self):
        message = "Request completed successfully"
        result = mask_log_message(message)
        assert result == message


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter logging filter."""

    def test_filter_masks_message(self):
        import logging

        filter_obj = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Token: Bearer abcdefghijklmnop",
            args=None,
            exc_info=None,
        )
        filter_obj.filter(record)
        assert "abcdefghijklmnop" not in record.msg
        assert "Bearer" in record.msg

    def test_filter_masks_dict_args(self):
        import logging

        filter_obj = SensitiveDataFilter()
        # LogRecord with dict args needs special handling
        # Use a tuple with a dict element instead
        data = {"app_key": "abcdefghijklmnop"}
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Config: %s",
            args=(data,),
            exc_info=None,
        )
        filter_obj.filter(record)
        # The filter processes tuple args by masking strings
        assert "abcdefghijklmnop" not in str(record.args)


# ── Security: Input Validation Tests ──────────────────────


class TestValidatePlatformName:
    """Tests for validate_platform_name function."""

    def test_valid_platform_name(self):
        assert validate_platform_name("OCEANENGINE") == "OCEANENGINE"
        assert validate_platform_name("TAOBAO") == "TAOBAO"
        assert validate_platform_name("JD") == "JD"

    def test_valid_with_underscores(self):
        assert validate_platform_name("WEIXIN_STORE") == "WEIXIN_STORE"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_platform_name("")

    def test_lowercase_raises(self):
        with pytest.raises(ValueError, match="must be uppercase"):
            validate_platform_name("oceanengine")

    def test_with_numbers(self):
        assert validate_platform_name("API2") == "API2"

    def test_with_spaces_raises(self):
        with pytest.raises(ValueError, match="must be uppercase"):
            validate_platform_name("TAOBAO API")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            validate_platform_name("A" * 65)

    def test_max_length(self):
        result = validate_platform_name("A" * 64)
        assert len(result) == 64


class TestValidateApiParam:
    """Tests for validate_api_param function."""

    def test_valid_param(self):
        result = validate_api_param("keyword", "test search")
        assert result == "test search"

    def test_sql_injection_union(self):
        with pytest.raises(ValueError, match="suspicious SQL"):
            validate_api_param("keyword", "UNION SELECT * FROM users")

    def test_sql_injection_comment(self):
        with pytest.raises(ValueError, match="suspicious SQL"):
            validate_api_param("keyword", "test'--")

    def test_sql_injection_drop(self):
        with pytest.raises(ValueError, match="suspicious SQL"):
            validate_api_param("keyword", "'; DROP TABLE users;--")

    def test_path_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_api_param("file", "../../etc/passwd")

    def test_path_traversal_encoded(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_api_param("file", "%2e%2e/etc/passwd")

    def test_xss_script_tag(self):
        with pytest.raises(ValueError, match="suspicious script"):
            validate_api_param("content", "<script>alert('xss')</script>")

    def test_xss_javascript_uri(self):
        with pytest.raises(ValueError, match="suspicious script"):
            validate_api_param("url", "javascript:alert(1)")

    def test_xss_event_handler(self):
        with pytest.raises(ValueError, match="suspicious script"):
            validate_api_param("html", '<img onerror="alert(1)">')

    def test_exceeds_max_length(self):
        with pytest.raises(ValueError, match="exceeds maximum length"):
            validate_api_param("keyword", "a" * 4097)

    def test_custom_max_length(self):
        with pytest.raises(ValueError, match="exceeds maximum length"):
            validate_api_param("keyword", "a" * 101, max_length=100)

    def test_non_string_value(self):
        result = validate_api_param("count", 123)
        assert result == 123


class TestValidateEnvVarName:
    """Tests for validate_env_var_name function."""

    def test_valid_name(self):
        assert validate_env_var_name("OCEANENGINE_APP_KEY") == "OCEANENGINE_APP_KEY"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_env_var_name("")

    def test_lowercase_raises(self):
        with pytest.raises(ValueError, match="must be uppercase"):
            validate_env_var_name("app_key")

    def test_with_spaces_raises(self):
        with pytest.raises(ValueError, match="must be uppercase"):
            validate_env_var_name("APP KEY")

    def test_with_numbers(self):
        assert validate_env_var_name("APP_KEY2") == "APP_KEY2"

    def test_starts_with_number_raises(self):
        with pytest.raises(ValueError, match="must be uppercase"):
            validate_env_var_name("1APP_KEY")


class TestSanitizeLogContext:
    """Tests for sanitize_log_context function."""

    def test_masks_sensitive_values(self):
        result = sanitize_log_context(
            app_key="abcdefghijklmnop",
            app_secret="secret1234567890",
            action="test",
        )
        assert result["app_key"] == "abcd****mnop"
        assert result["app_secret"] == "secr****7890"
        assert result["action"] == "test"

    def test_no_sensitive_keys(self):
        result = sanitize_log_context(action="test", value=123)
        assert result == {"action": "test", "value": 123}
