"""CLI tool for mcp-cn-commerce.

Provides commands to start MCP servers, check health, and show version info.
Supports configuration via files and environment variables.
"""

from __future__ import annotations

import argparse
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
        "module": "mcp_oceanengine.server",
        "env_prefix": "OCEANENGINE",
        "description": "Ocean Engine (巨量引擎) advertising platform",
    },
    "doudian": {
        "module": "mcp_doudian.server",
        "env_prefix": "DOUDIAN",
        "description": "Douyin Shop (抖店) e-commerce platform",
    },
    "jd": {
        "module": "mcp_jd.server",
        "env_prefix": "JD",
        "description": "JD.com (京东) e-commerce platform",
    },
    "taobao": {
        "module": "mcp_taobao.server",
        "env_prefix": "TAOBAO",
        "description": "Taobao (淘宝) e-commerce platform",
    },
    "pinduoduo": {
        "module": "mcp_pinduoduo.server",
        "env_prefix": "PINDUODUO",
        "description": "Pinduoduo (拼多多) e-commerce platform",
    },
    "kuaishou": {
        "module": "mcp_kuaishou.server",
        "env_prefix": "KUAISHOU",
        "description": "Kuaishou (快手) e-commerce platform",
    },
    "xiaohongshu": {
        "module": "mcp_xiaohongshu.server",
        "env_prefix": "XIAOHONGSHU",
        "description": "Xiaohongshu (小红书) e-commerce platform",
    },
    "weixin-store": {
        "module": "mcp_weixin_store.server",
        "env_prefix": "WEIXIN_STORE",
        "description": "Weixin Store (微信小店) e-commerce platform",
    },
}

# ── Path Setup ─────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHARED_DIR = _REPO_ROOT / "shared"
_SERVERS_DIR = _REPO_ROOT / "servers"

# ── Config File Support ────────────────────────────────────

