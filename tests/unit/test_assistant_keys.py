"""WL2 key and relationship arithmetic over synthetic and saved source data."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest

from pbip_assistant.sources import assistant_keys as keys
from pbip_assistant.sources.assistant_ingest import canonical_hash, resolve
from pbip_assistant.sources.assistant_profile import profile_table
from tests.support.paths import FIXTURES


def raw(name: str, header: list[str], rows: list[list[str]], *, identifier: str | None = None) -> dict:
    result = {"sourceId": "src_" + canonical_hash(name)[7:19], "name": name,
              "locator": {"kind": "file", "sheet": None, "range": None,
                          "path": name + ".csv", "fileCount": 1},
              "header": header, "rows": rows}
    if identifier is not None:
        result["id"] = identifier
    return result


def table_id(table: dict) -> str:
    return table.get("id", profile_table(table)["id"])


def relation(report: dict, left: dict, right: dict, columns: list[str], target: list[str] | None = None) -> dict:
    return next(item for item in report["relationships"]
                if item["fromTable"] == table_id(left) and item["toTable"] == table_id(right)
                and item["fromColumns"] == columns and item["toColumns"] == (target or columns))


def scenario_tables(scenario: str) -> list[dict]:
    root = FIXTURES / "assistant" / scenario
    requests = [{"kind": "csv", "path": "source/" + path.name}
                for path in sorted((root / "source").glob("*.csv"))]
    if scenario == "tp-sales":
        requests.append({"kind": "folder", "path": "source/orders", "name": "Orders"})
    result = resolve({"root": root}, requests)
    if result["errors"] or result["requiresRename"]:
        raise AssertionError("Synthetic source ingestion must succeed before key checks")
    return result["tables"]


class AssistantKeysTests(unittest.TestCase):
    def test_single_keys_require_exact_uniqueness_and_no_nulls(self) -> None:
        table = raw("Single", ["Code", "Payload"], [[str(i % 2000), str(i)] for i in range(2001)])
        found = keys.candidate_keys([table])
        self.assertNotIn(["Code"], [entry["columns"] for entry in found], "Rounded ratio cannot make a duplicate key unique")
        self.assertIn(["Payload"], [entry["columns"] for entry in found])
        null_table = raw("Null", ["Code", "Other"], [["", "a"], ["x", "b"]])
        self.assertNotIn(["Code"], [entry["columns"] for entry in keys.candidate_keys([null_table])])
        for entry in found:
            self.assertEqual((entry["distinctRatio"], entry["nullCount"], entry["unique"]), (1.0, 0, True))

    def test_composite_key_is_genuinely_unique_and_minimal(self) -> None:
        table = raw("Composite", ["A", "B", "Constant"],
                    [["x", "1", "same"], ["x", "2", "same"], ["y", "1", "same"], ["y", "2", "same"]])
        found = keys.candidate_keys([table])
        self.assertEqual([entry["columns"] for entry in found], [["A", "B"]])
        self.assertEqual(found[0]["kind"], "composite")
        self.assertEqual(keys.candidate_keys([raw("Empty", ["Key"], [])]), [])

    def test_complete_row_duplicates_preclude_every_raw_key(self) -> None:
        table = raw("Duplicates", ["Key", "Value"], [["x", "1"], ["x", "1"]])
        self.assertEqual(keys.candidate_keys([table]), [])
        self.assertEqual(len(table["rows"]), 2, "Key discovery never deduplicates raw data")

    def test_foreign_keys_support_currency_alias_without_measure_coincidences(self) -> None:
        left = raw("Transactions", ["Currency"], [["USD"], ["USD"], ["VND"]])
        right = raw("Currencies", ["CurrencyCode"], [["USD"], ["VND"]])
        report = keys.key_report([left, right])
        match = relation(report, left, right, ["Currency"], ["CurrencyCode"])
        self.assertEqual(match["evidence"], {"name": 0.0, "type": 1.0, "overlap": 1.0, "orphan": 0})
        measures = [raw("MeasuresA", ["Amount"], [["1"], ["2"]]),
                    raw("MeasuresB", ["Amount"], [["1"], ["2"]])]
        self.assertEqual(keys.key_report(measures)["foreignKeys"], [], "Numeric coincidence is not a key-name relationship")

    def test_four_cardinalities_use_uniqueness_independently_of_fan_out(self) -> None:
        cases = (([["a"], ["b"]], [["a"], ["b"]], "1:1", False),
                 ([["a"], ["a"], ["b"]], [["a"], ["b"]], "N:1", False),
                 ([["a"], ["b"]], [["a"], ["a"], ["b"]], "1:N", True),
                 ([["a"], ["a"], ["b"]], [["a"], ["a"], ["b"]], "N:N", True))
        for left_rows, right_rows, cardinality, high in cases:
            with self.subTest(cardinality=cardinality):
                left, right = raw("Left", ["Key"], left_rows), raw("Right", ["Key"], right_rows)
                report = keys.key_report([left, right])
                match = relation(report, left, right, ["Key"])
                self.assertEqual(match["cardinality"], cardinality)
                self.assertEqual(match["fanOutRisk"], "high" if high else "none")
                self.assertEqual(match["status"], "needs_confirm" if high else "auto")
                if high:
                    after = sum(max(1, sum(row == other for other in right_rows)) for row in left_rows)
                    self.assertEqual(match["fanOutEvidence"]["rowsBefore"], len(left_rows))
                    self.assertEqual(match["fanOutEvidence"]["rowsAfter"], after)
                    self.assertTrue(any(entry["fromTable"] == table_id(left) and entry["toTable"] == table_id(right)
                                        for entry in report["fanOut"]))

    def test_generic_orphans_require_confirmation_even_above_finance_threshold(self) -> None:
        left = raw("Left", ["Key"], [[str(index)] for index in range(10)])
        right = raw("Right", ["Key"], [[str(index)] for index in range(9)])
        match = relation(keys.key_report([left, right]), left, right, ["Key"])
        self.assertEqual((match["score"], match["evidence"]["orphan"]), (0.9, 1))
        self.assertEqual(match["status"], "needs_confirm")
        self.assertEqual(match["fanOutRisk"], "none")

    def test_low_and_zero_overlaps_remain_visible_and_block_auto_application(self) -> None:
        left = raw("Left", ["Key"], [[str(index)] for index in range(4)])
        for row, overlap in ((["0"], 0.25), (["missing"], 0.0)):
            right = raw("Right", ["Key"], [row])
            with self.subTest(overlap=overlap):
                match = relation(keys.key_report([left, right]), left, right, ["Key"])
                self.assertEqual(match["score"], overlap)
                self.assertEqual(match["status"], "needs_confirm")

    def test_finance_threshold_uses_exact_arithmetic_before_display_rounding(self) -> None:
        account = raw("Accounts", ["AccountCode", "AccountType", "PnlGroup"], [["A", "Revenue", "NetRevenue"]])
        rates = raw("Rates", ["CurrencyCode", "Month", "RateType", "Rate"], [["USD", "2026-09", "average", "1"]])
        left = raw("Left", ["Key"], [[str(index)] for index in range(1001)])
        right = raw("Right", ["Key"], [[str(index)] for index in range(500)])
        match = relation(keys.key_report([account, rates, left, right]), left, right, ["Key"])
        self.assertEqual(match["score"], 0.5, "The displayed ratio rounds to three places")
        self.assertEqual(match["status"], "needs_confirm", "Rounding must not promote a below-threshold ratio")

    def test_ledger_view_derives_month_and_uses_average_rates_without_mutating_rows(self) -> None:
        entry = ["D1", "1", "2026-09-03", "C", "100", "USD"]
        ledger = raw("Ledger", ["DocNo", "LineNo", "PostingDate", "DebitCredit", "Amount", "Currency"],
                     [entry, list(entry), ["D2", "1", "2026-10-03", "D", "200", "USD"]])
        rates = raw("Rates", ["CurrencyCode", "Month", "RateType", "Rate"],
                    [["USD", month, kind, value] for month, kind, value in
                     (("2026-09", "average", "24000"), ("2026-09", "closing", "24100"),
                      ("2026-10", "average", "24500"), ("2026-10", "closing", "24600"))])
        before = deepcopy([ledger, rates])
        report = keys.key_report([ledger, rates])
        match = relation(report, ledger, rates, ["Currency", "Month"], ["CurrencyCode", "Month"])
        self.assertEqual((match["score"], match["evidence"]["orphan"], match["fanOutRisk"]), (1.0, 0, "none"))
        partial = relation(report, ledger, rates, ["Currency"], ["CurrencyCode"])
        self.assertEqual((partial["fanOutEvidence"]["rowsBefore"], partial["fanOutEvidence"]["rowsAfter"]), (2, 4))
        self.assertEqual([ledger, rates], before)
        self.assertEqual(len(ledger["rows"]), 3)
        self.assertNotIn("Month", ledger["header"])

    def test_disagreeing_iso_dates_do_not_invent_a_virtual_month(self) -> None:
        dates = raw("Dates", ["PostingDate", "OtherDate", "Currency"], [["2026-09-01", "2026-10-01", "USD"]])
        rates = raw("Rates", ["CurrencyCode", "Month", "RateType", "Rate"], [["USD", "2026-09", "average", "1"]])
        report = keys.key_report([dates, rates])
        self.assertFalse(any("Month" in candidate["fromColumns"] and candidate["fromTable"] == table_id(dates)
                             for candidate in report["foreignKeys"]))

    def test_table_ids_match_wl1_or_explicit_snapshot_binding(self) -> None:
        table = raw("One", ["Key"], [["a"]])
        self.assertEqual(keys.candidate_keys([table])[0]["tableId"], profile_table(table)["id"])
        table["id"] = "tbl_123456abcdef"
        self.assertEqual(keys.candidate_keys([table])[0]["tableId"], table["id"])
        with self.assertRaises(ValueError):
            keys.key_report([table, deepcopy(table)])

    def test_results_are_deterministic_sorted_and_do_not_alias_input(self) -> None:
        left, right = raw("Left", ["Key"], [["a"], ["a"], ["b"]]), raw("Right", ["Key"], [["a"], ["b"]])
        before = deepcopy([left, right])
        first = keys.key_report([left, right])
        self.assertEqual(first, keys.key_report([right, left]))
        first["keys"][0]["columns"][0] = "Changed"
        self.assertEqual([left, right], before)

    def test_bounded_composite_search_fails_instead_of_claiming_incomplete_success(self) -> None:
        self.assertEqual(keys.MAX_COMPOSITE_KEY_COLUMNS, 16)
        self.assertEqual(keys.MAX_KEY_ROW_EVALUATIONS, 5_000_000)
        table = raw("Wide", ["C" + str(index) for index in range(17)],
                    [[str((row >> (index % 5)) & 1) for index in range(17)] for row in range(32)])
        with self.assertRaisesRegex(ValueError, "column pool"):
            keys.candidate_keys([table])
        expensive = raw("Costly", ["C" + str(index) for index in range(10)],
                        [[str((row >> index) & 1) for index in range(10)] for row in range(1000)])
        with self.assertRaisesRegex(ValueError, "row-evaluation"):
            keys.candidate_keys([expensive])

    def test_relationship_search_is_bounded_before_wide_combination_materialization(self) -> None:
        header = ["Key" + str(index) + "ID" for index in range(64)]
        left, right = raw("Left", header, [["a"] * len(header)]), raw("Right", header, [["a"] * len(header)])
        with self.assertRaisesRegex(ValueError, "candidate limit"):
            keys.key_report([left, right])
        small_left, small_right = raw("A", ["Key"], [["a"]]), raw("B", ["Key"], [["a"]])
        fake = {"fromTable": table_id(small_left), "toTable": table_id(small_right),
                "fromColumns": ["Key"], "toColumns": ["Key"], "overlap": 1.0, "orphan": 0}
        with self.assertRaisesRegex(ValueError, "candidate limit"):
            keys.relationships([small_left, small_right], [], [fake] * 10_001)

    def test_finance_key_orphan_and_fan_out_numbers_are_derived_from_saved_csv(self) -> None:
        paths = sorted((FIXTURES / "assistant" / "tp-fin" / "source").glob("*.csv"))
        before = {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        tables = scenario_tables("tp-fin")
        by_name = {table["name"]: table for table in tables}
        report = keys.key_report(tables)
        gl, coa, cc, budget, rates = [by_name[name] for name in ("GL_Actuals_2026-09", "CoA", "CostCenter", "Budget_2026", "FX_Rates_2026")]
        self.assertTrue(keys.has_finance_schema(tables))
        self.assertTrue(any(item["tableId"] == table_id(coa) and item["columns"] == ["AccountCode"] for item in report["keys"]))
        self.assertFalse(any(item["tableId"] == table_id(gl) and item["columns"] == ["DocNo", "LineNo"] for item in report["keys"]))
        for table, column, orphan, overlap in ((coa, "AccountCode", 3, 0.9), (cc, "CostCenter", 7, 0.767)):
            match = relation(report, gl, table, [column])
            self.assertEqual((match["evidence"]["orphan"], match["score"], match["status"]), (orphan, overlap, "auto"))
        risk = relation(report, gl, budget, ["AccountCode", "CostCenter", "Month"])
        self.assertEqual((risk["score"], risk["evidence"]["orphan"], risk["cardinality"]), (0.567, 13, "N:N"))
        self.assertEqual(risk["fanOutEvidence"], {"rowsBefore": 30, "rowsAfter": 32, "inflationFactor": 1.067, "blockedBy": "AF_FANOUT_RISK"})
        self.assertEqual((risk["fanOutRisk"], risk["status"]), ("high", "needs_confirm"))
        self.assertEqual(relation(report, gl, rates, ["Currency", "Month"], ["CurrencyCode", "Month"])["fanOutRisk"], "none")
        self.assertEqual(report, keys.key_report(tables))
        self.assertEqual({path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}, before)

    def test_sales_orphans_use_generic_confirmation_policy(self) -> None:
        tables = scenario_tables("tp-sales")
        by_name = {table["name"]: table for table in tables}
        report = keys.key_report(tables)
        self.assertFalse(keys.has_finance_schema(tables))
        orders = by_name["Orders"]
        for name, column, orphan, overlap in (("Customers", "CustomerID", 1, 0.917), ("Territory", "TerritoryID", 3, 0.75)):
            match = relation(report, orders, by_name[name], [column])
            self.assertEqual((match["evidence"]["orphan"], match["score"], match["status"]), (orphan, overlap, "needs_confirm"))

    def test_invalid_inputs_fail_without_coercing_or_dropping_rows(self) -> None:
        for invalid in (None, [None], [raw("Bad", ["Key"], [[1]])], [raw("Bad", ["Key"], [["a", "extra"]])]):
            with self.subTest(shape=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    keys.key_report(invalid)


if __name__ == "__main__":
    unittest.main()
