"""Report contract regressions with multi-shop, pagination and partial data."""

import copy
import unittest
from dataclasses import asdict

from shared.aggregation import build_daily_report
from shared.normalizer import OrderItem, UnifiedOrder, UnifiedRefund

TODAY = "2026-09-10"
YESTERDAY = "2026-09-09"


def shop(platform="doudian", shop_id="one"):
    return {
        "platform": platform,
        "shop_id": shop_id,
        "shop_name": shop_id,
        "orders": [],
        "refunds": [],
        "coverage": {day: {"orders": True, "refunds": True} for day in (TODAY, YESTERDAY)},
    }


def order(order_id="o1", amount=1999, paid_at="2026-09-10T00:30:00+08:00", platform="doudian"):
    return asdict(
        UnifiedOrder(
            order_id=order_id,
            platform=platform,
            status="paid",
            amount_paid=amount,
            paid_at=paid_at,
            items=[OrderItem(product_id="p1", product_name="Product", price=amount, quantity=1)],
        )
    )


def refund(refund_id="r1", order_id="o1", amount=299, completed_at="2026-09-10T12:00:00+08:00"):
    return asdict(
        UnifiedRefund(
            refund_id=refund_id,
            order_id=order_id,
            platform="doudian",
            amount=amount,
            status="completed",
            completed_at=completed_at,
        )
    )


def report(shops):
    return build_daily_report(TODAY, shops, timezone="Asia/Shanghai")


