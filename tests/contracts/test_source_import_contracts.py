"""The source import actions keep preparation requests closed."""
import json
import unittest

from pbip_assistant.core.resources import schema_path
from pbip_assistant.errors import InputError
from pbip_assistant.sources.preparation.wire import validate_request
from tests.support.json_schema_oracle import validate


class SourceImportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(schema_path("preparation.schema.json").read_text(encoding="utf-8"))

    def assert_accepted(self, request):
        self.assertEqual(validate(request, self.schema), [])
        self.assertEqual(validate_request(request), request)

    def assert_rejected(self, request, path="request"):
        self.assertTrue(validate(request, self.schema))
        with self.assertRaises(InputError) as error:
            validate_request(request)
        self.assertEqual(error.exception.code, "INVALID_REQUEST")
        self.assertEqual(error.exception.path, path)

    def browse(self, relative_path=""):
        return {
            "schemaVersion": 1, "action": "browse", "preparationId": "prep_01",
            "expectedClaimVersion": 3, "root": r"C:\Data\dataset", "relativePath": relative_path,
        }

    def inventory(self, items):
        return {
            "schemaVersion": 1, "action": "inventory", "preparationId": "prep_01",
            "expectedClaimVersion": 3, "root": r"C:\Data\dataset", "items": items,
        }

    def test_browse_rejects_extra_keys(self):
        self.assert_accepted(self.browse())
        browse = self.browse("sales/2026")
        self.assert_accepted(browse)
        self.assert_rejected({**browse, "includeContents": True})
        missing_claim = {key: value for key, value in browse.items() if key != "expectedClaimVersion"}
        self.assert_rejected(missing_claim)

    def test_inventory_requires_items_within_limit(self):
        first = {"relativePath": "", "fileName": "root.csv"}
        self.assert_accepted(self.inventory([first]))
        selected = [first] + [{"relativePath": "sales/2026", "fileName": f"sales{i}.xlsx"} for i in range(199)]
        self.assert_accepted(self.inventory(selected))
        self.assert_rejected(self.inventory([]), "request.items")
        extra = {"relativePath": "", "fileName": "last.csv"}
        self.assert_rejected(self.inventory(selected + [extra]), "request.items")
        legacy = {"schemaVersion": 1, "action": "inventory", "preparationId": "prep_01", "root": r"C:\Data\dataset"}
        self.assert_rejected({**legacy, "relativePath": "."})
        self.assert_rejected(self.inventory([{**first, "readContents": True}]), "request.items[0]")

    def test_inventory_rejects_legacy_relative_path_with_selection(self):
        request = self.inventory([{"relativePath": "", "fileName": "root.csv"}])
        self.assert_accepted(request)
        self.assert_rejected({**request, "relativePath": "."})

    def test_browse_and_inventory_require_fully_qualified_roots(self):
        requests = (self.browse(), self.inventory([{"relativePath": "", "fileName": "root.csv"}]))
        valid = {
            "drive": r"C:\Data\dataset",
            "drive root": "D:\\",
            "drive with forward slash": "D:/Data/dataset",
            "UNC share": r"\\host\share",
            "UNC subfolder": r"\\host\share\dataset",
            "UNC with forward slashes": "//host/share/dataset",
            "POSIX": "/tmp/dataset",
            "POSIX root": "/",
        }
        invalid = {
            "current directory": ".",
            "parent directory": "..",
            "relative directory": "relative/root",
            "drive-relative": "C:relative",
            "current-drive path": r"\dataset",
            "current-drive root": "\\",
            "UNC without share": r"\\host",
            "drive path with null": "C:\\Data\x00",
            "POSIX path with newline": "/tmp/dataset\n",
            "UNC share with delete control": "\\\\host\\share\x7f",
            "POSIX path with C1 control": "/tmp/data\x85",
        }
        for request in requests:
            for label, root in valid.items():
                with self.subTest(action=request["action"], root_kind=label):
                    self.assert_accepted({**request, "root": root})
            for label, root in invalid.items():
                with self.subTest(action=request["action"], root_kind=label):
                    self.assert_rejected({**request, "root": root}, "request.root")

    def test_inventory_rejects_absolute_or_parent_path(self):
        accepted = {"relativePath": r"sales\2026", "fileName": "quý 1.CSV"}
        self.assert_accepted(self.inventory([accepted]))
        for relative_path in ("/etc", r"\sales", r"\\host\share", r"C:\sales", "C:sales",
                              "..", "../sales", "sales/../2026", r"sales\..\2026"):
            with self.subTest(relative_path=relative_path):
                self.assert_rejected(self.browse(relative_path), "request.relativePath")
                self.assert_rejected(
                    self.inventory([{**accepted, "relativePath": relative_path}]), "request.items[0].relativePath")
        for file_name in ("../root.csv", "sales/root.csv", r"sales\root.csv", "C:root.csv"):
            with self.subTest(file_name=file_name):
                self.assert_rejected(
                    self.inventory([{**accepted, "fileName": file_name}]), "request.items[0].fileName")

    def test_packages_rejects_unknown_date_system(self):
        request = {
            "schemaVersion": 1, "action": "packages", "preparationId": "prep_01",
            "reviewHash": "sha256:" + "1" * 64,
        }
        self.assert_accepted(request)
        for date_system in ("1900", "1904"):
            self.assert_accepted({**request, "dateSystem": date_system})
        for date_system in ("1901", 1900, None):
            with self.subTest(date_system=date_system):
                self.assert_rejected({**request, "dateSystem": date_system}, "request.dateSystem")

    def test_legacy_actions_unchanged(self):
        for request in (
            {"schemaVersion": 1, "action": "pick-folder"},
            {"schemaVersion": 1, "action": "state", "preparationId": "prep_01", "expectedClaimVersion": 3},
            {"schemaVersion": 1, "action": "answer", "preparationId": "prep_01", "questionId": "date_format",
             "expectedAnswerRevision": 2, "answer": {"choice": "DMY", "reason": None}},
            {"schemaVersion": 1, "action": "approve", "preparationId": "prep_01", "reviewHash": "sha256:" + "1" * 64,
             "kind": "import", "target": {"strategy": "import_new", "sheetIds": ["{sheet_01}"]}},
        ):
            with self.subTest(action=request["action"]):
                self.assert_accepted(request)
                self.assert_rejected({**request, "allowSourceWrite": True})
        self.assert_rejected({"schemaVersion": 1, "action": "execute"}, "request.action")

    def test_report_reason_codes_closed(self):
        definitions = self.schema["$defs"]
        self.assertIsNotNone(definitions.get("importReasonCode"), "Missing import report reason-code contract")
        reason_contract = {"$defs": definitions, "$ref": "#/$defs/importReasonCode"}
        expected = (
            "DECIMAL_DOT", "DECIMAL_COMMA", "GROUP_SEPARATOR", "DATE_ORDER_DETECTED", "DATE_DMY_DEFAULT",
            "INVALID_DATE_TEXT", "DATE_UNSUPPORTED_TEXT", "LEADING_ZERO_TEXT", "MIXED_TYPE_TEXT",
            "PRECISION_TEXT", "FORMULA_LIKE_TEXT", "EMPTY_COLUMN", "ENCODING_FALLBACK", "DELIMITER_INFERRED",
        )
        self.assertCountEqual(definitions["importReasonCode"]["enum"], expected)
        for reason in expected:
            with self.subTest(reason=reason):
                self.assertEqual(validate(reason, reason_contract), [])
        for reason in ("UNKNOWN", "TEXT", "NUMBER", None):
            with self.subTest(reason=reason):
                self.assertTrue(validate(reason, reason_contract))
