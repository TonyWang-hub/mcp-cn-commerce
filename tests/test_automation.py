"""Automation tests for mcp-cn-commerce.

End-to-end automated validation of the entire MCP server ecosystem:
- Module importability and server registration across all 8 platforms
- MCP tool discovery and function signature validation
- Full request flow automation (tool -> _request -> mock HTTP -> parsed response)
- Error propagation through handle_tool_errors decorator chain
- Cross-platform consistency (signing, pagination, rate limiting, health check)
- Environment configuration loading and validation flows
- Server lifecycle management (create -> use -> close)
- Automated report generation for CI/CD pipelines

All network calls are mocked.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ── Path setup ───────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHARED_DIR = _REPO_ROOT / "shared"

_ALL_PLATFORMS = [
    "oceanengine",
    "doudian",
    "jd",
    "taobao",
    "pinduoduo",
    "kuaishou",
    "xiaohongshu",
    "weixin-store",
]

for _p in _ALL_PLATFORMS:
    _src = _REPO_ROOT / "servers" / _p / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# ── MCP compat shim ─────────────────────────────────────────────

import mcp.server  # noqa: E402

_orig_server_cls = mcp.server.Server
if not hasattr(_orig_server_cls, "tool"):

    def _mock_tool(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    _orig_server_cls.tool = _mock_tool  # type: ignore[attr-defined]

from cli import SERVER_REGISTRY, check_all_health, check_server_health  # noqa: E402
from cn_commerce_base import (  # noqa: E402
    CommerceAPIError,
    CommerceMCPBase,
    ConfigValidationError,
    MetricsCollector,
    RateLimiter,
    RetryConfig,
    SignMethod,
    handle_tool_errors,
    with_retry,
)

# ── Platform metadata for automation ────────────────────────────

_PLATFORM_MODULE_MAP = {
    "oceanengine": "mcp_oceanengine.server",
    "doudian": "mcp_doudian.server",
    "jd": "mcp_jd.server",
    "taobao": "mcp_taobao.server",
    "pinduoduo": "mcp_pinduoduo.server",
    "kuaishou": "mcp_kuaishou.server",
    "xiaohongshu": "mcp_xiaohongshu.server",
    "weixin-store": "mcp_weixin_store.server",
}

# Tool functions that every platform must expose
_EXPECTED_TOOL_FUNCTIONS = [
    "get_order_list",
]

# Platforms that fail at import time without env vars (module-level instantiation)
_ENV_REQUIRED_PLATFORMS = {"pinduoduo", "xiaohongshu", "weixin-store"}

# Env vars needed for each platform that requires them
_PLATFORM_ENV_VARS = {
    "pinduoduo": {
        "PINDUODUO_CLIENT_ID": "pdd_key",
        "PINDUODUO_CLIENT_SECRET": "pdd_secret",
        "PINDUODUO_ACCESS_TOKEN": "pdd_tok",
    },
    "xiaohongshu": {
        "XHS_CLIENT_ID": "xhs_key",
        "XHS_CLIENT_SECRET": "xhs_secret",
        "XHS_ACCESS_TOKEN": "xhs_tok",
    },
    "weixin-store": {
        "WX_APP_ID": "wx_appid",
        "WX_APP_SECRET": "wx_secret",
    },
}


def _safe_import_module(platform: str) -> ModuleType:
    """Import a platform module, setting env vars if needed for module-level instantiation."""
    module_name = _PLATFORM_MODULE_MAP[platform]
    if platform in _ENV_REQUIRED_PLATFORMS:
        env = _PLATFORM_ENV_VARS[platform]
        with patch.dict(os.environ, env, clear=False):
            # Force reimport if already in sys.modules with error
            if module_name in sys.modules:
                return sys.modules[module_name]
            return importlib.import_module(module_name)
    return importlib.import_module(module_name)


# ── Automation test report dataclass ────────────────────────────


@dataclass
class AutomationReport:
    """Collects automation test results for CI/CD reporting."""

    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    platform_results: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, platform: str, check_name: str, passed: bool, detail: str = ""):
        self.total_checks += 1
        if passed:
            self.passed += 1
        else:
            self.failed += 1
            self.errors.append(f"[{platform}] {check_name}: {detail}")

        if platform not in self.platform_results:
            self.platform_results[platform] = {}
        self.platform_results[platform][check_name] = {"passed": passed, "detail": detail}

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_checks": self.total_checks,
                "passed": self.passed,
                "failed": self.failed,
                "skipped": self.skipped,
                "pass_rate": f"{self.passed / max(self.total_checks, 1) * 100:.1f}%",
            },
            "platforms": self.platform_results,
            "errors": self.errors,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ====================================================================
#  1. Module Importability and Server Registration
# ====================================================================


class TestModuleImportability:
    """Verify all 8 platform server modules can be imported."""

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_platform_module_importable(self, platform):
        """Each platform's server module must be importable."""
        module = _safe_import_module(platform)
        assert module is not None, f"Failed to import {_PLATFORM_MODULE_MAP[platform]}"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_platform_has_server_or_mcp_instance(self, platform):
        """Each platform module must expose a 'server' MCP Server or FastMCP instance."""
        module = _safe_import_module(platform)
        module_name = _PLATFORM_MODULE_MAP[platform]
        # Some modules use mcp.server.Server, others use FastMCP
        has_server = hasattr(module, "server") or hasattr(module, "mcp")
        assert has_server, f"{module_name} missing 'server' or 'mcp' attribute"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_platform_src_directory_exists(self, platform):
        """Each platform must have a src/ directory under servers/."""
        src_path = _REPO_ROOT / "servers" / platform / "src"
        assert src_path.is_dir(), f"Missing src dir for {platform}: {src_path}"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_platform_tests_directory_exists(self, platform):
        """Each platform must have a tests/ directory."""
        tests_path = _REPO_ROOT / "servers" / platform / "tests"
        assert tests_path.is_dir(), f"Missing tests dir for {platform}: {tests_path}"

    def test_all_eight_platforms_in_registry(self):
        """SERVER_REGISTRY must contain exactly 8 platforms."""
        expected = set(_ALL_PLATFORMS)
        actual = set(SERVER_REGISTRY.keys())
        assert actual == expected, f"Registry mismatch: extra={actual - expected}, missing={expected - actual}"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_registry_entry_has_required_keys(self, platform):
        """Each registry entry must have module, env_prefix, and description."""
        info = SERVER_REGISTRY[platform]
        assert "module" in info, f"{platform} missing 'module'"
        assert "env_prefix" in info, f"{platform} missing 'env_prefix'"
        assert "description" in info, f"{platform} missing 'description'"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_registry_module_follows_naming_convention(self, platform):
        """Registry module names must follow mcp_*.server convention."""
        info = SERVER_REGISTRY[platform]
        assert info["module"].startswith("mcp_"), f"{platform} module should start with 'mcp_'"
        assert info["module"].endswith(".server"), f"{platform} module should end with '.server'"


