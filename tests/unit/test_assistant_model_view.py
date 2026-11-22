"""Unit tests for the deterministic modelView engine (feature 004, T402).

The module under test is `pbip_assistant.sources.assistant_model_view`.
Expected values come from `tests.support.model_view_oracle` (independent
reimplementation) or from hand-written fixtures; the oracle never imports
the module under test.
"""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path
import unittest

import pbip_assistant
from pbip_assistant.core.resources import schema_path
from pbip_assistant.sources.assistant_ingest import canonical_hash, close, resolve
from pbip_assistant.sources.assistant_keys import has_finance_schema, key_report
from pbip_assistant.sources.assistant_profile import build_snapshot
from pbip_assistant.sources.assistant_roles import assumption_ledger, warning_classification
from pbip_assistant.sources.assistant_session import _questions
from pbip_assistant.sources.assistant_understand import _HASH_BASIS, build_understand, understand_hash
from pbip_assistant.sources.assistant_model_view import build_model_view, grain_kind, model_view_hash
from tests.support.json_schema_oracle import validate
from tests.support.model_view_oracle import build_model_view_oracle
from tests.support.paths import FIXTURES


ROOT = FIXTURES / "assistant"


def scenario(scenario: str) -> tuple[list[dict], dict, dict, list[dict]]:
    """(bound raw tables, snapshot, understand, questions) for a fixture."""
    root = ROOT / scenario
    requests = [{"kind": "csv", "path": "source/" + path.name} for path in sorted((root / "source").glob("*.csv"))]
    if scenario == "tp-sales":
        requests.append({"kind": "folder", "path": "source/orders", "name": "Orders"})
    session = {"root": root}
    result = resolve(session, requests)
    close(session)
    snapshot = build_snapshot(result)
    ids = {table["name"]: table["id"] for table in snapshot["tables"]}
    bound = []
    for raw in result["tables"]:
        copied = deepcopy(raw)
        copied["id"] = ids[copied["name"]]
        bound.append(copied)
    understand = understand_for(bound, snapshot)
    questions = _questions(snapshot, understand)
    return bound, snapshot, understand, questions


def understand_for(bound: list[dict], snapshot: dict) -> dict:
    """build_understand, falling back to the store's roles:[] branch (P4)."""
    try:
        return build_understand(bound, snapshot)
    except ValueError as exc:
        if str(exc) != "No largest table has repeated foreign keys and at least two targets":
            raise
        finance = has_finance_schema(bound)
        pack = {"id": "fin-pl-v1" if finance else "generic", "version": "1.0",
                "genericMode": not finance, "notice": None}
        report = key_report(bound)
        context = {**deepcopy(snapshot), "pack": pack}
        model = {"schemaVersion": "1.0", "snapshotHash": snapshot["snapshotHash"], "pack": pack,
                 "roles": [], "relationships": report["relationships"],
                 "assumptions": assumption_ledger(context, report),
                 "warnings": warning_classification(context, bound),
                 "variantOf": None, "variantReason": None, "hashBasis": list(_HASH_BASIS)}
        model["understandHash"] = understand_hash(model)
        return model


def make_raw(name: str, header: list[str], rows: list[list[str]], total_rows: int | None = None,
             mode: str = "compute") -> dict:
    return {"name": name, "header": header, "rows": rows, "locator": {"type": "csv", "path": name + ".csv"},
            "mode": mode, "totalRows": total_rows if total_rows is not None else len(rows),
            "sampleOrdinals": list(range(len(rows))) if mode == "compute" else list(range(min(20, len(rows))))}