DEFAULT_CONFIG_PATHS = [
    Path.cwd() / "mcp-cn-commerce.json",
    Path.home() / ".config" / "mcp-cn-commerce" / "config.json",
]


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration from a JSON file.

    Args:
        config_path: Optional explicit path to config file.

    Returns:
        Configuration dict, empty if no file found.
    """
    paths_to_try = []
    if config_path:
        paths_to_try.append(Path(config_path))
    else:
        paths_to_try.extend(DEFAULT_CONFIG_PATHS)

    for p in paths_to_try:
        if p.is_file():
            try:
                with open(p) as f:
                    config = json.load(f)
                logging.debug(f"Loaded config from {p}")
                return config
            except (json.JSONDecodeError, OSError) as e:
                logging.warning(f"Failed to load config from {p}: {e}")
    return {}


def get_src_path(platform: str) -> Path:
    """Get the src directory for a platform server.

    Args:
        platform: Platform name (e.g. 'oceanengine').

    Returns:
        Path to the platform's src directory.
    """
    return _SERVERS_DIR / platform / "src"


def build_pythonpath(platforms: list[str]) -> str:
    """Build PYTHONPATH string including shared dir and platform src dirs.

    Args:
        platforms: List of platform names.

    Returns:
        Colon-separated PYTHONPATH value.
    """
    paths = [str(_SHARED_DIR)]
    for platform in platforms:
        src = get_src_path(platform)
        if src.is_dir():
            paths.append(str(src))
    return os.pathsep.join(paths)


# ── Health Check ───────────────────────────────────────────


def check_server_health(platform: str) -> dict[str, Any]:
    """Check health of a single platform server.

    Verifies that the module can be imported and environment variables are set.

    Args:
        platform: Platform name.

    Returns:
        Health status dict.
    """
    info = SERVER_REGISTRY.get(platform)
    if not info:
        return {"platform": platform, "status": "error", "error": f"Unknown platform: {platform}"}

    result: dict[str, Any] = {
        "platform": platform,
        "description": info["description"],
        "module": info["module"],
        "status": "unknown",
        "env_configured": False,
        "importable": False,
    }

    # Check if env vars are set
    env_prefix = info["env_prefix"]
    key_var = f"{env_prefix}_APP_KEY"
    secret_var = f"{env_prefix}_APP_SECRET"
    token_var = f"{env_prefix}_ACCESS_TOKEN"

    has_key = bool(os.environ.get(key_var))
    has_secret = bool(os.environ.get(secret_var))
    has_token = bool(os.environ.get(token_var))

    result["env_vars"] = {
        key_var: "set" if has_key else "missing",
        secret_var: "set" if has_secret else "missing",
        token_var: "set" if has_token else "missing",
    }
    result["env_configured"] = has_key and has_secret

    # Check if module is importable
    src_path = get_src_path(platform)
    if src_path.is_dir():
        result["src_path"] = str(src_path)
        # Try importing by adding paths
        old_path = sys.path.copy()
        try:
            sys.path.insert(0, str(_SHARED_DIR))
            sys.path.insert(0, str(src_path))
            __import__(info["module"])
            result["importable"] = True
        except Exception as e:
            result["import_error"] = f"{type(e).__name__}: {e}"
        finally:
            sys.path = old_path
    else:
        result["error"] = f"Source directory not found: {src_path}"

    # Determine overall status
    if result["importable"] and result["env_configured"]:
        result["status"] = "ready"
    elif result["importable"]:
        result["status"] = "importable_no_creds"
    else:
        result["status"] = "not_ready"

    return result


def check_all_health() -> list[dict[str, Any]]:
    """Check health of all registered platform servers.

    Returns:
        List of health status dicts.
    """
    return [check_server_health(p) for p in SERVER_REGISTRY]


# ── Server Launch ──────────────────────────────────────────


def start_server(platform: str) -> None:
    """Start a single MCP server as a subprocess.

    Args:
        platform: Platform name to start.

    Raises:
        SystemExit: If platform is unknown or server fails to start.
    """
    if platform not in SERVER_REGISTRY:
        print(f"Error: Unknown platform '{platform}'", file=sys.stderr)
        print(f"Available platforms: {', '.join(SERVER_REGISTRY)}", file=sys.stderr)
        sys.exit(1)

    info = SERVER_REGISTRY[platform]
    src_path = get_src_path(platform)
    module_name = info["module"]

    if not src_path.is_dir():
        print(f"Error: Source directory not found: {src_path}", file=sys.stderr)
        sys.exit(1)

    # Build environment with correct PYTHONPATH
    env = os.environ.copy()
    pythonpath = build_pythonpath([platform])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{pythonpath}{os.pathsep}{existing}" if existing else pythonpath

    # Run the server module
    cmd = [sys.executable, "-m", module_name]
    logging.info(f"Starting {platform} server: {' '.join(cmd)}")
    logging.debug(f"PYPATH={env['PYTHONPATH']}")

    try:
        result = subprocess.run(cmd, env=env, cwd=str(_REPO_ROOT))
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        logging.info(f"Server {platform} stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting {platform} server: {e}", file=sys.stderr)
        sys.exit(1)


def start_servers(platforms: list[str]) -> None:
    """Start multiple MCP servers (sequential, first platform runs in foreground).

    For multiple platforms, subsequent platforms are started as background
    subprocesses. The first platform runs in the foreground so the CLI
    stays alive.

    Args:
        platforms: List of platform names to start.
    """
    if not platforms:
        print("Error: No platforms specified", file=sys.stderr)
        sys.exit(1)

    # Validate all platforms first
    for p in platforms:
        if p not in SERVER_REGISTRY:
            print(f"Error: Unknown platform '{p}'", file=sys.stderr)
            print(f"Available platforms: {', '.join(SERVER_REGISTRY)}", file=sys.stderr)
            sys.exit(1)

    if len(platforms) == 1:
        start_server(platforms[0])
        return

    # Multiple servers: start all but last in background, last in foreground
    env = os.environ.copy()
    pythonpath = build_pythonpath(platforms)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{pythonpath}{os.pathsep}{existing}" if existing else pythonpath

    bg_processes: list[subprocess.Popen[bytes]] = []
    try:
        for platform in platforms[:-1]:
            info = SERVER_REGISTRY[platform]
            cmd = [sys.executable, "-m", info["module"]]
            logging.info(f"Starting {platform} server in background: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, env=env, cwd=str(_REPO_ROOT))
            bg_processes.append(proc)

        # Run the last server in foreground
        last = platforms[-1]
        info = SERVER_REGISTRY[last]
        cmd = [sys.executable, "-m", info["module"]]
        logging.info(f"Starting {last} server in foreground: {' '.join(cmd)}")
        result = subprocess.run(cmd, env=env, cwd=str(_REPO_ROOT))
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        logging.info("Stopping all servers...")
        for proc in bg_processes:
            proc.terminate()
        for proc in bg_processes:
            proc.wait(timeout=5)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        for proc in bg_processes:
            proc.terminate()
        sys.exit(1)


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
        help="Start one or more MCP servers",
    )
    start_parser.add_argument(
        "platforms",
        nargs="+",
        metavar="PLATFORM",
        help=f"Platform(s) to start. Available: {', '.join(SERVER_REGISTRY)}",
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

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load config if specified
    if args.config:
        config = load_config(args.config)
        if config:
            logging.debug(f"Config loaded: {list(config.keys())}")

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        start_servers(args.platforms)

    elif args.command == "health":
        platforms = args.platforms if args.platforms else None
        if platforms:
            results = [check_server_health(p) for p in platforms]
        else:
            results = check_all_health()
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
