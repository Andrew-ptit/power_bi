"""Assistant v2 uses the real loopback HTTP/token harness and synthetic sources."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from pbip_assistant.coordinator.server import (
    ASSISTANT_PATHS, CODEX_JOB_PATHS, EXCEL_JOB_PATHS, STATE_PATHS, ExcelAddinRequestHandler,
)
from tests.integration import test_excel_addin_server as harness
from tests.support.paths import FIXTURES


class AssistantFlowApiTests(unittest.TestCase):
    setUp = harness.ExcelAddinServerTests.setUp
    tearDown = harness.ExcelAddinServerTests.tearDown
    request = harness.ExcelAddinServerTests.request
    auth = harness.ExcelAddinServerTests.auth

    def post(self, suffix, body=None):
        status, _, payload = self.request("POST", "/api/assistant/" + suffix, body or {}, self.auth())
        return status, payload

    def bind(self):
        root = FIXTURES / "assistant/tp-fin/source"
        status, payload = self.post("session", {"root": str(root.resolve())})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["stage"], "new")
        self.assertEqual(payload["rootLabel"], "source")
        self.assertNotIn(str(root.resolve()), json.dumps(payload))
        return root

    def selection(self, mode="discover", count=2):
        return {"kind": "workbook", "mode": mode, "payload": {
            "header": ["ID", "Amount"], "rows": [[str(n), str(n * 10)] for n in range(count)],
            "sampleOrdinals": list(range(count)), "totalRows": count, "totalColumns": 2,
            "name": "Transactions", "origin": "Workbook!Data", "sheet": "Data", "table": True,
        }}

    def test_workbook_only_session_does_not_require_or_grant_a_folder(self):
        status, payload = self.post("session", {"sourceMode": "workbook"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["rootLabel"], "Workbook")
        status, payload = self.post("ingest", {"requests": [self.selection()]})
        self.assertEqual(status, 200, payload)
        self.assertIsNotNone(payload["snapshot"])
        status, payload = self.post("session", {"sourceMode": "workbook", "root": "ignored"})
        self.assertEqual(status, 400, payload)
        status, payload = self.post("ingest", {"requests": [{"kind": "csv", "mode": "compute", "path": "private.csv"}]})
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["error"]["code"], "ASSISTANT_WORKBOOK_REQUIRED")

    def test_session_ingest_understand_fixture_and_deterministic_questions(self):
        root = self.bind()
        requests = [{"kind": "csv", "mode": "discover", "path": str(path.resolve())}
                    for path in sorted(root.glob("*.csv"))]
        status, ingest = self.post("ingest", {"requests": requests})
        self.assertEqual(status, 200, ingest)
        self.assertEqual(ingest["stage"], "ingested")
        self.assertEqual(len(ingest["tables"]), 7)
        self.assertTrue(all(t["rowCount"] <= 20 for t in ingest["sampleInfo"]))
        status, first = self.post("understand")
        self.assertEqual(status, 200, first)
        self.assertEqual(first["stage"], "understood")
        self.assertGreaterEqual(len(first["questions"]), 3)
        self.assertTrue(all(q["evidence"] for q in first["questions"]))
        status, second = self.post("understand")
        self.assertEqual(status, 200, second)
        self.assertEqual(first, second)

    def test_duplicate_names_block_understand(self):
        self.bind()
        status, result = self.post("ingest", {"requests": [self.selection(), self.selection()]})
        self.assertEqual(status, 200)
        self.assertEqual(result["stage"], "ingest_blocked")
        self.assertTrue(result["requiresRename"])
        self.assertIsNone(result["snapshot"])
        status, error = self.post("understand")
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "AF_STAGE_INVALID")

    def test_relative_or_missing_root_rejected(self):
        for root in ("relative/root", str(Path(self.temp.name) / "missing")):
            with self.subTest(root=root):
                status, result = self.post("session", {"root": root})
                self.assertEqual(status, 400)
                self.assertEqual(result["error"]["code"], "ASSISTANT_ROOT_INVALID")

    def test_sample_ordinals_are_validated(self):
        self.bind()
        for ordinals in (None, [0, 0], [1, 0], [0, 2], [True, 1], [0], [0.0, 1]):
            with self.subTest(ordinals=ordinals):
                selection = self.selection()
                if ordinals is None:
                    selection["payload"].pop("sampleOrdinals")
                else:
                    selection["payload"]["sampleOrdinals"] = ordinals
                status, result = self.post("ingest", {"requests": [selection]})
                self.assertEqual(status, 200)
                self.assertEqual(result["stage"], "ingest_blocked")
                self.assertEqual(result["errors"][0]["code"], "AF_INGEST_FAILED")

    def test_discover_rejects_more_than_twenty_rows(self):
        self.bind()
        status, result = self.post("ingest", {"requests": [self.selection(count=21)]})
        self.assertEqual(status, 200)
        self.assertEqual(result["stage"], "ingest_blocked")
        self.assertEqual(result["errors"][0]["code"], "AF_INGEST_FAILED")

    def test_empty_workbook_or_file_selection_is_blocked(self):
        self.post("session", {"root": self.temp.name})
        empty_csv = Path(self.temp.name) / "empty.csv"
        empty_csv.write_text("ID,Amount\n", encoding="utf-8")
        for selection in (self.selection(count=0), {"kind": "csv", "mode": "discover",
                "path": str(empty_csv), "options": {"delimiter": ","}}):
            with self.subTest(kind=selection["kind"]):
                status, result = self.post("ingest", {"requests": [selection]})
                self.assertEqual(status, 200)
                self.assertEqual(result["stage"], "ingest_blocked")
                self.assertEqual(result["errors"][0]["code"], "AF_INGEST_FAILED")

    def test_compute_requires_full_rows_and_correct_width(self):
        self.bind()
        for variant in ("partial", "width"):
            selection = self.selection("compute")
            if variant == "partial":
                selection["payload"]["totalRows"] = 3
            else:
                selection["payload"]["rows"][0].pop()
            with self.subTest(variant=variant):
                status, result = self.post("ingest", {"requests": [selection]})
                self.assertEqual(status, 200)
                self.assertEqual(result["stage"], "ingest_blocked")

    def test_unknown_or_mixed_mode_is_bad_request(self):
        self.bind()
        for requests in ([self.selection("bad")], [self.selection(), self.selection("compute")]):
            status, result = self.post("ingest", {"requests": requests})
            self.assertEqual(status, 400)
            self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

    def test_mode_ordinals_and_total_rows_are_snapshot_hash_bound(self):
        self.bind()
        snapshots = []
        for mode, total, ordinals in (("discover", 2, [0, 1]), ("compute", 2, [0, 1]),
                                       ("discover", 3, [0, 1]), ("discover", 3, [0, 2])):
            selection = self.selection(mode)
            selection["payload"].update(totalRows=total, sampleOrdinals=ordinals)
            status, result = self.post("ingest", {"requests": [selection]})
            self.assertEqual(status, 200, result)
            self.assertEqual(result["stage"], "ingested")
            snapshots.append(result["snapshotHash"])
        self.assertEqual(len(set(snapshots)), 4)

    def test_discover_sample_is_deterministic_per_content(self):
        self.post("session", {"root": self.temp.name})
        source = Path(self.temp.name) / "data.csv"
        source.write_text("id,amount\n" + "\n".join(f"{i},{i * 10}" for i in range(50)), encoding="utf-8")
        requests = [{"kind": "csv", "mode": "discover", "path": str(source), "options": {"delimiter": ","}}]
        _, first = self.post("ingest", {"requests": requests})
        _, repeat = self.post("ingest", {"requests": requests})
        self.assertEqual(first["snapshotHash"], repeat["snapshotHash"])
        self.assertEqual(first["sampleInfo"], repeat["sampleInfo"])
        self.assertEqual(first["sampleInfo"][0]["rowCount"], 20)
        self.assertEqual(first["sampleInfo"][0]["totalRows"], 50)
        self.assertEqual(first["sampleInfo"][0]["sampleOrdinals"][0], 0)
        self.assertEqual(first["sampleInfo"][0]["sampleOrdinals"][-1], 49)
        source.write_text(source.read_text(encoding="utf-8") + "0", encoding="utf-8")
        _, changed = self.post("ingest", {"requests": requests})
        self.assertNotEqual(first["snapshotHash"], changed["snapshotHash"])

    def test_one_table_or_unrelated_tables_ask_roles_without_fabricated_fact(self):
        self.bind()
        for count in (1, 2):
            requests = [self.selection()]
            if count == 2:
                other = deepcopy(self.selection())
                other["payload"].update(name="Independent", header=["Category", "Label"],
                                         rows=[["a", "Alpha"], ["b", "Beta"]])
                requests.append(other)
            _, ingested = self.post("ingest", {"requests": requests})
            self.assertEqual(ingested["stage"], "ingested")
            status, result = self.post("understand")
            self.assertEqual(status, 200, result)
            self.assertEqual(result["understand"]["roles"], [])
            roles = [q for q in result["questions"] if q["topic"] == "role"]
            self.assertEqual(len(roles), 1)
            self.assertEqual(roles[0]["evidence"][0]["value"]["tableCount"], count)

    def test_high_null_rate_produces_question(self):
        self.bind()
        selection = self.selection()
        selection["payload"]["rows"][0][1] = ""
        self.post("ingest", {"requests": [selection]})
        status, result = self.post("understand")
        self.assertEqual(status, 200, result)
        nulls = [q for q in result["questions"] if q["topic"] == "nulls"]
        self.assertEqual(len(nulls), 1)
        self.assertEqual(nulls[0]["evidence"][0]["value"], "nullRate=0.5")

    def test_high_fanout_produces_confirmation_question(self):
        root = self.bind()
        self.post("ingest", {"requests": [{"kind": "csv", "mode": "compute", "path": str(p.resolve())}
                                            for p in sorted(root.glob("*.csv"))]})
        status, result = self.post("understand")
        self.assertEqual(status, 200, result)
        risky = {link["id"] for link in result["understand"]["relationships"] if link["fanOutRisk"] == "high"}
        self.assertTrue(risky)
        questions = [q for q in result["questions"] if q["topic"] == "relationship"]
        self.assertTrue(risky <= {q["evidence"][0]["ref"] for q in questions})

    def test_tampered_snapshot_rejected_before_unknown_role_fallback(self):
        self.bind()
        self.post("ingest", {"requests": [self.selection()]})
        store = self.server.app.assistant
        with store._lock:
            store._snapshot["tables"][0]["rowCount"] += 1
        status, result = self.post("understand")
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "AF_UNDERSTAND_INVALID")

    def test_compute_tail_is_hash_bound_and_revalidated(self):
        self.bind()
        _, result = self.post("ingest", {"requests": [self.selection("compute", count=25)]})
        self.assertIn("contentHash", result["tables"][0])
        store = self.server.app.assistant
        with store._lock:
            store._raw_tables[0]["rows"][-1][1] = "999999"
        status, error = self.post("understand")
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "AF_UNDERSTAND_INVALID")

    def test_ambiguous_csv_has_relative_origin_for_retry(self):
        self.post("session", {"root": self.temp.name})
        source = Path(self.temp.name) / "ambiguous.csv"
        source.write_text("A,B;C\n1,2;3\n4,5;6\n", encoding="utf-8")
        _, blocked = self.post("ingest", {"requests": [{"kind": "csv", "mode": "discover", "path": str(source)}]})
        self.assertEqual(blocked["stage"], "ingest_blocked")
        self.assertFalse(blocked["sources"])
        self.assertEqual(blocked["csvOptions"][0]["origin"], "ambiguous.csv")
        self.assertEqual(blocked["csvOptions"][0]["requestIndex"], 0)

    def test_state_reset_and_bootstrap_clear_assistant_artifacts(self):
        self.bind()
        self.post("ingest", {"requests": [self.selection()]})
        self.post("understand")
        _, state = self.post("state")
        self.assertEqual(state["stage"], "understood")
        self.assertNotIn("root", state)
        self.assertEqual(state["understand"]["understandHash"], state["understandHash"])
        self.assertTrue(state["questions"])
        self.assertTrue(state["tables"])
        _, reset = self.post("reset")
        self.assertEqual(reset["stage"], "new")
        self.assertIsNone(reset["snapshotHash"])
        self.assertEqual(reset["sampleInfo"], [])
        self.bind()
        self.post("ingest", {"requests": [self.selection()]})
        self.server.app._clear_session_state()
        self.assertEqual(self.server.app.assistant.state()["stage"], "new")

    def test_all_routes_registered_with_central_authorization_and_slots(self):
        self.assertEqual(len(ASSISTANT_PATHS), 11)
        self.assertTrue(ASSISTANT_PATHS <= STATE_PATHS)
        self.assertIn("/api/assistant/plan-draft", CODEX_JOB_PATHS)
        self.assertNotIn("/api/assistant/branches", EXCEL_JOB_PATHS)
        self.assertNotIn("/api/assistant/apply", EXCEL_JOB_PATHS)
        for route in ASSISTANT_PATHS:
            method = ExcelAddinRequestHandler.POST_ENDPOINTS[route]
            self.assertTrue(callable(getattr(ExcelAddinRequestHandler, method)), route)
            status, _, error = self.request("POST", route, {})
            self.assertEqual(status, 403, route)
            self.assertEqual(error["error"]["code"], "TOKEN_REQUIRED")
        status, _, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue(bootstrap["capabilities"]["assistantFlowV2"])
        self.assertEqual(bootstrap["capabilities"]["assistantFlowStages"], [
            "new", "ingested", "understood", "planning", "branched", "frozen", "approved",
            "handoff", "partial", "applied", "recorded",
        ])


if __name__ == "__main__":
    unittest.main()
