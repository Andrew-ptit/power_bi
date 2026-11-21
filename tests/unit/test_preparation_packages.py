"""Bounded reviewed source transfer; no native qualification claims."""
import tempfile
import unittest
from pathlib import Path
from pbip_assistant.errors import InputError
from pbip_assistant.sources.preparation.inventory import inventory_folder, propose_sheet_names


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
