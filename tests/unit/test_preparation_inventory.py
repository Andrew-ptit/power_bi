"""Read-only source groups and deterministic reviewed destination mapping."""
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from pbip_assistant.errors import InputError
from tests.support.preparation import preparation_workbook


class PreparationInventoryTests(unittest.TestCase):
    def setUp(self):
        try:
            from pbip_assistant.sources.preparation import inventory
        except ImportError:
            self.fail("Preparation source inventory is unavailable")
        self.inventory = inventory
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "a.csv").write_text("Code,Qty\n00123,2\n", encoding="utf-8")
        (self.root / "b.xlsx").write_bytes(preparation_workbook(source=True))

    def test_mixed_folder_one_csv_one_sheet_all_xlsx_sheets(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = self.inventory.inventory_folder(self.root, ".")
        self.assertEqual([s["sourceName"] for s in result.public()["sheets"]], [None, "Orders", "Rates"])
        self.assertEqual([s["proposedName"] for s in result.public()["sheets"]], ["a", "b_Orders", "b_Rates"])
        self.assertEqual(result.public()["errors"], [])
        self.assertNotIn(str(self.root), str(result.public()))
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)

    def test_package_root_sheet_relationships_are_valid_but_cannot_escape_package(self):
        original = preparation_workbook(source=True)
        for prefix, valid in (("/xl/worksheets/", True), ("/../../outside/", False)):
            stream = BytesIO()
            with ZipFile(BytesIO(original)) as source, ZipFile(stream, "w") as target:
                for name in source.namelist():
                    data = source.read(name)
                    if name == "xl/_rels/workbook.xml.rels":
                        data = data.replace(b'Target="worksheets/', ('Target="' + prefix).encode())
                    target.writestr(name, data)
            (self.root / "b.xlsx").write_bytes(stream.getvalue())
            result = self.inventory.inventory_folder(self.root, ".").public()
            if valid:
                self.assertEqual(result["errors"], [])
                self.assertEqual([s["sourceName"] for s in result["sheets"]], [None, "Orders", "Rates"])
            else:
                self.assertEqual(result["errors"][0]["code"], "INVALID_XLSX")

    def test_names_case_unicode_length_collisions(self):
        result = self.inventory.inventory_folder(self.root, ".")
        mappings = self.inventory.propose_sheet_names(result, ["A", "b_orders"])
        self.assertEqual([m["proposedName"] for m in mappings], ["a_2", "b_Orders_2", "b_Rates"])
        self.assertEqual(self.inventory.safe_sheet_name("bad:/name*[]?\\", set()), "bad__name_____")
        name = self.inventory.safe_sheet_name("😀" * 40, set())
        self.assertLessEqual(len(name.encode("utf-16-le")), 62)

    def test_defined_names_and_table_names_are_visible_for_preservation_preflight(self):
        result = self.inventory.inventory_folder(self.root, ".")
        workbook = next(f for f in result.public()["files"] if f["kind"] == "xlsx")
        self.assertEqual(workbook["definedNames"], [
            {"name": "TaxRate", "scope": "workbook"}, {"name": "LocalRate", "scope": "Rates"}])
        self.assertEqual(workbook["tableNames"], ["OrdersTable"])
        self.assertIn("defined_names", workbook["features"])

    def test_source_hash_changes_block_review(self):
        result = self.inventory.inventory_folder(self.root, ".")
        mappings = self.inventory.propose_sheet_names(result, [])
        (self.root / "a.csv").write_text("Code,Qty\n00123,3\n", encoding="utf-8")
        with self.assertRaises(InputError) as caught:
            self.inventory.review_import(result, result.inventory_hash, mappings, [])
        self.assertEqual(caught.exception.code, "DP_SOURCE_STALE")

    def test_review_rejects_partial_xlsx_group_and_duplicate_destination(self):
        result = self.inventory.inventory_folder(self.root, ".")
        mappings = self.inventory.propose_sheet_names(result, [])
        with self.assertRaises(InputError):
            self.inventory.review_import(result, result.inventory_hash, mappings[:-1], [])
        mappings[1]["proposedName"] = mappings[0]["proposedName"].upper()
        with self.assertRaises(InputError):
            self.inventory.review_import(result, result.inventory_hash, mappings, [])

    def test_root_escape_and_zip_bomb_blocked(self):
        with self.assertRaises(InputError):
            self.inventory.inventory_folder(self.root, "../")
        with self.assertRaises(InputError):
            self.inventory.inventory_folder(self.root, str(self.root))
        with ZipFile(self.root / "bomb.xlsx", "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", "x" * 1024)
        with patch.object(self.inventory, "MAX_UNCOMPRESSED", 512):
            result = self.inventory.inventory_folder(self.root, ".")
        self.assertIn("XLSX_LIMIT", [e["code"] for e in result.public()["errors"]])

    def test_ambiguous_csv_blocks_until_explicit_reading(self):
        (self.root / "ambiguous.csv").write_text("a,b;c\n1,2;3\n", encoding="utf-8")
        result = self.inventory.inventory_folder(self.root, ".")
        self.assertTrue(any(e["fileName"] == "ambiguous.csv" for e in result.public()["errors"]))
        result = self.inventory.inventory_folder(self.root, ".", csv_options={"ambiguous.csv": {"encoding": "utf-8", "delimiter": ";"}})
        self.assertFalse(any(e["fileName"] == "ambiguous.csv" for e in result.public()["errors"]))

    def test_subfolders_are_not_recursively_imported(self):
        folder = self.root / "nested"
        folder.mkdir()
        (folder / "hidden.csv").write_text("A,B\n1,2\n", encoding="utf-8")
        result = self.inventory.inventory_folder(self.root, ".")
        self.assertEqual(len(result.public()["files"]), 2)


if __name__ == "__main__":
    unittest.main()
