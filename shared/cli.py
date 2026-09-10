"""CLI tool for mcp-cn-commerce.

Provides commands to start MCP servers, check health, and show version info.
Supports configuration via files and environment variables.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from shared import __version__

# ── Server Registry ────────────────────────────────────────

# Maps short platform names to their module paths and env var prefixes
SERVER_REGISTRY: dict[str, dict[str, str]] = {
    "oceanengine": {
        "module": "servers.oceanengine.server",
        "env_prefix": "OCEANENGINE",
        "description": "Ocean Engine (巨量引擎) advertising platform",
    },
    "doudian": {
        "module": "servers.doudian.server",
        "env_prefix": "DOUDIAN",
        "description": "Douyin Shop (抖店) e-commerce platform",
    },
    "jd": {
        "module": "servers.jd.server",
        "env_prefix": "JD",
        "description": "JD.com (京东) e-commerce platform",
    },
    "taobao": {
        "module": "servers.taobao.server",
        "env_prefix": "TAOBAO",
        "description": "Taobao (淘宝) e-commerce platform",
    },
    "pinduoduo": {
        "module": "servers.pinduoduo.server",
        "env_prefix": "PINDUODUO",
        "description": "Pinduoduo (拼多多) e-commerce platform",
    },
    "kuaishou": {
        "module": "servers.kuaishou.server",
        "env_prefix": "KUAISHOU",
        "description": "Kuaishou (快手) e-commerce platform",
    },
    "xiaohongshu": {
        "module": "servers.xiaohongshu.server",
        "env_prefix": "XHS",
        "description": "Xiaohongshu (小红书) e-commerce platform",
    },
    "weixin_store": {
        "module": "servers.weixin_store.server",
        "env_prefix": "WX",
        "description": "Weixin Store (微信小店) e-commerce platform",
    },
}

# Fields follow each platform's real authentication contract. Ocean Engine
# needs only the already-issued token; Weixin has alternative auth modes.
PLATFORM_ENV_FIELDS: dict[str, tuple[str, ...]] = {
    "oceanengine": ("OCEANENGINE_ACCESS_TOKEN",),
    "doudian": ("DOUDIAN_APP_KEY", "DOUDIAN_APP_SECRET", "DOUDIAN_SHOP_ID", "DOUDIAN_ACCESS_TOKEN"),
    "jd": ("JD_APP_KEY", "JD_APP_SECRET", "JD_ACCESS_TOKEN"),
    "taobao": ("TAOBAO_APP_KEY", "TAOBAO_APP_SECRET", "TAOBAO_ACCESS_TOKEN"),
    "pinduoduo": ("PINDUODUO_CLIENT_ID", "PINDUODUO_CLIENT_SECRET", "PINDUODUO_ACCESS_TOKEN"),
    "kuaishou": ("KUAISHOU_APP_KEY", "KUAISHOU_APP_SECRET", "KUAISHOU_SIGN_SECRET", "KUAISHOU_ACCESS_TOKEN"),
    "xiaohongshu": ("XHS_CLIENT_ID", "XHS_CLIENT_SECRET", "XHS_ACCESS_TOKEN"),
    "weixin_store": ("WX_APP_ID", "WX_APP_SECRET", "WX_ACCESS_TOKEN", "WX_TOKEN_MODE"),
}

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVERS_DIR = _REPO_ROOT / "servers"

DEFAULT_CONFIG_PATHS = [
    Path.cwd() / "mcp-cn-commerce.json",
    Path.home() / ".config" / "mcp-cn-commerce" / "config.json",
]


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load the explicit file, or the first existing default file.

    Invalid or explicitly missing files fail visibly instead of silently
    launching with a different account/configuration.
    """
    paths = [Path(config_path)] if config_path else DEFAULT_CONFIG_PATHS
    for path in paths:
        if not path.is_file():
            if config_path:
                raise ValueError(f"Configuration file not found: {path}")
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Cannot read configuration file: {path}") from exc
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a JSON object")
        unknown = set(config) - {"servers", "env", "verbose", "log_level"}
        if unknown:
            raise ValueError(f"Unknown configuration fields: {', '.join(sorted(unknown))}")
        if "servers" in config and (
            not isinstance(config["servers"], list)
            or any(not isinstance(name, str) or name not in SERVER_REGISTRY for name in config["servers"])
        ):
            raise ValueError("Configuration servers must be a list of registered platform names")
        if "verbose" in config and not isinstance(config["verbose"], bool):
            raise ValueError("Configuration verbose must be a boolean")
        if "log_level" in config and str(config["log_level"]).upper() not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ValueError("Invalid configuration log_level")
        env = config.get("env", {})
        if not isinstance(env, dict) or any(
            not isinstance(k, str)
            or not k
            or "=" in k
            or "\0" in k
            or not isinstance(v, str)
            or "\0" in v
            for k, v in env.items()
        ):
            raise ValueError("Configuration env must map variable names to string values")
        return config
    return {}


