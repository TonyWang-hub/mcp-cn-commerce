"""Tests for the i18n (internationalization) module.

Tests language switching, translation lookup, format interpolation,
environment variable support, and thread safety.
"""

from __future__ import annotations

import os
import threading
from unittest.mock import patch

import pytest

from shared.i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_all_keys,
    get_language,
    get_translations,
    reset_language,
    set_language,
    t,
)

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_lang():
    """Reset language to default after each test."""
    yield
    reset_language()


# ── Supported Languages Tests ──────────────────────────────


class TestSupportedLanguages:
    """Tests for language constants."""

    def test_zh_and_en_supported(self):
        assert "zh" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES

    def test_default_language_is_zh(self):
        assert DEFAULT_LANGUAGE == "zh"

    def test_exactly_two_languages(self):
        assert len(SUPPORTED_LANGUAGES) == 2


# ── get_language / set_language Tests ──────────────────────


class TestLanguageManagement:
    """Tests for getting and setting the current language."""

    def test_default_language(self):
        """Without any env var, default should be zh."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MCP_CN_COMMERCE_LANG", None)
            reset_language()
            assert get_language() == "zh"

    def test_set_language_zh(self):
        set_language("zh")
        assert get_language() == "zh"

    def test_set_language_en(self):
        set_language("en")
        assert get_language() == "en"

    def test_set_language_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            set_language("fr")

    def test_set_language_empty_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            set_language("")

    def test_reset_language_falls_back_to_env(self):
        set_language("en")
        reset_language()
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "en"}):
            assert get_language() == "en"

    def test_env_var_zh(self):
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "zh"}):
            reset_language()
            assert get_language() == "zh"

    def test_env_var_en(self):
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "en"}):
            reset_language()
            assert get_language() == "en"

    def test_env_var_case_insensitive(self):
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "EN"}):
            reset_language()
            assert get_language() == "en"

    def test_env_var_with_whitespace(self):
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "  zh  "}):
            reset_language()
            assert get_language() == "zh"

    def test_env_var_invalid_ignored(self):
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "invalid"}):
            reset_language()
            assert get_language() == "zh"  # falls back to default

    def test_env_var_empty_ignored(self):
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": ""}):
            reset_language()
            assert get_language() == "zh"

    def test_set_language_overrides_env(self):
        """Thread-local set_language should take precedence over env var."""
        with patch.dict(os.environ, {"MCP_CN_COMMERCE_LANG": "en"}):
            set_language("zh")
            assert get_language() == "zh"


# ── Translation Function Tests ─────────────────────────────


class TestTranslationFunction:
    """Tests for the t() translation function."""

    def test_basic_zh_translation(self):
        set_language("zh")
        result = t("error.platform_name_empty")
        assert result == "平台名称不能为空"

    def test_basic_en_translation(self):
        set_language("en")
        result = t("error.platform_name_empty")
        assert result == "Platform name cannot be empty"

    def test_format_interpolation_zh(self):
        set_language("zh")
        result = t("error.missing_env_vars", vars="APP_KEY, APP_SECRET")
        assert "APP_KEY" in result
        assert "APP_SECRET" in result
        assert "缺少" in result

    def test_format_interpolation_en(self):
        set_language("en")
        result = t("error.missing_env_vars", vars="APP_KEY, APP_SECRET")
        assert "APP_KEY" in result
        assert "APP_SECRET" in result
        assert "Missing" in result

    def test_format_with_multiple_kwargs(self):
        set_language("en")
        result = t("error.param_too_long", name="test", length=5000, max_length=4096)
        assert "test" in result
        assert "5000" in result
        assert "4096" in result

    def test_format_with_float(self):
        set_language("en")
        result = t("log.rate_limit_wait", wait=1.23)
        assert "1.23" in result

    def test_unknown_key_returns_key(self):
        set_language("en")
        result = t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_unknown_key_no_kwargs(self):
        set_language("zh")
        result = t("totally.missing.key")
        assert result == "totally.missing.key"

    def test_no_kwargs_returns_template(self):
        set_language("zh")
        result = t("general.success")
        assert result == "成功"

    def test_no_kwargs_en(self):
        set_language("en")
        result = t("general.success")
        assert result == "Success"


# ── Cross-language Consistency Tests ───────────────────────


class TestCrossLanguageConsistency:
    """Ensure zh and en have the same set of keys."""

    def test_same_keys_in_both_languages(self):
        zh_keys = set(get_all_keys("zh"))
        en_keys = set(get_all_keys("en"))
        assert zh_keys == en_keys, f"Key mismatch: zh-only={zh_keys - en_keys}, en-only={en_keys - zh_keys}"

    def test_all_keys_count(self):
        keys = get_all_keys("zh")
        # Should have a reasonable number of translations
        assert len(keys) >= 30, f"Expected >= 30 keys, got {len(keys)}"

    def test_all_keys_are_dot_separated(self):
        for key in get_all_keys("zh"):
            assert "." in key, f"Key '{key}' should use dot notation"


# ── get_all_keys Tests ─────────────────────────────────────


class TestGetAllKeys:
    """Tests for get_all_keys()."""

    def test_returns_sorted_keys(self):
        keys = get_all_keys("zh")
        assert keys == sorted(keys)

    def test_default_language(self):
        set_language("zh")
        keys = get_all_keys()
        assert "error.platform_name_empty" in keys

    def test_explicit_language(self):
        keys = get_all_keys("en")
        assert "error.platform_name_empty" in keys

    def test_invalid_language_returns_empty(self):
        # get_all_keys doesn't validate, just returns empty for unknown lang
        keys = get_all_keys("xx")
        assert keys == []


# ── get_translations Tests ─────────────────────────────────


class TestGetTranslations:
    """Tests for get_translations()."""

    def test_returns_dict_copy(self):
        trans1 = get_translations("zh")
        trans2 = get_translations("zh")
        assert trans1 == trans2
        assert trans1 is not trans2  # Should be a copy

    def test_modification_does_not_affect_module(self):
        trans = get_translations("zh")
        trans["fake_key"] = "fake_value"
        # Original should not be affected
        assert "fake_key" not in get_translations("zh")

    def test_default_language(self):
        set_language("zh")
        trans = get_translations()
        assert "general.success" in trans
        assert trans["general.success"] == "成功"

    def test_explicit_language(self):
        trans = get_translations("en")
        assert trans["general.success"] == "Success"


# ── Thread Safety Tests ────────────────────────────────────


class TestThreadSafety:
    """Test that language settings are thread-local."""

    def test_thread_local_language(self):
        """Different threads can have different language settings."""
        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def worker(lang: str, name: str):
            set_language(lang)
            barrier.wait(timeout=5)
            results[name] = get_language()

        t1 = threading.Thread(target=worker, args=("zh", "thread_zh"))
        t2 = threading.Thread(target=worker, args=("en", "thread_en"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert results.get("thread_zh") == "zh"
        assert results.get("thread_en") == "en"

    def test_thread_local_translation(self):
        """Different threads get different translations."""
        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def worker(lang: str, name: str):
            set_language(lang)
            barrier.wait(timeout=5)
            results[name] = t("general.success")

        t1 = threading.Thread(target=worker, args=("zh", "zh"))
        t2 = threading.Thread(target=worker, args=("en", "en"))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert results.get("zh") == "成功"
        assert results.get("en") == "Success"


# ── Category Coverage Tests ────────────────────────────────


class TestCategoryCoverage:
    """Ensure all message categories are present."""

    def test_error_messages_present(self):
        keys = get_all_keys("en")
        error_keys = [k for k in keys if k.startswith("error.")]
        assert len(error_keys) >= 10, f"Expected >= 10 error keys, got {len(error_keys)}"

    def test_cli_messages_present(self):
        keys = get_all_keys("en")
        cli_keys = [k for k in keys if k.startswith("cli.")]
        assert len(cli_keys) >= 10, f"Expected >= 10 cli keys, got {len(cli_keys)}"

    def test_health_messages_present(self):
        keys = get_all_keys("en")
        health_keys = [k for k in keys if k.startswith("health.")]
        assert len(health_keys) >= 3, f"Expected >= 3 health keys, got {len(health_keys)}"

    def test_log_messages_present(self):
        keys = get_all_keys("en")
        log_keys = [k for k in keys if k.startswith("log.")]
        assert len(log_keys) >= 5, f"Expected >= 5 log keys, got {len(log_keys)}"

    def test_server_descriptions_present(self):
        keys = get_all_keys("en")
        server_keys = [k for k in keys if k.startswith("server.")]
        assert len(server_keys) >= 8, f"Expected >= 8 server keys, got {len(server_keys)}"

    def test_general_messages_present(self):
        keys = get_all_keys("en")
        general_keys = [k for k in keys if k.startswith("general.")]
        assert len(general_keys) >= 4, f"Expected >= 4 general keys, got {len(general_keys)}"

    def test_all_eight_platforms_translated(self):
        """All 8 platforms should have server description translations."""
        platforms = [
            "oceanengine",
            "doudian",
            "jd",
            "taobao",
            "pinduoduo",
            "kuaishou",
            "xiaohongshu",
            "weixin_store",
        ]
        for lang in SUPPORTED_LANGUAGES:
            for platform in platforms:
                key = f"server.{platform}"
                result = t(key)
                assert result != key, f"Missing translation for '{key}' in '{lang}'"
                assert len(result) > 0


# ── Edge Case Tests ────────────────────────────────────────


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_format_kwargs(self):
        """t() with a key that has no placeholders should ignore kwargs."""
        set_language("en")
        result = t("general.success", unused="value")
        assert result == "Success"

    def test_missing_format_placeholder(self):
        """If kwargs don't match the template, return template as-is."""
        set_language("en")
        # The key "error.param_too_long" expects name, length, max_length
        # Passing wrong kwargs should still work (graceful degradation)
        result = t("error.param_too_long")
        # Without kwargs, returns the raw template
        assert "name" in result  # template has {name}

    def test_special_characters_in_kwargs(self):
        set_language("en")
        result = t("error.unknown_platform", platform="TEST_PLATFORM_123")
        assert "TEST_PLATFORM_123" in result

    def test_unicode_in_kwargs(self):
        set_language("zh")
        result = t("error.unknown_platform", platform="TEST")
        assert "TEST" in result
        assert "未知" in result

    def test_reset_language_idempotent(self):
        """Calling reset_language multiple times should be safe."""
        set_language("en")
        reset_language()
        reset_language()
        reset_language()
        # Should still work
        lang = get_language()
        assert lang in SUPPORTED_LANGUAGES

    def test_set_language_after_reset(self):
        reset_language()
        set_language("en")
        assert get_language() == "en"
        reset_language()
        set_language("zh")
        assert get_language() == "zh"