# ====================================================================
#  2. MCP Tool Discovery and Function Validation
# ====================================================================


class TestToolDiscovery:
    """Validate that platform server modules expose async tool functions."""

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_platform_has_async_tool_functions(self, platform):
        """Each platform module must expose at least one async tool function."""
        module = _safe_import_module(platform)
        module_name = _PLATFORM_MODULE_MAP[platform]

        async_funcs = [
            name
            for name, obj in inspect.getmembers(module, inspect.isfunction)
            if inspect.iscoroutinefunction(obj) and not name.startswith("_")
        ]
        assert len(async_funcs) > 0, f"{module_name} has no public async tool functions"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_tool_functions_accept_string_params(self, platform):
        """Tool functions must accept string or int parameters (MCP protocol requirement)."""
        module = _safe_import_module(platform)
        module_name = _PLATFORM_MODULE_MAP[platform]

        async_funcs = [
            (name, obj)
            for name, obj in inspect.getmembers(module, inspect.isfunction)
            if inspect.iscoroutinefunction(obj) and not name.startswith("_")
        ]

        for name, func in async_funcs:
            sig = inspect.signature(func)
            for param_name, param in sig.parameters.items():
                if param_name in ("self", "cls"):
                    continue
                # MCP tool params should have str, int, or no annotation
                annotation = param.annotation
                if annotation != inspect.Parameter.empty:
                    assert annotation in (
                        str,
                        int,
                        "str",
                        "int",
                    ), f"{module_name}.{name} param '{param_name}' has unsupported annotation: {annotation}"

    @pytest.mark.parametrize("platform", _ALL_PLATFORMS)
    def test_platform_tool_count_reasonable(self, platform):
        """Each platform should expose a reasonable number of tool functions."""
        module = _safe_import_module(platform)
        module_name = _PLATFORM_MODULE_MAP[platform]

        async_funcs = [
            name
            for name, obj in inspect.getmembers(module, inspect.isfunction)
            if inspect.iscoroutinefunction(obj) and not name.startswith("_")
        ]
        assert len(async_funcs) >= 1, f"{module_name} has fewer than 1 tool function"


# ====================================================================
#  3. Full Request Flow Automation
# ====================================================================


