"""Reject accidental private dependencies, imports and payloads in public Core.

This static packaging gate does not prove provenance of renamed/copied code or
resolve arbitrary computed imports. It needs no installed product or network.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import re
import sys
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from importlib.util import resolve_name
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

PUBLIC_NAMESPACES = frozenset({"shared", "servers"})
PRIVATE_NAMESPACES = frozenset({"pro", "cn_commerce_client", "mcp_cn_commerce_pro", "mcp_cn_commerce_client"})
PRIVATE_DISTRIBUTIONS = frozenset({"mcp-cn-commerce-pro", "mcp-cn-commerce-client"})
SDIST_ROOTS = frozenset(
    {
        "shared",
        "servers",
        "tests",
        "scripts",
        "docs",
        "mcp_cn_commerce.egg-info",
        "LICENSE",
        "PKG-INFO",
        "README.md",
        "README_en.md",
        "CHANGELOG.md",
        "pyproject.toml",
        "setup.cfg",
        "server.json",
        "requirements-lock.txt",
    }
)
WHEEL_METADATA = frozenset(
    {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt", "LICENSE", "licenses/LICENSE"}
)
SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "venv", "build", "dist", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)


def _private_module(name: str) -> bool:
    return name.split(".", 1)[0] in PRIVATE_NAMESPACES


def _private_path(path: PurePosixPath) -> bool:
    private = PRIVATE_NAMESPACES | PRIVATE_DISTRIBUTIONS
    return any(part.split(".", 1)[0] in private for part in path.parts)


def _dependency(value: str, location: str) -> None:
    normalized = re.sub(r"[-_.]+", "-", unquote(value).casefold().replace(".git", ""))
    if any(
        re.search(r"(?<![a-z0-9-])" + re.escape(name) + r"(?=$|[^a-z0-9-]|-[0-9])", normalized)
        for name in PRIVATE_DISTRIBUTIONS
    ):
        raise ValueError(f"{location}: private dependency")
    # Also reject direct use of the private import namespace as a distribution.
    first = re.match(r"[a-z0-9-]+", normalized)
    if first and first.group() in {"pro", "cn-commerce-client"}:
        raise ValueError(f"{location}: private dependency")


def _project(content: str, location: str) -> None:
    project = tomllib.loads(content)
    metadata = project.get("project", {})
    if metadata.get("name") != "mcp-cn-commerce":
        raise ValueError(f"{location}: expected public Core project name")
    if "dependencies" in metadata.get("dynamic", []) or "optional-dependencies" in metadata.get("dynamic", []):
        raise ValueError(f"{location}: dynamic dependencies require an explicit boundary policy")
    groups = [metadata.get("dependencies", []), project.get("build-system", {}).get("requires", [])]
    groups.extend(metadata.get("optional-dependencies", {}).values())
    for group in groups:
        for requirement in group:
            _dependency(requirement, location)
    entry_groups = [metadata.get("scripts", {}), metadata.get("gui-scripts", {})]
    entry_groups.extend(metadata.get("entry-points", {}).values())
    for group in entry_groups:
        for target in group.values():
            if _private_module(target.split(":", 1)[0].strip()):
                raise ValueError(f"{location}: private entry point")


def _literal_argument(node: ast.Call, keyword: str, position: int) -> str | None:
    argument = next((item.value for item in node.keywords if item.arg == keyword), None)
    if argument is None and len(node.args) > position:
        argument = node.args[position]
    return argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else None


def _python(content: str, location: str) -> None:
    tree = ast.parse(content, filename=location)
    importlib_names = {"importlib"}
    importer_names = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _private_module(alias.name):
                    raise ValueError(f"{location}:{node.lineno}: private import")
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if not node.level and _private_module(node.module or ""):
                raise ValueError(f"{location}:{node.lineno}: private import")
            if node.module == "importlib":
                importer_names.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        direct = isinstance(node.func, ast.Name) and node.func.id in importer_names
        qualified = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in importlib_names
        )
        if not (direct or qualified):
            continue
        name = _literal_argument(node, "name", 0)
        if name is None:
            continue
        package = _literal_argument(node, "package", 1)
        if name.startswith(".") and package is not None:
            try:
                name = resolve_name(name, package)
            except (ImportError, ValueError):
                continue
        if _private_module(name):
            raise ValueError(f"{location}:{node.lineno}: private import")


def _metadata(content: str, location: str) -> None:
    metadata = Parser().parsestr(content)
    if re.sub(r"[-_.]+", "-", metadata.get("Name", "").lower()) != "mcp-cn-commerce":
        raise ValueError(f"{location}: distribution is not public Core")
    for requirement in metadata.get_all("Requires-Dist", []):
        _dependency(requirement, location)


def _content(path: PurePosixPath, payload: bytes) -> None:
    filename = path.name
    if filename.endswith(".py"):
        _python(payload.decode("utf-8-sig"), str(path))
    elif filename == "pyproject.toml":
        _project(payload.decode(), str(path))
    elif filename in {"METADATA", "PKG-INFO"}:
        _metadata(payload.decode(), str(path))
    elif filename == "requires.txt" or filename.startswith("requirements") and filename.endswith(".txt"):
        for line in payload.decode().splitlines():
            _dependency(line, str(path))
    elif filename == "top_level.txt":
        if set(payload.decode().split()) - PUBLIC_NAMESPACES:
            raise ValueError(f"{path}: unexpected top-level import namespace")
    elif filename == "entry_points.txt":
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(payload.decode())
        for section in config.sections():
            for target in config[section].values():
                if _private_module(target.split(":", 1)[0].strip()):
                    raise ValueError(f"{path}: private entry point")


def check_source(root: Path) -> None:
    root = root.resolve()
    if not (root / "pyproject.toml").is_file():
        raise ValueError("source pyproject.toml is missing")
    for path in root.rglob("*"):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if any(part in SKIP_DIRECTORIES or part.endswith(".egg-info") for part in relative.parts):
            continue
        if _private_path(relative):
            raise ValueError(f"{relative}: private path in public Core source")
        if path.is_symlink() and relative.parts[0] in PUBLIC_NAMESPACES:
            raise ValueError(f"{relative}: linked runtime source is not accepted")
        runtime_source = path.suffix == ".py" and relative.parts[0] in PUBLIC_NAMESPACES | {"scripts"}
        dependency_manifest = relative.name == "pyproject.toml" or (
            relative.name.startswith("requirements") and relative.suffix == ".txt"
        )
        if path.is_file() and (runtime_source or dependency_manifest):
            _content(relative, path.read_bytes())


def _path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or "\\" in name or "\x00" in name or path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe distribution member path")
    return path


def check_artifact(path: Path) -> None:
    members = []
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                if member.external_attr >> 16 & 0o170000 == 0o120000:
                    raise ValueError("linked distribution member")
                members.append((_path(member.filename), archive.read(member)))
        metadata_files = [name for name, _ in members if name.name == "METADATA"]
        if len(metadata_files) != 1 or not re.fullmatch(
            r"mcp_cn_commerce-[^/]+\.dist-info", metadata_files[0].parts[0]
        ):
            raise ValueError("expected one public Core wheel metadata directory")
        metadata_root = metadata_files[0].parts[0]
        for name, _ in members:
            if name.parts[0] not in PUBLIC_NAMESPACES | {metadata_root}:
                raise ValueError(f"{name}: unexpected wheel namespace")
            if name.parts[0] == metadata_root and name.relative_to(metadata_root).as_posix() not in WHEEL_METADATA:
                raise ValueError(f"{name}: unexpected wheel metadata payload")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("linked or special distribution member")
                name = _path(member.name)
                if len(name.parts) < 2 or not re.fullmatch(r"mcp_cn_commerce-[^/]+", name.parts[0]):
                    raise ValueError("unexpected source distribution root")
                members.append((PurePosixPath(*name.parts[1:]), archive.extractfile(member).read()))
        if not any(name.as_posix() == "PKG-INFO" for name, _ in members):
            raise ValueError("source distribution metadata is missing")
        for name, _ in members:
            if name.parts[0] not in SDIST_ROOTS:
                raise ValueError(f"{name}: unexpected source distribution namespace")
    else:
        raise ValueError(f"{path.name}: unsupported distribution format")
    names = [name.as_posix() for name, _ in members]
    if len(names) != len(set(names)):
        raise ValueError("duplicate distribution members")
    if not all(f"{namespace}/__init__.py" in names for namespace in PUBLIC_NAMESPACES):
        raise ValueError("public Core runtime namespace is missing")
    for name, payload in members:
        if _private_path(name):
            raise ValueError(f"{name}: private path in public distribution")
        _content(name, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist", type=Path, help="Check both wheel and sdist before installation/upload")
    args = parser.parse_args()
    try:
        check_source(args.root)
        if args.dist is not None:
            artifacts = sorted(args.dist.iterdir())
            if (
                not artifacts
                or not any(p.name.endswith(".whl") for p in artifacts)
                or not any(p.name.endswith(".tar.gz") for p in artifacts)
            ):
                raise ValueError("both wheel and source distribution are required")
            for artifact in artifacts:
                check_artifact(artifact)
    except (ValueError, OSError, SyntaxError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"Public boundary check failed: {exc}", file=sys.stderr)
        return 1
    print("Public Core boundary verified: source" + (", wheel and sdist." if args.dist is not None else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
