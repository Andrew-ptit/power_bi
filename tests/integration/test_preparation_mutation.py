"""Real service/journal transfer tests, independent from native Excel qualification."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import tempfile
import unittest
from pbip_assistant.errors import InputError
from pbip_assistant.sources.preparation.store import PreparationStore
from pbip_assistant.sources.preparation.packages import image_fingerprint
from pbip_assistant.sources.preparation.evidence import PreservationEvidenceStore
from pbip_assistant.sources.assistant_ingest import canonical_hash
from tests.support.preparation_images import capture_image, native_package


def digest(data): return "sha256:" + hashlib.sha256(data).hexdigest()


class PreparationMutationTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.store = PreparationStore(native_write_enabled=True, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.store._evidence = PreservationEvidenceStore(clock=lambda: self.now)
        self.addCleanup(self.store._evidence.close)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        (Path(self.folder.name) / "data.csv").write_text("Code,Qty\n00123,2\n", encoding="utf-8")
        self.image = {"version": 1, "sheets": [{"sheetId": "native", "name": "Personal", "rowOffset": 0,
            "columnOffset": 0, "values": [["original"]], "formulas": [["original"]], "formulaCells": [], "numberFormats": [["General"]]}]}
        self.image = capture_image(self.store._evidence, "transport", self.image)
        state = self.store.attach("transport", {"marker": None, "semanticFingerprint": self.image["fingerprint"],
            "targetConfirmed": True, "expectedClaimVersion": 0, "workbookName": "Synthetic", "locationHash": None,
            "nativeIdentityHash": canonical_hash(sorted(s["sheetId"] for s in self.image["sheets"])), "preservationFingerprint": self.image["fullFingerprint"]})
        self.pid = state["preparationId"]

    def prepare(self):
        state = self.store.inventory("transport", self.pid, self.folder.name, ".")
        mappings = [{k: s[k] for k in ("fileId", "sourceSheetId", "proposedName")} for s in state["inventory"]["sheets"]]
        review = self.store.review_import("transport", self.pid, state["inventory"]["inventoryHash"], mappings, ["Personal"])
        grant = self.store.approve("transport", self.pid, review["reviewHash"], "import", {"strategy": "import_new", "sheetIds": ["native"]})
        attempt = self.store.begin_mutation("transport", self.pid, grant["grantId"], self.image["fingerprint"], self.image["fullFingerprint"])
        return attempt

    def upload(self, attempt, purpose, image, package_bytes=None):
        image = capture_image(self.store._evidence, "transport", image, package_bytes)
        data = json.dumps(image, ensure_ascii=False, separators=(",", ":")).encode()
        upload = self.store.image_begin("transport", self.pid, attempt["attemptId"], purpose, len(data), digest(data))
        args = ("transport", self.pid, attempt["attemptId"], upload["uploadId"], 0, 0, digest(data), base64.b64encode(data).decode())
        self.store.image_chunk(*args)
        self.store.image_chunk(*args)  # identical retry must not duplicate bytes
        return self.store.image_finish("transport", self.pid, attempt["attemptId"], upload["uploadId"])

    def imported_image(self):
        after = deepcopy(self.image)
        after.pop("fingerprint")
        after["sheets"].append({"sheetId": "new_native", "name": "data", "rowOffset": 0, "columnOffset": 0,
            "values": [["Code", "Qty"], ["00123", "2"]], "formulas": [["Code", "Qty"], ["00123", "2"]],
            "formulaCells": [], "numberFormats": [["@", "@"], ["@", "@"]]})
        after["fingerprint"] = image_fingerprint(after)
        return after

    def test_legacy_true_flag_without_native_claim_still_cannot_approve(self):
        legacy = self.store.attach("legacy", {"marker":None,"semanticFingerprint":self.image["fingerprint"],
            "targetConfirmed":True,"expectedClaimVersion":0,"workbookName":"Synthetic","locationHash":None})
        with self.assertRaises(InputError) as caught:
            self.store.approve("legacy",legacy["preparationId"],self.image["fingerprint"],"import",{"strategy":"import_new","sheetIds":["native"]})
        self.assertEqual(caught.exception.code,"DP_BINDING_REQUIRED")

    def test_approved_import_requires_verified_before_and_actual_after(self):
        attempt = self.prepare()
        with self.assertRaises(InputError):
            self.store.write_ready("transport", self.pid, attempt["attemptId"], "unknown", self.image["fingerprint"], self.image["fullFingerprint"])
        before = self.upload(attempt, "before", self.image)
        permit = self.store.write_ready("transport", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], self.image["fullFingerprint"])
        self.assertTrue(permit["writePermit"])
        with self.assertRaises(InputError):
            self.store.write_ready("transport", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], self.image["fullFingerprint"])
        after = self.imported_image()
        self.assertEqual(after["fingerprint"], before["expectedFingerprint"])
        saved = self.upload(attempt, "after", after)
        state = self.store.complete_mutation("transport", self.pid, attempt["attemptId"], {"phase": "verified",
            "observedFingerprint": after["fingerprint"], "imageId": saved["imageId"], "actualSheetIds": ["new_native"], "rows": 2, "columns": 2})
        self.assertEqual(state["journal"]["undoCount"], 1)
        self.assertEqual(state["importedSheetIds"], ["new_native"])
        point = state["journal"]["points"][0]["pointId"]
        for direction, expected, created in (("undo", self.image, []), ("redo", after, ["redo_native"]), ("undo", self.image, [])):
            recovery = self.store.checkout_recovery("transport", self.pid, point, direction, state["journal"]["cursor"],
                state["claimFingerprint"], state["preservationFingerprint"])
            self.store.write_ready("transport", self.pid, recovery["attemptId"], recovery["imageId"],
                state["claimFingerprint"], state["preservationFingerprint"])
            result = deepcopy(expected)
            if direction == "redo": result["sheets"][1]["sheetId"] = "redo_native"
            saved = self.upload(recovery, "restore-readback", result)
            state = self.store.complete_recovery("transport", self.pid, recovery["attemptId"], {"phase": "verified",
                "observedFingerprint": result["fingerprint"], "imageId": saved["imageId"], "actualSheetIds": created, "rows": 2, "columns": 2})
            self.assertEqual(state["journal"]["status"], "ready")
            self.assertEqual(state["journal"]["undoCount"], 1 if direction == "redo" else 0)
            self.assertEqual(state["importedSheetIds"], created)

    def test_native_style_change_after_write_is_unknown_and_does_not_commit(self):
        attempt = self.prepare()
        before = self.upload(attempt, "before", self.image)
        self.store.write_ready("transport", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], self.image["fullFingerprint"])
        after = self.imported_image()
        output = BytesIO()
        with ZipFile(BytesIO(native_package(after))) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
            for name in source.namelist():
                data = source.read(name)
                if name == "xl/styles.xml": data = data.replace(b"Calibri", b"Arial")
                target.writestr(name, data)
        saved = self.upload(attempt, "after", after, output.getvalue())
        state = self.store.complete_mutation("transport", self.pid, attempt["attemptId"], {"phase":"verified",
            "observedFingerprint":after["fingerprint"],"imageId":saved["imageId"],"actualSheetIds":["new_native"]})
        self.assertEqual(state["status"], "partial_unknown")
        self.assertEqual(state["journal"]["undoCount"], 0)
        self.assertFalse(state["writeEnabled"])

    def test_native_identity_and_preservation_cas_block_before_write(self):
        attempt = self.prepare()
        wrong = deepcopy(self.image); wrong["sheets"][0]["sheetId"] = "replacement"
        with self.assertRaises(InputError) as caught: self.upload(attempt, "before", wrong)
        self.assertEqual(caught.exception.code, "DP_SOURCE_STALE")
        # Failed evidence never allocated an executable journal backup.
        self.assertIsNone(self.store._documents[self.pid]["attempt"]["reservation"])
        self.store.complete_mutation("transport", self.pid, attempt["attemptId"], {"phase":"prewrite_failed"})
        attempt = self.prepare()
        before = self.upload(attempt, "before", self.image)
        with self.assertRaises(InputError) as caught:
            self.store.write_ready("transport", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], "sha256:" + "f" * 64)
        self.assertEqual(caught.exception.code, "DP_RESTORE_CONFLICT")
        self.assertEqual(self.store._documents[self.pid]["attempt"]["phase"], "prepared")

    def test_transport_and_grant_are_bound_and_source_rechecked(self):
        attempt = self.prepare()
        with self.assertRaises(InputError):
            self.store.image_begin("other", self.pid, attempt["attemptId"], "before", 2, digest(b"{}"))
        before = self.upload(attempt, "before", self.image)
        (Path(self.folder.name) / "data.csv").write_text("Code,Qty\n00123,3\n", encoding="utf-8")
        with self.assertRaises(InputError) as caught:
            self.store.write_ready("transport", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], self.image["fullFingerprint"])
        self.assertEqual(caught.exception.code, "DP_SOURCE_STALE")

    def test_idle_expiry_pins_only_active_native_completion_then_retires_state(self):
        attempt = self.prepare()
        before = self.upload(attempt, "before", self.image)
        self.store.write_ready("transport", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], self.image["fullFingerprint"])
        self.now = 1801
        # A worker may report unknown after the clock expires, but cannot gain
        # another write or leave retained source data beyond the original TTL.
        try:
            state = self.store.complete_mutation("transport", self.pid, attempt["attemptId"], {"phase": "partial_unknown"})
        except InputError as exc:
            self.fail("Active native completion was discarded by expiry: " + exc.code)
        self.assertEqual(state["status"], "expired")
        with self.assertRaises(InputError): self.store.state("transport", self.pid)

    def test_production_owner_gate_cannot_be_enabled_by_wire_approval(self):
        disabled = PreparationStore()
        self.addCleanup(disabled.close)
        claim = {"marker": None, "semanticFingerprint": self.image["fingerprint"], "targetConfirmed": True,
                 "expectedClaimVersion": 0, "workbookName": "Synthetic", "locationHash": None}
        state = disabled.attach("production", claim)
        self.assertFalse(state["writeEnabled"])
        with self.assertRaises(InputError) as caught:
            disabled.approve("production", state["preparationId"], self.image["fingerprint"], "import", {"strategy": "import_new", "sheetIds": ["native"]})
        self.assertEqual(caught.exception.code, "DP_UNSUPPORTED_PRESERVATION")

    def test_cleanup_personal_copy_and_native_id_conflict_on_recovery(self):
        # Start directly with personal data, preserving a non-A1 frame.
        self.image["sheets"][0].update(rowOffset=3, columnOffset=2, values=[["Code"], [" 00123 "]],
            formulas=[["Code"], [" 00123 "]], numberFormats=[["@"], ["@"]])
        self.image.pop("fingerprint")
        self.image["fingerprint"] = image_fingerprint(self.image)
        self.image = capture_image(self.store._evidence, "cleanup", self.image)
        # New attachment is explicitly bound to this current workbook.
        state = self.store.attach("cleanup", {"marker": None, "semanticFingerprint": self.image["fingerprint"],
            "targetConfirmed": True, "expectedClaimVersion": 0, "workbookName": "Synthetic", "locationHash": None,
            "nativeIdentityHash": canonical_hash(["native"]), "preservationFingerprint": self.image["fullFingerprint"]})
        self.pid = state["preparationId"]
        state = self.store.put_source_snapshot("cleanup", self.pid, {"sourceId": "source", "sheetId": "native", "headers": ["Code"],
            "rows": [[" 00123 "]], "formulaCells": [], "columnKinds": ["identifier"], "numberFormats": [["@"]],
            "dateSystem": "1900", "rowOffset": 4, "columnOffset": 2})
        state = self.store.scan("cleanup", self.pid, state["sourceRevision"], state["sourceHash"])
        for question in state["questions"]:
            state = self.store.answer_question("cleanup", self.pid, question["questionId"], {"choice": "keep_text", "reason": None}, state["answerRevision"])
        state = self.store.preview("cleanup", self.pid, state["sourceHash"], state["answerRevision"])
        grant = self.store.approve("cleanup", self.pid, state["preview"]["reviewHash"], "cleanup", {"strategy": "personal_copy", "sheetIds": ["native"]})
        attempt = self.store.begin_mutation("cleanup", self.pid, grant["grantId"], self.image["fingerprint"], self.image["fullFingerprint"])
        self.assertEqual((attempt["changes"][0]["row"], attempt["changes"][0]["column"]), (4, 2))
        self.assertEqual(attempt["changes"][0]["beforeNumberFormat"], "@")
        def transfer(purpose, image, current=attempt):
            image = capture_image(self.store._evidence, "cleanup", image)
            data = json.dumps(image, separators=(",", ":")).encode()
            upload = self.store.image_begin("cleanup", self.pid, current["attemptId"], purpose, len(data), digest(data))
            self.store.image_chunk("cleanup", self.pid, current["attemptId"], upload["uploadId"], 0, 0, digest(data), base64.b64encode(data).decode())
            return self.store.image_finish("cleanup", self.pid, current["attemptId"], upload["uploadId"])
        before = transfer("before", self.image)
        self.assertEqual(before["targetCopies"], [{"sourceSheetId": "native", "targetName": "Personal_Result"}])
        self.store.write_ready("cleanup", self.pid, attempt["attemptId"], before["imageId"], self.image["fingerprint"], self.image["fullFingerprint"])
        after = deepcopy(self.image); after.pop("fingerprint")
        copy = deepcopy(after["sheets"][0]); copy.update(sheetId="result", name="Personal_Result")
        copy["values"][1][0] = copy["formulas"][1][0] = "00123"
        after["sheets"].append(copy); after["fingerprint"] = image_fingerprint(after)
        saved = transfer("after", after)
        receipt = {"phase": "verified", "observedFingerprint": after["fingerprint"], "imageId": saved["imageId"], "actualSheetIds": ["result"], "rows": 2, "columns": 1}
        state = self.store.complete_mutation("cleanup", self.pid, attempt["attemptId"], receipt)
        self.assertEqual(state["journal"]["undoCount"], 1)
        recovery = self.store.checkout_recovery("cleanup", self.pid, state["journal"]["points"][0]["pointId"], "undo", state["journal"]["cursor"], after["fingerprint"], state["preservationFingerprint"])
        self.assertEqual(recovery["operation"], "undo")
        self.store.write_ready("cleanup", self.pid, recovery["attemptId"], recovery["imageId"], after["fingerprint"], state["preservationFingerprint"])
        wrong = deepcopy(self.image); wrong["sheets"][0]["sheetId"] = "replacement"
        self.assertEqual(image_fingerprint(wrong), self.image["fingerprint"])
        saved = transfer("restore-readback", wrong, recovery)
        receipt.update(observedFingerprint=wrong["fingerprint"], imageId=saved["imageId"], actualSheetIds=[])
        state = self.store.complete_recovery("cleanup", self.pid, recovery["attemptId"], receipt)
        self.assertEqual(state["journal"]["status"], "partial_unknown")
        self.assertEqual(state["journal"]["undoCount"], 1)
