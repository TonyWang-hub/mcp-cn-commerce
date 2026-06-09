"""Pytest path bootstrap for the monorepo.

Centralizes what used to be a per-file ``sys.path.insert`` block scattered
across every test and server module. Adds:
  - the repo root, so ``import shared.cn_commerce_base`` resolves;
  - each ``servers/<platform>/src`` dir, so platform modules (``mcp_jd`` …)
    import without an editable install.

In production, servers depend on the ``mcp-cn-commerce`` distribution and are
installed normally — this file only serves the test/dev workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for _src in sorted((_ROOT / "servers").glob("*/src")):
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
