"""Regression tests for two latent bugs surfaced by wiring the advanced
features into the product (Item 3).

1. ``ExportFormat`` carried a stray ``@dataclass`` over a ``StrEnum``, making
   all members compare equal and unhashable — so export always emitted CSV.
2. ``FailoverManager.get_healthy_endpoint()`` deadlocked: it held a
   non-reentrant lock and then called ``is_circuit_open()`` which re-acquired
   it.
"""

from __future__ import annotations

from shared.cn_commerce_base import (
    DataExporter,
    ExportFormat,
    FailoverManager,
    LoadBalancer,
)


class TestExportFormatEnum:
    def test_members_are_distinct(self):
        assert ExportFormat.CSV != ExportFormat.JSON
        assert ExportFormat.JSON != ExportFormat.EXCEL

    def test_members_are_hashable(self):
        # Was unhashable (__hash__ = None) under the stray @dataclass.
        assert len({ExportFormat.CSV, ExportFormat.JSON, ExportFormat.EXCEL}) == 3

    def test_export_respects_format(self):
        rows = [{"a": 1, "b": 2}]
        as_json = DataExporter.export_to_string(rows, format=ExportFormat.JSON)
        as_csv = DataExporter.export_to_string(rows, format=ExportFormat.CSV)
        # JSON is a bracketed document; CSV is a header line + value line.
        assert as_json.lstrip().startswith("[")
        assert not as_csv.lstrip().startswith("[")
        assert "a" in as_csv and "b" in as_csv


class TestFailoverNoDeadlock:
    def test_get_healthy_endpoint_returns_without_deadlock(self):
        lb = LoadBalancer()
        lb.add_endpoint("https://a.test")
        lb.add_endpoint("https://b.test")
        fm = FailoverManager(load_balancer=lb)
        # Previously hung forever (reentrant lock re-acquire).
        endpoint = fm.get_healthy_endpoint()
        assert endpoint is not None
        assert endpoint.url in ("https://a.test", "https://b.test")