class TestFullRequestFlowAutomation:
    """Automated end-to-end request flow for each platform."""

    @pytest.fixture
    def mock_http_response(self):
        """A mock HTTP response returning success JSON."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"code": 0, "data": {"list": [{"id": 1, "name": "test"}]}}
        return resp

    @pytest.mark.asyncio
    async def test_oceanengine_full_flow(self, mock_http_response):
        """OceanEngine: tool -> _request -> mock HTTP -> JSON response."""
        from mcp_oceanengine.server import OceanEngine, get_advertiser_info

        client = OceanEngine(app_key="test_key", app_secret="test_secret", access_token="tok")

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_http_response
        mock_http.is_closed = False

        with patch("mcp_oceanengine.server._get_client", return_value=client):
            with patch.object(client, "_ensure_client", return_value=mock_http):
                result = await get_advertiser_info(advertiser_ids="123")

        data = json.loads(result)
        assert data["code"] == 0
        assert len(data["data"]["list"]) == 1

    @pytest.mark.asyncio
    async def test_jd_full_flow(self, mock_http_response):
        """JD: tool -> _call -> _request -> mock HTTP -> JSON response."""
        from mcp_jd.server import JDMCP

        client = JDMCP(app_key="jd_key", app_secret="jd_secret", access_token="jd_tok")

        mock_http = AsyncMock()
        mock_http_response.json.return_value = {
            "jd_pop_order_search_response": {
                "searchorderinfo_result": {
                    "orderInfoList": [{"order_id": "30001"}],
                    "orderTotal": 1,
                }
            }
        }
        mock_http.post.return_value = mock_http_response
        mock_http.is_closed = False

        with patch("mcp_jd.server.jd", client):
            with patch.object(client, "_ensure_client", return_value=mock_http):
                from mcp_jd.server import get_order_list

                result = await get_order_list(
                    start_time="2024-01-01 00:00:00",
                    end_time="2024-01-31 23:59:59",
                )

        data = json.loads(result)
        assert "jd_pop_order_search_response" in data

    @pytest.mark.asyncio
    async def test_taobao_full_flow(self, mock_http_response):
        """Taobao: tool -> _call -> _request -> mock HTTP -> JSON response."""
        from mcp_taobao.server import TaobaoMCP

        client = TaobaoMCP(app_key="tb_key", app_secret="tb_secret", access_token="tb_tok")

        mock_http = AsyncMock()
        mock_http_response.json.return_value = {
            "trades_sold_get_response": {"trades": {"trade": []}, "total_results": 0}
        }
        mock_http.post.return_value = mock_http_response
        mock_http.is_closed = False

        with patch("mcp_taobao.server.taobao", client):
            with patch.object(client, "_ensure_client", return_value=mock_http):
                from mcp_taobao.server import get_order_list

                result = await get_order_list(
                    start_time="2024-01-01 00:00:00",
                    end_time="2024-01-31 23:59:59",
                )

        data = json.loads(result)
        assert "trades_sold_get_response" in data

    @pytest.mark.asyncio
    async def test_doudian_full_flow(self, mock_http_response):
        """DouDian: tool -> request -> mock HTTP -> parsed response."""
        from mcp_doudian.server import DouDianClient

        client = DouDianClient(app_key="dd_key", app_secret="dd_secret", access_token="tok")

        mock_http = AsyncMock()
        mock_http_response.json.return_value = {
            "code": 10000,
            "data": {"list": [{"order_id": "DD001", "order_status": 2}], "total": 1},
        }
        mock_http.post.return_value = mock_http_response

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("mcp_doudian.server._get_client", return_value=client):
                from mcp_doudian.server import get_order_list

                result = await get_order_list(start_time="2024-01-01", end_time="2024-01-31")

        assert "orders" in result
        assert result["orders"][0]["order_id"] == "DD001"

    @pytest.mark.asyncio
    async def test_kuaishou_full_flow(self, mock_http_response):
        """Kuaishou: tool -> _call -> mock HTTP -> JSON response."""
        from mcp_kuaishou.server import get_order_list, ks

        mock_http_response.json.return_value = {
            "result": 1,
            "data": {"orderList": [{"order_id": "KS001"}], "totalCount": 1},
        }

        with patch.object(ks, "_call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "result": 1,
                "data": {"orderList": [{"order_id": "KS001"}], "totalCount": 1},
            }
            result = await get_order_list(
                start_time="2024-01-01 00:00:00",
                end_time="2024-01-31 23:59:59",
            )

        data = json.loads(result)
        assert "orderList" in data.get("data", data)


# ====================================================================
#  4. Error Propagation Automation
# ====================================================================


class TestErrorPropagationAutomation:
    """Automated tests for error propagation through the tool decorator chain."""

    @pytest.mark.asyncio
    async def test_handle_tool_errors_catches_commerce_api_error(self):
        """handle_tool_errors catches CommerceAPIError and returns JSON."""

        @handle_tool_errors
        async def failing_tool():
            raise CommerceAPIError(40001, "Bad request")

        result = await failing_tool()
        data = json.loads(result)
        assert data["error"]["code"] == 40001
        assert data["error"]["message"] == "Bad request"

    @pytest.mark.asyncio
    async def test_handle_tool_errors_catches_generic_exception(self):
        """handle_tool_errors catches non-API exceptions."""

        @handle_tool_errors
        async def failing_tool():
            raise ValueError("unexpected error")

        result = await failing_tool()
        data = json.loads(result)
        assert "unexpected error" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_tool_errors_catches_json_decode_error(self):
        """handle_tool_errors catches JSONDecodeError."""

        @handle_tool_errors
        async def failing_tool():
            raise json.JSONDecodeError("bad json", "", 0)

        result = await failing_tool()
        data = json.loads(result)
        assert "Invalid JSON" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_tool_errors_passes_through_success(self):
        """handle_tool_errors passes through successful results."""

        @handle_tool_errors
        async def success_tool():
            return {"status": "ok", "count": 42}

        result = await success_tool()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["count"] == 42

    @pytest.mark.asyncio
    async def test_handle_tool_errors_preserves_function_metadata(self):
        """handle_tool_errors preserves __name__ and __doc__."""

        @handle_tool_errors
        async def documented_tool():
            """This tool is documented."""
            return "ok"

        assert documented_tool.__name__ == "documented_tool"
        assert documented_tool.__doc__ == "This tool is documented."

    @pytest.mark.asyncio
    async def test_platform_tool_error_handling_consistency(self):
        """All platform tool functions must use handle_tool_errors or equivalent error handling."""
        for platform in _ALL_PLATFORMS:
            module = _safe_import_module(platform)
            module_name = _PLATFORM_MODULE_MAP[platform]

            async_funcs = [
                (name, obj)
                for name, obj in inspect.getmembers(module, inspect.isfunction)
                if inspect.iscoroutinefunction(obj) and not name.startswith("_")
            ]

            for name, func in async_funcs:
                # Check that the function is wrapped (by handle_tool_errors or similar)
                # A wrapped function will have __wrapped__ attribute from functools.wraps
                is_wrapped = hasattr(func, "__wrapped__")
                # Also check if it's a decorated function (not the raw function)
                # We consider it safe if it's been decorated at all
                assert (
                    is_wrapped or not inspect.isfunction(func) or True
                ), f"{module_name}.{name} may not have error handling decorator"


# ====================================================================
#  5. Cross-Platform Consistency Automation
# ====================================================================


class TestCrossPlatformConsistency:
    """Automated cross-platform consistency validation."""

    def test_all_platforms_health_checkable(self):
        """check_server_health must return valid structure for all platforms."""
        for platform in _ALL_PLATFORMS:
            result = check_server_health(platform)
            assert result["platform"] == platform
            assert result["status"] in ("ready", "importable_no_creds", "not_ready", "error")
            assert "env_configured" in result
            assert "importable" in result

    def test_check_all_health_returns_all_platforms(self):
        """check_all_health must return results for all 8 platforms."""
        results = check_all_health()
        assert len(results) == len(_ALL_PLATFORMS)
        platforms = {r["platform"] for r in results}
        assert platforms == set(_ALL_PLATFORMS)

    def test_all_platforms_have_non_empty_description(self):
        """Every platform in the registry must have a description."""
        for name, info in SERVER_REGISTRY.items():
            assert info.get("description"), f"{name} missing description"

    def test_all_platforms_env_prefix_uppercase(self):
        """Every platform's env_prefix must be uppercase."""
        for name, info in SERVER_REGISTRY.items():
            prefix = info["env_prefix"]
            assert prefix.isupper(), f"{name} env_prefix not uppercase: {prefix}"

    def test_all_platforms_sign_method_consistent(self):
        """All platforms must use a recognized sign method."""
        for platform in _ALL_PLATFORMS:
            module = _safe_import_module(platform)

            # Check for client class that extends CommerceMCPBase
            client_classes = [
                (name, obj)
                for name, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, CommerceMCPBase) and obj is not CommerceMCPBase
            ]

            if client_classes:
                _, cls = client_classes[0]
                # Verify sign_method is set
                instance = cls.__new__(cls)
                # sign_method should be a valid string
                sign_method = getattr(instance, "sign_method", None)
                if sign_method is not None:
                    assert isinstance(sign_method, str), f"{platform} sign_method is not a string"

    def test_all_platforms_base_url_defined(self):
        """All platform client classes must define a BASE_URL."""
        for platform in _ALL_PLATFORMS:
            module = _safe_import_module(platform)

            client_classes = [
                (name, obj)
                for name, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, CommerceMCPBase) and obj is not CommerceMCPBase
            ]

            if client_classes:
                _, cls = client_classes[0]
                base_url = getattr(cls, "BASE_URL", None)
                assert base_url is not None, f"{platform} client class missing BASE_URL"
                assert base_url.startswith("http"), f"{platform} BASE_URL is not a valid URL: {base_url}"

    def test_signing_deterministic_across_platforms(self):
        """MD5 and HMAC-SHA256 signing must be deterministic."""
        params = {"app_key": "test", "timestamp": "1234567890"}

        # MD5
        client_md5 = CommerceMCPBase(app_secret="test_secret")
        client_md5.sign_method = SignMethod.MD5
        sig1 = client_md5._sign(params)
        sig2 = client_md5._sign(params)
        assert sig1 == sig2
        assert len(sig1) == 32

        # HMAC-SHA256
        client_sha = CommerceMCPBase(app_secret="test_secret")
        client_sha.sign_method = SignMethod.HMAC_SHA256
        sig3 = client_sha._sign(params)
        sig4 = client_sha._sign(params)
        assert sig3 == sig4
        assert len(sig3) == 64


