"""Bounded reviewed source transfer; no native qualification claims."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pbip_assistant.errors import InputError
from pbip_assistant.sources.preparation.inventory import inventory_folder, inventory_selection, propose_sheet_names
from pbip_assistant.sources.preparation.packages import build_packages


class PreparationPackageTests(unittest.TestCase):
    def test_csv_preserves_identifier_and_formula_like_literal_and_source(self):
        from pbip_assistant.sources.preparation import packages
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.csv"
            original = b'Code,Value\n00123,=1+1\n'
            path.write_bytes(original)
            inventory = inventory_folder(Path(folder), ".")
            mappings = propose_sheet_names(inventory, [])
            result = packages.build_packages(inventory, inventory.inventory_hash, mappings, [])
            self.assertEqual(result[0]["sheets"][0]["values"], [["Code", "Value"], ["00123", "=1+1"]])
            self.assertEqual(result[0]["sheets"][0]["formulaCells"], [])
            self.assertEqual(path.read_bytes(), original)
            path.write_text("Code,Value\n00123,9\n", encoding="utf-8")
            with self.assertRaises(InputError) as caught:
                packages.build_packages(inventory, inventory.inventory_hash, mappings, [])
            self.assertEqual(caught.exception.code, "DP_SOURCE_STALE")

    def test_xlsx_known_unsupported_preservation_blocks_package(self):
        from pbip_assistant.sources.preparation import packages
        from tests.support.preparation import preparation_workbook
        from io import BytesIO
        from zipfile import ZipFile
        raw = BytesIO()
        with ZipFile(BytesIO(preparation_workbook(source=True))) as source, ZipFile(raw, "w") as protected:
            for member in source.infolist():
                content = source.read(member.filename)
                if member.filename == "xl/workbook.xml":
                    content = content.replace(b"<sheets>", b'<workbookProtection lockStructure="1"/><sheets>')
                protected.writestr(member, content)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "a.xlsx").write_bytes(raw.getvalue())
            inventory = inventory_folder(Path(folder), ".")
            with self.assertRaises(InputError) as caught:
                packages.build_packages(inventory, inventory.inventory_hash, propose_sheet_names(inventory, []), [])
            self.assertEqual(caught.exception.code, "DP_UNSUPPORTED_PRESERVATION")

    def test_image_hash_ignores_only_native_ids_and_validates_full_shape(self):
        from pbip_assistant.sources.preparation import packages
        sheet = {"sheetId": "{native}", "name": "Data", "rowOffset": 0, "columnOffset": 0,
                 "values": [["00123"]], "formulas": [["00123"]], "formulaCells": [], "numberFormats": [["@"]]}
        image = {"version": 1, "sheets": [sheet]}
        expected = packages.image_fingerprint(image)
        sheet["sheetId"] = "{new}"
        self.assertEqual(packages.image_fingerprint(image), expected)
        sheet["values"][0][0] = "123"
        self.assertNotEqual(packages.image_fingerprint(image), expected)
        sheet["numberFormats"] = []
        with self.assertRaises(InputError):
            packages.image_fingerprint(image)

    def test_hash_uses_native_double_bytes_and_ignores_only_formula_cached_values(self):
        from pbip_assistant.sources.preparation.packages import image_fingerprint
        from pbip_assistant.sources.assistant_ingest import canonical_hash
        image = {"version": 1, "sheets": [{"sheetId": "native", "name": "Data", "rowOffset": 0, "columnOffset": 0,
            "values": [[1e-7, 100000000000000000000, 7]], "formulas": [[1e-7, 100000000000000000000, "=A1+1"]],
            "formulaCells": [[0, 2]], "numberFormats": [["General"] * 3]}]}
        projected = {"version": 1, "sheets": [{"name": "Data", "rowOffset": 0, "columnOffset": 0,
            "values": [[{"$number": "3e7ad7f29abcaf48"}, {"$number": "4415af1d78b58c40"}, None]],
            "formulas": [[{"$number": "3e7ad7f29abcaf48"}, {"$number": "4415af1d78b58c40"}, "=A1+1"]],
            "formulaCells": [[0, 2]], "numberFormats": [["General"] * 3]}]}
        expected = canonical_hash(projected)
        self.assertEqual(image_fingerprint(image), expected)
        image["sheets"][0]["values"][0][2] = 999
        self.assertEqual(image_fingerprint(image), expected)
        image["sheets"][0]["formulas"][0][2] = "=A1+2"
        self.assertNotEqual(image_fingerprint(image), expected)

class TypedImportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / "nested").mkdir()
        self.source = self.root / "nested" / "data.csv"
        self.payload = (
            "Price;Qty;Code;Date;Note;Literal\n"
            "-1.234,56;1.234;00123;1904-01-01; private text ;+42\n"
            "0,99;2.345;00023;1904-01-02; other text ;+43\n"
        ).encode()
        self.source.write_bytes(self.payload)
        (self.root / "data.csv").write_bytes(b"wrong\n42\n")
        (self.root / "ragged.csv").write_bytes(b"A,B\n1,2\n2\n")
        self.inventory = inventory_selection(self.root, [
            {"relativePath": "nested", "fileName": "data.csv"},
            {"relativePath": "", "fileName": "ragged.csv"},
            {"relativePath": "", "fileName": "missing.csv"},
        ])
        self.mappings = propose_sheet_names(self.inventory, [])

    def build(self, system):
        report = {}
        packages = build_packages(self.inventory, self.inventory.inventory_hash,
                                  self.mappings, [], date_system=system, report=report)
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.assertEqual(len(packages), 1)
        return packages[0]["sheets"][0], report

    def test_csv_number_column_written_as_number_general(self):
        sheet, _ = self.build("1900")
        self.assertEqual(sheet["values"][1][:2], [-1234.56, 1234])
        self.assertIs(type(sheet["values"][1][0]), float)
        self.assertEqual(sheet["numberFormats"][1][:2], ["General", "General"])
        self.assertEqual(sheet["numberFormats"][0], ["@"] * 6)

    def test_csv_date_column_serial_matches_1900_and_1904(self):
        for system, expected in (("1900", 1462), ("1904", 0)):
            with self.subTest(system=system):
                sheet, _ = self.build(system)
                self.assertEqual(sheet["values"][1][3], expected)
                self.assertEqual(sheet["numberFormats"][1][3], "yyyy-mm-dd")
                self.assertEqual(sheet["formulas"], sheet["values"])
                self.assertEqual(sheet["formulaCells"], [])

    def test_csv_leading_zero_and_text_columns_use_at_format(self):
        sheet, _ = self.build("1904")
        self.assertEqual(sheet["values"][1][2:], ["00123", 0, "private text", "+42"])
        self.assertEqual(sheet["numberFormats"][1][2:], ["@", "yyyy-mm-dd", "@", "@"])

    def test_import_report_lists_decisions_with_reason_codes(self):
        sheet, report = self.build("1900")
        entry = next(f for f in report["files"] if f["status"] == "imported")
        self.assertEqual(entry["reading"], {"encoding": "utf-8", "delimiter": ";", "headerRow": 1, "columns": 6})
        self.assertEqual(entry["readingDecisions"], [{"reasonCode": "DELIMITER_INFERRED"}])
        self.assertEqual(entry["sheets"], [{"sourceSheetId": sheet["sourceSheetId"], "targetName": "data"}])
        self.assertEqual([d["reasonCode"] for d in entry["decisions"]], [
            "DECIMAL_COMMA", "GROUP_SEPARATOR", "LEADING_ZERO_TEXT", "DATE_ORDER_DETECTED", "FORMULA_LIKE_TEXT"])
        self.assertEqual(entry["decisions"][0]["affectedRows"], 2)
        self.assertEqual(entry["decisions"][0]["samples"], ["-1.234,56", "0,99"])
        self.assertEqual(report["totals"], {"files": 1, "sheets": 1, "skipped": 2, "decisions": 6})

    def test_ragged_csv_skipped_but_other_files_import(self):
        _, report = self.build("1904")
        skipped = {f["fileName"]: f for f in report["files"] if f["status"] == "skipped"}
        for name, code in (("ragged.csv", "CSV_COLUMN_COUNT"), ("missing.csv", "DP_SOURCE_STALE")):
            self.assertEqual(skipped[name]["sheets"], [])
            self.assertEqual(skipped[name]["decisions"], [])
            self.assertEqual(skipped[name]["readingDecisions"], [])
            self.assertEqual(skipped[name]["issues"][0]["code"], code)
            self.assertTrue(skipped[name]["issues"][0]["message"])

    def test_report_has_no_absolute_path_or_raw_row(self):
        _, report = self.build("1904")
        serialized = json.dumps(report)
        for private in (self.root.name, "nested", "private text", "other text", "formulas", "values"):
            self.assertNotIn(private, serialized)

    def test_reading_fallback_and_inferred_delimiter(self):
        self.source.write_bytes(b"Code;Label\n1;caf\xe9\n")
        self.inventory = inventory_selection(self.root, [{"relativePath": "nested", "fileName": self.source.name}])
        report = {}
        build_packages(self.inventory, self.inventory.inventory_hash, propose_sheet_names(self.inventory, []), [], report=report)
        entry = report["files"][0]
        self.assertEqual(entry["reading"]["encoding"], "cp1252")
        self.assertEqual(entry["readingDecisions"], [
            {"reasonCode": "ENCODING_FALLBACK"}, {"reasonCode": "DELIMITER_INFERRED"}])
        self.assertEqual(report["totals"]["decisions"], 2)

    def test_oversized_csv_is_skipped_without_blocking_other_files(self):
        report = {}
        with patch("pbip_assistant.sources.preparation.packages.MAX_CELLS", 1):
            packages = build_packages(self.inventory, self.inventory.inventory_hash, self.mappings, [],
                                      date_system="1900", report=report)
        self.assertEqual(packages, [])
        self.assertEqual(report["totals"]["files"], 0)
        self.assertEqual(report["totals"]["skipped"], 3)
        codes = {f["fileName"]: f["issues"][0]["code"] for f in report["files"] if f["status"] == "skipped"}
        self.assertEqual(codes["data.csv"], "REQUEST_LIMIT")

    def test_empty_cells_are_blank_with_general_format(self):
        self.source.write_bytes(b"Code,Qty,Note\nA,1,x\nB,,\n")
        self.inventory = inventory_selection(self.root, [{"relativePath": "nested", "fileName": "data.csv"}])
        mappings = propose_sheet_names(self.inventory, [])
        report = {}
        packages = build_packages(self.inventory, self.inventory.inventory_hash, mappings, [],
                                  date_system="1900", report=report)
        sheet = packages[0]["sheets"][0]
        self.assertEqual(sheet["values"], [["Code", "Qty", "Note"], ["A", 1, "x"], ["B", None, None]])
        self.assertEqual(sheet["numberFormats"], [["@", "@", "@"], ["@", "General", "@"],
                                                  ["@", "General", "General"]])
        self.assertEqual(report["files"][0]["decisions"], [])

    def test_date_system_required_when_date_columns_exist(self):
        with self.assertRaises(InputError) as caught:
            self.build(None)
        self.assertEqual(caught.exception.code, "DP_DATE_SYSTEM_REQUIRED")

    def test_xlsx_package_unchanged(self):
        from tests.support.preparation_images import native_package
        sheet = {"name": "Data", "rowOffset": 0, "columnOffset": 0, "values": [["001", 2]],
                 "formulas": [["001", 2]], "numberFormats": [["@", "General"]], "formulaCells": []}
        payload = native_package({"sheets": [sheet]})
        path = self.root / "native.xlsx"
        path.write_bytes(payload)
        inventory = inventory_selection(self.root, [{"relativePath": "", "fileName": path.name}])
        mappings = propose_sheet_names(inventory, [])
        mappings[0]["proposedName"] = "Data"

        class SyntheticRunner:
            def apply(self, request):
                Path(request["outputPath"]).write_bytes(payload)
                return {"sheets": [sheet], "namespaceId": request["namespaceId"]}

        report = {}
        result = build_packages(inventory, inventory.inventory_hash, mappings, [],
                                native_runner=SyntheticRunner(), report=report)
        self.assertEqual(path.read_bytes(), payload)
        self.assertEqual(base64.b64decode(result[0]["base64"]), payload)
        self.assertEqual({key: result[0]["sheets"][0][key] for key in sheet if key != "name"},
                         {key: value for key, value in sheet.items() if key != "name"})
        self.assertEqual(report["files"][0]["decisions"], [])
        self.assertEqual(report["files"][0]["readingDecisions"], [])


class CsvNativeVerificationTests(unittest.TestCase):
    """The native verifier compares each cell with the package formats, not with a fixed '@'."""

    @staticmethod
    def evidence(*sheets):
        from tests.support.preparation_images import native_package
        from pbip_assistant.sources.preparation.package_preservation import inspect_package
        return inspect_package(native_package({"sheets": list(sheets)}))

    def frames(self):
        base = {"name": "Personal", "rowOffset": 0, "columnOffset": 0, "values": [["original"]],
                "formulas": [["original"]], "formulaCells": [], "numberFormats": [["General"]]}
        typed = {"name": "data", "rowOffset": 0, "columnOffset": 0,
                 "values": [["Code", "Qty"], ["00123", 2]],
                 "formulas": [["Code", "Qty"], ["00123", 2]],
                 "formulaCells": [], "numberFormats": [["@", "@"], ["@", "General"]]}
        return base, typed

    def test_typed_formats_pass_and_wrong_format_is_rejected(self):
        from copy import deepcopy
        from pbip_assistant.sources.preparation.package_preservation import verify_package_csv_import
        base, typed = self.frames()
        before, after = self.evidence(base), self.evidence(base, typed)
        plan = {"targetName": "data", "values": typed["values"], "numberFormats": typed["numberFormats"]}
        self.assertTrue(verify_package_csv_import(before, after, [plan], _validate_only=True))
        wrong = deepcopy(plan)
        wrong["numberFormats"] = [["@", "@"], ["@", "@"]]
        with self.assertRaises(InputError) as caught:
            verify_package_csv_import(before, after, [wrong], _validate_only=True)
        self.assertIn("format", str(caught.exception))
