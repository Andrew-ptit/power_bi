"""Measured WL2 role proposals, with no AI or writable source fixtures."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from pbip_assistant.sources.assistant_ingest import canonical_hash, resolve
from pbip_assistant.sources.assistant_profile import build_snapshot, profile_table
from pbip_assistant.sources.assistant_roles import (
    assumption_ledger, column_roles, structural_roles, warning_classification,
)
from tests.support.paths import FIXTURES


def raw(name: str, header: list[str], rows: list[list[str]], identifier: str | None = None) -> dict:
    item = {"sourceId": "src_" + canonical_hash(name)[7:19], "name": name,
            "locator": {"kind": "file", "sheet": None, "range": None, "path": name + ".csv", "fileCount": 1},
            "header": header, "rows": rows}
    if identifier is not None:
        item["id"] = identifier
    return item


def snapshot(items: list[dict]) -> dict:
    return {"tables": [{**profile_table(item), "id": item.get("id", profile_table(item)["id"])} for item in items]}


def report() -> dict:
    return {"keys": [], "foreignKeys": [], "relationships": [], "fanOut": []}


def key(table: str, *columns: str) -> dict:
    return {"tableId": table, "columns": list(columns), "unique": True, "nullCount": 0,
            "kind": "single" if len(columns) == 1 else "composite", "distinctRatio": 1.0}


def link(source: str, target: str, source_column: str, target_column: str, cardinality: str = "N:1") -> dict:
    return {"fromTable": source, "toTable": target, "fromColumns": [source_column],
            "toColumns": [target_column], "cardinality": cardinality, "score": 1.0,
            "evidence": {"name": 1.0, "type": 1.0, "overlap": 1.0, "orphan": 0}}


def finance() -> tuple[dict, list[dict]]:
    base = FIXTURES / "assistant" / "tp-fin"
    requests = [{"kind": "csv", "path": "source/" + path.name} for path in sorted((base / "source").glob("*.csv"))]
    ingested = resolve({"root": base}, requests)
    if ingested["errors"]:
        raise AssertionError("Synthetic finance inputs must be readable")
    return build_snapshot(ingested), ingested["tables"]


class AssistantRoleTests(unittest.TestCase):
    def role_proposals(self, items: list[dict], key_data: dict | None = None) -> list[dict]:
        with patch("pbip_assistant.sources.assistant_roles._key_report", return_value=key_data or report()):
            return column_roles(snapshot(items), items)

    def test_fact_accepts_unique_composite_row_pk_with_repeated_foreign_key_grain(self) -> None:
        items = [raw("Large", ["Row", "Customer", "Product"], [[str(i), "c", "p"] for i in range(4)], "f"),
                 raw("People", ["Customer"], [["c"]], "d"), raw("Goods", ["Product"], [["p"]], "e")]
        data = {**report(), "keys": [key("f", "Row"), key("d", "Customer"), key("e", "Product")],
                "relationships": [link("f", "d", "Customer", "Customer"), link("f", "e", "Product", "Product")]}
        roles = structural_roles(snapshot(items), data)
        self.assertEqual({r["tableId"]: r["structural"] for r in roles}, {"f": "fact", "d": "dim", "e": "dim"})
        self.assertEqual(sum(r["structural"] == "fact" for r in roles), 1)
        for role in roles:
            self.assertTrue(role["evidence"])
            self.assertTrue(all(isinstance(e["value"], str) for e in role["evidence"]))
            self.assertGreaterEqual(role["confidence"], 0)
            self.assertLessEqual(role["confidence"], 1)
            self.assertNotIn("verified", role.values())

    def test_bridge_requires_many_to_many_and_partial_key_target_is_lookup(self) -> None:
        items = [raw("Rows", ["A", "B"], [["a", "b"]] * 5, "f"),
                 raw("Rates", ["Currency", "Month", "Kind"], [["USD", "2026-09", "average"], ["USD", "2026-09", "closing"]], "l"),
                 raw("Mapped", ["A", "C"], [["a", "c"], ["a", "d"]], "b"),
                 raw("Dimension", ["B"], [["b"]], "d")]
        data = {**report(), "keys": [key("l", "Currency", "Month", "Kind"), key("d", "B")],
                "relationships": [link("f", "l", "A", "Currency"), link("f", "b", "A", "A", "N:N"), link("f", "d", "B", "B")]}
        roles = {r["tableId"]: r["structural"] for r in structural_roles(snapshot(items), data)}
        self.assertEqual(roles, {"f": "fact", "l": "lookup", "b": "bridge", "d": "dim"})

    def test_partial_lookup_evidence_outweighs_secondary_many_to_many_candidate(self) -> None:
        items = [raw("Rows", ["A", "B"], [["a", "b"]] * 5, "f"),
                 raw("Catalog", ["Currency", "Month", "Kind"],
                     [["USD", "2026-09", "average"], ["USD", "2026-09", "closing"]], "l"),
                 raw("Secondary", ["A"], [["a"], ["a"]], "b")]
        data = {**report(), "keys": [key("l", "Currency", "Month", "Kind")],
                "relationships": [link("f", "l", "A", "Currency", "N:1"),
                                  link("f", "b", "B", "A", "N:N"),
                                  link("b", "l", "A", "Currency", "N:N")]}
        roles = {r["tableId"]: r for r in structural_roles(snapshot(items), data)}
        self.assertEqual(roles["l"]["structural"], "lookup")
        self.assertTrue(any(e["kind"] == "partial_key_reference_count" for e in roles["l"]["evidence"]))
        self.assertEqual(roles["b"]["structural"], "bridge")

    def test_insufficient_fact_evidence_fails_instead_of_guessing_by_name(self) -> None:
        tables = snapshot([raw("GL_Actuals", ["A"], [["a"]])])
        with self.assertRaises(ValueError):
            structural_roles(tables, report())
        with self.assertRaises(ValueError):
            structural_roles({"tables": []}, report())
        items = [raw("Largest", ["K"], [["a"]] * 4, "f"),
                 raw("D", ["K"], [["a"]], "d"), raw("E", ["K"], [["b"]], "e")]
        unrelated = link("f", "e", "K", "K")
        unrelated["score"] = 0.0
        unrelated["evidence"]["overlap"] = 0.0
        data = {**report(), "relationships": [link("f", "d", "K", "K"), unrelated]}
        with self.assertRaises(ValueError, msg="Zero-overlap candidates do not create the second fact target"):
            structural_roles(snapshot(items), data)

    def test_structural_roles_are_input_order_independent_and_readonly(self) -> None:
        items = [raw("R", ["A", "B"], [["a", "b"]] * 3, "f"), raw("D", ["A"], [["a"]], "d"), raw("E", ["B"], [["b"]], "e")]
        state = snapshot(items)
        data = {**report(), "keys": [key("d", "A"), key("e", "B")], "relationships": [link("f", "d", "A", "A"), link("f", "e", "B", "B")]}
        original = deepcopy((state, data))
        first = structural_roles(state, data)
        other_state, other_data = deepcopy((state, data))
        other_state["tables"].reverse()
        other_data["relationships"].reverse()
        self.assertEqual(structural_roles(other_state, other_data), first)
        self.assertEqual((state, data), original)

    def test_pk_subset_keeps_foreign_key_superset_unique(self) -> None:
        items = [raw("Rows", ["Row", "A"], [[str(i), "a"] for i in range(4)], "f"),
                 raw("D", ["A"], [["a"]], "d"), raw("E", ["A"], [["a"]], "e")]
        first = link("f", "d", "Row", "A")
        second = link("f", "e", "Row", "A")
        first["fromColumns"] = second["fromColumns"] = ["Row", "A"]
        data = {**report(), "keys": [key("f", "Row")], "relationships": [first, second]}
        with self.assertRaises(ValueError, msg="Adding columns to a unique PK does not create repeated FK grain"):
            structural_roles(snapshot(items), data)

    def test_currency_meaning_wins_over_pk_fk_and_preserves_key_evidence(self) -> None:
        item = raw("Money", ["CurrencyCode"], [["USD"], ["VND"]], "m")
        proposals = self.role_proposals([item], {**report(), "keys": [key("m", "CurrencyCode")]})
        self.assertEqual(proposals[0]["role"], "currency")
        self.assertEqual(proposals[0]["roleStatus"], "inferred")
        self.assertTrue(any(e["kind"] == "detected_key" and e["value"] == "1" for e in proposals[0]["evidence"]))

    def test_date_and_amount_need_ninety_five_percent_finite_parseable_values(self) -> None:
        rows = [["2026-09-01", "001.00"] for _ in range(19)] + [["bad", "NaN"]]
        proposals = self.role_proposals([raw("Facts", ["PostingDate", "Amount"], rows)])
        self.assertEqual([p["role"] for p in proposals], ["date", "amount"])
        self.assertEqual([p["confidence"] for p in proposals], [0.95, 0.95])
        lower = [["2026-09-01", "001.00"] for _ in range(18)] + [["bad", "NaN"]] * 2
        proposals = self.role_proposals([raw("Facts", ["PostingDate", "Amount"], lower)])
        self.assertEqual([p["role"] for p in proposals], [None, None])

    def test_percent_name_and_high_distinct_text_keep_unknown_for_repeated_segment(self) -> None:
        item = raw("Labels", ["DiscountPct", "Label", "Segment2"],
                   [["10", "A", "S"], ["10", "A", "S"], ["10", "B", "S"], ["10", "B", "S"]])
        proposals = self.role_proposals([item])
        self.assertEqual([p["role"] for p in proposals], ["percent", "text", None])
        self.assertEqual(proposals[2]["roleStatus"], "unknown")
        self.assertTrue(all(p["evidence"] for p in proposals))

    def test_detected_non_currency_key_is_key(self) -> None:
        item = raw("Data", ["ObjectID"], [["A"], ["B"]], "t")
        result = self.role_proposals([item], {**report(), "keys": [key("t", "ObjectID")]})
        self.assertEqual(result[0]["role"], "key")

    def test_zero_overlap_candidate_does_not_turn_unknown_column_into_key(self) -> None:
        item = raw("Data", ["Segment2"], [["S"]] * 4, "t")
        candidate = link("t", "other", "Segment2", "Code")
        candidate["score"] = candidate["evidence"]["overlap"] = 0.0
        result = self.role_proposals([item], {**report(), "relationships": [candidate]})
        self.assertIsNone(result[0]["role"])
        self.assertFalse(any(e["kind"] == "detected_key" for e in result[0]["evidence"]))

    def test_column_proposals_preserve_raw_values_and_survive_reordered_input(self) -> None:
        items = [raw("A", ["Amount"], [["001.00"], ["-2"]], "a"), raw("B", ["Segment2"], [["S"], ["S"]], "b")]
        state = snapshot(items)
        before = deepcopy((state, items))
        with patch("pbip_assistant.sources.assistant_roles._key_report", return_value=report()):
            first = column_roles(state, items)
            other_state = deepcopy(state)
            other_state["tables"].reverse()
            self.assertEqual(column_roles(other_state, list(reversed(items))), first)
        self.assertEqual((state, items), before)

    def test_column_proposals_reject_snapshot_raw_count_or_identifier_mismatch(self) -> None:
        item = raw("A", ["Amount"], [["1"]], "a")
        state = snapshot([item])
        state["tables"][0]["rowCount"] = 2
        with self.assertRaises(ValueError):
            column_roles(state, [item])
        with self.assertRaises(ValueError):
            column_roles(snapshot([item]), [])
        stale = snapshot([item])
        changed = deepcopy(item)
        changed["rows"][0][0] = "2"
        with self.assertRaises(ValueError):
            column_roles(stale, [changed])

    def test_ledger_emits_only_used_data_and_selected_pack_sources(self) -> None:
        state = snapshot([raw("A", ["K"], [["a"]])])
        original = deepcopy(state)
        data_entries = assumption_ledger(state, report())
        self.assertEqual({entry["source"] for entry in data_entries}, {"data"})
        packed = {**state, "pack": {"id": "fin-pl-v1", "genericMode": False}}
        entries = assumption_ledger(packed, report())
        self.assertEqual({entry["source"] for entry in entries}, {"data", "pack"})
        for entry in entries:
            self.assertRegex(entry["id"], r"^asm_[a-f0-9]{12}$")
            self.assertTrue(entry["evidence"])
            self.assertIn(entry["risk"], {"low", "medium", "high"})
            self.assertGreaterEqual(entry["confidence"], 0)
            self.assertLessEqual(entry["confidence"], 1)
        self.assertEqual(state, original)
        self.assertEqual(assumption_ledger(packed, report()), entries)

    def rate_inputs(self, *, used_currency: str = "USD", rates: list[list[str]] | None = None) -> list[dict]:
        return [raw("Events", ["Currency", "PostingDate", "Amount"], [[used_currency, "2026-09-03", "1"]], "e"),
                raw("Currencies", ["CurrencyCode"], [["USD"], ["EUR"]], "c"),
                raw("Rates", ["CurrencyCode", "Month", "RateType", "Rate"],
                    [["USD", "2026-09", "average", "1"], ["EUR", "2026-09", "closing", "1"]] if rates is None else rates, "r")]

    def test_missing_used_average_blocks_but_closing_only_warns(self) -> None:
        items = self.rate_inputs(used_currency="EUR")
        messages = warning_classification(snapshot(items), items)
        blockers = [w for w in messages if w["severity"] == "blocker"]
        self.assertEqual(len(blockers), 1)
        self.assertIn("EUR average", blockers[0]["message"])
        self.assertTrue(any(w["severity"] == "warning" and "USD closing" in w["message"] for w in messages))
        self.assertTrue(all(w["code"] == "AF_MISSING_DATA" for w in messages))

    def test_missing_unused_average_is_warning_and_generic_has_no_fx_claim(self) -> None:
        items = self.rate_inputs()
        messages = warning_classification(snapshot(items), items)
        self.assertTrue(messages)
        self.assertTrue(all(w["severity"] == "warning" for w in messages))
        generic = [raw("Sales", ["OrderID", "Amount"], [["A", "1"]])]
        self.assertEqual(warning_classification(snapshot(generic), generic), [])

    def test_invalid_zero_or_nonfinite_rate_cannot_satisfy_used_lookup(self) -> None:
        for value in ("", "0", "-1", "NaN", "Infinity", "not-number"):
            with self.subTest(rate=value):
                items = self.rate_inputs(rates=[["USD", "2026-09", "average", value]])
                self.assertTrue(any(w["severity"] == "blocker" and "USD average" in w["message"]
                                    for w in warning_classification(snapshot(items), items)))

    def test_unknown_currency_diagnostics_do_not_echo_arbitrary_cell_text(self) -> None:
        sensitive = "arbitrary-private-cell-value-that-is-not-a-currency"
        items = self.rate_inputs(used_currency=sensitive)
        messages = warning_classification(snapshot(items), items)
        self.assertTrue(any(w["severity"] == "blocker" for w in messages))
        self.assertTrue(all(sensitive not in w["message"] for w in messages))
        self.assertTrue(all(len(w["message"]) < 300 for w in messages))

    def test_warning_classification_is_readonly_and_input_order_independent(self) -> None:
        items = self.rate_inputs()
        state = snapshot(items)
        before = deepcopy((state, items))
        expected = warning_classification(state, items)
        state["tables"].reverse()
        self.assertEqual(warning_classification(state, list(reversed(items))), expected)
        state["tables"].reverse()
        self.assertEqual((state, items), before)

    def test_iso_basic_and_week_dates_bind_normalized_calendar_month(self) -> None:
        for value in ("20260903", "2026-W36-4", "2026-09-03T11:00:00Z"):
            with self.subTest(iso_form=value):
                items = self.rate_inputs()
                items[0]["rows"][0][1] = value
                warnings = warning_classification(snapshot(items), items)
                self.assertTrue(all(w["severity"] == "warning" for w in warnings))
                self.assertTrue(all("2026-09" in w["message"] for w in warnings))

    def test_real_finance_data_has_required_meanings_and_one_measured_fact(self) -> None:
        from pbip_assistant.sources.assistant_keys import key_report
        state, items = finance()
        report_data = key_report(items)
        roles = structural_roles(state, report_data)
        names = {table["id"]: table["name"] for table in state["tables"]}
        self.assertEqual([names[r["tableId"]] for r in roles if r["structural"] == "fact"], ["GL_Actuals_2026-09"])
        fx_role = next(r for r in roles if names[r["tableId"]] == "FX_Rates_2026")
        self.assertEqual(fx_role["structural"], "lookup", "Partial average-rate key is lookup despite secondary N:N candidates")
        gl_id = next(identifier for identifier, name in names.items() if name == "GL_Actuals_2026-09")
        columns = {p["name"]: p for p in column_roles(state, items) if p["tableId"] == gl_id}
        self.assertEqual({name: columns[name]["role"] for name in ("PostingDate", "Amount", "Currency", "Segment2")},
                         {"PostingDate": "date", "Amount": "amount", "Currency": "currency", "Segment2": None})
        self.assertEqual(columns["Segment2"]["roleStatus"], "unknown")
        warnings = warning_classification(state, items)
        self.assertTrue(warnings)
        self.assertTrue(all(w["severity"] == "warning" for w in warnings))
        ledger = assumption_ledger(state, report_data)
        self.assertTrue(all(entry["source"] in {"data", "pack", "history", "user"} for entry in ledger))


if __name__ == "__main__":
    unittest.main()