def config_environment(config: dict[str, Any]) -> dict[str, str]:
    """Environment overrides file defaults, including explicitly empty values."""
    return {**config.get("env", {}), **os.environ}


def get_src_path(platform: str) -> Path:
    """Return the platform package directory (legacy helper name)."""
    return _SERVERS_DIR / platform


def build_pythonpath(platforms: list[str]) -> str:
    """Return the package parent for source and installed-wheel launches."""
    return str(_REPO_ROOT)


# ── Health Check ───────────────────────────────────────────


def check_server_health(platform: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Inspect local configuration/imports; never claim live authorization."""
    info = SERVER_REGISTRY.get(platform)
    if not info:
        return {"platform": platform, "status": "error", "error": f"Unknown platform: {platform}"}
    effective_env = os.environ if env is None else env
    fields = PLATFORM_ENV_FIELDS[platform]
    required = fields
    config_error = None
    if platform == "weixin_store":
        mode = effective_env.get("WX_TOKEN_MODE") or ("static" if effective_env.get("WX_ACCESS_TOKEN") else "managed")
        if mode == "static":
            required = ("WX_ACCESS_TOKEN",)
        elif mode == "managed":
            required = ("WX_APP_ID", "WX_APP_SECRET")
        else:
            required = ()
            config_error = "WX_TOKEN_MODE must be static or managed"
    missing = [name for name in required if not effective_env.get(name)]
    result: dict[str, Any] = {
        "platform": platform,
        "description": info["description"],
        "module": info["module"],
        "env_configured": not missing and config_error is None,
        "env_vars": {name: "set" if effective_env.get(name) else "missing" for name in fields},
        "required_env_vars": list(required),
        "missing_env_vars": missing,
        "importable": False,
        "check_scope": "local_configuration",
        "protocol_status": "not_checked",
        "authorization_status": "not_checked",
    }
    if config_error:
        result["error"] = config_error
    try:
        module = importlib.import_module(info["module"])
        result["importable"] = True
        result["server_path"] = str(module.__file__)
    except Exception as exc:
        # Import-time configuration errors may contain secrets. Report the
        # exception class only; credentials never belong in health output.
        result["import_error"] = type(exc).__name__
    if result["importable"] and result["env_configured"]:
        result["status"] = "ready"
    elif result["importable"]:
        result["status"] = "importable_no_creds"
    else:
        result["status"] = "not_ready"
    return result


def check_all_health(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Check local configuration of all registered platforms."""
    return [check_server_health(platform, env) for platform in SERVER_REGISTRY]


# ── Server Launch ──────────────────────────────────────────


def start_server(platform: str, env: dict[str, str] | None = None) -> None:
    """Run one installed platform module on this stdio connection."""
    if platform not in SERVER_REGISTRY:
        print(f"Error: Unknown platform '{platform}'", file=sys.stderr)
        sys.exit(1)
    child_env = (os.environ if env is None else env).copy()
    pythonpath = build_pythonpath([platform])
    existing = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = f"{pythonpath}{os.pathsep}{existing}" if existing else pythonpath
    cmd = [sys.executable, "-m", SERVER_REGISTRY[platform]["module"]]
    logging.info("Starting %s server", platform)
    try:
        # Inherit cwd for user-provided relative paths. The module is located
        # through the installed package, without relying on a source/src tree.
        result = subprocess.run(cmd, env=child_env, check=False)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(0)
    except OSError as exc:
        print(f"Error starting {platform}: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)


def start_servers(platforms: list[str], env: dict[str, str] | None = None) -> None:
    """Require one platform per MCP stdio connection."""
    if len(platforms) != 1:
        print(
            "Error: Start exactly one platform per stdio connection. "
            "Configure a separate MCP client connection for each platform.",
            file=sys.stderr,
        )
        sys.exit(1)
    start_server(platforms[0], env)


# ── Version ────────────────────────────────────────────────


def show_version(verbose: bool = False) -> None:
    """Print version information.

    Args:
        verbose: If True, show additional environment details.
    """
    print(f"mcp-cn-commerce CLI v{__version__}")
    if verbose:
        print(f"Python: {sys.version}")
        print(f"Platform: {sys.platform}")
        print(f"Repo root: {_REPO_ROOT}")
        print(f"Available servers: {len(SERVER_REGISTRY)}")
        for name, info in SERVER_REGISTRY.items():
            src = get_src_path(name)
            status = "found" if src.is_dir() else "missing"
            print(f"  - {name}: {info['description']} [{status}]")


# ── List Platforms ─────────────────────────────────────────


def list_platforms() -> None:
    """Print a formatted list of available platforms."""
    print("Available MCP servers:\n")
    print(f"{'Platform':<16} {'Module':<28} {'Description'}")
    print("-" * 80)
    for name, info in SERVER_REGISTRY.items():
        print(f"{name:<16} {info['module']:<28} {info['description']}")
    print(f"\nTotal: {len(SERVER_REGISTRY)} platforms")


# ── CLI Argument Parser ────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="mcp-cn-commerce",
        description="CLI tool for Chinese e-commerce MCP servers",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to configuration file (JSON)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start command
    start_parser = subparsers.add_parser(
        "start",
        help="Start one MCP server per stdio connection",
    )
    start_parser.add_argument(
        "platforms",
        nargs="*",
        metavar="PLATFORM",
        help=f"Platform to start (or config servers). Available: {', '.join(SERVER_REGISTRY)}",
    )

    # health command
    health_parser = subparsers.add_parser(
        "health",
        help="Check health of MCP servers",
    )
    health_parser.add_argument(
        "platforms",
        nargs="*",
        metavar="PLATFORM",
        help="Platform(s) to check (default: all)",
    )
    health_parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output as JSON",
    )

    # version command
    version_parser = subparsers.add_parser(
        "info",
        help="Show version and environment info",
    )
    version_parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output as JSON",
    )

    # list command
    subparsers.add_parser(
        "list",
        help="List available MCP server platforms",
    )

    return parser