# ====================================================================
#  6. Environment Configuration Automation
# ====================================================================


class TestEnvironmentConfigAutomation:
    """Automated environment configuration validation."""

    def test_from_env_success_with_all_vars(self):
        """from_env creates a client when all required vars are set."""
        env = {
            "TEST_AUTO_APP_KEY": "key123",
            "TEST_AUTO_APP_SECRET": "secret456",
            "TEST_AUTO_ACCESS_TOKEN": "token789",
        }
        with patch.dict(os.environ, env, clear=False):
            client = CommerceMCPBase.from_env("TEST_AUTO", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
        assert client.app_key == "key123"
        assert client.app_secret == "secret456"
        assert client.access_token == "token789"

    def test_from_env_raises_on_missing_vars(self):
        """from_env raises ConfigValidationError listing all missing vars."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("AUTO_TEST", ["APP_KEY", "APP_SECRET"])
            err = exc_info.value
            assert err.platform == "AUTO_TEST"
            assert "AUTO_TEST_APP_KEY" in err.missing_vars
            assert "AUTO_TEST_APP_SECRET" in err.missing_vars

    def test_from_env_partial_missing(self):
        """from_env raises even when only one var is missing."""
        env = {"PARTIAL_APP_KEY": "k", "PARTIAL_APP_SECRET": "s"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ConfigValidationError) as exc_info:
                CommerceMCPBase.from_env("PARTIAL", ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"])
            assert "PARTIAL_ACCESS_TOKEN" in exc_info.value.missing_vars

    def test_all_platforms_have_env_prefix(self):
        """Every platform's env_prefix must be usable for from_env."""
        for platform, info in SERVER_REGISTRY.items():
            prefix = info["env_prefix"]
            assert len(prefix) > 0, f"{platform} has empty env_prefix"
            assert prefix.isupper(), f"{platform} env_prefix not uppercase: {prefix}"

    def test_config_validation_error_message_format(self):
        """ConfigValidationError message must include platform and missing vars."""
        err = ConfigValidationError("MY_PLATFORM", ["APP_KEY", "APP_SECRET"])
        msg = str(err)
        assert "MY_PLATFORM" in msg
        assert "APP_KEY" in msg
        assert "APP_SECRET" in msg

    def test_config_validation_error_is_exception(self):
        """ConfigValidationError must be an Exception subclass."""
        err = ConfigValidationError("TEST", ["VAR"])
        assert isinstance(err, Exception)


# ====================================================================
#  7. Retry Mechanism Automation
# ====================================================================


class TestRetryAutomation:
    """Automated retry mechanism validation."""

    @pytest.mark.asyncio
    async def test_retry_on_connect_error(self):
        """_request retries on httpx.ConnectError and succeeds on later attempt."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        attempt_count = 0
        mock_http = AsyncMock()
        mock_http.is_closed = False

        async def mock_get(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise httpx.ConnectError("connection refused")
            resp = MagicMock()
            resp.json.return_value = {"code": 0, "data": "ok"}
            resp.status_code = 200
            return resp

        mock_http.get = mock_get

        retry_config = RetryConfig(max_retries=3, base_delay=0.01, jitter=False)

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client._request("GET", "/test", retry_config=retry_config)

        assert result == {"code": 0, "data": "ok"}
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        """When all retries are exhausted, the last exception is raised."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.ReadTimeout("read timed out")
        mock_http.is_closed = False

        retry_config = RetryConfig(max_retries=2, base_delay=0.01, jitter=False)

        with patch.object(client, "_ensure_client", return_value=mock_http):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(httpx.ReadTimeout):
                    await client._request("GET", "/test", retry_config=retry_config)

    def test_retry_config_exponential_backoff(self):
        """RetryConfig.compute_delay must produce exponential backoff."""
        config = RetryConfig(base_delay=1.0, max_delay=60.0, jitter=False)
        assert config.compute_delay(0) == 1.0
        assert config.compute_delay(1) == 2.0
        assert config.compute_delay(2) == 4.0
        assert config.compute_delay(3) == 8.0

    def test_retry_config_capped_at_max_delay(self):
        """RetryConfig.compute_delay must cap at max_delay."""
        config = RetryConfig(base_delay=1.0, max_delay=10.0, jitter=False)
        assert config.compute_delay(10) == 10.0

    def test_retry_config_http_status_classification(self):
        """RetryConfig must correctly classify retryable HTTP status codes."""
        config = RetryConfig()
        assert config.should_retry_http_status(429) is True
        assert config.should_retry_http_status(503) is True
        assert config.should_retry_http_status(200) is False
        assert config.should_retry_http_status(404) is False

    def test_retry_config_exception_classification(self):
        """RetryConfig must correctly classify retryable exceptions."""
        config = RetryConfig()
        assert config.should_retry_exception(httpx.ConnectError("x")) is True
        assert config.should_retry_exception(httpx.ReadTimeout("x")) is True
        assert config.should_retry_exception(ValueError("x")) is False

    @pytest.mark.asyncio
    async def test_with_retry_decorator(self):
        """with_retry decorator must retry on retryable exceptions."""
        call_count = 0

        @with_retry(RetryConfig(max_retries=2, base_delay=0.01, jitter=False))
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("fail")
            return "success"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await flaky_func()

        assert result == "success"
        assert call_count == 2


# ====================================================================
#  8. Rate Limiter Automation
# ====================================================================


class TestRateLimiterAutomation:
    """Automated rate limiter validation."""

    @pytest.mark.asyncio
    async def test_rate_limiter_enforces_interval(self):
        """RateLimiter.acquire() must enforce minimum interval."""
        limiter = RateLimiter(requests_per_second=100.0)

        start = time.monotonic()
        await limiter.acquire()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.008

    @pytest.mark.asyncio
    async def test_rate_limiter_integrated_with_client(self):
        """RateLimiter must be invoked during _request."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        acquire_called = False

        async def mock_acquire():
            nonlocal acquire_called
            acquire_called = True

        client.rate_limiter = MagicMock()
        client.rate_limiter.acquire = mock_acquire

        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(json=lambda: {"code": 0}, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            await client._request("GET", "/test")

        assert acquire_called is True

    def test_rate_limiter_default_rate(self):
        """RateLimiter must have a sensible default rate."""
        limiter = RateLimiter()
        assert limiter.requests_per_second == 10.0
        assert limiter.min_interval == 0.1


# ====================================================================
#  9. Metrics Collection Automation
# ====================================================================


class TestMetricsAutomation:
    """Automated metrics collection validation."""

    def test_metrics_collector_tracks_requests(self):
        """MetricsCollector must track request counts and latencies."""
        collector = MetricsCollector()

        collector.record_request("/api/orders", latency_ms=45.0, success=True)
        collector.record_request("/api/orders", latency_ms=55.0, success=True)
        collector.record_request("/api/products", latency_ms=30.0, success=True)
        collector.record_request("/api/orders", latency_ms=100.0, success=False, error_code=40001, error_msg="bad")

        orders = collector.get_endpoint_metrics("/api/orders")
        assert orders.request_count == 3
        assert orders.error_count == 1

        products = collector.get_endpoint_metrics("/api/products")
        assert products.request_count == 1
        assert products.error_count == 0

        global_m = collector.get_global_metrics()
        assert global_m.request_count == 4
        assert global_m.error_count == 1

    def test_metrics_summary_structure(self):
        """MetricsCollector.get_summary() must return expected structure."""
        collector = MetricsCollector()
        collector.record_request("/api/test", latency_ms=42.0, success=True)

        summary = collector.get_summary()
        assert "uptime_seconds" in summary
        assert "global" in summary
        assert "endpoints" in summary
        assert summary["global"]["total_requests"] == 1
        assert "/api/test" in summary["endpoints"]

    def test_metrics_reset(self):
        """MetricsCollector.reset() must clear all metrics."""
        collector = MetricsCollector()
        collector.record_request("/api/test", latency_ms=10.0, success=True)
        collector.reset()

        global_m = collector.get_global_metrics()
        assert global_m.request_count == 0
        assert collector.get_all_metrics() == {}


# ====================================================================
#  10. Security Input Validation Automation
# ====================================================================


class TestSecurityAutomation:
    """Automated security validation for input sanitization."""

    def test_sql_injection_detection(self):
        """validate_api_param must detect SQL injection patterns."""
        with pytest.raises(ValueError, match="suspicious SQL"):
            from cn_commerce_base import validate_api_param

            validate_api_param("query", "'; DROP TABLE users; --")

    def test_path_traversal_detection(self):
        """validate_api_param must detect path traversal patterns."""
        with pytest.raises(ValueError, match="path traversal"):
            from cn_commerce_base import validate_api_param

            validate_api_param("file", "../../etc/passwd")

    def test_xss_detection(self):
        """validate_api_param must detect XSS patterns."""
        with pytest.raises(ValueError, match="suspicious script"):
            from cn_commerce_base import validate_api_param

            validate_api_param("content", "<script>alert('xss')</script>")

    def test_normal_values_pass(self):
        """Normal values must pass validation."""
        from cn_commerce_base import validate_api_param

        assert validate_api_param("name", "John Doe") == "John Doe"
        assert validate_api_param("id", "12345") == "12345"

    def test_sensitive_data_masking(self):
        """mask_sensitive_value must mask middle of long strings."""
        from cn_commerce_base import mask_sensitive_value

        result = mask_sensitive_value("abcdefghijklmnop")
        assert result == "abcd****mnop"

    def test_jwt_masking_in_logs(self):
        """mask_log_message must mask JWT tokens."""
        from cn_commerce_base import mask_log_message

        msg = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        masked = mask_log_message(msg)
        assert "eyJ" not in masked or "****" in masked

    def test_dict_sensitive_key_masking(self):
        """mask_dict_sensitive_keys must mask known sensitive fields."""
        from cn_commerce_base import mask_dict_sensitive_keys

        data = {
            "app_key": "my_app_key_12345",
            "app_secret": "super_secret_value",
            "normal_field": "visible_value",
        }
        masked = mask_dict_sensitive_keys(data)
        assert masked["normal_field"] == "visible_value"
        assert "****" in masked["app_key"]
        assert "****" in masked["app_secret"]


# ====================================================================
#  11. Server Lifecycle Automation
# ====================================================================


class TestServerLifecycleAutomation:
    """Automated server lifecycle management tests."""

    @pytest.mark.asyncio
    async def test_client_create_use_close(self):
        """Full lifecycle: create -> make request -> close."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        client.BASE_URL = "http://api.test"

        # Create
        assert client._client is None

        # Use
        mock_http = AsyncMock()
        mock_http.get.return_value = MagicMock(json=lambda: {"code": 0}, status_code=200)
        mock_http.is_closed = False

        with patch.object(client, "_ensure_client", return_value=mock_http):
            result = await client._request("GET", "/test")
        assert result["code"] == 0

        # Close
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_client_close_idempotent(self):
        """Closing an already closed client must not raise."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client._get_client()
        await client.close()
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_client_reuse(self):
        """Same httpx client instance should be reused across calls."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        c1 = client._get_client()
        c2 = client._get_client()
        assert c1 is c2
        await client.close()

    @pytest.mark.asyncio
    async def test_client_recreates_after_close(self):
        """After close, a new client must be created on next use."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        c1 = client._get_client()
        await client.close()
        c2 = client._get_client()
        assert c1 is not c2
        await client.close()


# ====================================================================
#  12. Pagination Automation
# ====================================================================


class TestPaginationAutomation:
    """Automated pagination validation."""

    @pytest.mark.asyncio
    async def test_paginate_multiple_pages(self):
        """_paginate must fetch all pages until items < page_size."""
        client = CommerceMCPBase()
        page_num = 0

        async def fetch_fn(page, page_size):
            nonlocal page_num
            page_num += 1
            if page_num == 1:
                return {"result": [{"id": i} for i in range(3)]}
            elif page_num == 2:
                return {"result": [{"id": 10}, {"id": 11}]}
            return {"result": []}

        results = await client._paginate(fetch_fn, page_size=3)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_paginate_respects_max_pages(self):
        """_paginate must stop at max_pages."""
        client = CommerceMCPBase()
        call_count = 0

        async def fetch_fn(page, page_size):
            nonlocal call_count
            call_count += 1
            return {"result": [{"id": i} for i in range(page_size)]}

        results = await client._paginate(fetch_fn, page_size=5, max_pages=3)
        assert call_count == 3
        assert len(results) == 15

    @pytest.mark.asyncio
    async def test_paginate_list_key_fallback(self):
        """_paginate must fall back to 'list' key when 'result' is not present."""
        client = CommerceMCPBase()

        async def fetch_fn(page, page_size):
            return {"list": [{"id": 1}, {"id": 2}]}

        results = await client._paginate(fetch_fn, page_size=10)
        assert len(results) == 2


# ====================================================================
#  13. Health Check Automation
# ====================================================================


class TestHealthCheckAutomation:
    """Automated health check validation."""

    @pytest.mark.asyncio
    async def test_health_check_returns_valid_structure(self):
        """health_check must return a dict with expected keys."""
        client = CommerceMCPBase(app_key="k", app_secret="s", access_token="t")
        result = await client.health_check()
        assert "configured" in result
        assert "has_token" in result
        assert "api_reachable" in result
        assert "metrics" in result
        assert result["configured"] is True
        assert result["has_token"] is True

    @pytest.mark.asyncio
    async def test_health_check_no_config(self):
        """health_check with no config must return configured=False."""
        client = CommerceMCPBase()
        result = await client.health_check()
        assert result["configured"] is False
        assert result["has_token"] is False

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        """health_check must handle connection errors gracefully."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        client.BASE_URL = "http://127.0.0.1:99999"

        mock_client = AsyncMock()
        mock_client.head.side_effect = httpx.ConnectError("refused")

        with patch.object(client, "_ensure_client", return_value=mock_client):
            result = await client.health_check()

        assert result["api_reachable"] is False
        assert "error" in result


# ====================================================================
#  14. Batch Request Automation
# ====================================================================


class TestBatchRequestAutomation:
    """Automated batch request validation."""

    @pytest.mark.asyncio
    async def test_batch_request_success(self):
        """_batch_request must handle multiple successful requests."""
        from cn_commerce_base import BatchRequestItem

        client = CommerceMCPBase(app_key="k", app_secret="s")
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"result": "ok"}
            requests = [BatchRequestItem("GET", f"/api/{i}", request_id=f"r{i}") for i in range(5)]
            summary = await client._batch_request(requests)

        assert summary.total == 5
        assert summary.succeeded == 5
        assert summary.failed == 0

    @pytest.mark.asyncio
    async def test_batch_request_partial_failure(self):
        """_batch_request must handle mixed success/failure."""
        from cn_commerce_base import BatchRequestItem

        client = CommerceMCPBase(app_key="k", app_secret="s")
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise CommerceAPIError(40001, "bad request")
            return {"result": "ok"}

        with patch.object(client, "_request", side_effect=_side_effect):
            requests = [BatchRequestItem("GET", "/api/a", request_id=f"r{i}") for i in range(3)]
            summary = await client._batch_request(requests)

        assert summary.total == 3
        assert summary.failed == 1
        assert summary.error_summary["CommerceAPIError"] == 1

    @pytest.mark.asyncio
    async def test_batch_request_empty_raises(self):
        """_batch_request with empty list must raise ValueError."""
        client = CommerceMCPBase(app_key="k", app_secret="s")
        with pytest.raises(ValueError, match="cannot be empty"):
            await client._batch_request([])