def synthetic(raws: list[dict], mode: str = "compute") -> tuple[list[dict], dict, dict, list[dict]]:
    """Build a snapshot/understand/questions over hand-written raw tables."""
    sources = []
    tables = []
    for index, raw in enumerate(raws):
        source_id = "src_" + f"{index:012x}"
        sources.append({"id": source_id, "name": "source" + str(index), "type": "csv",
                        "path": raw["name"] + ".csv", "hash": "h" + str(index), "size": 1,
                        "rows": len(raw["rows"]), "columns": len(raw["header"]),
                        "origin": "origin" + str(index), "fingerprint": "fp" + str(index)})
        tables.append({"sourceId": source_id, **deepcopy(raw)})
    result = {"errors": [], "requiresRename": False, "csvOptions": [], "warnings": [],
              "sources": sources, "tables": tables}
    snapshot = build_snapshot(result)
    snapshot["snapshot"]["mode"] = mode
    for table, raw in zip(snapshot["tables"], raws, strict=True):
        table["totalRows"] = raw.get("totalRows", len(raw["rows"]))
    # mode/totalRows are runtime fields; rebind the canonical WL1 hash to content.
    snapshot["snapshotHash"] = canonical_hash({key: snapshot[key] for key in snapshot["hashBasis"]})
    ids = {table["name"]: table["id"] for table in snapshot["tables"]}
    bound = []
    for raw in result["tables"]:
        copied = deepcopy(raw)
        copied["id"] = ids[copied["name"]]
        bound.append(copied)
    understand = understand_for(bound, snapshot)
    questions = _questions(snapshot, understand)
    return bound, snapshot, understand, questions


