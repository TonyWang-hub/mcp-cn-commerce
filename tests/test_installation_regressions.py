"""CLI configuration and packaging regressions, runnable with stdlib unittest.

The installed-wheel/stdout protocol gate lives in scripts/smoke_install.py;
these tests cover local configuration without requiring merchant access.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shared import cli

ROOT = Path(__file__).resolve().parents[1]


class InstallationRegressions(unittest.TestCase):
    def test_jd_smoke_reaches_missing_credentials_after_business_validation(self):
        exercise = runpy.run_path(str(ROOT / "scripts/smoke_install.py"))["exercise"]
        asyncio.run(exercise([sys.executable, "-m", "servers.jd.server"], "jd", missing_credentials=True))

    def test_each_platform_launches_actual_module_without_src_directory(self):
        for platform, info in cli.SERVER_REGISTRY.items():
            with self.subTest(platform=platform), patch.object(cli.subprocess, "run") as run:
                run.return_value.returncode = 0
                with self.assertRaises(SystemExit) as stopped:
                    cli.start_server(platform, {"EXAMPLE": "value"})
                self.assertEqual(stopped.exception.code, 0)
                self.assertEqual(run.call_args.args[0], [sys.executable, "-m", info["module"]])
                self.assertEqual(run.call_args.kwargs["env"]["EXAMPLE"], "value")
                self.assertNotIn("cwd", run.call_args.kwargs)
                self.assertTrue((cli.get_src_path(platform) / "server.py").is_file())

    def test_multi_platform_stdio_rejected_before_any_process(self):
        with patch.object(cli.subprocess, "run") as run, patch.object(cli.subprocess, "Popen") as popen:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.start_servers(["jd", "taobao"])
            run.assert_not_called()
            popen.assert_not_called()

    def test_environment_overrides_file_even_when_explicitly_empty(self):
        with patch.dict(os.environ, {"JD_APP_KEY": "env-key", "JD_ACCESS_TOKEN": ""}, clear=True):
            env = cli.config_environment(
                {"env": {"JD_APP_KEY": "file-key", "JD_APP_SECRET": "secret", "JD_ACCESS_TOKEN": "file-token"}}
            )
        self.assertEqual(env, {"JD_APP_KEY": "env-key", "JD_APP_SECRET": "secret", "JD_ACCESS_TOKEN": ""})

    def test_explicit_config_applies_env_and_default_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"servers": ["jd"], "env": {"JD_APP_KEY": "configured"}}))
            with patch.dict(os.environ, {}, clear=True), patch.object(cli, "start_servers") as start:
                cli.main(["--config", str(path), "start"])
            self.assertEqual(start.call_args.args[0], ["jd"])
            self.assertEqual(start.call_args.args[1]["JD_APP_KEY"], "configured")

    def test_explicit_cli_platform_overrides_config(self):
        with (
            patch.object(cli, "load_config", return_value={"servers": ["jd"]}),
            patch.object(cli, "start_servers") as start,
        ):
            cli.main(["start", "taobao"])
        self.assertEqual(start.call_args.args[0], ["taobao"])

    def test_default_config_is_loaded_without_config_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp-cn-commerce.json"
            path.write_text('{"servers": ["jd"]}')
            with patch.object(cli, "DEFAULT_CONFIG_PATHS", [path]), patch.object(cli, "start_servers") as start:
                cli.main(["start"])
            self.assertEqual(start.call_args.args[0], ["jd"])

    def test_invalid_config_fails_instead_of_changing_account_silently(self):
        invalid = [
            "[]",
            '{"env": []}',
            '{"env": {"JD_APP_KEY": 5}}',
            '{"servers": "jd"}',
            '{"servers": ["unknown"]}',
            '{"log_level": "TRACE"}',
            '{"verbose": "false"}',
            "{",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for data in invalid:
                with self.subTest(data=data):
                    path.write_text(data)
                    with self.assertRaises(ValueError):
                        cli.load_config(str(path))

    def health(self, platform, env):
        with patch.object(cli.importlib, "import_module", return_value=SimpleNamespace(__file__="server.py")):
            return cli.check_server_health(platform, env)

    def test_health_uses_real_pdd_and_xhs_fields(self):
        for platform in ("pinduoduo", "xiaohongshu", "kuaishou", "doudian"):
            env = dict.fromkeys(cli.PLATFORM_ENV_FIELDS[platform], "present")
            with self.subTest(platform=platform):
                self.assertTrue(self.health(platform, env)["env_configured"])
                del env[next(name for name in env if name.endswith("ACCESS_TOKEN"))]
                self.assertFalse(self.health(platform, env)["env_configured"])
        env = {"KUAISHOU_APP_KEY": "k", "KUAISHOU_APP_SECRET": "s", "KUAISHOU_ACCESS_TOKEN": "t"}
        self.assertFalse(self.health("kuaishou", env)["env_configured"])

    def test_health_accepts_oceanengine_token_and_weixin_modes(self):
        self.assertTrue(self.health("oceanengine", {"OCEANENGINE_ACCESS_TOKEN": "secret"})["env_configured"])
        self.assertTrue(self.health("weixin_store", {"WX_ACCESS_TOKEN": "secret"})["env_configured"])
        self.assertTrue(self.health("weixin_store", {"WX_APP_ID": "id", "WX_APP_SECRET": "secret"})["env_configured"])
        self.assertFalse(
            self.health("weixin_store", {"WX_TOKEN_MODE": "managed", "WX_ACCESS_TOKEN": "t"})["env_configured"]
        )
        self.assertFalse(
            self.health("weixin_store", {"WX_TOKEN_MODE": "static", "WX_APP_ID": "id", "WX_APP_SECRET": "s"})[
                "env_configured"
            ]
        )
        self.assertFalse(self.health("weixin_store", {"WX_TOKEN_MODE": "unknown"})["env_configured"])

    def test_health_never_claims_live_authorization_or_discloses_secret(self):
        result = self.health("oceanengine", {"OCEANENGINE_ACCESS_TOKEN": "super-secret-token"})
        self.assertEqual(result["authorization_status"], "not_checked")
        self.assertEqual(result["protocol_status"], "not_checked")
        self.assertNotIn("super-secret-token", json.dumps(result))

    def test_registry_commands_cover_all_platforms_and_real_credentials(self):
        manifest = json.loads((ROOT / "server.json").read_text())
        package = manifest["packages"][0]
        names = {field["name"] for field in package["environmentVariables"]}
        self.assertEqual(set(package["packageArguments"][1]["choices"]), set(cli.SERVER_REGISTRY))
        self.assertEqual(package["packageArguments"][0]["value"], "start")
        for fields in cli.PLATFORM_ENV_FIELDS.values():
            self.assertTrue(set(fields) <= names)

    def test_actual_cli_reports_packages_and_rejects_multiplexing(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "shared.cli", "info", "--json"],
                cwd=directory,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=True,
            )
            self.assertTrue(all(item["src_found"] for item in json.loads(result.stdout)["servers"].values()))
            result = subprocess.run(
                [sys.executable, "-m", "shared.cli", "start", "jd", "taobao"],
                cwd=directory,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("one platform", result.stderr)


if __name__ == "__main__":
    unittest.main()
