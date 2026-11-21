"""No-backup approval and semantic read-back; synthetic inputs, no live Excel."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.preparation.packages import image_fingerprint
from pbip_assistant.sources.preparation.store import PreparationStore
from pbip_assistant.sources.preparation.wire import validate_request
from tests.integration import test_preparation_api as api_support


class PreparationDirectTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.store = PreparationStore(native_write_enabled=True, backup_enabled=False, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        (Path(self.folder.name) / "data.csv").write_text("Code,Qty\n00123,2\n", encoding="utf-8")
        self.before = {"version": 1, "sheets": [{"sheetId": "native", "name": "Personal", "rowOffset": 0,
            "columnOffset": 0, "values": [["original"]], "formulas": [["original"]], "formulaCells": [], "numberFormats": [["General"]]}]}
        self.claim = {"marker": None, "semanticFingerprint": image_fingerprint(self.before), "targetConfirmed": True,
            "expectedClaimVersion": 0, "workbookName": "Synthetic", "locationHash": None,
            "nativeIdentityHash": canonical_hash(["native"])}
        self.state = self.store.attach("transport", self.claim)
        self.pid = self.state["preparationId"]

    def prepare(self):
        state = self.store.inventory("transport", self.pid, self.folder.name,
            [{"relativePath": "", "fileName": "data.csv"}], expected_claim_version=self.state["claimVersion"])
        mappings = [{k: s[k] for k in ("fileId", "sourceSheetId", "proposedName")} for s in state["inventory"]["sheets"]]
        review = self.store.review_import("transport", self.pid, state["inventory"]["inventoryHash"], mappings, ["Personal"])
        return self.store.approve("transport", self.pid, review["reviewHash"], "import", {"strategy": "import_new", "sheetIds": ["native"]})

    def begin(self):
        grant = self.prepare()
        return self.store.direct_begin("transport", self.pid, grant["grantId"], self.before)

    def after(self):
        image = deepcopy(self.before)
        image["sheets"].append({"sheetId": "new_native", "name": "data", "rowOffset": 0, "columnOffset": 0,
            "values": [["Code", "Qty"], ["00123", 2]], "formulas": [["Code", "Qty"], ["00123", 2]],
            "formulaCells": [], "numberFormats": [["@", "@"], ["@", "General"]]})
        return image

    def ready(self, a, fingerprint=None, permit=None):
        return self.store.direct_write_ready("transport", self.pid, a["attemptId"], permit or a["writePermit"],
            fingerprint or image_fingerprint(self.before))

    def complete(self, a, image=None, **receipt):
        image = self.after() if image is None else image
        return self.store.direct_complete("transport", self.pid, a["attemptId"], {"phase": "verified", "imageId": None,
            "observedFingerprint": image_fingerprint(image), "actualSheetIds": ["new_native"], **receipt}, image)

    def test_identical_xlsx_rereview_rejects_delayed_approval(self):
        from tests.support.preparation_images import native_package
        frame = {"name": "Data", "rowOffset": 0, "columnOffset": 0, "values": [[2]], "formulas": [[2]],
                 "formulaCells": [], "numberFormats": [["General"]]}
        payload = native_package({"sheets": [frame]})
        (Path(self.folder.name) / "data.xlsx").write_bytes(payload)
        state = self.store.inventory("transport", self.pid, self.folder.name,
            [{"relativePath": "", "fileName": "data.xlsx"}], expected_claim_version=self.state["claimVersion"])
        inventory = state["inventory"]
        first_sheet = inventory["sheets"][0]
        mapping = {"fileId": first_sheet["fileId"], "sourceSheetId": first_sheet["sourceSheetId"], "proposedName": "Data"}

        class Runner:
            def apply(self, request):
                Path(request["outputPath"]).write_bytes(payload)
                return {"sheets": [frame], "namespaceId": request["namespaceId"]}

        target = {"strategy": "import_new", "sheetIds": ["native"]}
        with patch("pbip_assistant.sources.preparation.xlsx_preservation.PowerShellExcelRunner", return_value=Runner()):
            transfers = []
            for _ in range(2):
                review = self.store.review_import("transport", self.pid, inventory["inventoryHash"], [mapping], ["Personal"])
                for read in range(2):
                    transfer = self.store.packages("transport", self.pid, review["reviewHash"], reuse_reviewed=False)
                    if read == 0:
                        transfers.append(transfer)
                    else:
                        self.assertEqual(transfer, transfers[-1])
            first, second = transfers
            self.assertNotEqual(first["packages"][0]["namespace"], second["packages"][0]["namespace"])
            with self.assertRaises(InputError) as caught:
                self.store.approve("transport", self.pid, first["reviewHash"], "import", target)
            self.assertEqual(caught.exception.code, "DP_REVIEW_STALE")
            with self.assertRaises(InputError) as caught:
                self.store.packages("transport", self.pid, first["reviewHash"], reuse_reviewed=False)
            self.assertEqual(caught.exception.code, "DP_REVIEW_STALE")
            grant = self.store.approve("transport", self.pid, second["reviewHash"], "import", target)
            attempt = self.store.direct_begin("transport", self.pid, grant["grantId"], self.before)
            self.assertEqual(attempt["packages"], second["packages"])

    def test_import_success_retains_identity_but_no_recoverable_images_or_packages(self):
        self.assertTrue(self.state["writeEnabled"])
        self.assertIs(self.state["backupEnabled"], False)
        a = self.begin()
        self.assertEqual(a["beforeSheetIds"], ["native"])
        self.assertEqual(a["expectedFingerprint"], image_fingerprint(self.after()))
        self.ready(a)
        state = self.complete(a)
        self.assertEqual(state["status"], "verified")
        self.assertEqual(state["importedSheetIds"], ["new_native"])
        self.assertEqual(state["claimFingerprint"], image_fingerprint(self.after()))
        self.assertIsNone(state["journal"])
        self.assertIsNone(self.store._journal)
        self.assertEqual(self.store._points, {})
        retained = self.store._documents[self.pid]
        self.assertIsNone(retained["attempt"])
        self.assertIsNone(retained.get("packageCache"))
        self.assertNotIn("original", str(retained))
        with self.assertRaises(InputError): self.complete(a)

    def test_changed_target_and_invalid_permit_cannot_authorize_write(self):
        a = self.begin()
        for fields in ({"fingerprint": "sha256:" + "0" * 64}, {"permit": "wrong"}):
            with self.assertRaises(InputError): self.ready(a, **fields)
        self.ready(a)
        with self.assertRaises(InputError): self.ready(a)

    def test_before_native_identity_and_semantic_head_are_both_checked(self):
        grant = self.prepare()
        for field, value in (("sheetId", "replaced"), ("values", [["changed"]])):
            before = deepcopy(self.before)
            before["sheets"][0][field] = value
            with self.assertRaises(InputError): self.store.direct_begin("transport", self.pid, grant["grantId"], before)
        self.assertIsNone(self.store._journal)

    def test_failed_or_mismatched_readback_stops_replay_without_snapshot(self):
        for failure in ("wrong_value", "wrong_identity", "wrong_created_ids", "partial_unknown"):
            with self.subTest(failure=failure):
                self.setUp()
                a = self.begin()
                self.ready(a)
                after = self.after()
                receipt = {}
                if failure == "wrong_value": after["sheets"][1]["values"][1][1] = "bad"
                if failure == "wrong_identity": after["sheets"][0]["sheetId"] = "replaced"
                if failure == "wrong_created_ids": receipt["actualSheetIds"] = []
                if failure == "partial_unknown":
                    state = self.store.direct_complete("transport", self.pid, a["attemptId"], {"phase": "partial_unknown", "imageId": None}, None)
                else: state = self.complete(a, after, **receipt)
                self.assertEqual(state["status"], "partial_unknown")
                self.assertFalse(state["writeEnabled"])
                self.assertIsNone(self.store._journal)
                self.assertNotIn("original", str(self.store._documents[self.pid]))
                with self.assertRaises(InputError): self.ready(a)
                with self.assertRaises(InputError): self.store.approve("transport", self.pid, a["expectedFingerprint"], "import", {"strategy": "import_new", "sheetIds": ["native"]})

    def test_lost_completion_blocks_reapproval_and_prewrite_failure_can_be_reviewed_again(self):
        a = self.begin()
        state = self.store.direct_complete("transport", self.pid, a["attemptId"], {"phase": "prewrite_failed", "imageId": None}, None)
        self.assertEqual(state["status"], "needs_review")
        a = self.begin()
        self.ready(a)
        with self.assertRaises(InputError): self.begin()
        self.now = 1801
        state = self.store.direct_complete("transport", self.pid, a["attemptId"], {"phase": "partial_unknown", "imageId": None}, None)
        self.assertEqual(state["status"], "expired")
        self.assertIsNone(self.store._journal)

    def test_explicit_fresh_attach_retires_lost_begin_and_fences_delayed_ready(self):
        a = self.begin()  # The native client never receives this reply.
        old_pid = self.pid
        fresh = self.store.attach("transport", self.claim)
        self.assertNotEqual(fresh["preparationId"], old_pid)
        self.assertEqual(fresh["status"], "needs_source_read")
        self.assertIsNone(fresh["journal"])
        with self.assertRaises(InputError): self.ready(a)
        with self.assertRaises(InputError): self.store.state("transport", old_pid)
        self.pid = fresh["preparationId"]
        with self.assertRaises(InputError):
            self.store.direct_begin("transport", self.pid, "old_or_missing_approval", self.before)
        newly_reviewed = self.begin()
        self.assertNotEqual(newly_reviewed["attemptId"], a["attemptId"])
        self.ready(newly_reviewed)

    def test_partial_unknown_before_consumption_abandons_permit_and_allows_explicit_recovery(self):
        a = self.begin()
        # write-ready was lost before reaching the server; its receipt is uncertain.
        state = self.store.direct_complete("transport", self.pid, a["attemptId"], {"phase": "partial_unknown", "imageId": None}, None)
        self.assertEqual(state["status"], "partial_unknown")
        self.assertFalse(state["writeEnabled"])
        retained = self.store._documents[self.pid]["attempt"]
        for key in ("writePermit", "packages", "changes", "target", "targetCopies"):
            self.assertNotIn(key, retained)
        with self.assertRaises(InputError): self.ready(a)
        fresh = self.store.attach("transport", self.claim)
        self.assertNotEqual(fresh["preparationId"], self.pid)
        self.assertEqual(fresh["status"], "needs_source_read")

    def test_explicit_fresh_attach_retires_unreported_write_and_fences_delayed_messages(self):
        a = self.begin()
        self.ready(a)
        for index in range(7):
            self.store.attach("other_" + str(index), self.claim)
        # The permit reply and subsequent unknown receipt are both lost. A new
        # user-confirmed capture observes the workbook's current imported state.
        after = self.after()
        fresh = self.store.attach("transport", {**self.claim, "semanticFingerprint": image_fingerprint(after),
            "nativeIdentityHash": canonical_hash(["native", "new_native"])})
        self.assertNotEqual(fresh["preparationId"], self.pid)
        with self.assertRaises(InputError): self.ready(a)
        with self.assertRaises(InputError): self.complete(a, after)
        current = self.store.state("transport", fresh["preparationId"])
        self.assertEqual(current["claimFingerprint"], image_fingerprint(after))
        self.assertEqual(current["importedSheetIds"], [])
        self.assertEqual(current["status"], "needs_source_read")

    def test_background_or_identityless_attach_cannot_abandon_an_unreported_write(self):
        a = self.begin()
        self.ready(a)
        state = self.store.state("transport", self.pid)
        same_marker = {**self.claim, "marker": state["marker"], "expectedClaimVersion": state["claimVersion"]}
        with self.assertRaises(InputError): self.store.attach("transport", same_marker)
        with self.assertRaises(InputError): self.store.attach("transport", {**self.claim, "nativeIdentityHash": None})
        result = self.store.attach("transport", {**self.claim, "targetConfirmed": False})
        self.assertEqual(result["status"], "needs_target_confirmation")
        self.assertEqual(self.store.state("transport", self.pid)["status"], "writing")

    def test_source_file_changes_and_cross_transport_are_rejected(self):
        a = self.begin()
        with self.assertRaises(InputError): self.store.direct_write_ready("other", self.pid, a["attemptId"], a["writePermit"], a["beforeFingerprint"])
        (Path(self.folder.name) / "data.csv").write_text("Code,Qty\n00123,3\n", encoding="utf-8")
        with self.assertRaises(InputError): self.ready(a)

    def cleanup_grant(self, formula=None):
        sheet = self.before["sheets"][0]
        sheet.update(rowOffset=3, columnOffset=2, values=[["Code"], [" 00123 "]],
            formulas=[["Code"], [" 00123 "]], numberFormats=[["@"], ["@"]])
        if formula:
            sheet["values"].append([42])
            sheet["formulas"].append([formula])
            sheet["numberFormats"].append(["General"])
            sheet["formulaCells"] = [[2, 0]]
        state = self.store.attach("transport", {**self.claim, "semanticFingerprint": image_fingerprint(self.before)})
        self.pid = state["preparationId"]
        state = self.store.put_source_snapshot("transport", self.pid, {"sourceId": "source", "sheetId": "native",
            "headers": ["Code"], "rows": [[" 00123 "]], "formulaCells": [], "columnKinds": ["identifier"],
            "numberFormats": [["@"]], "dateSystem": "1900", "rowOffset": 4, "columnOffset": 2})
        state = self.store.scan("transport", self.pid, state["sourceRevision"], state["sourceHash"])
        for question in state["questions"]:
            state = self.store.answer_question("transport", self.pid, question["questionId"], {"choice": "keep_text", "reason": None}, state["answerRevision"])
        state = self.store.preview("transport", self.pid, state["sourceHash"], state["answerRevision"])
        return self.store.approve("transport", self.pid, state["preview"]["reviewHash"], "cleanup", {"strategy": "personal_copy", "sheetIds": ["native"]})

    def test_cleanup_personal_copy_preserves_source_and_checks_semantic_result(self):
        grant = self.cleanup_grant()
        a = self.store.direct_begin("transport", self.pid, grant["grantId"], self.before)
        self.assertEqual(a["targetCopies"], [{"sourceSheetId": "native", "targetName": "Personal_Result"}])
        self.assertEqual((a["changes"][0]["row"], a["changes"][0]["column"]), (4, 2))
        after = deepcopy(self.before)
        copied = deepcopy(after["sheets"][0])
        copied.update(sheetId="result", name="Personal_Result")
        copied["values"][1][0] = copied["formulas"][1][0] = "00123"
        after["sheets"].append(copied)
        self.assertEqual(a["expectedFingerprint"], image_fingerprint(after))
        self.ready(a)
        state = self.complete(a, after, actualSheetIds=["result"])
        self.assertEqual(state["status"], "verified")
        self.assertEqual(after["sheets"][0]["values"][1][0], " 00123 ")
        self.assertEqual(state["importedSheetIds"], [])
        self.assertIsNone(self.store._journal)

    def test_cleanup_rejects_copy_formulas_requiring_native_retargeting(self):
        for formula in ("='Personal'!C5", "=Personal!C5", "=SUM(Table1[Code])"):
            with self.subTest(formula=formula):
                self.setUp()
                grant = self.cleanup_grant(formula)
                with self.assertRaises(InputError) as caught:
                    self.store.direct_begin("transport", self.pid, grant["grantId"], self.before)
                self.assertEqual(caught.exception.code, "DP_UNSUPPORTED_PRESERVATION")
                self.assertIsNone(self.store._documents[self.pid].get("attempt"))

    def test_failed_operation_requires_explicit_new_attachment_and_fresh_review(self):
        a = self.begin()
        self.ready(a)
        self.store.direct_complete("transport", self.pid, a["attemptId"], {"phase": "partial_unknown", "imageId": None}, None)
        fresh = self.store.attach("transport", self.claim)
        self.assertNotEqual(fresh["preparationId"], self.pid)
        self.assertEqual(fresh["status"], "needs_source_read")
        self.assertTrue(fresh["writeEnabled"])
        with self.assertRaises(InputError): self.ready(a)

    def test_direct_schema_closes_images_receipt_and_request(self):
        bodies = [
            {"action": "direct-begin", "grantId": "grant", "beforeImage": self.before},
            {"action": "direct-write-ready", "attemptId": "attempt", "writePermit": "permit", "currentFingerprint": self.claim["semanticFingerprint"]},
            {"action": "direct-complete", "attemptId": "attempt", "receipt": {"phase": "partial_unknown", "imageId": None,
                "actualSheetIds": [], "observedFingerprint": None, "rows": 0, "columns": 0}, "afterImage": None},
        ]
        for fields in bodies:
            body = {"schemaVersion": 1, "preparationId": self.pid, **fields}
            self.assertEqual(validate_request(body), body)
            with self.assertRaises(InputError): validate_request({**body, "backup": True})
        body = {"schemaVersion": 1, "preparationId": self.pid, **bodies[0]}
        body["beforeImage"] = {**self.before, "preservation": {"evidenceId": "forbidden"}}
        with self.assertRaises(InputError): validate_request(body)


class PreparationDirectApiTests(unittest.TestCase):
    setUp = api_support.PreparationApiTests.setUp
    stop = api_support.PreparationApiTests.stop
    call = api_support.PreparationApiTests.call
    post = api_support.PreparationApiTests.post

    def test_authenticated_closed_direct_import_and_legacy_rejection(self):
        before = {"version": 1, "sheets": [{"sheetId": "native", "name": "Personal", "rowOffset": 0,
            "columnOffset": 0, "values": [["original"]], "formulas": [["original"]], "formulaCells": [], "numberFormats": [["General"]]}]}
        _, boot = self.call("GET", "/api/bootstrap")
        self.assertIs(boot["capabilities"]["preparationBackups"], False)
        self.assertIsNone(self.server.app.preparation_evidence)
        status, state = self.post("attach", claim={"marker": None, "semanticFingerprint": image_fingerprint(before),
            "targetConfirmed": True, "expectedClaimVersion": 0, "workbookName": "Synthetic", "locationHash": None,
            "nativeIdentityHash": canonical_hash(["native"])})
        self.assertEqual(status, 200)
        pid = state["preparationId"]
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "data.csv").write_text("Code,Qty,Date\n00123,2,1904-01-01\n", encoding="utf-8")
            status, state = self.post("inventory", preparationId=pid, root=directory,
                items=[{"relativePath": "", "fileName": "data.csv"}], expectedClaimVersion=state["claimVersion"])
            self.assertEqual(status, 200)
            mappings = [{k: s[k] for k in ("fileId", "sourceSheetId", "proposedName")} for s in state["inventory"]["sheets"]]
            status, review = self.post("review-import", preparationId=pid, inventoryHash=state["inventory"]["inventoryHash"], mappings=mappings, existingNames=["Personal"])
            self.assertEqual(status, 200)
            status, packages = self.post("packages", preparationId=pid, reviewHash=review["reviewHash"], dateSystem="1904")
            self.assertEqual(status, 200)
            self.assertEqual(packages["packages"][0]["sheets"][0]["values"][1], ["00123", 2, 0])
            request = {"preparationId": pid, "reviewHash": review["reviewHash"]}
            target = {"strategy": "import_new", "sheetIds": ["native"]}
            old_hash = packages["reviewHash"]
            status, switched = self.post("packages", **request, dateSystem="1900")
            self.assertEqual(status, 200)
            self.assertEqual(switched["packages"][0]["sheets"][0]["values"][1], ["00123", 2, 1462])
            # A delayed approval from the first panel must fail even before any grant exists.
            status, rejected = self.post("approve", preparationId=pid, reviewHash=old_hash, kind="import", target=target)
            self.assertEqual(rejected["error"]["code"], "DP_REVIEW_STALE")
            status, old_grant = self.post("approve", preparationId=pid, reviewHash=switched["reviewHash"], kind="import", target=target)
            self.assertEqual(status, 200)
            status, current = self.post("packages", **request, dateSystem="1904")
            self.assertEqual(status, 200)
            status, rejected = self.post("direct-begin", preparationId=pid, grantId=old_grant["grantId"], beforeImage=before)
            self.assertEqual(rejected["error"]["code"], "DP_REVIEW_STALE")
            status, grant = self.post("approve", preparationId=pid, reviewHash=current["reviewHash"], kind="import", target=target)
            self.assertEqual(status, 200)
            begin = {"schemaVersion": 1, "action": "direct-begin", "preparationId": pid, "grantId": grant["grantId"], "beforeImage": before}
            self.assertEqual(self.call("POST", "/api/preparation/direct-begin", begin)[0], 403)
            self.assertEqual(self.call("POST", "/api/preparation/direct-begin", {**begin, "backup": True}, self.token)[0], 400)
            status, attempt = self.call("POST", "/api/preparation/direct-begin", begin, self.token)
            self.assertEqual(status, 200)
            status, _ = self.post("direct-write-ready", preparationId=pid, attemptId=attempt["attemptId"], writePermit=attempt["writePermit"], currentFingerprint=image_fingerprint(before))
            self.assertEqual(status, 200)
            after = deepcopy(before)
            after["sheets"].append({"sheetId": "new_native", "name": "data", "rowOffset": 0, "columnOffset": 0,
                "values": [["Code", "Qty", "Date"], ["00123", 2, 0]], "formulas": [["Code", "Qty", "Date"], ["00123", 2, 0]],
                "formulaCells": [], "numberFormats": [["@", "@", "@"], ["@", "General", "yyyy-mm-dd"]]})
            receipt = {"phase": "verified", "imageId": None, "observedFingerprint": image_fingerprint(after), "actualSheetIds": ["new_native"], "rows": 2, "columns": 3}
            status, state = self.post("direct-complete", preparationId=pid, attemptId=attempt["attemptId"], receipt=receipt, afterImage=after)
            self.assertEqual(status, 200)
            self.assertEqual(state["status"], "verified")
            self.assertEqual(state["importedSheetIds"], ["new_native"])
            self.assertIsNone(state["journal"])
        h = "sha256:" + "1" * 64
        legacy = {
            "begin": {"grantId": "gone", "expectedFingerprint": h, "expectedPreservationFingerprint": h},
            "image-begin": {"attemptId": "gone", "purpose": "before", "byteLength": 1, "imageHash": h},
            "image-chunk": {"attemptId": "gone", "uploadId": "gone", "index": 0, "offset": 0, "chunkHash": h, "dataBase64": "eA=="},
            "image-finish": {"attemptId": "gone", "uploadId": "gone"},
            "write-ready": {"attemptId": "gone", "beforeImageId": "gone", "expectedFingerprint": h, "expectedPreservationFingerprint": h},
            "complete": {"attemptId": "gone", "receipt": receipt},
            "undo": {"pointId": "gone", "expectedCursor": 0, "expectedFingerprint": h, "expectedPreservationFingerprint": h},
            "redo": {"pointId": "gone", "expectedCursor": 0, "expectedFingerprint": h, "expectedPreservationFingerprint": h},
            "restore-complete": {"attemptId": "gone", "receipt": receipt},
        }
        for action, fields in legacy.items():
            with self.subTest(action=action):
                status, result = self.post(action, preparationId=pid, **fields)
                self.assertEqual(status, 409)
                self.assertEqual(result["error"]["code"], "DP_UNSUPPORTED_PRESERVATION")
        self.assertIsNone(self.server.app.preparation._journal)