class AssistantModelViewUnitTests(unittest.TestCase):
    def test_star_model_tables_keys_roles_match_oracle(self) -> None:
        bound, snapshot, understand, questions = scenario("tp-sales")
        actual = build_model_view(bound, snapshot, understand, questions)
        expected = build_model_view_oracle(bound, snapshot, understand, questions)
        self.assertEqual(actual, expected, "TP-SALES modelView must match the oracle")

    def test_finance_model_matches_oracle(self) -> None:
        bound, snapshot, understand, questions = scenario("tp-fin")
        actual = build_model_view(bound, snapshot, understand, questions)
        expected = build_model_view_oracle(bound, snapshot, understand, questions)
        self.assertEqual(actual, expected, "TP-FIN modelView must match the oracle")

    def test_per_sheet_mode_when_roles_empty(self) -> None:
        raw = make_raw("Flat", ["a", "b"], [["x1", "1"], ["x2", "2"], ["x3", "3"]])
        bound, snapshot, understand, questions = synthetic([raw])
        self.assertEqual(understand["roles"], [], "single flat table has no fact graph")
        model = build_model_view(bound, snapshot, understand, questions)
        self.assertEqual(model["mode"], "per_sheet")
        self.assertEqual(model["counts"]["tables"], 1)
        self.assertEqual(model["tables"][0]["structural"], "unclassified")
        self.assertEqual(model["relationships"], [])

    def test_snapshot_detected_entity_by_date(self) -> None:
        rows = []
        for day in range(1, 6):  # 5 days, entity E-1 appears on >= 2 days
            rows.append(["E-1", f"2026-01-0{day}"])
        for day in range(1, 4):
            rows.append(["E-2", f"2026-01-0{day}"])
        raw = make_raw("Snap", ["entity", "d"], rows)
        kind, evidence = grain_kind(raw, [{"columns": ["entity", "d"], "unique": True, "nullCount": 0}])
        self.assertEqual(kind, "snapshot")
        self.assertEqual(evidence["dateColumn"], "d")
        self.assertEqual(evidence["entityColumns"], ["entity"])
        self.assertEqual(evidence["distinctDates"], 5)
        self.assertEqual(evidence["entities"], 2)
        self.assertEqual(evidence["repeatedEntities"], 2)  # both entities span >= 2 dates

    def test_event_when_date_not_in_key(self) -> None:
        rows = [["E-" + str(i), f"2026-01-{i:02d}", str(i)] for i in range(1, 6)]
        raw = make_raw("Evt", ["entity", "d", "x"], rows)
        kind, evidence = grain_kind(raw, [
            {"columns": ["entity"], "unique": True, "nullCount": 0},
            {"columns": ["entity", "x"], "unique": True, "nullCount": 0},
        ])
        self.assertEqual(kind, "event")
        self.assertEqual(evidence["dateColumn"], "d")
        self.assertEqual(evidence["entityColumns"], [])

    def test_unknown_without_date_column(self) -> None:
        raw = make_raw("NoDates", ["a", "b"], [["1", "2"], ["3", "4"]])
        kind, evidence = grain_kind(raw, [{"columns": ["a"], "unique": True, "nullCount": 0}])
        self.assertEqual(kind, "unknown")
        self.assertIsNone(evidence)

    def test_empty_table_unknown(self) -> None:
        raw = make_raw("Empty", ["a", "d"], [])
        kind, evidence = grain_kind(raw, [])
        self.assertEqual(kind, "unknown")
        self.assertIsNone(evidence)

    def test_snapshot_thresholds_at_boundary(self) -> None:
        key = {"columns": ["entity", "d"], "unique": True, "nullCount": 0}
        # Exactly 3 distinct dates qualifies; 2 does not.
        three = make_raw("T3", ["entity", "d"],
                         [["E-1", "2026-01-01"], ["E-1", "2026-01-02"], ["E-1", "2026-01-03"], ["E-2", "2026-01-01"]])
        self.assertEqual(grain_kind(three, [key])[0], "snapshot")
        two = make_raw("T2", ["entity", "d"],
                       [["E-1", "2026-01-01"], ["E-1", "2026-01-02"], ["E-2", "2026-01-01"]])
        self.assertEqual(grain_kind(two, [key])[0], "event")
        # Exactly 50% repeated entities qualifies; below does not.
        at_half = make_raw("H50", ["entity", "d"],
                           [["E-1", "2026-01-01"], ["E-1", "2026-01-02"], ["E-1", "2026-01-03"],
                            ["E-2", "2026-01-01"], ["E-2", "2026-01-02"], ["E-2", "2026-01-03"],
                            ["E-3", "2026-01-01"], ["E-4", "2026-01-01"]])
        self.assertEqual(grain_kind(at_half, [key])[0], "snapshot")
        below = make_raw("B50", ["entity", "d"],
                         [["E-1", "2026-01-01"], ["E-1", "2026-01-02"], ["E-1", "2026-01-03"],
                          ["E-2", "2026-01-01"], ["E-3", "2026-01-01"], ["E-4", "2026-01-01"]])
        self.assertEqual(grain_kind(below, [key])[0], "event")
        # Exactly 95% ISO values is a date column; 90% is not.
        iso_rows = [["E-1", f"2026-01-{i:02d}"] for i in range(1, 20)] + [["E-1", "junk"]]
        at_95 = make_raw("D95", ["entity", "d"], iso_rows)  # 19/20 = 0.95
        self.assertEqual(grain_kind(at_95, [key])[0], "snapshot")
        below_95 = make_raw("D90", ["entity", "d"], iso_rows + [["E-1", "junk"]])  # 19/21 < 0.95
        self.assertEqual(grain_kind(below_95, [key])[0], "unknown")

    def test_snapshot_picks_smallest_key_then_name_order(self) -> None:
        rows = [["E-1", "A1", "2026-01-01"], ["E-1", "A1", "2026-01-02"], ["E-1", "A1", "2026-01-03"],
                ["E-2", "B1", "2026-01-01"], ["E-2", "B1", "2026-01-02"], ["E-2", "B1", "2026-01-03"]]
        raw = make_raw("Keys", ["entity", "a", "d"], rows)
        keys = [
            {"columns": ["entity", "d"], "unique": True, "nullCount": 0},
            {"columns": ["a", "d"], "unique": True, "nullCount": 0},
            {"columns": ["entity", "a", "d"], "unique": True, "nullCount": 0},
        ]
        kind, evidence = grain_kind(raw, keys)
        self.assertEqual(kind, "snapshot")
        self.assertEqual(evidence["entityColumns"], ["a"])  # smallest key, then name order (a < entity)

    def test_wire_state_fanout_beats_orphan(self) -> None:
        raw = make_raw("A", ["id"], [["1"], ["2"]])
        bound, snapshot, understand, questions = synthetic([raw])
        understand = deepcopy(understand)
        understand["roles"] = []
        understand["relationships"] = [{
            "id": "rel_x", "fromTable": bound[0]["id"], "fromColumns": ["id"],
            "toTable": bound[0]["id"], "toColumns": ["id"], "cardinality": "N:N",
            "status": "needs_confirm", "fanOutRisk": "high",
            "evidence": {"name": 1.0, "type": 1.0, "overlap": 0.9, "orphan": 5},
            "fanOutEvidence": {"rowsBefore": 2, "rowsAfter": 9, "inflationFactor": 4.5, "blockedBy": "AF_FANOUT_RISK"},
        }]
        model = build_model_view(bound, snapshot, understand, [])
        self.assertEqual(model["relationships"][0]["wireState"], "fanout")
        self.assertEqual(model["relationships"][0]["orphan"], 5)

    def test_question_ids_linked_for_relationship_role_grain_warning(self) -> None:
        raw = make_raw("Snap", ["entity", "d"],
                       [["E-1", "2026-01-01"], ["E-1", "2026-01-02"], ["E-1", "2026-01-03"],
                        ["E-2", "2026-01-01"], ["E-2", "2026-01-02"], ["E-2", "2026-01-03"]])
        bound, snapshot, understand, questions = synthetic([raw])
        understand = deepcopy(understand)
        understand["roles"] = [{"tableId": bound[0]["id"], "structural": "fact", "confidence": 0.9, "evidence": []}]
        warning = {"code": "AF_WARN", "severity": "warning", "message": "message"}
        understand["warnings"] = [warning]
        relationship = {"id": "rel_x", "fromTable": bound[0]["id"], "fromColumns": ["entity"],
                        "toTable": bound[0]["id"], "toColumns": ["entity"], "cardinality": "N:1",
                        "status": "auto", "fanOutRisk": "none",
                        "evidence": {"name": 1.0, "type": 1.0, "overlap": 1.0, "orphan": 0},
                        "fanOutEvidence": None}
        understand["relationships"] = [relationship]
        table_id = bound[0]["id"]
        questions = [
            {"id": "q_rel", "topic": "relationship", "question": "?", "whyItMatters": "w", "kind": "single_choice",
             "options": ["Xác nhận"], "evidence": [{"kind": "relationship", "ref": "rel_x", "value": {}}], "source": "data"},
            {"id": "q_role", "topic": "role", "question": "?", "whyItMatters": "w", "kind": "single_choice",
             "options": ["Đúng"], "evidence": [{"kind": "role", "value": {"tableId": table_id}}], "source": "data"},
            {"id": "q_grain", "topic": "grain", "question": "?", "whyItMatters": "w", "kind": "single_choice",
             "options": ["Đúng, là ảnh chụp"], "evidence": [{"kind": "grain", "ref": table_id, "value": {}}], "source": "data"},
            {"id": "q_warn", "topic": "warning", "question": "?", "whyItMatters": "w", "kind": "single_choice",
             "options": ["Xác nhận"], "evidence": [{"kind": "warning", "value": deepcopy(warning)}], "source": "data"},
            {"id": "q_other", "topic": "nulls", "question": "?", "whyItMatters": "w", "kind": "single_choice",
             "options": ["Giữ trống"], "evidence": [], "source": "data"},
        ]
        model = build_model_view(bound, snapshot, understand, questions)
        table = model["tables"][0]
        self.assertEqual(table["roleQuestionId"], "q_role")
        self.assertEqual(table["grainQuestionId"], "q_grain")
        self.assertEqual(model["relationships"][0]["questionId"], "q_rel")
        self.assertEqual(model["warnings"][0]["questionId"], "q_warn")
        self.assertEqual(model["counts"]["needsConfirm"], 3)  # relationship + role + grain only

    def test_relationships_identical_set_and_order_to_understand(self) -> None:
        bound, snapshot, understand, questions = scenario("tp-fin")
        model = build_model_view(bound, snapshot, understand, questions)
        self.assertEqual([link["id"] for link in model["relationships"]],
                         [link["id"] for link in understand["relationships"]])
        self.assertEqual(len(model["relationships"]), len(understand["relationships"]))

    def test_columns_capped_and_column_count_true(self) -> None:
        header = ["c" + str(index) for index in range(250)]
        rows = [[str(index) + "-" + str(row) for index in range(250)] for row in range(2)]
        raw = make_raw("Wide", header, rows)
        bound, snapshot, understand, questions = synthetic([raw])
        model = build_model_view(bound, snapshot, understand, questions)
        self.assertEqual(model["tables"][0]["columnCount"], 250)
        self.assertEqual(len(model["tables"][0]["columns"]), 200)

    def test_is_key_and_is_link_flags(self) -> None:
        orders = make_raw("orders", ["order_id", "customer_id", "order_date"],
                          [["O-1", "C-1", "2026-01-01"], ["O-2", "C-1", "2026-01-02"], ["O-3", "C-2", "2026-01-03"]])
        customers = make_raw("customers", ["customer_id", "name"], [["C-1", "a"], ["C-2", "b"]])
        bound, snapshot, understand, questions = synthetic([orders, customers])
        model = build_model_view(bound, snapshot, understand, questions)
        by_name = {table["name"]: table for table in model["tables"]}
        order_columns = {column["name"]: column for column in by_name["orders"]["columns"]}
        customer_columns = {column["name"]: column for column in by_name["customers"]["columns"]}
        self.assertTrue(order_columns["order_id"]["isKey"])
        self.assertTrue(order_columns["customer_id"]["isLink"])
        self.assertFalse(order_columns["customer_id"]["isKey"])
        self.assertTrue(customer_columns["customer_id"]["isKey"])
        self.assertTrue(customer_columns["customer_id"]["isLink"])

    def test_no_cell_values_except_date_range(self) -> None:
        rows = [["SENTINEL_XYZZY_" + str(i), "C-" + str(i), f"2026-01-{i:02d}"] for i in range(1, 4)]
        raw = make_raw("Sentinel", ["note", "customer_id", "order_date"], rows)
        bound, snapshot, understand, questions = synthetic([raw])
        model = build_model_view(bound, snapshot, understand, questions)
        serialized = json.dumps(model, ensure_ascii=False)
        self.assertNotIn("SENTINEL_XYZZY", serialized)
        self.assertEqual(model["tables"][0]["dateRange"], {"column": "order_date", "min": "2026-01-01", "max": "2026-01-03"})

    def test_inputs_not_mutated(self) -> None:
        bound, snapshot, understand, questions = scenario("tp-sales")
        bound_before, snapshot_before = deepcopy(bound), deepcopy(snapshot)
        understand_before, questions_before = deepcopy(understand), deepcopy(questions)
        build_model_view(bound, snapshot, understand, questions)
        self.assertEqual(bound, bound_before)
        self.assertEqual(snapshot, snapshot_before)
        self.assertEqual(understand, understand_before)
        self.assertEqual(questions, questions_before)

    def test_deterministic_twice_identical_hash(self) -> None:
        bound, snapshot, understand, questions = scenario("tp-fin")
        first = build_model_view(bound, snapshot, understand, questions)
        second = build_model_view(bound, snapshot, understand, questions)
        self.assertEqual(first, second)
        self.assertEqual(first["modelViewHash"], second["modelViewHash"])
        self.assertEqual(model_view_hash(first), first["modelViewHash"])

    def test_output_validates_against_schema(self) -> None:
        schema = json.loads(schema_path("assistant_model_view.schema.json").read_text(encoding="utf-8"))
        for fixture in ("tp-fin", "tp-sales"):
            with self.subTest(fixture=fixture):
                bound, snapshot, understand, questions = scenario(fixture)
                model = build_model_view(bound, snapshot, understand, questions)
                self.assertEqual(validate(model, schema), [])

    def test_measured_on_full_vs_sample_and_measured_rows(self) -> None:
        header = ["order_id", "order_date"]
        rows = [[f"O-{index:04d}", f"2026-{(index % 12) + 1:02d}-15"] for index in range(500)]
        full_raw = make_raw("Big", header, rows, total_rows=500, mode="compute")
        bound, snapshot, understand, questions = synthetic([full_raw], mode="compute")
        model = build_model_view(bound, snapshot, understand, questions)
        self.assertEqual(model["measuredOn"], "full")
        table = model["tables"][0]
        self.assertEqual(table["rowCount"], 500)
        self.assertEqual(table["measuredRows"], 500)
        sample_raw = make_raw("Big", header, rows[:20], total_rows=500, mode="discover")
        bound_s, snapshot_s, understand_s, questions_s = synthetic([sample_raw], mode="discover")
        model_s = build_model_view(bound_s, snapshot_s, understand_s, questions_s)
        self.assertEqual(model_s["measuredOn"], "sample")
        self.assertEqual(model_s["tables"][0]["rowCount"], 500)
        self.assertEqual(model_s["tables"][0]["measuredRows"], 20)

    def test_relationship_orphans_on_full_rows_match_oracle(self) -> None:
        # 60 orders: C-01..C-12, five rows each; only C-01..C-10 exist.
        order_rows = []
        for customer in range(1, 13):
            for _ in range(5):
                order_rows.append([f"O-{len(order_rows) + 1:04d}", f"C-{customer:02d}", f"2026-{(customer % 12) + 1:02d}-15"])
        orders = make_raw("orders", ["order_id", "customer_id", "order_date"], order_rows)
        customers = make_raw("customers", ["customer_id", "name"],
                             [[f"C-{index:02d}", "name" + str(index)] for index in range(1, 11)])
        bound, snapshot, understand, questions = synthetic([orders, customers])
        model = build_model_view(bound, snapshot, understand, questions)
        orders_id = next(table["id"] for table in snapshot["tables"] if table["name"] == "orders")
        link = next(link for link in model["relationships"]
                    if link["fromTable"] == orders_id and link["fromColumns"] == ["customer_id"])
        self.assertEqual(link["orphan"], 10, "orphans must be measured on all 60 rows, not the 20-row sample")
        # The first 20 rows only contain C-01..C-04 (0 orphans on a sample), so
        # this assertion also guards against sample-based measurement.
        self.assertNotEqual(link["orphan"], 0)
        orders_table = next(table for table in model["tables"] if table["name"] == "orders")
        self.assertEqual(orders_table["grainEvidence"]["distinctDates"], 12)

    def test_module_has_no_external_or_ai_imports(self) -> None:
        package = Path(pbip_assistant.__file__).parent / "sources"
        tree = ast.parse((package / "assistant_model_view.py").read_text(encoding="utf-8"))
        forbidden = {"socket", "urllib", "http", "requests", "subprocess", "openai"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name.split(".")[0] in forbidden for alias in node.names),
                                 "assistant_model_view must not import network/AI modules")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertFalse(node.module.split(".")[0] in forbidden,
                                 "assistant_model_view must not import network/AI modules")
        self.assertNotIn("coordinator", tree_text := ast.dump(tree), "no coordinator import")


if __name__ == "__main__":
    unittest.main()