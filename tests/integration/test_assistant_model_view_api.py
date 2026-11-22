"""Store/API return the derived modelView; grain questions and AF_UNDERSTAND_LIMIT (T403)."""

from __future__ import annotations

from copy import deepcopy
import json
import unittest

from pbip_assistant.core.resources import schema_path
from pbip_assistant.sources.assistant_session import _questions
from pbip_assistant.sources.assistant_understand import build_understand, understand_hash
from tests.integration import test_excel_addin_server as harness
from tests.support.assistant_flow import AssistantBranchPlanner
from tests.support.json_schema_oracle import validate
from tests.support.paths import FIXTURES


class RecordingPlanner:
    """Deterministic local planner that records the exact Codex-bound payload."""

    def __init__(self):
        self.calls = []

    def propose(self, payload):
        self.calls.append(deepcopy(payload))
        return AssistantBranchPlanner().propose(payload)


class AssistantModelViewApiTests(unittest.TestCase):
    setUp = harness.ExcelAddinServerTests.setUp
    tearDown = harness.ExcelAddinServerTests.tearDown
    request = harness.ExcelAddinServerTests.request
    auth = harness.ExcelAddinServerTests.auth

    def post(self, suffix, body=None):
        status, _, payload = self.request("POST", "/api/assistant/" + suffix, body or {}, self.auth())
        return status, payload

    def bind_fixture(self, scenario: str, mode="discover") -> None:
        root = FIXTURES / ("assistant/" + scenario + "/source")
        status, payload = self.post("session", {"root": str(root.resolve())})
        self.assertEqual(status, 200, payload)
        requests = [{"kind": "csv", "mode": mode, "path": str(path.resolve())}
                    for path in sorted(root.glob("*.csv"))]
        if scenario == "tp-sales":
            requests.append({"kind": "folder", "mode": mode, "path": str((root / "orders").resolve()), "name": "Orders"})
        status, ingest = self.post("ingest", {"requests": requests})
        self.assertEqual(status, 200, ingest)
        self.assertEqual(ingest["stage"], "ingested")

    def workbook_selection(self, header, rows, mode="discover", total_rows=None):
        return {"kind": "workbook", "mode": mode, "payload": {
            "header": header, "rows": rows, "sampleOrdinals": list(range(len(rows))),
            "totalRows": total_rows if total_rows is not None else len(rows),
            "totalColumns": len(header), "name": "Transactions", "origin": "Workbook!Data",
            "sheet": "Data", "table": True}}

    def schema(self) -> dict:
        return json.loads(schema_path("assistant_model_view.schema.json").read_text(encoding="utf-8"))

    def test_understand_returns_model_view_bound_to_understand_hash(self) -> None:
        self.bind_fixture("tp-fin")
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        model = payload["modelView"]
        self.assertIsNotNone(model)
        self.assertEqual(model["understandHash"], payload["understand"]["understandHash"])
        self.assertEqual(model["mode"], "model")
        self.assertEqual(validate(model, self.schema()), [])

    def test_state_returns_same_model_view_then_null_after_reset_and_reingest(self) -> None:
        self.bind_fixture("tp-fin")
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        status, state = self.post("state")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["modelView"], payload["modelView"])
        # A fresh session clears the view.
        self.post("session", {"sourceMode": "workbook"})
        status, state = self.post("state")
        self.assertEqual(status, 200, state)
        self.assertIsNone(state["modelView"])
        # Re-ingesting and understanding restores a modelView again.
        status, ingest = self.post("ingest", {"requests": [self.workbook_selection(["ID"], [["1"], ["2"]])]})
        self.assertEqual(status, 200, ingest)
        status, understand = self.post("understand")
        self.assertEqual(status, 200, understand)
        self.assertIsNotNone(understand["modelView"])
        self.assertNotEqual(understand["modelView"], payload["modelView"])

    def test_understand_hash_unchanged_for_all_fixtures(self) -> None:
        # Recompute through the untouched build_understand path inside the test;
        # the store must return the exact same hash (no string is pinned).
        for scenario in ("tp-fin", "tp-sales"):
            with self.subTest(scenario=scenario):
                self.bind_fixture(scenario, mode="compute")
                status, payload = self.post("understand")
                self.assertEqual(status, 200, payload)
                store = self.server.app.assistant
                with store._lock:
                    expected = understand_hash(build_understand(store._raw_tables, store._snapshot))
                self.assertEqual(payload["understand"]["understandHash"], expected,
                                 scenario + ": understandHash must not change")

    def test_existing_question_ids_unchanged_and_grain_added_only_for_snapshot(self) -> None:
        # compute mode sees every row; TP-FIN's snapshot table (FX_Rates) is a
        # lookup and TP-SALES has none, so no grain question appears there.
        self.bind_fixture("tp-fin", mode="compute")
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        self.assertEqual([q for q in payload["questions"] if q["topic"] == "grain"], [])
        store = self.server.app.assistant
        with store._lock:
            legacy = _questions(store._snapshot, store._understand)
        legacy_ids = {question["id"] for question in legacy}
        store_ids = {question["id"] for question in payload["questions"]}
        self.assertEqual(legacy_ids, store_ids, "existing question ids must be unchanged")
        self.bind_fixture("tp-sales", mode="compute")
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        self.assertEqual([q for q in payload["questions"] if q["topic"] == "grain"], [])
        # A single snapshot table without a dim/lookup role gets exactly one
        # grain question with the contract's options and evidence ref.
        self.post("session", {"sourceMode": "workbook"})
        rows = [["E-1", "2026-01-01"], ["E-1", "2026-01-02"], ["E-1", "2026-01-03"],
                ["E-2", "2026-01-01"], ["E-2", "2026-01-02"], ["E-2", "2026-01-03"]]
        status, ingest = self.post("ingest", {"requests": [
            self.workbook_selection(["entity", "d"], rows, mode="compute")]})
        self.assertEqual(status, 200, ingest)
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        grain = [q for q in payload["questions"] if q["topic"] == "grain"]
        self.assertEqual(len(grain), 1, "one snapshot table → one grain question")
        table_id = payload["snapshot"]["tables"][0]["id"]
        self.assertEqual(grain[0]["evidence"][0]["ref"], table_id)
        self.assertEqual(grain[0]["options"], ["Đúng, là ảnh chụp", "Không, là sự kiện", "Chưa rõ"])

    def test_grain_answer_reaches_plan_request(self) -> None:
        self.bind_fixture("tp-fin")
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        grain = next(question for question in payload["questions"] if question["topic"] == "grain")
        planner = RecordingPlanner()
        store = self.server.app.assistant
        with store._lock:
            store.plan_draft("Tính P&L theo tháng", [{"questionId": grain["id"], "answer": "Đúng, là ảnh chụp"}],
                             True, runner=planner)
        self.assertTrue(planner.calls, "planner must receive the payload")
        answers = planner.calls[0]["answers"]
        self.assertIn({"questionId": grain["id"], "answer": "Đúng, là ảnh chụp"}, answers)
        self.assertNotIn("modelView", planner.calls[0])

    def test_no_fact_graph_returns_per_sheet_without_error(self) -> None:
        self.post("session", {"sourceMode": "workbook"})
        status, ingest = self.post("ingest", {"requests": [self.workbook_selection(["A", "B"], [["1", "x"], ["2", "y"]])]})
        self.assertEqual(status, 200, ingest)
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["stage"], "understood")
        self.assertEqual(payload["modelView"]["mode"], "per_sheet")

    def test_model_view_absent_from_plan_request_payload(self) -> None:
        self.post("session", {"sourceMode": "workbook"})
        self.post("ingest", {"requests": [self.workbook_selection(["ID", "Amount"], [[str(n), str(n * 10)] for n in range(6)])]})
        self.post("understand")
        planner = RecordingPlanner()
        store = self.server.app.assistant
        with store._lock:
            store.plan_draft("Tổng Amount", [], True, runner=planner)
        serialized = json.dumps(planner.calls[0], ensure_ascii=False)
        self.assertNotIn("modelView", serialized)
        self.assertNotIn("dateRange", serialized)

    def test_http_understand_and_state_shapes(self) -> None:
        self.bind_fixture("tp-sales")
        status, understand = self.post("understand")
        self.assertEqual(status, 200, understand)
        status, state = self.post("state")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["modelView"], understand["modelView"])
        self.assertEqual(validate(state["modelView"], self.schema()), [])

    def test_compute_first_ingest_then_understand_measures_all_rows(self) -> None:
        self.post("session", {"sourceMode": "workbook"})
        rows = [[str(n), str(n * 10)] for n in range(30)]
        status, ingest = self.post("ingest", {"requests": [self.workbook_selection(["ID", "Amount"], rows, mode="compute")]})
        self.assertEqual(status, 200, ingest)
        status, payload = self.post("understand")
        self.assertEqual(status, 200, payload)
        model = payload["modelView"]
        self.assertEqual(model["measuredOn"], "full")
        self.assertEqual(model["tables"][0]["rowCount"], 30)
        self.assertEqual(model["tables"][0]["measuredRows"], 30)

    def test_wl2_limit_maps_to_af_understand_limit_409_and_leaves_no_partial_state(self) -> None:
        # 20 eligible columns with no single-column key force the composite
        # pool over 16 columns, raising the bounded column-pool ValueError.
        header = ["c" + str(index) for index in range(19)] + ["unique"]
        rows = [["a"] * 19 + ["u0"], ["b"] * 19 + ["u1"], ["a"] * 18 + ["b"] + ["u2"]]
        self.post("session", {"sourceMode": "workbook"})
        status, ingest = self.post("ingest", {"requests": [self.workbook_selection(header, rows, mode="compute")]})
        self.assertEqual(status, 200, ingest)
        status, error = self.post("understand")
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "AF_UNDERSTAND_LIMIT")
        self.assertIn("vượt giới hạn", error["error"]["detail"])
        status, state = self.post("state")
        self.assertEqual(status, 200, state)
        self.assertEqual(state["stage"], "ingested")
        self.assertIsNone(state["understand"])
        self.assertIsNone(state["modelView"])

    def test_other_value_errors_still_af_understand_invalid(self) -> None:
        self.bind_fixture("tp-fin")
        store = self.server.app.assistant
        with store._lock:
            store._raw_tables[0]["rows"][0][0] = "CHANGED_CELL"
        status, error = self.post("understand")
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "AF_UNDERSTAND_INVALID")

    def test_plan_request_still_has_at_most_20_sample_rows_after_compute_ingest(self) -> None:
        self.post("session", {"sourceMode": "workbook"})
        rows = [[str(n), str(n * 10)] for n in range(50)]
        self.post("ingest", {"requests": [self.workbook_selection(["ID", "Amount"], rows, mode="compute")]})
        self.post("understand")
        planner = RecordingPlanner()
        store = self.server.app.assistant
        with store._lock:
            store.plan_draft("Tổng Amount", [], True, runner=planner)
        self.assertLessEqual(len(planner.calls[0]["sampleRows"]), 20)


if __name__ == "__main__":
    unittest.main()