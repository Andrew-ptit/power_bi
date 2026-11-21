"""Real loopback HTTP journeys with plan-only AI and handwritten numeric oracles.

These are synthetic coordinator tests, not Office.js or live Excel evidence.
"""

from copy import deepcopy
import base64
import json
from pathlib import Path
import unittest

from pbip_assistant.sources.assistant_ingest import canonical_hash
from tests.integration import test_excel_addin_server as harness
from tests.support.assistant_flow import AssistantBranchPlanner


class AssistantV2JourneyTests(unittest.TestCase):
    setUp = harness.ExcelAddinServerTests.setUp
    tearDown = harness.ExcelAddinServerTests.tearDown
    request = harness.ExcelAddinServerTests.request
    auth = harness.ExcelAddinServerTests.auth

    def post(self, suffix, body=None, expected=200):
        status, _, payload = self.request("POST", "/api/assistant/" + suffix,
                                          body or {}, self.auth())
        self.assertEqual(status, expected, payload)
        return payload

    def draft(self, file_source=False):
        self.planner = AssistantBranchPlanner()
        self.server.app.assistant_plan_runner = self.planner
        self.post("session", {"root": self.temp.name})
        self.selection = {"kind": "workbook", "mode": "discover", "payload": {
            "name": "Transactions", "origin": "synthetic", "sheet": "Data", "table": True,
            "header": ["ID", "Amount"], "rows": [["A", "10"], ["B", "-3"], ["C", "5"]],
            "totalRows": 3, "totalColumns": 2, "sampleOrdinals": [0, 1, 2],
        }}
        if file_source:
            Path(self.temp.name, "Transactions.csv").write_text(
                "ID,Amount\nA,10\nB,-3\nC,5\n", encoding="utf-8")
            self.selection = {"kind": "csv", "mode": "discover", "path": "Transactions.csv",
                              "options": {"delimiter": ","}}
        self.post("ingest", {"requests": [self.selection]})
        self.post("understand")
        return self.post("plan-draft", {
            "prompt": "Compare the sum of Amount for all rows and for positive rows.",
            "answers": [], "acknowledged": True,
        })

    def compute(self, file_source=False):
        planning = self.draft(file_source)
        self.selection["mode"] = "compute"
        bound = self.post("ingest", {"requests": [self.selection],
                                     "expectedPlanningHash": planning["planningHash"]})
        self.assertEqual(bound["planningHash"], planning["planningHash"])
        return self.post("branches")

    def freeze(self):
        branches = self.compute(file_source=True)
        self.branch = branches["branches"][0]
        self.identity = {"name": "Synthetic", "documentHash": canonical_hash("owned-synthetic-workbook")}
        self.frozen = self.post("freeze", {
            "branchId": "A", "createdAt": "2026-10-31T03:00:00.000Z",
            "workbookIdentity": self.identity, "acknowledgeMissingControl": False,
            "expectedPlanningHash": branches["planningHash"],
            "expectedPreviewHash": self.branch["previewHash"],
            "expectedResultDigest": self.branch["resultDigest"],
        })
        return self.frozen

    def approval_body(self):
        return {"approvedAt": "2026-10-31T03:00:00.000Z", "acknowledged": True,
                "workbookIdentity": self.identity, "workbookSources": [],
                "expectedSpecFingerprint": self.frozen["spec"]["fingerprint"],
                "expectedPreviewHash": self.branch["previewHash"],
                "expectedResultDigest": self.branch["resultDigest"]}

    def apply_body(self):
        body = self.approval_body()
        body.pop("approvedAt")
        body.pop("acknowledged")
        return {**body, "appliedAt": "2026-10-31T03:00:00.000Z",
                "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii")}

    def complete_synthetic_apply(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        handoff = self.post("apply", self.apply_body())
        receipt = {**handoff["receiptBinding"], "verified": True}
        return self.post("apply", {"receipt": receipt, "appliedAt": "2026-10-31T03:00:00.000Z"})

    def test_compute_http_branches_share_snapshot_and_keep_full_results_private(self):
        result = self.compute()
        self.assertEqual(result["stage"], "branched")
        self.assertEqual(result["snapshotHash"], self.post("state")["snapshotHash"])
        self.assertEqual({branch["id"] for branch in result["branches"]}, {"A", "B"})
        for branch in result["branches"]:
            self.assertEqual(branch["rows"], [["12" if branch["id"] == "A" else "15"]])
            self.assertEqual(branch["totalRows"], 1)
            self.assertTrue(branch["reconciliation"]["passed"])
            self.assertTrue(branch["selectable"])
            self.assertEqual(branch["engine"]["parityChecked"], "none")
        self.assertEqual(result["delta"]["value"], "-3")
        self.assertTrue(result["abIdentityPassed"])
        state = self.post("state")
        serialized = json.dumps(state)
        self.assertNotIn("_branch_results", serialized)
        self.assertNotIn(self.temp.name, serialized)
        self.assertEqual(len(self.planner.calls), 1)

    def test_discover_execution_and_changed_planning_binding_fail_closed(self):
        planning = self.draft()
        error = self.post("branches", expected=409)
        self.assertEqual(error["error"]["code"], "AF_SAMPLE_ONLY")
        selection = deepcopy(self.selection)
        selection["mode"] = "compute"
        error = self.post("ingest", {"requests": [selection],
                                     "expectedPlanningHash": "sha256:" + "0" * 64}, expected=409)
        self.assertEqual(error["error"]["code"], "AF_SPEC_STALE")
        self.assertEqual(self.post("state")["planningHash"], planning["planningHash"])

    def test_exact_approval_handoff_and_receipt_are_separate_http_stages(self):
        self.freeze()
        stale = self.approval_body()
        stale["expectedSpecFingerprint"] = "sha256:" + "0" * 64
        error = self.post("approvals", stale, expected=409)
        self.assertEqual(error["error"]["code"], "AF_SPEC_STALE")
        approved = self.post("approvals", self.approval_body())
        self.assertEqual(approved["stage"], "approved")
        self.assertFalse(approved["approval"]["consumed"])
        handoff = self.post("apply", self.apply_body())
        self.assertEqual(handoff["stage"], "handoff")
        self.assertEqual(handoff["result"]["rows"], [["12"]])
        self.assertTrue(handoff["apply"]["approval"]["consumed"])
        self.assertFalse(handoff["apply"]["workbookSaved"])
        error = self.post("record", expected=409)
        self.assertEqual(error["error"]["code"], "AF_STAGE_INVALID")
        receipt = {**handoff["receiptBinding"], "rowCount": 1, "columnCount": 1, "verified": True}
        # This is a synthetic host receipt, not a real Excel write assertion.
        completed = self.post("apply", {"receipt": receipt, "appliedAt": "2026-10-31T03:00:00.000Z"})
        self.assertEqual(completed["stage"], "applied")
        self.assertEqual(Path(self.temp.name, "Transactions.csv").read_text(encoding="utf-8"),
                         "ID,Amount\nA,10\nB,-3\nC,5\n")

    def test_receipt_mismatch_reports_consumed_partial_unknown_and_blocks_record(self):
        self.freeze()
        self.post("approvals", self.approval_body())
        handoff = self.post("apply", self.apply_body())
        receipt = {**handoff["receiptBinding"], "rowCount": 1, "columnCount": 1, "verified": True}
        incorrect = {**receipt, "resultDigest": "sha256:" + "0" * 64}
        status, _, rejected = self.request("POST", "/api/assistant/apply", {
            "receipt": incorrect, "appliedAt": "2026-10-31T03:00:00.000Z"}, self.auth())
        self.assertIn(status, (409, 500), rejected)
        self.assertEqual(rejected["error"]["code"], "AF_WRITE_PARTIAL")
        self.assertTrue(rejected["error"]["approvalConsumed"])
        self.assertIsNone(rejected["error"]["written"])
        self.assertFalse(rejected["error"]["retryable"])
        self.assertEqual(self.post("state")["stage"], "partial")
        self.post("record", expected=409)

    def test_external_file_change_cannot_be_approved_from_an_old_preview(self):
        self.freeze()
        Path(self.temp.name, "Transactions.csv").write_text("ID,Amount\nA,11\nB,-3\nC,5\n", encoding="utf-8")
        error = self.post("approvals", self.approval_body(), expected=409)
        self.assertIn(error["error"]["code"], ("AF_SOURCE_LOST", "AF_SPEC_STALE"))

    def test_record_http_metadata_hash_and_full_record_hash_have_complete_distinct_bases(self):
        self.complete_synthetic_apply()
        result = self.post("record")
        self.assertEqual(result["stage"], "recorded")
        record, node = result["record"], result["node"]
        self.assertEqual(record["schemaVersion"], "2.0")
        self.assertEqual(result["recordId"], record["id"])
        self.assertEqual(result["recordHash"], record["hash"])
        self.assertEqual(canonical_hash({key: record[key] for key in record["hashBasis"]}), record["hash"])
        self.assertEqual(node["recordHash"], record["hash"])
        self.assertEqual(node["hash"], canonical_hash({key: value for key, value in node.items() if key != "hash"}))
        self.assertNotEqual(node["hash"], record["hash"])
        self.assertEqual(node["spec"], self.frozen["spec"]["fingerprint"])
        self.assertEqual(record["reconciliations"][0]["engine"]["parityChecked"], "none")
        self.assertEqual(record["reconciliations"][0]["specFingerprint"], node["spec"])
        self.assertEqual(record["steps"], self.frozen["spec"]["steps"])
        self.assertFalse(result["workbookSaved"])
        serialized = json.dumps(record)
        self.assertNotIn('"sampleRows"', serialized)
        self.assertNotIn('"raw_tables"', serialized)
        self.assertNotIn(self.temp.name, serialized)
        restored = self.post("state")
        self.assertEqual(restored["stage"], "recorded")
        self.assertEqual(restored["recordHash"], record["hash"])
        self.assertEqual(restored["handoffStatus"], "readback-verified")

    def test_record_source_change_is_ephemeral_staleness_without_rewriting_history(self):
        self.complete_synthetic_apply()
        first = self.post("record")
        Path(self.temp.name, "Transactions.csv").write_text("ID,Amount\nA,11\nB,-3\nC,5\n", encoding="utf-8")
        changed = self.post("record")
        self.assertEqual(changed["record"], first["record"])
        self.assertEqual(changed["node"], first["node"])
        self.assertEqual(changed["recordHash"], first["recordHash"])
        self.assertTrue(changed["staleCheck"]["stale"])
        self.assertEqual(changed["staleCheck"]["reason"], "sourceChanged")


if __name__ == "__main__":
    unittest.main()
