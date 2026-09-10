"""Semantic regressions: lossless money, explicit timezone and bounded alerts."""
import unittest
from datetime import datetime

from shared.dashboard import AlertRule, MonitoringDashboard
from shared.normalizer import Normalizer, normalize_price, normalize_time


class MoneyAndTimeRegressionTests(unittest.TestCase):
    def test_decimal_amounts_are_not_truncated_and_unknowns_are_not_zero(self):
        for raw, expected in (("0.29", 29), ("19.99", 1999), ("9007199254740993.99", 900719925474099399)):
            self.assertEqual(normalize_price(raw, "kuaishou", unit="yuan"), expected)
        for raw in (None, "", "NaN", "Infinity", "garbage", True, "0.001"):
            warnings = []
            self.assertIsNone(normalize_price(raw, "kuaishou", unit="yuan", warnings=warnings))
            self.assertTrue(warnings)
        self.assertEqual(normalize_price("0", "kuaishou", unit="yuan"), 0)
        self.assertIsNone(normalize_price("1.5", "doudian", unit="fen"))

    def test_bad_item_never_discards_order_amount_and_retains_source_value(self):
        order = Normalizer().normalize_order({
            "order_id": "order", "order_status": 2, "pay_amount": "1999",
            "product_info": {"list": [None, {"product_id": "P", "price": 1999, "combo_num": "bad"}]},
            "buyer_info": ["invalid object"],
        }, "doudian")
        self.assertEqual(order.amount_paid, 1999)
        self.assertIsNone(order.amount_shipping)
        self.assertIsNone(order.items[0].quantity)
        self.assertEqual(order.source_values["amount_paid"]["value"], "1999")
        self.assertIn({"field": "items[1].quantity", "code": "integer_invalid"}, order.warnings)

    def test_malformed_status_isolated_from_money(self):
        result = Normalizer().normalize_order({"order_id": "o", "order_status": {"bad": "status"}, "pay_amount": 1299}, "doudian")
        self.assertEqual(result.amount_paid, 1299)
        self.assertEqual(result.status, "unknown")

    def test_all_identity_fields_reject_boolean_and_object_stringification(self):
        n = Normalizer()
        for invalid in (False, True, [], {}, 1.5):
            cases = (
                (n.normalize_order, {"order_id": invalid, "shop_id": invalid}, ("order_id", "shop_id")),
                (n.normalize_product, {"product_id": invalid}, ("product_id",)),
                (n.normalize_refund, {"refund_id": invalid, "order_id": invalid, "shop_id": invalid},
                 ("refund_id", "order_id", "shop_id")),
                (n.normalize_review, {"review_id": invalid, "order_id": invalid, "product_id": invalid},
                 ("review_id", "order_id", "product_id")),
                (n.normalize_shop, {"shop_id": invalid}, ("shop_id",)),
            )
            for method, raw, fields in cases:
                result = method(raw, "doudian")
                for field in fields:
                    self.assertEqual(getattr(result, field), "")
                    self.assertIn({"field": field, "code": "identifier_invalid"}, result.warnings)
            result = n.normalize_order({"order_id": 123, "items": [{"product_id": invalid, "sku_id": invalid}]}, "doudian")
            self.assertEqual(result.order_id, "123")
            self.assertEqual(result.items[0].product_id, "")
            self.assertEqual(result.items[0].sku_id, "")
            product = n.normalize_product({"product_id": "p", "skus": [{"sku_id": invalid}]}, "doudian")
            self.assertEqual(product.skus[0].sku_id, "")

    def test_bad_product_and_refund_metadata_preserve_valid_money(self):
        n = Normalizer()
        product = n.normalize_product({"min_price": 1200, "stock": "bad", "skus": [None]}, "weixin")
        self.assertEqual(product.price_min, 1200)
        refund = n.normalize_refund({"refund_amount": 1200, "evidence": None}, "doudian")
        self.assertEqual(refund.amount, 1200)

    def test_doudian_tool_amount_alias_is_fen_and_platform_scoped(self):
        n = Normalizer()
        projected = {"order_id": "o", "status": 2, "amount": 1999}
        order = n.normalize_order(projected, "doudian")
        self.assertEqual(order.amount_paid, 1999)
        self.assertEqual(order.source_values["amount_paid"]["unit"], "fen")
        self.assertIsNone(n.normalize_order(projected, "pdd").amount_paid)

    def test_units_are_chosen_per_field_not_once_for_platform(self):
        n = Normalizer(amount_units={"jd.payment": "yuan", "jd.orderTotalPrice": "fen"})
        raw = {"orderInfo": {"orderId": "j", "payment": "19.99", "orderTotalPrice": "1999"}}
        result = n.normalize_order(raw, "jd")
        self.assertEqual(result.amount_paid, 1999)
        self.assertEqual(result.amount_total, 1999)
        unknown = Normalizer().normalize_order(raw, "jd")
        self.assertIsNone(unknown.amount_paid)
        self.assertIn({"field": "amount_paid", "code": "amount_unit_unknown"}, unknown.warnings)

    def test_seconds_milliseconds_and_numeric_strings_refer_to_same_instant(self):
        values = [1718006400, "1718006400", 1718006400000, "1718006400000"]
        normalized = {normalize_time(value, "pdd") for value in values}
        self.assertEqual(len(normalized), 1)
        self.assertTrue(next(iter(normalized)).endswith("+00:00"))
        self.assertEqual(normalize_time("0", "pdd"), "1970-01-01T00:00:00+00:00")
        self.assertEqual(normalize_time("1000", "pdd", timestamp_unit="milliseconds"), "1970-01-01T00:00:01+00:00")

    def test_naive_time_is_not_mislabeled_utc_and_explicit_zone_is_applied(self):
        warnings = []
        value = normalize_time("2026-09-10 00:30:00", "doudian", warnings=warnings)
        self.assertIsNone(datetime.fromisoformat(value).tzinfo)
        self.assertIn({"field": "timestamp", "code": "timezone_missing"}, warnings)
        self.assertEqual(normalize_time(value, "doudian", source_timezone="Asia/Shanghai"), "2026-09-10T00:30:00+08:00")
        self.assertEqual(normalize_time("2026-09-09T16:30:00Z", "doudian"), "2026-09-09T16:30:00+00:00")

    def test_dst_ambiguous_and_nonexistent_civil_times_are_not_guessed(self):
        for value in ("2026-11-01T01:30:00", "2026-03-08T02:30:00"):
            warnings = []
            self.assertEqual(normalize_time(value, "jd", source_timezone="America/New_York", warnings=warnings), "")
            self.assertEqual(warnings[0]["code"], "timezone_ambiguous_or_nonexistent")

    def test_aliases_share_schema_and_invalid_time_is_marked(self):
        n = Normalizer(amount_units={"pinduoduo.pay_amount": "yuan"})
        order = n.normalize_order({"order_sn": "p", "pay_amount": "19.99", "pay_time": "bad"}, "pinduoduo")
        self.assertEqual(order.platform, "pdd")
        self.assertEqual(order.amount_paid, 1999)
        self.assertIsNone(order.paid_at)
        self.assertIn({"field": "paid_at", "code": "timestamp_invalid"}, order.warnings)


