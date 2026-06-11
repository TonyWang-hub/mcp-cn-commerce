"""Post-install smoke test — run against the INSTALLED package, never the repo.

Guards against the two failure modes that shipped broken releases in 0.1.x:
  * wheel missing packages / runtime dependencies (0.1.1 had no servers/ at all);
  * modules that import under mocked tests but crash against the real MCP SDK
    (0.1.2's oceanengine/doudian used Server.tool(), which doesn't exist).

Usage (the cwd MUST NOT be the repo root, or `import servers` resolves to the
working tree instead of site-packages):

    python -m venv /tmp/smoke && /tmp/smoke/bin/pip install dist/*.whl
    cd /tmp && /tmp/smoke/bin/python /path/to/repo/scripts/smoke_install.py
"""

from __future__ import annotations

import asyncio
import importlib
import os
import pathlib
import shutil
import sys

# Placeholder credentials: several servers build their API client eagerly at
# import time and exit if config is missing.
_DUMMY_ENV = {
    "OCEANENGINE_APP_KEY": "k",
    "OCEANENGINE_APP_SECRET": "s",
    "OCEANENGINE_ACCESS_TOKEN": "t",
    "DOUDIAN_APP_KEY": "k",
    "DOUDIAN_APP_SECRET": "s",
    "DOUDIAN_SHOP_ID": "1",
    "DOUDIAN_ACCESS_TOKEN": "t",
    "JD_APP_KEY": "k",
    "JD_APP_SECRET": "s",
    "JD_ACCESS_TOKEN": "t",
    "TAOBAO_APP_KEY": "k",
    "TAOBAO_APP_SECRET": "s",
    "TAOBAO_ACCESS_TOKEN": "t",
    "PINDUODUO_CLIENT_ID": "k",
    "PINDUODUO_CLIENT_SECRET": "s",
    "PINDUODUO_ACCESS_TOKEN": "t",
    "KUAISHOU_APP_KEY": "k",
    "KUAISHOU_APP_SECRET": "s",
    "KUAISHOU_SIGN_SECRET": "ss",
    "KUAISHOU_ACCESS_TOKEN": "t",
    "XHS_CLIENT_ID": "k",
    "XHS_CLIENT_SECRET": "s",
    "XHS_ACCESS_TOKEN": "t",
    "WX_APP_ID": "k",
    "WX_APP_SECRET": "s",
    "WX_ACCESS_TOKEN": "t123456",
}

# Registered tool count per server (4 common ops tools included). Update this
# table when tools are added or removed — drift here also means the README
# tool table is stale.
EXPECTED_TOOLS = {
    "oceanengine": 22,
    "doudian": 24,
    "jd": 19,
    "taobao": 17,
    "pinduoduo": 17,
    "kuaishou": 16,
    "xiaohongshu": 17,
    "weixin_store": 15,
}

ENTRY_POINTS = [
    "mcp-cn-commerce",
    "mcp-cn-oceanengine",
    "mcp-cn-doudian",
    "mcp-cn-jd",
    "mcp-cn-taobao",
    "mcp-cn-pinduoduo",
    "mcp-cn-kuaishou",
    "mcp-cn-xiaohongshu",
    "mcp-cn-weixin-store",
]


def main() -> int:
    failures: list[str] = []

    # Refuse to run from the repo root — cwd would shadow site-packages and
    # the whole test would silently validate the working tree instead.
    if (pathlib.Path.cwd() / "pyproject.toml").exists() and (pathlib.Path.cwd() / "servers").is_dir():
        print("FATAL: run this script from a neutral cwd, not the repo root")
        return 2

    os.environ.update(_DUMMY_ENV)

    shared = importlib.import_module("shared")
    if "site-packages" not in pathlib.Path(shared.__file__).parts:
        failures.append(f"'shared' imported from {shared.__file__}, not site-packages")
    print(f"package version: {shared.__version__}")

    for name, expected in EXPECTED_TOOLS.items():
        try:
            mod = importlib.import_module(f"servers.{name}.server")
        except Exception as exc:  # noqa: BLE001 — any import crash is the finding
            failures.append(f"servers.{name}.server failed to import: {exc!r}")
            continue
        instance = getattr(mod, "mcp", None) or getattr(mod, "server", None)
        if instance is None:
            failures.append(f"servers.{name}.server exposes neither 'mcp' nor 'server'")
            continue
        count = len(asyncio.run(instance.list_tools()))
        status = "OK" if count == expected else f"EXPECTED {expected}"
        print(f"  {name}: {count} tools [{status}]")
        if count != expected:
            failures.append(f"{name}: {count} tools registered, expected {expected}")

    for ep in ENTRY_POINTS:
        if shutil.which(ep) is None:
            failures.append(f"console script not on PATH: {ep}")
    print(f"entry points present: {sum(shutil.which(e) is not None for e in ENTRY_POINTS)}/{len(ENTRY_POINTS)}")

    if failures:
        print("\nSMOKE TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
