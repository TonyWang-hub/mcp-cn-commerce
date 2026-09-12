"""Public distribution guards reject private code before build or upload."""

import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_public_boundary.py"


def checker():
    assert SCRIPT.is_file(), "public package boundary checker is not implemented"
    spec = importlib.util.spec_from_file_location("public_boundary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source(tmp_path):
    (tmp_path / "shared").mkdir()
    (tmp_path / "servers").mkdir()
    (tmp_path / "shared/__init__.py").write_text('__version__ = "0.1.6"\n')
    (tmp_path / "servers/__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools>=77"]\n'
        '[project]\nname = "mcp-cn-commerce"\ndependencies = ["httpx>=0.27"]\n'
    )
    return tmp_path


@pytest.mark.parametrize(
    "statement",
    [
        "import pro.runtime",
        "from pro import licensing",
        "import cn_commerce_client",
        'import importlib; importlib.import_module("pro.runtime")',
        'from importlib import import_module as load; load("pro.runtime")',
        '__import__("cn_commerce_client")',
    ],
)
def test_source_rejects_private_runtime_imports(tmp_path, statement):
    root = source(tmp_path)
    (root / "shared/bad.py").write_text(statement)
    with pytest.raises(ValueError, match="private import"):
        checker().check_source(root)


@pytest.mark.parametrize(
    "dependency",
    [
        "mcp-cn-commerce-pro>=0.1",
        "MCP_CN_COMMERCE_CLIENT==0.1.0b1",
        "renamed @ git+https://github.com/example/mcp-cn-commerce-pro.git",
    ],
)
def test_source_rejects_private_dependencies(tmp_path, dependency):
    root = source(tmp_path)
    with (root / "pyproject.toml").open("a") as output:
        output.write(f'\n[project.optional-dependencies]\nextra = ["{dependency}"]\n')
    with pytest.raises(ValueError, match="private dependency"):
        checker().check_source(root)


def test_source_rejects_private_tree_even_if_packager_excludes_it(tmp_path):
    root = source(tmp_path)
    (root / "pro").mkdir()
    (root / "pro/licensing.py").write_text("PRIVATE_IMPLEMENTATION = True")
    with pytest.raises(ValueError, match="private path"):
        checker().check_source(root)


def test_public_source_and_documentation_references_remain_allowed(tmp_path):
    root = source(tmp_path)
    (root / "shared/good.py").write_text('from shared import aggregation\nDOC = "Pro is a separate project"\n')
    (root / "README.md").write_text("Core supports multiple shops. Private Pro adds governance.")
    checker().check_source(root)


def wheel(path, extra=None, dependency="httpx>=0.27"):
    files = {
        "shared/__init__.py": '__version__ = "0.1.6"',
        "servers/__init__.py": "",
        "mcp_cn_commerce-0.1.6.dist-info/METADATA": (
            "Metadata-Version: 2.4\nName: mcp-cn-commerce\nVersion: 0.1.6\n" f"Requires-Dist: {dependency}\n"
        ),
        "mcp_cn_commerce-0.1.6.dist-info/top_level.txt": "shared\nservers\n",
        "mcp_cn_commerce-0.1.6.dist-info/entry_points.txt": "[console_scripts]\nmcp-cn-commerce = shared.cli:main\n",
    }
    files.update(extra or {})
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


@pytest.mark.parametrize(
    "extra",
    [
        {"pro/runtime.py": "PRIVATE = True"},
        {"cn_commerce_client/__init__.py": ""},
        {"other/runtime.py": "PRIVATE = True"},
        {"shared/pro/licensing.py": "PRIVATE = True"},
        {"mcp_cn_commerce-0.1.6.data/purelib/pro/runtime.py": "PRIVATE = True"},
        {"../pro/runtime.py": "PRIVATE = True"},
    ],
)
def test_wheel_rejects_private_or_unexpected_payload(tmp_path, extra):
    path = wheel(tmp_path / "core.whl", extra)
    with pytest.raises(ValueError):
        checker().check_artifact(path)


def test_wheel_rejects_generated_metadata_private_dependency(tmp_path):
    path = wheel(tmp_path / "core.whl", dependency="mcp-cn-commerce-pro>=0.1")
    with pytest.raises(ValueError, match="private dependency"):
        checker().check_artifact(path)