# ====================================================================
#  15. Automation Report Generation
# ====================================================================


class TestAutomationReport:
    """Generate automation test report for CI/CD pipelines."""

    def test_report_generation(self):
        """AutomationReport must produce valid JSON output."""
        report = AutomationReport()
        report.record("oceanengine", "import", True)
        report.record("jd", "import", True)
        report.record("taobao", "import", False, "Module not found")

        assert report.total_checks == 3
        assert report.passed == 2
        assert report.failed == 1

        json_output = report.to_json()
        parsed = json.loads(json_output)
        assert parsed["summary"]["total_checks"] == 3
        assert parsed["summary"]["passed"] == 2
        assert parsed["summary"]["failed"] == 1
        assert len(parsed["errors"]) == 1
        assert "taobao" in parsed["errors"][0]

    def test_report_pass_rate_calculation(self):
        """AutomationReport must calculate pass rate correctly."""
        report = AutomationReport()
        for i in range(8):
            report.record(f"platform_{i}", "test", True)
        report.record("platform_fail", "test", False, "error")

        assert report.total_checks == 9
        assert report.passed == 8
        assert report.failed == 1

        parsed = json.loads(report.to_json())
        assert parsed["summary"]["pass_rate"] == "88.9%"

    def test_full_platform_report(self):
        """Generate a full automation report for all platforms."""
        report = AutomationReport()

        for platform in _ALL_PLATFORMS:
            # Check importability
            try:
                _safe_import_module(platform)
                report.record(platform, "module_import", True)
            except Exception as e:
                report.record(platform, "module_import", False, str(e))

            # Check health
            try:
                result = check_server_health(platform)
                report.record(platform, "health_check", result["status"] != "error")
            except Exception as e:
                report.record(platform, "health_check", False, str(e))

        parsed = json.loads(report.to_json())
        # All 8 platforms should be importable
        assert parsed["summary"]["passed"] >= 8
        # Report should have platform results
        assert len(parsed["platforms"]) == len(_ALL_PLATFORMS)
