"""V2 exact-revision approval and two-phase values-only handoff guards."""

import base64
from copy import deepcopy
import gc
import io
import json
from pathlib import Path
import tempfile
import unittest
import weakref
from zipfile import ZipFile, ZIP_STORED

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_approval import issue_approval_v2, validate_approval_v2, consume_approval
from pbip_assistant.sources.assistant_freeze import build_frozen_spec, spec_fingerprint_v2
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_session import AssistantSessionStore
from pbip_assistant.sources.assistant_reconcile_v2 import build_preview, reconcile_v2, bind_ab_identity
from tests.support.assistant_flow import AssistantBranchPlanner
from tests.support.paths import FIXTURES


STAMP = "2026-10-31T10:00:00+07:00"
IDENTITY = {"name": "Synthetic.xlsx", "documentHash": canonical_hash("owned-synthetic")}
PACKAGE = base64.b64encode((FIXTURES / "source/orders_synthetic.xlsx").read_bytes()).decode("ascii")


class Planner(AssistantBranchPlanner):
    def __init__(self, missing_control=False):
        super().__init__()
        self.missing_control = missing_control
    def propose(self, payload):
        result = super().propose(payload)
        if self.missing_control:
            result["branches"][0]["controlTotal"] = None
        return result


class AssistantFreezeV2Tests(unittest.TestCase):
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
        self.prepare()

    def prepare(self, missing=False):
        self.store.ingest([deepcopy(self.request)])
        self.store.understand()
        self.store.plan_draft("Sum Amount and compare alternatives", [], True, Planner(missing))
        self.store.run_branches(self.store.state()["planningHash"])

    def freeze(self, ack=False, **overrides):
        branch = self.store.state()["branches"][0]
        options = {"expected_planning_hash": self.store.state()["planningHash"],
            "expected_preview_hash": branch["previewHash"], "expected_result_digest": branch["resultDigest"]}
        options.update(overrides)
        return self.store.freeze("A", STAMP, IDENTITY, ack, **options)

    def expected(self):
        spec = self.store.state()["spec"]
        return {"expected_spec_fingerprint": spec["fingerprint"], "expected_preview_hash": spec["previewHash"], "expected_result_digest": spec["resultDigest"]}

    def approve(self, sources=None, **overrides):
        options = self.expected()
        options.update(overrides)
        return self.store.approve(STAMP, True, IDENTITY, [deepcopy(self.request)] if sources is None else sources, **options)

    def apply(self, package=PACKAGE, sources=None, **overrides):
        options = self.expected()
        options.update(overrides)
        return self.store.apply(package, STAMP, IDENTITY, [deepcopy(self.request)] if sources is None else sources, **options)

    def assert_code(self, code, operation):
        with self.assertRaises(InputError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_freeze_requires_compute_snapshot(self):
        self.store._mode = "discover"
        self.assert_code("AF_SAMPLE_ONLY", self.freeze)

    def test_freeze_requires_chosen_branch_passed(self):
        self.store._branch_results["A"]["reconciliation"].update(hardChecksPassed=False, selectable=False)
        self.assert_code("AF_RECONCILE_FAILED", lambda: self.freeze(ack=True))

    def test_missing_control_requires_explicit_ack_and_keeps_unverified(self):
        self.prepare(missing=True)
        self.assert_code("AF_MISSING_DATA", self.freeze)
        frozen = self.freeze(ack=True)
        self.assertIn("unverified", frozen["spec"]["labels"])
        self.assertFalse(self.store._branch_results["A"]["reconciliation"]["passed"])
        self.approve()
        self.assertEqual(self.store.state()["stage"], "approved")

    def test_spec_binds_plan_hash_and_exact_created_timestamp(self):
        first = self.freeze()["spec"]
        branch = deepcopy(self.store._branch_results["A"])
        branch["plan"]["steps"][0]["variableName"] = "SourceChangedName"
        branch["planHash"] = canonical_hash({"steps": branch["plan"]["steps"], "finalOutputStepId": branch["plan"]["finalOutputStepId"],
            "sourceSchemas": [{"sourceId": source["sourceId"], "schemaHash": source["schemaHash"]} for source in branch["plan"]["sources"]]})
        branch["preview"] = build_preview(self.store._snapshot["snapshotHash"], branch, branch["result"])
        branch["reconciliation"] = bind_ab_identity(reconcile_v2(branch["preview"], branch, self.store._raw_tables, branch["result"]), self.store._delta)
        second = build_frozen_spec(self.store._snapshot, self.store._understand, branch,
            planning_hash=self.store.state()["planningHash"], created_at=STAMP, workbook=IDENTITY)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["fingerprint"], spec_fingerprint_v2(first))

    def test_changed_reconciliation_flags_cannot_bypass_a_hard_blocker(self):
        branch = self.store._branch_results["A"]
        branch["reconciliation"].update(passed=True, hardChecksPassed=True, selectable=True,
            blockers=[{"code": "AF_FANOUT_RISK", "path": "fanOut", "detail": "Synthetic blocker"}])
        self.assert_code("AF_RECONCILE_FAILED", lambda: self.freeze(ack=True))

    def test_rehashed_fabricated_reconciliation_cannot_replace_independent_checks(self):
        branch = self.store._branch_results["A"]
        branch["reconciliation"]["controlTotalSource"] = "999"
        branch["reconciliation"]["reconcileHash"] = canonical_hash({key: branch["reconciliation"][key] for key in branch["reconciliation"]["hashBasis"]})
        self.assert_code("AF_RECONCILE_FAILED", self.freeze)

    def test_spec_never_serializes_source_samples_or_full_catalog(self):
        spec = self.freeze()["spec"]
        serialized = json.dumps(spec)
        for forbidden in ("sampleRows", "planningSamples", "sampleOrdinals", "relativeOrigin", "objectName"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(set(spec["sourceSchemas"][0]), {"sourceId", "schemaHash", "columns"})
        copied = deepcopy(spec)
        copied["sourceSchemas"][0]["sampleRows"] = [["private"]]
        self.assert_code("AF_SPEC_STALE", lambda: spec_fingerprint_v2(copied))

    def test_freeze_rejects_stale_displayed_preview_or_planning_binding(self):
        self.assert_code("AF_SPEC_STALE", lambda: self.freeze(expected_preview_hash=canonical_hash("old")))
        self.assert_code("AF_SPEC_STALE", lambda: self.freeze(expected_planning_hash=canonical_hash("old")))

    def test_approval_rejects_stale_viewed_spec_without_issuing_capability(self):
        self.freeze()
        self.assert_code("AF_SPEC_STALE", lambda: self.approve(expected_spec_fingerprint=canonical_hash("old")))
        self.assertIsNone(self.store._approval)

    def test_store_holds_original_capability_but_display_copy_cannot_grant(self):
        self.freeze()
        public = self.approve()
        reference = weakref.ref(self.store._approval)
        gc.collect()
        self.assertIsNotNone(reference())
        branch = self.store._branch_results["A"]
        self.assert_code("AF_SPEC_STALE", lambda: validate_approval_v2(public["approval"], self.store._frozen_spec, branch["preview"]))
        self.apply()
        self.assertTrue(self.store.state()["approvalConsumed"])

    def test_generic_capability_is_one_use_and_rejects_legacy_serialized_copy(self):
        self.freeze()
        branch = self.store._branch_results["A"]
        capability = issue_approval_v2(self.store._frozen_spec, branch["preview"], approved_at=STAMP)
        consume_approval(capability)
        self.assert_code("AF_SPEC_STALE", lambda: consume_approval(capability))

    def test_fresh_selected_workbook_cells_are_compared_not_client_hashes(self):
        self.freeze()
        changed = deepcopy(self.request)
        changed["payload"]["rows"][2][1] = "900"
        self.assert_code("AF_SPEC_STALE", lambda: self.approve([changed]))
        self.assertIsNone(self.store._approval)

    def test_source_change_after_approval_does_not_consume_capability(self):
        self.freeze(); self.approve()
        changed = deepcopy(self.request)
        changed["payload"]["rows"][2][1] = "900"
        self.assert_code("AF_SPEC_STALE", lambda: self.apply(sources=[changed]))
        self.assertFalse(self.store.state()["approvalConsumed"])

    def test_external_file_is_reread_before_approve(self):
        path = Path(self.temp.name) / "rows.csv"
        path.write_text("ID,Amount\na,12\nb,-3\nc,3\n", encoding="utf-8")
        self.store.ingest([{"kind": "csv", "path": "rows.csv", "mode": "compute", "options": {"delimiter": ","}}])
        self.store.understand()
        self.store.plan_draft("Sum Amount and compare alternatives", [], True, Planner())
        self.store.run_branches(self.store.state()["planningHash"])
        self.freeze()
        path.write_text("ID,Amount\na,12\nb,-3\nc,900\n", encoding="utf-8")
        self.assert_code("AF_SPEC_STALE", lambda: self.approve(sources=[]))

    def test_invalid_package_or_stale_review_does_not_consume(self):
        self.freeze(); self.approve()
        self.assert_code("AF_WRITE_PARTIAL", lambda: self.apply(package="not-base64"))
        self.assert_code("AF_SPEC_STALE", lambda: self.apply(expected_result_digest=canonical_hash("old")))
        self.assertFalse(self.store.state()["approvalConsumed"])

    def test_existing_target_sheet_blocks_before_consuming_approval(self):
        self.freeze(); self.approve()
        sheet_name = self.store.state()["spec"]["target"]["sheet"]
        source = base64.b64decode(PACKAGE)
        output = io.BytesIO()
        with ZipFile(io.BytesIO(source)) as original, ZipFile(output, "w", ZIP_STORED) as modified:
            for entry in original.infolist():
                payload = original.read(entry.filename)
                if entry.filename == "xl/workbook.xml":
                    from xml.etree import ElementTree as ET
                    tree = ET.fromstring(payload)
                    tree.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets")[0].set("name", sheet_name)
                    payload = ET.tostring(tree)
                modified.writestr(entry.filename, payload)
        collision = base64.b64encode(output.getvalue()).decode("ascii")
        self.assert_code("AF_WRITE_PARTIAL", lambda: self.apply(package=collision))
        self.assertFalse(self.store.state()["approvalConsumed"])
        self.assertEqual(self.store.state()["stage"], "approved")

    def test_workbook_identity_change_does_not_consume_approval(self):
        self.freeze(); self.approve()
        changed = {**IDENTITY, "documentHash": canonical_hash("another-workbook")}
        self.assert_code("AF_SPEC_STALE", lambda: self.store.apply(PACKAGE, STAMP, changed, [deepcopy(self.request)], **self.expected()))
        self.assertFalse(self.store.state()["approvalConsumed"])

    def test_handoff_is_not_applied_until_exact_full_readback_receipt(self):
        self.freeze(); self.approve()
        handoff = self.apply()
        self.assertEqual(handoff["stage"], "handoff")
        self.assertEqual(self.store.state()["handoffStatus"], "partial-unknown")
        self.assertEqual(handoff["result"]["rows"], [["12"]])
        completed = self.store.complete_apply({**handoff["receiptBinding"], "verified": True}, STAMP)
        self.assertEqual(completed["stage"], "applied")
        self.assertFalse(completed["apply"]["workbookSaved"])

    def test_consumed_handoff_cannot_reissue_refreeze_or_repeat_apply(self):
        self.freeze(); self.approve(); self.apply()
        self.assert_code("AF_SPEC_STALE", self.freeze)
        self.assert_code("AF_SPEC_STALE", self.approve)
        self.assert_code("AF_WRITE_PARTIAL", self.apply)

    def test_bad_receipt_is_partial_and_cannot_be_retried(self):
        self.freeze(); self.approve()
        handoff = self.apply()
        self.assert_code("AF_WRITE_PARTIAL", lambda: self.store.complete_apply({**handoff["receiptBinding"], "verified": True, "resultDigest": canonical_hash("wrong")}, STAMP))
        self.assertEqual(self.store.state()["stage"], "partial")
        self.assert_code("AF_SPEC_STALE", lambda: self.store.complete_apply({**handoff["receiptBinding"], "verified": True}, STAMP))

    def test_malformed_identity_fields_fail_closed_without_consuming(self):
        self.freeze()
        malformed = deepcopy(self.request)
        malformed["payload"]["name"] = []
        self.assert_code("INVALID_REQUEST", lambda: self.approve(sources=[malformed]))
        self.assertFalse(self.store.state()["approvalConsumed"])


if __name__ == "__main__":
    unittest.main()