def format_health_output(results: list[dict[str, Any]], as_json: bool = False) -> str:
    """Format health check results for display.

    Args:
        results: List of health check result dicts.
        as_json: If True, return JSON string.

    Returns:
        Formatted string.
    """
    if as_json:
        return json.dumps(results, indent=2, ensure_ascii=False)

    lines: list[str] = []
    status_icons = {
        "ready": "[READY]",
        "importable_no_creds": "[NO CREDS]",
        "not_ready": "[NOT READY]",
        "error": "[ERROR]",
        "unknown": "[UNKNOWN]",
    }

    for r in results:
        icon = status_icons.get(r["status"], "[?]")
        lines.append(f"{icon} {r['platform']}: {r.get('description', '')}")
        if r.get("check_scope") == "local_configuration":
            lines.append("       Local checks only; MCP handshake and platform authorization not checked")
        if r.get("env_vars"):
            for var, val in r["env_vars"].items():
                lines.append(f"       {var}: {val}")
        if r.get("import_error"):
            lines.append(f"       Import error: {r['import_error']}")
        if r.get("error"):
            lines.append(f"       Error: {r['error']}")

    return "\n".join(lines)


# ── Main Entry Point ───────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:]).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ValueError as exc:
        parser.error(str(exc))
    env = config_environment(config)
    # CLI verbose takes precedence, then config verbose, then config log_level.
    log_level = (
        logging.DEBUG
        if args.verbose or config.get("verbose", False)
        else getattr(logging, str(config.get("log_level", "INFO")).upper())
    )
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        start_servers(args.platforms or config.get("servers", []), env)

    elif args.command == "health":
        platforms = args.platforms or config.get("servers", [])
        if platforms:
            results = [check_server_health(p, env) for p in platforms]
        else:
            results = check_all_health(env)
        print(format_health_output(results, as_json=args.output_json))

    elif args.command == "info":
        if args.output_json:
            info = {
                "version": __version__,
                "python": sys.version,
                "platform": sys.platform,
                "repo_root": str(_REPO_ROOT),
                "servers": {
                    name: {
                        "module": info["module"],
                        "description": info["description"],
                        "src_found": get_src_path(name).is_dir(),
                    }
                    for name, info in SERVER_REGISTRY.items()
                },
            }
            print(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            show_version(verbose=True)

    elif args.command == "list":
        list_platforms()


if __name__ == "__main__":
    main()