def test_wheel_rejects_private_entrypoint_and_top_level(tmp_path):
    for extra in (
        {"mcp_cn_commerce-0.1.6.dist-info/entry_points.txt": "[console_scripts]\ncore = pro.cli:main\n"},
        {"mcp_cn_commerce-0.1.6.dist-info/top_level.txt": "shared\nservers\npro\n"},
        {"shared/hidden.py": "from pro.runtime import CommerceRuntime"},
    ):
        path = wheel(tmp_path / "core.whl", extra)
        with pytest.raises(ValueError):
            checker().check_artifact(path)


def sdist(path, extra=None):
    files = {
        "mcp_cn_commerce-0.1.6/PKG-INFO": "Metadata-Version: 2.4\nName: mcp-cn-commerce\nVersion: 0.1.6\n",
        "mcp_cn_commerce-0.1.6/shared/__init__.py": "",
        "mcp_cn_commerce-0.1.6/servers/__init__.py": "",
        "mcp_cn_commerce-0.1.6/pyproject.toml": '[project]\nname="mcp-cn-commerce"\ndependencies=[]\n',
    }
    files.update(extra or {})
    with tarfile.open(path, "w:gz") as archive:
        for name, text in files.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path


def test_sdist_rejects_private_source_and_embedded_dependency(tmp_path):
    for extra in (
        {"mcp_cn_commerce-0.1.6/pro/runtime.py": "PRIVATE=True"},
        {"mcp_cn_commerce-0.1.6/shared/hidden.py": "import pro"},
        {"mcp_cn_commerce-0.1.6/mcp_cn_commerce.egg-info/requires.txt": "mcp-cn-commerce-pro>=0.1"},
    ):
        with pytest.raises(ValueError):
            checker().check_artifact(sdist(tmp_path / "core.tar.gz", extra))


def test_clean_artifacts_pass_without_installing_or_extracting(tmp_path):
    checker().check_artifact(wheel(tmp_path / "core.whl"))
    checker().check_artifact(sdist(tmp_path / "core.tar.gz"))
    assert not (tmp_path / "mcp_cn_commerce-0.1.6").exists()


def test_cli_rejects_empty_distribution_directory(tmp_path):
    root = source(tmp_path)
    (root / "dist").mkdir()
    assert SCRIPT.is_file(), "public package boundary checker is not implemented"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--dist", str(root / "dist")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0 and "distribution" in result.stderr


@pytest.mark.parametrize("container", ["source", "wheel", "sdist"])
@pytest.mark.parametrize(
    "statement",
    [
        "import importlib; importlib.import_module(name='pro.runtime')",
        "from importlib import import_module; import_module(name='cn_commerce_client')",
        "import importlib as loader; loader.import_module('.runtime', package='pro')",
        "from importlib import import_module as load; load(name='..runtime', package='pro.nested')",
        "import importlib; importlib.import_module('.runtime', 'pro')",
        "__import__(name='cn_commerce_client')",
    ],
)
def test_literal_dynamic_private_import_forms_are_rejected(tmp_path, container, statement):
    guard = checker()
    with pytest.raises(ValueError, match="private import"):
        if container == "source":
            root = source(tmp_path)
            (root / "shared/bad.py").write_text(statement)
            guard.check_source(root)
        elif container == "wheel":
            guard.check_artifact(wheel(tmp_path / "core.whl", {"shared/bad.py": statement}))
        else:
            guard.check_artifact(sdist(tmp_path / "core.tar.gz", {"mcp_cn_commerce-0.1.6/shared/bad.py": statement}))


@pytest.mark.parametrize("container", ["source", "wheel", "sdist"])
@pytest.mark.parametrize("filename", ["pro.cpython-312-x86_64-linux-gnu.so", "cn_commerce_client.pyc"])
def test_known_private_binary_names_are_rejected(tmp_path, container, filename):
    guard = checker()
    with pytest.raises(ValueError, match="private path"):
        if container == "source":
            root = source(tmp_path)
            (root / "shared" / filename).write_bytes(b"private payload")
            guard.check_source(root)
        elif container == "wheel":
            guard.check_artifact(wheel(tmp_path / "core.whl", {f"shared/{filename}": "private payload"}))
        else:
            guard.check_artifact(
                sdist(tmp_path / "core.tar.gz", {f"mcp_cn_commerce-0.1.6/shared/{filename}": "private payload"})
            )
