"""Closed preparation requests cannot broaden legacy source-write authority."""
from copy import deepcopy
import json
import unittest

from pbip_assistant.core.resources import schema_path
from tests.support.json_schema_oracle import validate


class PreparationContractTests(unittest.TestCase):
    def schema(self):
        path = schema_path("preparation.schema.json")
        self.assertTrue(path.is_file(), "Preparation has no closed request contract yet")
        return json.loads(path.read_text(encoding="utf-8"))

    def request(self):
        return {
            "schemaVersion": 1, "action": "answer", "preparationId": "prep_01",
            "questionId": "date_format", "expectedAnswerRevision": 2,
            "answer": {"choice": "DMY", "reason": None},
        }

    def test_unknown_keys_rejected(self):
        schema = self.schema()
        request = self.request()
        self.assertEqual(validate(request, schema), [])
        for field in ("approved", "allowSourceWrite", "workbookBase64"):
            altered = {**request, field: True}
            with self.subTest(field=field):
                self.assertTrue(validate(altered, schema))
        altered = deepcopy(request)
        altered["answer"]["overrideHardBlocker"] = True
        self.assertTrue(validate(altered, schema))

    def test_preparation_cannot_expand_advanced_or_typed(self):
        schema = self.schema()
        request = {
            "schemaVersion": 1, "action": "approve", "preparationId": "prep_01",
            "reviewHash": "sha256:" + "1" * 64, "kind": "cleanup",
            "target": {"strategy": "personal_copy", "sheetIds": ["sheet_01"]},
        }
        self.assertEqual(validate(request, schema), [])
        for kind in ("advanced", "typed", "formula", "tmdl", "freeform_m"):
            with self.subTest(kind=kind):
                self.assertTrue(validate({**request, "kind": kind}, schema))
        for strategy in ("replace_workbook", "source_file", "personal_inplace"):
            with self.subTest(strategy=strategy):
                changed = deepcopy(request)
                changed["target"]["strategy"] = strategy
                self.assertTrue(validate(changed, schema))

    def test_claim_marker_alone_cannot_be_a_complete_attachment(self):
        schema = self.schema()
        claim = {
            "schemaVersion": 1, "action": "attach",
            "claim": {"marker": "marker_01", "semanticFingerprint": "sha256:" + "2" * 64,
                      "targetConfirmed": False, "expectedClaimVersion": 0,
                      "workbookName": "Book1", "locationHash": None},
        }
        self.assertEqual(validate(claim, schema), [])
        claim["claim"].pop("semanticFingerprint")
        self.assertTrue(validate(claim, schema))

    def test_image_chunk_has_bounded_payload_and_no_filesystem_path(self):
        schema = self.schema()
        chunk = {
            "schemaVersion": 1, "action": "image-chunk", "preparationId": "prep_01",
            "attemptId": "attempt_01", "uploadId": "upload_01", "index": 0,
            "offset": 0, "chunkHash": "sha256:" + "3" * 64, "dataBase64": "AAAA",
        }
        self.assertEqual(validate(chunk, schema), [])
        self.assertTrue(validate({**chunk, "index": -1}, schema))
        self.assertTrue(validate({**chunk, "dataBase64": "A" * (1398104 + 1)}, schema))
        self.assertTrue(validate({**chunk, "path": "../outside"}, schema))

    def test_restore_requires_cursor_and_fingerprint_and_rejects_unknown_action(self):
        schema = self.schema()
        restore = {
            "schemaVersion": 1, "action": "undo", "preparationId": "prep_01",
            "pointId": "point_01", "expectedCursor": 1,
            "expectedFingerprint": "sha256:" + "4" * 64,
            "expectedPreservationFingerprint": "sha256:" + "5" * 64,
        }
        self.assertEqual(validate(restore, schema), [])
        for field in ("expectedCursor", "expectedFingerprint", "expectedPreservationFingerprint"):
            changed = dict(restore)
            changed.pop(field)
            self.assertTrue(validate(changed, schema))
        self.assertTrue(validate({**restore, "action": "execute"}, schema))

    def test_image_declaration_enforces_snapshot_cap_and_purpose(self):
        schema = self.schema()
        image = {
            "schemaVersion": 1, "action": "image-begin", "preparationId": "prep_01",
            "attemptId": "attempt_01", "purpose": "before", "byteLength": 67108864,
            "imageHash": "sha256:" + "5" * 64,
        }
        self.assertEqual(validate(image, schema), [])
        self.assertTrue(validate({**image, "byteLength": 67108865}, schema))
        self.assertTrue(validate({**image, "purpose": "arbitrary_file"}, schema))

    def test_native_excel_sheet_ids_are_not_restricted_to_grant_id_syntax(self):
        request = {
            "schemaVersion": 1, "action": "approve", "preparationId": "prep_01",
            "reviewHash": "sha256:" + "1" * 64, "kind": "cleanup",
            "target": {"strategy": "personal_copy", "sheetIds": ["{00000000-0001-0000-0000-000000000000}"]},
        }
        self.assertEqual(validate(request, self.schema()), [])
        request["target"]["sheetIds"] = ["sheet\x00invalid"]
        self.assertTrue(validate(request, self.schema()))

    def test_runtime_wire_validation_matches_closed_contract(self):
        try:
            from pbip_assistant.sources.preparation.wire import validate_request
        except ModuleNotFoundError:
            self.fail("Preparation runtime wire validator is unavailable")
        from pbip_assistant.errors import InputError
        request = self.request()
        self.assertEqual(validate_request(request), request)
        for changed in ({**request, "approved": True}, {**request, "expectedAnswerRevision": True},
                        {**request, "action": "execute"}, {**request, "answer": {"choice": "DMY", "reason": None, "path": "outside"}}):
            self.assertTrue(validate(changed, self.schema()))
            with self.assertRaises(InputError):
                validate_request(changed)

    def test_source_snapshot_wire_requires_real_frame_and_bounded_literal_cells(self):
        request = {"schemaVersion": 1, "action": "source-snapshot", "preparationId": "prep_01", "snapshot": {
            "sourceId": "source_01", "sheetId": "{sheet_01}", "headers": ["Code"], "rows": [["00123"]],
            "formulaCells": [], "columnKinds": ["identifier"], "numberFormats": [["@"]],
            "dateSystem": "1900", "rowOffset": 5, "columnOffset": 2}}
        self.assertEqual(validate(request, self.schema()), [])
        request["snapshot"].pop("rowOffset")
        self.assertTrue(validate(request, self.schema()))


if __name__ == "__main__":
    unittest.main()
