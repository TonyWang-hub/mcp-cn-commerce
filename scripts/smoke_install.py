"""Exercise installed entry points over actual MCP stdio JSON-RPC.

Run from a neutral directory after installing the wheel into a clean venv:
    python /path/to/repo/scripts/smoke_install.py
Add --docker IMAGE to exercise the same commands inside the built image.
No merchant API requests or real credentials are used. The client speaks the
wire protocol directly so the test does not depend on a particular SDK client
API; the server processes always load the actual installed MCP SDK.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

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
    "WX_TOKEN_MODE": "static",
}

# Five common tools per server, including the deterministic report builder.
EXPECTED_TOOLS = {
    "oceanengine": 23,
    "doudian": 25,
    "jd": 20,
    "taobao": 18,
    "pinduoduo": 18,
    "kuaishou": 17,
    "xiaohongshu": 18,
    "weixin_store": 16,
}

BUSINESS_CALLS = {
    "oceanengine": ("get_advertiser_info", {"advertiser_ids": "1"}),
    "doudian": ("get_order_detail", {"order_id": "1"}),
    "jd": ("get_order_detail", {"order_id": "1"}),
    "taobao": ("get_order_detail", {"tid": "1"}),
    "pinduoduo": ("get_order_detail", {"order_sn": "1"}),
    "kuaishou": ("get_order_detail", {"order_id": "1"}),
    "xiaohongshu": ("get_order_detail", {"order_id": "1"}),
    "weixin_store": ("get_order_detail", {"order_id": "1"}),
}


def registry_arguments(manifest: dict, platform: str) -> list[str]:
    """Resolve the published positional arguments exactly as a consumer does."""
    package = manifest["packages"][0]
    assert package["identifier"] == "mcp-cn-commerce"
    assert package["transport"]["type"] == "stdio"
    resolved = []
    for argument in package["packageArguments"]:
        assert argument["type"] == "positional"
        if "value" in argument:
            resolved.append(argument["value"])
        else:
            assert argument["valueHint"] == "platform"
            assert platform in argument["choices"]
            resolved.append(platform)
    assert resolved == ["start", platform]
    return resolved


async def _receive(proc: asyncio.subprocess.Process, request_id: int) -> dict:
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            raise AssertionError(f"Server closed stdout before response {request_id}")
        message = json.loads(line)  # Any non-protocol stdout is a test failure.
        assert message.get("jsonrpc") == "2.0", message
        if message.get("id") == request_id:
            assert "error" not in message, message
            return message["result"]


async def _send(proc: asyncio.subprocess.Process, method: str, params: dict, request_id: int | None = None):
    assert proc.stdin is not None
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    if request_id is not None:
        message["id"] = request_id
    proc.stdin.write((json.dumps(message) + "\n").encode())
    await proc.stdin.drain()
    if request_id is not None:
        return await _receive(proc, request_id)
    return None


async def exercise(command: list[str], platform: str, *, missing_credentials=False, docker=None) -> None:
    """Check handshake, tool success, tool failure, and process cleanup."""
    credentials = {key: "" for key in _DUMMY_ENV} if missing_credentials else _DUMMY_ENV
    env = {**os.environ, **credentials}
    env.pop("PYTHONPATH", None)
    if docker:
        environment_arguments = [item for key, value in credentials.items() for item in ("-e", f"{key}={value}")]
        command = ["docker", "run", "--rm", "-i", *environment_arguments, docker, *command]
    # Keep all diagnostic logs off stdout and drain them without pipe deadlock.
    with tempfile.TemporaryFile() as errors:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=errors,
            env=env,
            start_new_session=os.name != "nt",
        )
        try:
            async with asyncio.timeout(30):
                initialized = await _send(
                    proc,
                    "initialize",
                    {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp-cn-commerce-install-smoke", "version": "1.0.0"},
                    },
                    1,
                )
                assert initialized.get("protocolVersion"), initialized
                assert "tools" in initialized["capabilities"], initialized
                await _send(proc, "notifications/initialized", {})
                listed = await _send(proc, "tools/list", {}, 2)
                names = {tool["name"] for tool in listed["tools"]}
                assert len(names) == EXPECTED_TOOLS[platform], (platform, len(names))
                assert {"get_metrics", "export_data", "build_daily_report"} <= names
                metrics = await _send(proc, "tools/call", {"name": "get_metrics", "arguments": {}}, 3)
                assert not metrics.get("isError", False), metrics
                assert metrics.get("content") or metrics.get("structuredContent"), metrics
                if missing_credentials:
                    name, arguments = BUSINESS_CALLS[platform]
                    failure = await _send(proc, "tools/call", {"name": name, "arguments": arguments}, 4)
                    # Some adapters return an error object; others use MCP
                    # isError. In both cases require the actual config failure.
                    failure_text = json.dumps(failure).lower()
                    assert "missing" in failure_text and "environment" in failure_text, failure
                else:
                    exported = await _send(
                        proc,
                        "tools/call",
                        {"name": "export_data", "arguments": {"records_json": '[{"id":"smoke"}]'}},
                        4,
                    )
                    assert not exported.get("isError", False), exported
                    assert "smoke" in json.dumps(exported), exported
                    failure = await _send(
                        proc, "tools/call", {"name": "export_data", "arguments": {"records_json": "{"}}, 5
                    )
                    assert failure.get("isError") is True, failure
                # An error must not tear down the MCP connection.
                after = await _send(proc, "tools/list", {}, 6)
                assert len(after["tools"]) == EXPECTED_TOOLS[platform]
        finally:
            if proc.stdin:
                proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except TimeoutError:
                    if os.name != "nt":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    await proc.wait()
        assert proc.returncode == 0, f"Server exit code {proc.returncode}"


async def run_smoke(manifest: dict, docker: str | None) -> list[str]:
    failures = []
    for platform in EXPECTED_TOOLS:
        cli = ["mcp-cn-commerce", *registry_arguments(manifest, platform)]
        standalone = ["mcp-cn-" + platform.replace("_", "-")]
        for label, command, missing in (
            ("registry CLI", cli, False),
            ("standalone", standalone, False),
            ("no credentials", cli, True),
        ):
            try:
                await exercise(command, platform, missing_credentials=missing, docker=docker)
                print(f"  {platform} [{label}]: handshake, tools, calls OK", flush=True)
            except Exception as exc:
                failures.append(f"{platform} [{label}]: {type(exc).__name__}: {exc}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", metavar="IMAGE")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1] / "server.json")
    args = parser.parse_args()
    if (Path.cwd() / "pyproject.toml").exists() and (Path.cwd() / "servers").is_dir():
        print("FATAL: run this script from a neutral cwd, not the repo root")
        return 2
    failures = []
    if not args.docker:
        shared = importlib.import_module("shared")
        if "site-packages" not in Path(shared.__file__).parts:
            print(f"FATAL: imported source tree instead of installed package: {shared.__file__}")
            return 2
        manifest = json.loads(args.manifest.read_text())
        assert manifest["version"] == shared.__version__
        assert manifest["packages"][0]["version"] == shared.__version__
        print(f"installed package version: {shared.__version__}")
        for entry in ["mcp-cn-commerce", *("mcp-cn-" + name.replace("_", "-") for name in EXPECTED_TOOLS)]:
            if shutil.which(entry) is None:
                failures.append(f"Entry point missing: {entry}")
    else:
        manifest = json.loads(args.manifest.read_text())
    if not failures:
        failures.extend(asyncio.run(run_smoke(manifest, args.docker)))
    if failures:
        print("SMOKE TEST FAILED:\n" + "\n".join(failures))
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
