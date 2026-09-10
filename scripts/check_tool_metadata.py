"""Check README tool counts against registrations, without importing the SDK."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def tool_count(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                count += 1
    return count


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    base = ast.parse((root / "shared/cn_commerce_base.py").read_text(encoding="utf-8"))
    registration = next(
        node for node in base.body if isinstance(node, ast.FunctionDef) and node.name == "register_common_tools"
    )
    common = tool_count(registration)
    counts = {
        path.parent.name: tool_count(ast.parse(path.read_text(encoding="utf-8"))) + common
        for path in sorted((root / "servers").glob("*/server.py"))
    }
    problems = []
    for filename in ("README.md", "README_en.md"):
        text = (root / filename).read_text(encoding="utf-8")
        for name, expected in counts.items():
            match = re.search(r"^\| " + re.escape(name) + r" \| (\d+) \|", text, re.MULTILINE)
            if not match or int(match[1]) != expected:
                problems.append(f"{filename}: {name} must show {expected} tools")
        match = re.search(r"^\| \*\*(?:Total|合计)\*\* \| \*\*(\d+)\*\*", text, re.MULTILINE)
        if not match or int(match[1]) != sum(counts.values()):
            problems.append(f"{filename}: total must be {sum(counts.values())}")
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"Tool metadata consistent: {len(counts)} platforms, {common} common tools each, {sum(counts.values())} total.")


if __name__ == "__main__":
    main()
