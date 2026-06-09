"""Internationalization (i18n) module for mcp-cn-commerce.

Provides Chinese and English translations for error messages, CLI output,
and documentation strings. Language can be set via environment variable
``MCP_CN_COMMERCE_LANG`` or programmatically via :func:`set_language`.

Usage::

    from i18n import t, set_language

    set_language("en")
    print(t("error.missing_env_vars", vars="APP_KEY, APP_SECRET"))
    # => "Missing required environment variables: APP_KEY, APP_SECRET"

    set_language("zh")
    print(t("error.missing_env_vars", vars="APP_KEY, APP_SECRET"))
    # => "缺少必需的环境变量: APP_KEY, APP_SECRET"
"""

from __future__ import annotations

import os
import threading
from typing import Any

# ── Supported Languages ────────────────────────────────────

SUPPORTED_LANGUAGES: list[str] = ["zh", "en"]
DEFAULT_LANGUAGE: str = "zh"

# Thread-safe language storage
_local = threading.local()

# ── Translation Dictionaries ───────────────────────────────

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh": {
        # Error messages - Configuration
        "error.platform_name_empty": "平台名称不能为空",
        "error.platform_name_invalid": "无效的平台名称 '{platform}': 必须为大写字母、数字和下划线",
        "error.platform_name_too_long": "平台名称过长 ({length} > 64)",
        "error.param_too_long": "参数 '{name}' 超出最大长度 ({length} > {max_length})",
        "error.param_sql_injection": "参数 '{name}' 包含可疑的 SQL 模式",
        "error.param_path_traversal": "参数 '{name}' 包含路径遍历模式",
        "error.param_xss": "参数 '{name}' 包含可疑的脚本模式",
        "error.env_var_name_empty": "环境变量名不能为空",
        "error.env_var_name_invalid": "无效的环境变量名 '{name}': 必须为大写字母、数字和下划线",
        "error.missing_env_vars": "缺少必需的环境变量: {vars}",
        "error.unknown_sign_method": "未知的签名方法: {method}",
        "error.batch_empty": "批量请求列表不能为空",
        "error.unknown_platform": "未知平台: {platform}",
        "error.source_dir_not_found": "源码目录未找到: {path}",

        # Error messages - API
        "error.api_error": "API 错误: [{code}] {msg}",
        "error.max_retries_exhausted": "{func} 已用尽最大重试次数 ({max_retries})",
        "error.retry_attempt": "重试 {attempt}/{max_retries} {func}，{delay:.2f}s 后: {exc}",

        # CLI messages
        "cli.description": "中国电商 MCP 服务器 CLI 工具",
        "cli.start_help": "启动一个或多个 MCP 服务器",
        "cli.health_help": "检查 MCP 服务器健康状态",
        "cli.info_help": "显示版本和环境信息",
        "cli.list_help": "列出可用的 MCP 服务器平台",
        "cli.platforms_help": "要启动的平台。可用: {platforms}",
        "cli.version": "mcp-cn-commerce CLI v{version}",
        "cli.python": "Python: {version}",
        "cli.platform_info": "平台: {platform}",
        "cli.repo_root": "仓库根目录: {path}",
        "cli.available_servers": "可用服务器: {count}",
        "cli.server_entry": "  - {name}: {description} [{status}]",
        "cli.server_found": "已找到",
        "cli.server_missing": "未找到",
        "cli.available_mcp_servers": "可用 MCP 服务器:\n",
        "cli.total_platforms": "合计: {count} 个平台",
        "cli.error_unknown_platform": "错误: 未知平台 '{platform}'",
        "cli.error_available_platforms": "可用平台: {platforms}",
        "cli.error_no_platforms": "错误: 未指定平台",
        "cli.error_source_dir": "错误: 源码目录未找到: {path}",
        "cli.error_starting": "错误: 启动 {platform} 服务器失败: {error}",
        "cli.starting_server": "正在启动 {platform} 服务器: {cmd}",
        "cli.stopping_servers": "正在停止所有服务器...",
        "cli.server_stopped": "服务器 {platform} 已被用户停止",

        # Health status
        "health.status.ready": "就绪",
        "health.status.importable_no_creds": "可导入但无凭证",
        "health.status.not_ready": "未就绪",
        "health.status.error": "错误",
        "health.status.unknown": "未知",

        # Logging
        "log.client_initialized": "客户端已初始化: {platform}",
        "log.missing_config": "{platform} 配置缺失: {vars}",
        "log.rate_limit_wait": "速率限制: 等待 {wait:.2f}s",
        "log.request": "请求: {method} {url} (第 {attempt}/{max} 次尝试)",
        "log.response": "响应: {status}",
        "log.api_error": "API 错误: [{code}] {msg}",
        "log.pagination_page": "分页: 第 {page} 页, 获得 {count} 条",
        "log.pagination_complete": "分页完成: 共 {total} 条",
        "log.retry_warning": "重试 {attempt}/{max} {func}，{delay:.2f}s 后: {exc}",
        "log.max_retries_exhausted": "{func} 已用尽最大重试次数 ({max})",

        # MCP Server descriptions
        "server.oceanengine": "巨量引擎广告平台",
        "server.doudian": "抖店电商平台",
        "server.jd": "京东电商平台",
        "server.taobao": "淘宝电商平台",
        "server.pinduoduo": "拼多多电商平台",
        "server.kuaishou": "快手电商平台",
        "server.xiaohongshu": "小红书电商平台",
        "server.weixin_store": "微信小店电商平台",

        # General
        "general.success": "成功",
        "general.failure": "失败",
        "general.unknown": "未知",
        "general.configured": "已配置",
        "general.not_configured": "未配置",
        "general.token_set": "已设置",
        "general.token_missing": "未设置",
    },
    "en": {
        # Error messages - Configuration
        "error.platform_name_empty": "Platform name cannot be empty",
        "error.platform_name_invalid": "Invalid platform name '{platform}': must be uppercase alphanumeric with underscores",
        "error.platform_name_too_long": "Platform name too long ({length} > 64)",
        "error.param_too_long": "Parameter '{name}' exceeds maximum length ({length} > {max_length})",
        "error.param_sql_injection": "Parameter '{name}' contains suspicious SQL patterns",
        "error.param_path_traversal": "Parameter '{name}' contains path traversal patterns",
        "error.param_xss": "Parameter '{name}' contains suspicious script patterns",
        "error.env_var_name_empty": "Environment variable name cannot be empty",
        "error.env_var_name_invalid": "Invalid env var name '{name}': must be uppercase alphanumeric with underscores",
        "error.missing_env_vars": "Missing required environment variables: {vars}",
        "error.unknown_sign_method": "Unknown sign method: {method}",
        "error.batch_empty": "Batch request list cannot be empty",
        "error.unknown_platform": "Unknown platform: {platform}",
        "error.source_dir_not_found": "Source directory not found: {path}",

        # Error messages - API
        "error.api_error": "API error: [{code}] {msg}",
        "error.max_retries_exhausted": "Max retries ({max_retries}) exhausted for {func}",
        "error.retry_attempt": "Retry {attempt}/{max_retries} for {func} after {delay:.2f}s: {exc}",

        # CLI messages
        "cli.description": "CLI tool for Chinese e-commerce MCP servers",
        "cli.start_help": "Start one or more MCP servers",
        "cli.health_help": "Check health of MCP servers",
        "cli.info_help": "Show version and environment info",
        "cli.list_help": "List available MCP server platforms",
        "cli.platforms_help": "Platform(s) to start. Available: {platforms}",
        "cli.version": "mcp-cn-commerce CLI v{version}",
        "cli.python": "Python: {version}",
        "cli.platform_info": "Platform: {platform}",
        "cli.repo_root": "Repo root: {path}",
        "cli.available_servers": "Available servers: {count}",
        "cli.server_entry": "  - {name}: {description} [{status}]",
        "cli.server_found": "found",
        "cli.server_missing": "missing",
        "cli.available_mcp_servers": "Available MCP servers:\n",
        "cli.total_platforms": "Total: {count} platforms",
        "cli.error_unknown_platform": "Error: Unknown platform '{platform}'",
        "cli.error_available_platforms": "Available platforms: {platforms}",
        "cli.error_no_platforms": "Error: No platforms specified",
        "cli.error_source_dir": "Error: Source directory not found: {path}",
        "cli.error_starting": "Error starting {platform} server: {error}",
        "cli.starting_server": "Starting {platform} server: {cmd}",
        "cli.stopping_servers": "Stopping all servers...",
        "cli.server_stopped": "Server {platform} stopped by user",

        # Health status
        "health.status.ready": "Ready",
        "health.status.importable_no_creds": "Importable but no credentials",
        "health.status.not_ready": "Not Ready",
        "health.status.error": "Error",
        "health.status.unknown": "Unknown",

        # Logging
        "log.client_initialized": "Client initialized for {platform}",
        "log.missing_config": "Missing config for {platform}: {vars}",
        "log.rate_limit_wait": "Rate limit: waiting {wait:.2f}s",
        "log.request": "Request: {method} {url} (attempt {attempt}/{max})",
        "log.response": "Response: {status}",
        "log.api_error": "API error: [{code}] {msg}",
        "log.pagination_page": "Pagination: page {page}, got {count} items",
        "log.pagination_complete": "Pagination complete: {total} total items",
        "log.retry_warning": "Retry {attempt}/{max} for {func} after {delay:.2f}s: {exc}",
        "log.max_retries_exhausted": "Max retries ({max}) exhausted for {func}",

        # MCP Server descriptions
        "server.oceanengine": "Ocean Engine advertising platform",
        "server.doudian": "Douyin Shop e-commerce platform",
        "server.jd": "JD.com e-commerce platform",
        "server.taobao": "Taobao e-commerce platform",
        "server.pinduoduo": "Pinduoduo e-commerce platform",
        "server.kuaishou": "Kuaishou e-commerce platform",
        "server.xiaohongshu": "Xiaohongshu e-commerce platform",
        "server.weixin_store": "Weixin Store e-commerce platform",

        # General
        "general.success": "Success",
        "general.failure": "Failure",
        "general.unknown": "Unknown",
        "general.configured": "configured",
        "general.not_configured": "not configured",
        "general.token_set": "set",
        "general.token_missing": "missing",
    },
}