class AggregationTests(unittest.TestCase):
    def test_multishop_dedup_timezone_refunds_and_weighted_totals(self):
        a, b = shop(), shop(shop_id="two")
        paid = order()
        a["orders"] = [paid, copy.deepcopy(paid), order("old", 500, "2026-09-09T08:00:00+08:00")]
        a["refunds"] = [refund(), refund(), refund("r2", "older-order", 100)]
        b["orders"] = [order("o1", 3001, "2026-09-09T16:30:00Z")]
        result = report([b, a])
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_summary"]["gmv"], 5000)
        self.assertEqual(result["total_summary"]["order_count"], 2)
        self.assertEqual(result["total_summary"]["avg_order_value"], 2500)
        self.assertEqual(result["total_summary"]["refund_amount"], 399)
        self.assertEqual(result["total_summary"]["refund_count"], 2)
        self.assertEqual(result["total_summary"]["refund_rate"], 0.5)
        self.assertEqual(result["yesterday_summary"]["gmv"], 500)
        self.assertEqual(result["shops"][0]["duplicates_removed"], {"orders": 1, "refunds": 1})
        self.assertEqual(result, report([a, b]))

    def test_unconfirmed_page_coverage_never_presents_observed_totals_as_complete(self):
        a = shop()
        a["orders"] = [order()]
        del a["coverage"][TODAY]["orders"]
        result = report([a])
        self.assertFalse(result["complete"])
        self.assertIsNone(result["total_summary"]["order_count"])
        self.assertIsNone(result["total_summary"]["gmv"])
        self.assertEqual(result["shops"][0]["observed_summary"]["gmv"], 1999)
        self.assertTrue(result["yesterday_complete"])

    def test_incomplete_shop_invalidates_cross_shop_total(self):
        a, b = shop(), shop(shop_id="two")
        a["orders"] = [order()]
        b["errors"] = [{"code": "page_timeout", "token": "not-forwarded"}]
        result = report([a, b])
        self.assertIsNone(result["total_summary"]["gmv"])
        self.assertNotIn("not-forwarded", str(result))

    def test_invalid_money_remains_unknown_and_counts_remain_available(self):
        a = shop()
        a["orders"] = [order(amount=None)]
        result = report([a])
        self.assertEqual(result["total_summary"]["order_count"], 1)
        self.assertIsNone(result["total_summary"]["gmv"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["shops"][0]["observed_summary"]["known_paid_amount_count"], 0)

    def test_conflicting_duplicates_are_quarantined_not_double_counted_or_last_wins(self):
        a = shop()
        a["orders"] = [order(amount=100), order(amount=200)]
        result = report([a])
        self.assertIsNone(result["total_summary"]["gmv"])
        self.assertEqual(result["shops"][0]["observed_summary"]["order_count"], 0)
        self.assertIn("duplicate_conflict", [e["code"] for e in result["shops"][0]["errors"]])

    def test_naive_and_missing_paid_dates_cannot_fall_back_to_created_date(self):
        for paid in (None, "2026-09-10T12:00:00"):
            a = shop()
            o = order(paid_at=paid)
            o["created_at"] = "2026-09-10T12:00:00+08:00"
            a["orders"] = [o]
            result = report([a])
            self.assertFalse(result["complete"])
            self.assertIsNone(result["total_summary"]["order_count"])

    def test_refund_apply_date_does_not_substitute_for_completion(self):
        a = shop()
        r = refund(completed_at=None)
        r["applied_at"] = "2026-09-10T12:00:00+08:00"
        a["refunds"] = [r]
        result = report([a])
        self.assertIsNone(result["total_summary"]["refund_count"])
        self.assertEqual(result["total_summary"]["gmv"], 0)

    def test_raw_records_use_explicit_units_and_timezone_and_aliases(self):
        a = shop("pinduoduo")
        a["input_format"] = "raw"
        a["amount_units"] = {"pinduoduo.pay_amount": "yuan"}
        a["orders"] = [{"order_sn": "p", "order_status": 1, "pay_amount": "19.99", "pay_time": "2026-09-10 00:00:00"}]
        result = report([a])
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_summary"]["gmv"], 1999)
        self.assertEqual(result["shops"][0]["platform"], "pdd")
        a["input_format"] = "normalized"
        a["orders"] = [order(platform="pinduoduo")]
        self.assertTrue(report([a])["complete"])

    def test_partial_items_do_not_invent_product_gmv_or_rankings(self):
        a = shop()
        a["orders"] = [order()]
        product = report([a])["shops"][0]["top_products"][0]
        self.assertEqual(product["gross_item_amount"], 1999)
        self.assertIsNone(product["gmv"])
        a["orders"][0]["items"].append({"product_id": "bad", "price": None, "quantity": 1})
        result = report([a])["shops"][0]
        self.assertFalse(result["top_products_complete"])
        self.assertEqual(result["top_products"], [])
        self.assertEqual(result["summary"]["gmv"], 1999)

    def test_scope_conflicts_and_unknown_record_ids_are_explicit(self):
        for change in ({"shop_id": "different-shop"}, {"order_id": ""}, {"platform": "jd"}):
            a = shop()
            a["orders"] = [{**order(), **change}]
            self.assertFalse(report([a])["complete"])
        a = shop()
        with self.assertRaises(ValueError):
            report([a, a])
        with self.assertRaises(ValueError):
            report([])

    def test_coverage_cannot_turn_missing_sources_into_confirmed_empty_lists(self):
        for source, metric in (("orders", "gmv"), ("refunds", "refund_count")):
            a = shop()
            del a[source]
            result = report([a])
            self.assertFalse(result["complete"])
            self.assertFalse(result["yesterday_complete"])
            self.assertIsNone(result["total_summary"][metric])
            self.assertIn({"code": "source_missing", "source": source, "record_id": ""}, result["shops"][0]["errors"])
            a[source] = []
            explicit_empty = report([a])
            self.assertTrue(explicit_empty["complete"])
            self.assertEqual(explicit_empty["total_summary"][metric], 0)

    def test_raw_invalid_identifiers_cannot_become_complete_paid_orders(self):
        for identifier in (False, True, {}, [], 1.5, None):
            a = shop()
            a["input_format"] = "raw"
            a["orders"] = [
                {"order_id": identifier, "order_status": 2, "pay_amount": 100, "pay_time": "2026-09-10 12:00:00"}
            ]
            result = report([a])
            self.assertFalse(result["complete"])
            self.assertIsNone(result["total_summary"]["gmv"])
            self.assertIn("record_id_missing", [error["code"] for error in result["shops"][0]["errors"]])
        for invalid_scope in (False, True, {}, []):
            a = shop()
            a["orders"] = [{**order(), "shop_id": invalid_scope}]
            self.assertFalse(report([a])["complete"])
            a["shop_id"] = invalid_scope
            with self.assertRaises(ValueError):
                report([a])

    def test_complete_empty_sources_are_zero_with_undefined_ratios(self):
        result = report([shop()])
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_summary"]["gmv"], 0)
        self.assertEqual(result["total_summary"]["refund_count"], 0)
        self.assertIsNone(result["total_summary"]["avg_order_value"])
        self.assertIsNone(result["total_summary"]["refund_rate"])
        self.assertIsNone(result["low_stock_alerts"])


class DoudianProjectionContractTests(unittest.IsolatedAsyncioTestCase):
    """Execute real tool projection bodies, isolated from MCP SDK registration.

    The injected request client returns fixed upstream payloads. These tests
    verify local tool-to-report data contracts, not live API/MCP transport.
    """

    async def _project(self, tool_name, response, **arguments):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        from servers.doudian import server

        client = SimpleNamespace(request=AsyncMock(return_value=copy.deepcopy(response)))
        with patch.object(server, "_get_client", return_value=client):
            projected = await getattr(server, tool_name)(**arguments)
        self.assertNotIn("error", projected)
        client.request.assert_awaited_once()
        return projected

    async def test_actual_order_list_and_detail_projections_feed_daily_report(self):
        upstream = {
            "order_id": "projected-order",
            "order_status": 2,
            "pay_amount": 1000,
            "post_amount": 0,
            "total_amount": 1000,
            "create_time": "2026-09-10 09:00:00",
            "pay_time": "2026-09-10 09:30:00",
            "sku_order_list": [
                {"product_id": "projected-product", "product_name": "Projected", "price": 500, "item_num": 2}
            ],
        }
        listing = await self._project("get_order_list", {"shop_order_list": [upstream], "total": 1})
        detail = await self._project("get_order_detail", {"shop_order_detail": upstream}, order_id="projected-order")
        for projected in (listing["orders"][0], detail["order"]):
            a = shop()
            a["input_format"] = "raw"
            a["orders"] = [projected]
            result = report([a])
            self.assertTrue(result["complete"])
            self.assertEqual(result["total_summary"]["gmv"], 1000)
            self.assertEqual(result["total_summary"]["order_count"], 1)
            self.assertTrue(result["shops"][0]["top_products_complete"])
            self.assertEqual(result["shops"][0]["top_products"][0]["sales"], 2)
            self.assertEqual(result["shops"][0]["top_products"][0]["gross_item_amount"], 1000)

    async def test_actual_refund_projection_requires_detail_amount_and_completion_time(self):
        upstream = {
            "aftersale_info": {
                "aftersale_id": "projected-refund",
                "refund_status": 3,
                "refund_amount": 299,
                "apply_time": 1788883200,
                "update_time": 1788969600,
            },
            "order_info": {"shop_order_id": "o1"},
        }
        projected = await self._project("get_refund_list", {"items": [upstream], "total": 1, "has_more": False})
        self.assertTrue(projected["refunds"][0]["detail_required"])
        self.assertIsNone(projected["refunds"][0]["amount"])
        a = shop()
        a["input_format"] = "raw"
        a["refunds"] = projected["refunds"]
        result = report([a])
        self.assertFalse(result["complete"])
        self.assertIsNone(result["total_summary"]["refund_amount"])
