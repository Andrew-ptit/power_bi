"""Đối soát WL5 trên raw synthetic; không mở workbook hoặc sửa nguồn."""

from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import build_preview, preview_marker, result_digest, result_rows
from pbip_assistant.sources.assistant_reconcile import (
    assert_approvable, build_reconciliation, control_totals,
)
from pbip_assistant.sources.assistant_spec import spec_fingerprint
from tests.support.paths import FIXTURES
from tests.unit.test_assistant_brief import inputs, make
from tests.unit.test_assistant_spec import create, load, model


def setup(scenario="tp-fin"):
    data = inputs(scenario)
    brief = make(data)
    decision_model = model(scenario, brief=brief)
    spec = create(decision_model, scenario)
    result = result_rows(data[0]["tables"], spec, decision_model[1], data[3])
    sheet = load(scenario, "wl5_preview.json")["target"]["sheet"]
    preview = build_preview(result, spec, data[1], sheet=sheet, marker=preview_marker(result, spec, sheet=sheet))
    return preview, spec, data[0]["tables"], result


def rehash(artifact):
    name = "reconcileHash" if "reconcileHash" in artifact else "previewHash"
    artifact[name] = canonical_hash({key: artifact[key] for key in artifact["hashBasis"]})
    return artifact


def replace_rate(tables):
    raw = next(table for table in tables if {"CurrencyCode", "RateType", "Rate"} <= set(table["header"]))
    fields = raw["header"]
    row = next(row for row in raw["rows"] if row[fields.index("CurrencyCode")] == "USD"
               and row[fields.index("Month")] == "2026-09" and row[fields.index("RateType")] == "average")
    row[fields.index("Rate")] = "24000"


def add_eur(tables):
    ledger = next(table for table in tables if "DebitCredit" in table["header"])
    fields = ledger["header"]
    for index, sign in enumerate(("C", "D"), 1):
        row = deepcopy(ledger["rows"][0])
        for field, value in {"DocNo": "SYNTHETIC-EUR-" + str(index), "LineNo": "1", "Currency": "EUR",
                             "DebitCredit": sign, "Amount": "100", "PartnerEntity": ""}.items():
            row[fields.index(field)] = value
        ledger["rows"].append(row)


class AssistantReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fin = setup()
        cls.sales = setup("tp-sales")

    def test_fin_all_numeric_controls_and_dimensions_match_golden(self):
        actual = build_reconciliation(*self.fin)
        golden = load("tp-fin", "wl5_reconciliation.json")
        for field in ("rowsIn", "rowsInDeduped", "rowsOut", "colsIn", "colsOut", "controlTotalRawSource",
                      "droppedByDedupe", "controlTotalSource", "controlTotalResult", "controlTotalTolerance",
                      "controlTotalPassed", "passed", "bridge"):
            self.assertEqual(actual[field], golden[field], field)
        self.assertEqual([check["id"] for check in actual["checks"]], ["row_count", "control_total", "bridge_identity"])
        self.assertEqual(set(actual["labels"]), set(golden["labels"]))
        self.assertTrue(actual["warnings"])
        self.assertEqual(actual["blockers"], [])
        assert_approvable(actual)

    def test_sales_controls_dimensions_and_null_bridge_match_golden(self):
        actual = build_reconciliation(*self.sales)
        golden = load("tp-sales", "wl5_reconciliation.json")
        for field in ("rowsIn", "rowsInDeduped", "rowsOut", "colsIn", "colsOut", "controlTotalRawSource",
                      "droppedByDedupe", "controlTotalSource", "controlTotalResult", "controlTotalTolerance",
                      "controlTotalPassed", "passed", "bridge"):
            self.assertEqual(actual[field], golden[field], field)
        assert_approvable(actual)

    def test_control_totals_are_independent_of_result_and_close_raw_dedupe_identity(self):
        preview, spec, raw, result = self.fin
        totals = control_totals(raw, result, scenario="tp-fin")
        self.assertEqual(Decimal(totals["controlTotalRawSource"]) - Decimal(totals["droppedByDedupe"]),
                         Decimal(totals["controlTotalSource"]))
        self.assertEqual(totals["controlTotalSource"], totals["controlTotalResult"])
        changed = deepcopy(result)
        changed["rows"][0][4] += Decimal("1")
        altered = control_totals(raw, changed, scenario="tp-fin")
        self.assertEqual(altered["controlTotalSource"], totals["controlTotalSource"])
        self.assertEqual(Decimal(altered["controlTotalResult"]), Decimal(totals["controlTotalResult"]) + 1)

    def test_injected_drift_matches_variant_and_blocks_approval(self):
        actual = build_reconciliation(*self.fin, injected_drift=Decimal("1234560"))
        variant = load("variants", "fin_reconcile_control_drift.json")
        for field in ("controlTotalResult", "controlTotalPassed", "passed"):
            self.assertEqual(actual[field], variant[field])
        self.assertFalse(actual["checks"][1]["passed"])
        self.assertEqual(actual["blockers"][0]["code"], "AF_RECONCILE_FAILED")
        with self.assertRaises(InputError) as caught:
            assert_approvable(actual)
        self.assertEqual(caught.exception.code, "AF_RECONCILE_FAILED")

    def test_deleting_nonzero_result_row_fails_real_total_and_row_count(self):
        data = deepcopy(self.fin)
        rows = data[3]["rows"]
        rows.pop(next(i for i, row in enumerate(rows) if row[4] != 0))
        actual = build_reconciliation(*data)
        self.assertFalse(actual["passed"])
        self.assertFalse(actual["checks"][0]["passed"])
        self.assertFalse(actual["controlTotalPassed"])
        with self.assertRaises(InputError):
            assert_approvable(actual)

    def test_deleting_zero_actual_budget_row_is_caught_by_expected_group_keys(self):
        data = deepcopy(self.fin)
        budget = next(table for table in data[2] if {"Month", "AccountCode", "Amount"} <= set(table["header"])
                      and "DebitCredit" not in table["header"])
        fields = budget["header"]
        source = deepcopy(budget["rows"][0])
        for field, value in {"CostCenter": "SYNTHETIC-ONLY", "Amount": "100", "Currency": "VND"}.items():
            source[fields.index(field)] = value
        budget["rows"].append(source)
        accounts = next(table for table in data[2] if "PnlGroup" in table["header"])
        account_code = source[fields.index("AccountCode")]
        account = next(dict(zip(accounts["header"], row)) for row in accounts["rows"]
                       if row[accounts["header"].index("AccountCode")] == account_code)
        amount = Decimal("-100") if account["AccountType"] == "ContraRevenue" or account["PnlGroup"] in {"COGS", "Opex"} else Decimal("100")
        rows = data[3]["rows"]
        rows.append([account["PnlGroup"], account_code, "SYNTHETIC-ONLY", "UNKNOWN", Decimal("0"), amount,
                     -amount, source[fields.index("Month")], "VND"])
        rows.sort(key=lambda row: tuple(row[:4]))
        data[0]["sheets"]["after"]["rows"] = len(rows)
        parts = data[0]["target"]["marker"].split("|")
        parts[3] = "preview=" + result_digest(data[3])
        data[0]["target"]["marker"] = "|".join(parts)
        rehash(data[0])
        self.assertTrue(build_reconciliation(*data)["passed"])
        rows.pop(next(i for i, row in enumerate(rows) if row[4] == 0))
        actual = build_reconciliation(*data)
        self.assertTrue(actual["controlTotalPassed"])
        self.assertFalse(actual["checks"][0]["passed"])
        self.assertFalse(actual["passed"])

    def test_rate_mutation_reuses_fx_engine_and_preserves_exact_bridge(self):
        data = deepcopy(self.fin)
        replace_rate(data[2])
        changed = build_reconciliation(*data)
        before = build_reconciliation(*self.fin)["bridge"]
        bridge = changed["bridge"]
        delta = Decimal(before["actualUsd"]) * Decimal("-300")
        self.assertEqual(Decimal(bridge["fx"]) - Decimal(before["fx"]), delta)
        self.assertEqual(Decimal(bridge["total"]) - Decimal(before["total"]), delta)
        self.assertEqual(bridge["op"], before["op"])
        self.assertEqual(Decimal(bridge["op"]) + Decimal(bridge["fx"]), Decimal(bridge["total"]))
        self.assertEqual(bridge["total"], bridge["variance"])
        self.assertFalse(changed["controlTotalPassed"])  # Result cũ không được hợp thức hóa.

    def test_balanced_result_tampering_cannot_preserve_control_and_fake_bridge(self):
        data = deepcopy(self.fin)
        revenue = next(row for row in data[3]["rows"] if row[0] == "NetRevenue")
        cost = next(row for row in data[3]["rows"] if row[0] == "COGS")
        revenue[4] += Decimal("100")
        revenue[6] += Decimal("100")
        cost[4] -= Decimal("100")
        cost[6] -= Decimal("100")
        actual = build_reconciliation(*data)
        self.assertTrue(actual["controlTotalPassed"])
        self.assertFalse(actual["bridge"]["passed"])
        self.assertFalse(actual["checks"][2]["passed"])
        self.assertFalse(actual["passed"])
        with self.assertRaises(InputError):
            assert_approvable(actual)
        data = deepcopy(self.fin)
        data[3]["rows"][0][5] += Decimal("100")
        actual = build_reconciliation(*data)
        self.assertFalse(actual["bridge"]["passed"])
        self.assertFalse(actual["passed"])

    def test_payload_digest_catches_count_only_tamper_with_unchanged_control(self):
        data = deepcopy(self.sales)
        data[3]["rows"][0][2] += 1
        actual = build_reconciliation(*data)
        self.assertTrue(actual["controlTotalPassed"])
        self.assertFalse(actual["checks"][0]["passed"])
        self.assertFalse(actual["passed"])
        self.assertEqual(actual["blockers"][0]["code"], "AF_RECONCILE_FAILED")
        with self.assertRaises(InputError):
            assert_approvable(actual)

    def test_used_missing_average_rate_is_blocker_even_when_currency_net_is_zero(self):
        data = deepcopy(self.fin)
        add_eur(data[2])
        actual = build_reconciliation(*data)
        self.assertFalse(actual["passed"])
        self.assertTrue(any(m["code"] == "AF_MISSING_DATA" and m["severity"] == "blocker" for m in actual["blockers"]))
        self.assertIsNone(actual["controlTotalSource"])
        self.assertIsNone(actual["controlTotalRawSource"])
        self.assertIsNone(actual["bridge"]["fx"])
        self.assertFalse(actual["bridge"]["passed"])
        with self.assertRaises(InputError):
            assert_approvable(actual)

    def test_missing_unused_average_and_closing_rates_only_warn(self):
        actual = build_reconciliation(*self.fin)
        self.assertTrue(actual["passed"])
        self.assertTrue(any("average" in w["message"] and "EUR" in w["message"] for w in actual["warnings"]))
        self.assertTrue(any("closing" in w["message"] for w in actual["warnings"]))
        self.assertTrue(all(w["severity"] == "warning" for w in actual["warnings"]))
        self.assertFalse(actual["blockers"])

    def test_removing_more_unused_closing_rates_does_not_change_totals_or_bridge(self):
        data = deepcopy(self.fin)
        rates = next(t for t in data[2] if "RateType" in t["header"])
        index = rates["header"].index("RateType")
        rates["rows"] = [row for row in rates["rows"] if row[index] != "closing"]
        actual = build_reconciliation(*data)
        before = build_reconciliation(*self.fin)
        self.assertTrue(actual["passed"])
        self.assertEqual(actual["controlTotalSource"], before["controlTotalSource"])
        self.assertEqual(actual["bridge"], before["bridge"])
        self.assertTrue(actual["warnings"])

    def test_hash_determinism_recompute_and_input_immutability(self):
        for data in (self.fin, self.sales):
            before = deepcopy(data)
            first = build_reconciliation(*data)
            self.assertEqual(first, build_reconciliation(*data))
            self.assertEqual(first["reconcileHash"], canonical_hash({k: first[k] for k in first["hashBasis"]}))
            self.assertEqual(data, before)

    def test_decimal_context_does_not_change_reconciliation(self):
        expected = build_reconciliation(*self.fin)
        with localcontext() as context:
            context.prec = 4
            self.assertEqual(build_reconciliation(*self.fin), expected)

    def test_result_and_source_wrong_shape_or_nonfinite_number_fail_closed(self):
        for mutation in (lambda r: r["columns"].reverse(), lambda r: r["rows"][0].pop(),
                         lambda r: r["rows"][0].__setitem__(4, float("nan")),
                         lambda r: r["rows"][0].__setitem__(4, "0"),
                         lambda r: r["rows"][0].__setitem__(4, Decimal("Infinity"))):
            data = deepcopy(self.fin)
            mutation(data[3])
            with self.assertRaises(InputError):
                build_reconciliation(*data)
        data = deepcopy(self.fin)
        data[2][0]["rows"][0].pop()
        with self.assertRaises(InputError):
            build_reconciliation(*data)

    def test_control_totals_reject_wrong_scenario(self):
        for scenario in ("tp-sales", "unknown", [], None):
            with self.subTest(scenario=scenario), self.assertRaises(InputError):
                control_totals(self.fin[2], self.fin[3], scenario=scenario)

    def test_tolerance_cannot_be_negative_nonfinite_or_relaxed(self):
        for value in ("-0.01", "1", "Infinity", True, 0.01):
            with self.subTest(value=value), self.assertRaises(InputError):
                build_reconciliation(*self.fin, tolerance=value)

    def test_tolerance_boundary_uses_decimal_not_float(self):
        self.assertTrue(build_reconciliation(*self.fin, injected_drift=Decimal("0.01"))["controlTotalPassed"])
        self.assertFalse(build_reconciliation(*self.fin, injected_drift=Decimal("0.0100001"))["controlTotalPassed"])
        for tolerance in ("0.001", "0.005"):
            actual = build_reconciliation(*self.fin, tolerance=tolerance)
            self.assertEqual(actual["controlTotalTolerance"], tolerance)

    def test_stale_or_tampered_spec_and_preview_cannot_be_reconciled(self):
        for which, field, value in ((1, "stale", True), (1, "fingerprint", "bad"), (0, "specFingerprint", "bad"), (0, "previewHash", "bad")):
            data = deepcopy(self.fin)
            data[which][field] = value
            with self.assertRaises(InputError):
                build_reconciliation(*data)

    def test_valid_hashed_spec_with_unsupported_grain_is_not_silently_reinterpreted(self):
        data = deepcopy(self.fin)
        group = next(step for step in data[1]["steps"] if step["kind"] == "group")
        budget = next(step for step in data[1]["steps"] if step["params"]["operation"] == "join_budget")
        group["params"]["columns"] = ["pnlLine"]
        budget["params"]["rightGrain"] = ["pnlLine"]
        data[1]["fingerprint"] = spec_fingerprint(data[1])
        with self.assertRaises(InputError) as caught:
            build_reconciliation(*data)
        self.assertEqual(caught.exception.code, "AF_POLICY_UNSUPPORTED")

    def test_source_changed_and_formula_counts_are_not_accepted(self):
        for mutation in (lambda p: p["source"].__setitem__("unchanged", False),
                         lambda p: p["counts"].__setitem__("formulaCount", 1)):
            data = deepcopy(self.fin)
            mutation(data[0])
            rehash(data[0])
            with self.assertRaises(InputError):
                build_reconciliation(*data)

    def test_forged_passed_flags_and_hash_do_not_bypass_arithmetic_gate(self):
        actual = build_reconciliation(*self.fin, injected_drift=Decimal("1234560"))
        actual["passed"] = True
        actual["controlTotalPassed"] = True
        actual["checks"][1]["passed"] = True
        actual["blockers"] = []
        rehash(actual)
        with self.assertRaises(InputError):
            assert_approvable(actual)
        actual = build_reconciliation(*self.fin)
        actual["bridge"]["fx"] = "0"
        rehash(actual)
        with self.assertRaises(InputError):
            assert_approvable(actual)

    def test_altered_or_incomplete_reconciliation_hash_is_rejected(self):
        for candidate in (None, {}, {**build_reconciliation(*self.fin), "reconcileHash": "bad"}):
            with self.assertRaises(InputError):
                assert_approvable(candidate)
        for field, value in (("hiddenPolicy", "unhashed"), ("rowsIn", True), ("schemaVersion", "2.0"), ("labels", ["verified"])):
            actual = build_reconciliation(*self.fin)
            actual[field] = value
            rehash(actual)
            with self.subTest(field=field), self.assertRaises(InputError):
                assert_approvable(actual)

    def test_no_network_or_source_byte_mtime_mutation(self):
        paths = [p for scenario in ("tp-fin", "tp-sales") for p in (FIXTURES / "assistant" / scenario).rglob("*")
                 if p.is_file() and (p.suffix == ".csv" or p.name == "wl1_snapshot.json")]
        state = lambda: {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
        before = state()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Không được gọi network")):
            for data in (self.fin, self.sales):
                assert_approvable(build_reconciliation(*data))
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