# ── Language Management ────────────────────────────────────


def _get_env_language() -> str:
    """Read language from MCP_CN_COMMERCE_LANG environment variable.

    Returns:
        Language code ("zh" or "en"), defaults to DEFAULT_LANGUAGE.
    """
    lang = os.environ.get("MCP_CN_COMMERCE_LANG", "").lower().strip()
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return DEFAULT_LANGUAGE


def get_language() -> str:
    """Get the current language setting.

    Checks in order:
    1. Thread-local setting (set via :func:`set_language`)
    2. Environment variable ``MCP_CN_COMMERCE_LANG``
    3. Default language (``zh``)

    Returns:
        Current language code ("zh" or "en").
    """
    lang = getattr(_local, "language", None)
    if lang is not None:
        return lang
    return _get_env_language()


def set_language(lang: str) -> None:
    """Set the language for the current thread.

    Args:
        lang: Language code, must be "zh" or "en".

    Raises:
        ValueError: If the language code is not supported.
    """
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language '{lang}'. Supported: {SUPPORTED_LANGUAGES}")
    _local.language = lang


def reset_language() -> None:
    """Reset thread-local language to use environment/default.

    After calling this, :func:`get_language` will fall back to the
    ``MCP_CN_COMMERCE_LANG`` environment variable, then the default.
    """
    _local.language = None


