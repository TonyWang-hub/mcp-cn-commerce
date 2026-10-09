"""Static guardrails keep platform business tools on the capability wrapper."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATHS = sorted((ROOT / "servers").glob("*/server.py"))


def _decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


@pytest.mark.parametrize("path", SERVER_PATHS, ids=lambda path: path.parent.name)
def test_every_platform_business_tool_uses_capability_registration(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    business_tools = []
    legacy_registrations = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = {_decorator_name(decorator) for decorator in node.decorator_list}
        if "business_tool" in decorators:
            business_tools.append(node.name)
        if "tool" in decorators:
            legacy_registrations.append(node.name)

    assert business_tools, f"{path} has no capability-aware business tools"
    assert (
        not legacy_registrations
    ), f"{path} bypasses capability discovery/guards: {', '.join(sorted(legacy_registrations))}"
