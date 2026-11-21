"""Historical Record privacy, exact Apply authority and metadata freshness."""

import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_record import _BASIS
from pbip_assistant.sources.assistant_record_v2 import (record_hash_v2, record_node,
    compute_v2_delta, detect_stale_v2, utc_timestamp)
from pbip_assistant.sources.assistant_session import AssistantSessionStore
from tests.support.assistant_flow import AssistantBranchPlanner
from tests.support.paths import FIXTURES


STAMP = "2026-10-31T10:00:00+07:00"
IDENTITY = {"name": "Synthetic.xlsx", "documentHash": canonical_hash("synthetic")}
PACKAGE = base64.b64encode((FIXTURES / "source/orders_synthetic.xlsx").read_bytes()).decode("ascii")


class AssistantRecordV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AssistantSessionStore()
        self.addCleanup(self.store.close)
        self.store.bind_root(self.temp.name)
        self.request = {"kind": "workbook", "mode": "compute", "payload": {
            "name": "Transactions", "origin": "Workbook!Data!Transactions", "sheet": "Data", "table": True,
            "header": ["ID", "Amount"], "rows": [["a", "12"], ["b", "-3"], ["c", "3"]],
            "totalRows": 3, "sampleOrdinals": [0, 1, 2]}}

    def prepare(self, requests=None):
        self.store.ingest(requests or [deepcopy(self.request)])
        self.store.understand()
        self.store.plan_draft("Sum Amount and compare alternatives", [], True, AssistantBranchPlanner())
        self.store.run_branches(self.store.state()["planningHash"])
        branch = self.store.state()["branches"][0]
        self.store.freeze("A", STAMP, IDENTITY, False, expected_planning_hash=self.store.state()["planningHash"],
            expected_preview_hash=branch["previewHash"], expected_result_digest=branch["resultDigest"])
        spec = self.store.state()["spec"]
        self.expected = {"expected_spec_fingerprint": spec["fingerprint"], "expected_preview_hash": spec["previewHash"], "expected_result_digest": spec["resultDigest"]}
        sources = [deepcopy(self.request)] if requests is None else []
        self.store.approve(STAMP, True, IDENTITY, sources, **self.expected)
        self.handoff = self.store.apply(PACKAGE, STAMP, IDENTITY, sources, **self.expected)

    def complete(self):
        self.store.complete_apply({**self.handoff["receiptBinding"], "verified": True}, STAMP)

    def assert_code(self, code, action):
        with self.assertRaises(InputError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_record_requires_consumed_approval_and_exact_verified_receipt(self):
        self.assert_code("AF_STAGE_INVALID", self.store.record)
        self.prepare()
        self.assert_code("AF_STAGE_INVALID", self.store.record)
        self.complete()
        self.store._apply_receipt["resultDigest"] = canonical_hash("other")
        self.assert_code("AF_STAGE_INVALID", self.store.record)

    def test_record_roundtrip_preserves_basis_and_complete_auditable_plan(self):
        self.prepare()
        self.complete()
        output = self.store.record()
        record = output["record"]
        self.assertEqual(record["schemaVersion"], "2.0")
        self.assertEqual(record["hashBasis"], list(_BASIS))
        self.assertEqual(output["recordHash"], canonical_hash({key: record[key] for key in _BASIS}))
        self.assertEqual(record_hash_v2(json.loads(json.dumps(record))), record["hash"])
        self.assertEqual(record["steps"], self.store.state()["spec"]["steps"])
        reconciliation = record["reconciliations"][0]
        self.assertEqual(reconciliation["specFingerprint"], self.store.state()["spec"]["fingerprint"])
        self.assertEqual(reconciliation["engine"]["executor"], "typed_local")
        self.assertEqual(reconciliation["engine"]["parityChecked"], "none")
        self.assertIn("decimal-money", reconciliation["engine"]["knownDifferences"])
        self.assertEqual(output["node"]["recordHash"], record["hash"])
        self.assertEqual(output["node"]["hash"], canonical_hash({key: value for key, value in output["node"].items() if key != "hash"}))
        self.assertNotEqual(output["node"]["hash"], record["hash"])
        self.assertEqual(output["node"]["createdAt"], "2026-10-31T03:00:00Z")
        self.assertFalse(output["workbookSaved"])

    def test_record_repeated_calls_are_immutable_and_owned_copies(self):
        self.prepare(); self.complete()
        first = self.store.record()
        changed = deepcopy(first)
        changed["record"]["labels"].append("stale")
        changed["node"]["labels"].append("stale")
        self.assertEqual(first, self.store.record())
        state = self.store.state()
        self.assertEqual(state["stage"], "recorded")
        self.assertEqual(state["handoffStatus"], "readback-verified")
        self.assertEqual(state["recordHash"], first["recordHash"])

    def test_record_contains_no_raw_source_cells_samples_or_paths(self):
        self.request["payload"]["rows"][0][0] = "PRIVATE_SOURCE_SENTINEL"
        self.prepare(); self.complete()
        serialized = json.dumps(self.store.record()["record"])
        for forbidden in ("PRIVATE_SOURCE_SENTINEL", "sampleRows", "sampleOrdinals", "relativeOrigin", "objectName", self.temp.name):
            self.assertNotIn(forbidden, serialized)
        record = self.store.record()["record"]
        record["reconciliations"][0]["sourceSchemas"][0]["sampleRows"] = [["secret"]]
        self.assert_code("AF_RECORD_INVALID", lambda: record_hash_v2(record))

    def test_record_rejects_path_in_declared_plan_without_hiding_algorithm(self):
        self.prepare(); self.complete()
        record = self.store.record()["record"]
        record["brief"]["prompt"] = r"Load C:\private\file.csv"
        self.assert_code("AF_RECORD_INVALID", lambda: record_hash_v2(record))

    def test_record_rejects_changed_original_reconcile_hash_basis(self):
        self.prepare(); self.complete()
        record = self.store.record()["record"]
        record["reconciliations"][0]["controlTotalSource"] = "999"
        self.assert_code("AF_RECORD_INVALID", lambda: record_hash_v2(record))

    def test_record_marks_stale_after_source_change_without_rewriting_history(self):
        path = Path(self.temp.name) / "transactions.csv"
        path.write_text("ID,Amount\na,12\nb,-3\nc,3\n", encoding="utf-8")
        self.prepare([{"kind": "csv", "mode": "compute", "path": "transactions.csv", "options": {"delimiter": ","}}])
        self.complete()
        first = self.store.record()
        self.assertEqual(first["staleCheck"]["freshness"], "matches")
        path.write_text("ID,Amount\na,13\nb,-3\nc,3\n", encoding="utf-8")
        second = self.store.record()
        self.assertTrue(second["staleCheck"]["stale"])
        self.assertEqual(second["staleCheck"]["reason"], "sourceChanged")
        for field in ("record", "node", "recordHash"):
            self.assertEqual(first[field], second[field])

    def test_workbook_freshness_unknown_until_actual_full_source_reload(self):
        self.prepare(); self.complete()
        record = self.store.record()
        self.assertIsNone(record["staleCheck"]["stale"])
        self.assertEqual(record["staleCheck"]["freshness"], "unknown")
        self.assertFalse(detect_stale_v2(record["record"], current_snapshot_hash=record["node"]["snapshot"])["stale"])
        self.assertTrue(detect_stale_v2(record["record"], current_snapshot_hash=canonical_hash("changed"))["stale"])

    def test_unreadable_source_is_unknown_and_keeps_historical_record(self):
        path = Path(self.temp.name) / "transactions.csv"
        path.write_text("ID,Amount\na,12\nb,-3\nc,3\n", encoding="utf-8")
        self.prepare([{"kind": "csv", "mode": "compute", "path": "transactions.csv", "options": {"delimiter": ","}}])
        self.complete()
        first = self.store.record()
        path.unlink()
        second = self.store.record()
        self.assertIsNone(second["staleCheck"]["stale"])
        self.assertEqual(second["staleCheck"]["reason"], "sourceUnavailable")
        self.assertEqual(first["record"], second["record"])

    def test_generic_delta_counts_source_nulls_duplicates_and_typed_column_changes(self):
        self.request["payload"]["rows"] = [["a", "12"], ["a", "12"], ["", "3"]]
        self.prepare(); self.complete()
        delta = self.store.record()["record"]["delta"]
        self.assertEqual((delta["rowsIn"], delta["rowsOut"]), (3, 1))
        self.assertEqual(delta["duplicatesBefore"], 1)
        self.assertEqual(delta["duplicatesAfter"], 0)
        self.assertEqual(sorted(delta["nullsBefore"].values()), [0, 1])
        self.assertEqual(list(delta["nullsAfter"].values()), [0])
        self.assertTrue(any("table.changeTypes" in change for change in delta["changedColumns"]))
        self.assertTrue(any("table.aggregateRows" in change for change in delta["changedColumns"]))

    def test_record_timestamp_is_canonical_utc_at_most_milliseconds(self):
        self.assertEqual(utc_timestamp("2026-10-31T10:00:00.123456+07:00"), "2026-10-31T03:00:00.123Z")
        self.assert_code("AF_RECORD_INVALID", lambda: utc_timestamp("2026-10-31T10:00:00"))

    def test_generic_delta_counts_unique_ancestors_above_single_source_row_limit(self):
        column = {"columnId": "col_value", "name": "Value", "inferredType": "text"}
        sources = [{"sourceId": name, "columns": [column], "objectName": name} for name in ("left", "right")]
        def source_step(name):
            return {"stepId": name, "operation": {"type": "source.workbookTable", "parameters": {"sourceId": name}},
                "inputs": [], "outputContract": {"columns": [column]}}
        final = {"stepId": "append", "operation": {"type": "table.appendTables", "parameters": {}},
            "inputs": [{"kind": "step", "ref": name} for name in ("left", "right")], "outputContract": {"columns": [column]}}
        plan = {"sources": sources, "steps": [source_step("left"), source_step("right"), final], "finalOutputStepId": "append"}
        tables = [{"name": name, "mode": "compute", "header": ["Value"], "rows": [["x"]] * 50001, "totalRows": 50001} for name in ("left", "right")]
        result = {"columns": [{"name": "Value", "type": "text"}], "rows": [["x"]]}
        delta = compute_v2_delta(plan, tables, result)
        self.assertEqual(delta["rowsIn"], 100002)
        self.assertEqual(delta["duplicatesBefore"], 100000)
        final["inputs"][1]["ref"] = "left"
        self.assertEqual(compute_v2_delta(plan, tables, result)["rowsIn"], 50001)

    def test_record_rejects_unknown_operation_or_malformed_metadata(self):
        self.prepare(); self.complete()
        record = self.store.record()["record"]
        record["steps"][0]["operation"]["type"] = "table.unknown"
        self.assert_code("AF_RECORD_INVALID", lambda: record_hash_v2(record))
        self.assert_code("AF_RECORD_INVALID", lambda: record_hash_v2({"schemaVersion": "2.0"}))

    def test_record_node_cannot_mislabel_selected_branch(self):
        self.prepare(); self.complete()
        record = self.store.record()["record"]
        self.assert_code("AF_RECORD_INVALID", lambda: record_node(record, "B"))


if __name__ == "__main__":
    unittest.main()