# ── Translation Function ───────────────────────────────────


def t(key: str, **kwargs: Any) -> str:
    """Translate a message key to the current language.

    Args:
        key: Translation key (e.g. "error.missing_env_vars").
        **kwargs: Format arguments to interpolate into the template.

    Returns:
        Translated and formatted string.

    Examples::

        >>> set_language("en")
        >>> t("error.missing_env_vars", vars="APP_KEY")
        'Missing required environment variables: APP_KEY'

        >>> set_language("zh")
        >>> t("error.missing_env_vars", vars="APP_KEY")
        '缺少必需的环境变量: APP_KEY'

    If the key is not found, the key itself is returned as a fallback.
    """
    lang = get_language()
    translations = _TRANSLATIONS.get(lang, {})
    template = translations.get(key)

    if template is None:
        # Fallback: try the other language, then return the raw key
        for fallback_lang in SUPPORTED_LANGUAGES:
            if fallback_lang != lang:
                fallback_translations = _TRANSLATIONS.get(fallback_lang, {})
                template = fallback_translations.get(key)
                if template is not None:
                    break

    if template is None:
        return key

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template


def get_all_keys(lang: str | None = None) -> list[str]:
    """Get all available translation keys for a language.

    Args:
        lang: Language code. Defaults to current language.

    Returns:
        Sorted list of translation keys.
    """
    target_lang = lang or get_language()
    translations = _TRANSLATIONS.get(target_lang, {})
    return sorted(translations.keys())


def get_translations(lang: str | None = None) -> dict[str, str]:
    """Get all translations for a language.

    Args:
        lang: Language code. Defaults to current language.

    Returns:
        Copy of the translation dictionary.
    """
    target_lang = lang or get_language()
    return dict(_TRANSLATIONS.get(target_lang, {}))