class AlertRegressionTests(unittest.TestCase):
    def test_polling_deduplicates_and_recovery_opens_a_new_episode(self):
        dashboard = MonitoringDashboard(max_alerts=2)
        dashboard.add_alert_rule(AlertRule("cache.misses", 0))
        dashboard.cache.record_miss()
        for _ in range(100):
            dashboard.get_snapshot()
        self.assertEqual(len(dashboard.get_alerts()), 1)
        dashboard.cache.reset()
        dashboard.get_snapshot()
        self.assertEqual(dashboard.get_alerts()[0].state, "resolved")
        dashboard.cache.record_miss()
        dashboard.get_snapshot()
        self.assertEqual([a.state for a in dashboard.get_alerts()], ["resolved", "active"])
        for _ in range(10):
            dashboard.cache.reset()
            dashboard.get_snapshot()
            dashboard.cache.record_miss()
            dashboard.get_snapshot()
        self.assertEqual(len(dashboard.get_alerts()), 2)
        dashboard.clear_alerts()
        self.assertEqual(dashboard.get_alerts(), [])

    def test_duplicate_rules_do_not_expand_state_and_removal_resolves(self):
        dashboard = MonitoringDashboard(max_alert_rules=1)
        rule = AlertRule("cache.misses", 0)
        dashboard.add_alert_rule(rule)
        dashboard.add_alert_rule(rule)
        with self.assertRaises(ValueError):
            dashboard.add_alert_rule(AlertRule("cache.hits", 0))
        dashboard.cache.record_miss()
        dashboard.get_snapshot()
        dashboard.remove_alert_rules("cache.misses")
        self.assertEqual(dashboard.get_alerts()[0].state, "resolved")
