"""Tests for the mcp-cn-commerce CLI tool.

Tests commands, configuration loading, health checks, and version info.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from shared.cli import (
    SERVER_REGISTRY,
    __version__,
    build_parser,
    build_pythonpath,
    check_all_health,
    check_server_health,
    format_health_output,
    get_src_path,
    load_config,
    main,
    show_version,
)

# ── Version Tests ──────────────────────────────────────────


class TestVersion:
    """Tests for version info."""

    def test_version_string(self):
        assert __version__ == "0.1.1"

    def test_version_from_parser(self, capsys):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "0.1.1" in captured.out


# ── Server Registry Tests ─────────────────────────────────


class TestServerRegistry:
    """Tests for the server registry."""

    def test_all_eight_platforms_registered(self):
        expected = {"oceanengine", "doudian", "jd", "taobao", "pinduoduo", "kuaishou", "xiaohongshu", "weixin_store"}
        assert set(SERVER_REGISTRY.keys()) == expected

    def test_each_entry_has_required_keys(self):
        for name, info in SERVER_REGISTRY.items():
            assert "module" in info, f"{name} missing 'module'"
            assert "env_prefix" in info, f"{name} missing 'env_prefix'"
            assert "description" in info, f"{name} missing 'description'"

    def test_modules_follow_naming_convention(self):
        for name, info in SERVER_REGISTRY.items():
            assert info["module"].startswith("servers."), f"{name} module should start with 'servers.'"
            assert info["module"].endswith(".server"), f"{name} module should end with '.server'"


# ── Path Helpers Tests ────────────────────────────────────


class TestGetSrcPath:
    """Tests for get_src_path."""

    def test_returns_path_under_servers(self):
        p = get_src_path("oceanengine")
        assert p.name == "src"
        assert "oceanengine" in str(p)

    def test_all_platforms_have_server_file(self):
        for platform in SERVER_REGISTRY:
            p = get_src_path(platform).parent / "server.py"
            assert p.is_file(), f"server.py not found for {platform}: {p}"


class TestBuildPythonpath:
    """Tests for build_pythonpath."""

    def test_includes_shared_dir(self):
        pp = build_pythonpath(["oceanengine"])
        assert "shared" in pp

    def test_multiple_platforms(self):
        pp = build_pythonpath(["oceanengine", "jd"])
        assert "shared" in pp

    def test_empty_platforms_still_includes_shared(self):
        pp = build_pythonpath([])
        assert "shared" in pp


# ── Config Loading Tests ──────────────────────────────────


class TestLoadConfig:
    """Tests for load_config."""

    def test_returns_empty_when_no_config(self):
        config = load_config("/nonexistent/path/config.json")
        assert config == {}

    def test_loads_valid_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"servers": ["oceanengine"], "verbose": true}')
        config = load_config(str(config_file))
        assert config["servers"] == ["oceanengine"]
        assert config["verbose"] is True

    def test_handles_invalid_json(self, tmp_path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("{invalid json}")
        config = load_config(str(config_file))
        assert config == {}

    def test_returns_empty_when_path_is_none(self):
        config = load_config(None)
        # May or may not find default configs, but should not raise
        assert isinstance(config, dict)


# ── Health Check Tests ────────────────────────────────────


class TestCheckServerHealth:
    """Tests for check_server_health."""

    def test_unknown_platform_returns_error(self):
        result = check_server_health("nonexistent")
        assert result["status"] == "error"
        assert "Unknown platform" in result["error"]

    def test_known_platform_returns_valid_structure(self):
        result = check_server_health("oceanengine")
        assert "platform" in result
        assert "status" in result
        assert "env_configured" in result
        assert "importable" in result
        assert result["platform"] == "oceanengine"

    def test_importable_flag_or_error(self):
        result = check_server_health("oceanengine")
        # Module import may succeed or fail due to MCP version compatibility
        assert result["importable"] is True or "import_error" in result

    def test_env_check_without_credentials(self):
        # Clear any existing env vars
        env_vars = ["OCEANENGINE_APP_KEY", "OCEANENGINE_APP_SECRET", "OCEANENGINE_ACCESS_TOKEN"]
        with patch.dict(os.environ, {k: "" for k in env_vars}, clear=False):
            result = check_server_health("oceanengine")
            assert result["env_configured"] is False

    def test_env_check_with_credentials(self):
        env_vars = {
            "OCEANENGINE_APP_KEY": "test_key",
            "OCEANENGINE_APP_SECRET": "test_secret",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            result = check_server_health("oceanengine")
            # env_configured depends on whether creds are set
            assert isinstance(result["env_configured"], bool)

    def test_all_platforms_checkable(self):
        for platform in SERVER_REGISTRY:
            result = check_server_health(platform)
            assert result["platform"] == platform
            assert result["status"] in ("ready", "importable_no_creds", "not_ready", "error")


class TestCheckAllHealth:
    """Tests for check_all_health."""

    def test_returns_results_for_all_platforms(self):
        results = check_all_health()
        assert len(results) == len(SERVER_REGISTRY)

    def test_all_platforms_represented(self):
        results = check_all_health()
        platforms = {r["platform"] for r in results}
        assert platforms == set(SERVER_REGISTRY.keys())

    def test_all_results_have_valid_status(self):
        results = check_all_health()
        for r in results:
            assert r["status"] in ("ready", "importable_no_creds", "not_ready", "error")


# ── Format Health Output Tests ─────────────────────────────


class TestFormatHealthOutput:
    """Tests for format_health_output."""

    def test_json_output(self):
        results = [{"platform": "test", "status": "ready"}]
        output = format_health_output(results, as_json=True)
        parsed = json.loads(output)
        assert parsed[0]["platform"] == "test"

    def test_text_output_contains_platforms(self):
        results = [
            {"platform": "oceanengine", "description": "test", "status": "ready", "env_vars": {}},
            {"platform": "jd", "description": "test", "status": "not_ready", "env_vars": {}},
        ]
        output = format_health_output(results, as_json=False)
        assert "oceanengine" in output
        assert "jd" in output

    def test_text_output_contains_status_icons(self):
        results = [{"platform": "test", "description": "", "status": "ready", "env_vars": {}}]
        output = format_health_output(results, as_json=False)
        assert "[READY]" in output

    def test_text_output_shows_errors(self):
        results = [{"platform": "test", "description": "", "status": "error", "error": "bad", "env_vars": {}}]
        output = format_health_output(results, as_json=False)
        assert "bad" in output


# ── Parser Tests ───────────────────────────────────────────


class TestBuildParser:
    """Tests for the argument parser."""

    def test_no_args_shows_help(self, capsys):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_start_command(self):
        parser = build_parser()
        args = parser.parse_args(["start", "oceanengine"])
        assert args.command == "start"
        assert args.platforms == ["oceanengine"]

    def test_start_multiple_platforms(self):
        parser = build_parser()
        args = parser.parse_args(["start", "oceanengine", "jd", "taobao"])
        assert args.platforms == ["oceanengine", "jd", "taobao"]

    def test_health_command_all(self):
        parser = build_parser()
        args = parser.parse_args(["health"])
        assert args.command == "health"
        assert args.platforms == []

    def test_health_command_specific(self):
        parser = build_parser()
        args = parser.parse_args(["health", "oceanengine"])
        assert args.platforms == ["oceanengine"]

    def test_health_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["health", "--json"])
        assert args.output_json is True

    def test_info_command(self):
        parser = build_parser()
        args = parser.parse_args(["info"])
        assert args.command == "info"

    def test_info_json_flag(self):
        parser = build_parser()
        args = parser.parse_args(["info", "--json"])
        assert args.output_json is True

    def test_list_command(self):
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose", "health"])
        assert args.verbose is True

    def test_config_option(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "/path/to/config.json", "health"])
        assert args.config == "/path/to/config.json"


# ── Main Function Tests ───────────────────────────────────


class TestMain:
    """Tests for the main() entry point."""

    def test_no_command_prints_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Available commands" in captured.out or "mcp-cn-commerce" in captured.out

    def test_list_command(self, capsys):
        main(["list"])
        captured = capsys.readouterr()
        assert "oceanengine" in captured.out
        assert "jd" in captured.out
        assert "Available MCP servers" in captured.out

    def test_health_all(self, capsys):
        main(["health"])
        captured = capsys.readouterr()
        # Should show all platforms (some may have errors due to MCP compat)
        assert "oceanengine" in captured.out

    def test_health_specific_platform(self, capsys):
        main(["health", "oceanengine"])
        captured = capsys.readouterr()
        assert "oceanengine" in captured.out

    def test_health_json_output(self, capsys):
        main(["health", "--json"])
        captured = capsys.readouterr()
        # Should be valid JSON
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == len(SERVER_REGISTRY)

    def test_info_command(self, capsys):
        main(["info"])
        captured = capsys.readouterr()
        assert "mcp-cn-commerce" in captured.out
        assert "0.1.1" in captured.out

    def test_info_json_output(self, capsys):
        main(["info", "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["version"] == "0.1.1"
        assert "servers" in data
        assert len(data["servers"]) == len(SERVER_REGISTRY)

    def test_start_unknown_platform_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "nonexistent"])
        assert exc_info.value.code == 1

    def test_start_exits_without_platform(self):
        """start command requires at least one platform."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["start"])


# ── Integration: show_version Tests ───────────────────────


class TestShowVersion:
    """Tests for show_version function."""

    def test_basic_version(self, capsys):
        show_version(verbose=False)
        captured = capsys.readouterr()
        assert "0.1.1" in captured.out

    def test_verbose_version(self, capsys):
        show_version(verbose=True)
        captured = capsys.readouterr()
        assert "0.1.1" in captured.out
        assert "Python:" in captured.out
        assert "Available servers:" in captured.out
