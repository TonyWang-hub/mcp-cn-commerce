"""Run the deterministic report example without merchant credentials or HTTP.

From the repository root:
    python examples/daily-report/generate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.aggregation import build_daily_report


def main() -> None:
    payload = json.loads(Path(__file__).with_name("input.json").read_text(encoding="utf-8"))
    report = build_daily_report(payload["date"], payload["shops"], timezone=payload["timezone"])
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
