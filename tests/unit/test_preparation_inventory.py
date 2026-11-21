"""Read-only source groups and deterministic reviewed destination mapping."""
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from struct import unpack_from
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

    def test_inventory_reads_only_selected_items(self):
        nested = self.root / "nested"
        nested.mkdir()
        contents = b"Code,Qty,Date\n00123,2,03/04/2026\n"
        (self.root / "a.csv").write_bytes(contents)
        (nested / "a.csv").write_bytes(contents)
        (nested / "unselected.csv").write_bytes(b"other")
        items = [{"relativePath": "", "fileName": "a.csv"}, {"relativePath": "nested", "fileName": "a.csv"}]
        opened = []
        original_open = Path.open

        def trace_open(path, *args, **kwargs):
            opened.append(path.relative_to(self.root).as_posix())
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", trace_open):
            result = self.inventory.inventory_selection(self.root, items)
            self.inventory.verify_inventory(result)
        self.assertEqual(set(opened), {"a.csv", "nested/a.csv"})
        files = result.public()["files"]
        self.assertEqual([entry["fileName"] for entry in files], ["a.csv", "a.csv"])
        self.assertNotEqual(files[0]["fileId"], files[1]["fileId"])
        paths = [self.inventory.inventory_file_path(result, entry["fileId"]) for entry in files]
        self.assertEqual(paths, [self.root / "a.csv", nested / "a.csv"])
        self.assertEqual(files[1]["fileSummary"], {"columnCount": 3,
            "kinds": {"number": 1, "date": 1, "text": 1}, "encoding": "utf-8", "delimiter": ",", "headerRow": 1})
        self.assertNotIn("00123", str(files))

    def test_inventory_collects_per_file_errors_without_failing_batch(self):
        (self.root / "ragged.csv").write_bytes(b"Code,Qty\nz,1,2\n")
        (self.root / "broken.xlsx").write_bytes(b"not a zip")
        with (self.root / "oversize.csv").open("wb") as handle:
            handle.truncate(64 * 1024 * 1024 + 1)
        items = [{"relativePath": "", "fileName": name}
                 for name in ("a.csv", "ragged.csv", "broken.xlsx", "missing.csv", "oversize.csv")]
        result = self.inventory.inventory_selection(self.root, items)
        public = result.public()
        self.assertEqual({entry["fileName"]: entry["code"] for entry in public["errors"]},
                         {"ragged.csv": "CSV_COLUMN_COUNT", "broken.xlsx": "INVALID_XLSX",
                          "missing.csv": "DP_SOURCE_STALE", "oversize.csv": "REQUEST_LIMIT"})
        self.assertEqual([entry["proposedName"] for entry in public["sheets"]], ["a"])
        self.inventory.verify_inventory(result)

    def test_inventory_rejects_duplicate_items_and_over_200(self):
        item = {"relativePath": "", "fileName": "a.csv"}
        with self.assertRaises(InputError) as duplicate:
            self.inventory.inventory_selection(self.root, [item, item])
        self.assertEqual(duplicate.exception.code, "INVALID_REQUEST")
        with self.assertRaises(InputError) as limit:
            self.inventory.inventory_selection(self.root, [{"relativePath": "", "fileName": f"{n}.csv"}
                                                           for n in range(201)])
        self.assertEqual(limit.exception.code, "REQUEST_LIMIT")

    def test_inventory_still_detects_source_change(self):
        nested = self.root / "nested"
        nested.mkdir()
        selected = nested / "a.csv"
        selected.write_bytes(b"Code,Qty\n00123,2\n")
        result = self.inventory.inventory_selection(self.root, [{"relativePath": "nested", "fileName": "a.csv"}])
        (nested / "unselected.csv").touch()
        self.inventory.verify_inventory(result)
        selected.write_bytes(b"Code,Qty\n00123,3\n")
        with self.assertRaises(InputError) as changed:
            self.inventory.verify_inventory(result)
        self.assertEqual(changed.exception.code, "DP_SOURCE_STALE")

    def test_selected_csv_infers_encoding_and_single_column_dialect(self):
        for name, encoding, data, kinds in (
                ("western.csv", "cp1252", "Café;Qty\nElève;2\n", {"number": 1, "date": 0, "text": 1}),
                ("wide.csv", "utf-16", "Date,Qty\n03/04/2026,2\n", {"number": 1, "date": 1, "text": 0}),
                ("one.csv", "utf-8", "Quantity\n2\n3\n", {"number": 1, "date": 0, "text": 0})):
            with self.subTest(name=name):
                (self.root / name).write_bytes(data.encode(encoding))
                result = self.inventory.inventory_selection(self.root, [{"relativePath": "", "fileName": name}]).public()
                self.assertEqual(result["errors"], [])
                entry = result["files"][0]
                delimiter = ";" if encoding == "cp1252" else ","
                self.assertEqual(entry["csvReading"], {"encoding": encoding, "delimiter": delimiter, "header_row": 1})
                self.assertEqual(entry["fileSummary"]["kinds"], kinds)

    def test_selected_csv_rejects_cell_limit_before_describing_columns(self):
        header = ",".join(f"col{index}" for index in range(200))
        row = ",".join("1" for _ in range(200))
        (self.root / "large.csv").write_text(header + "\n" + (row + "\n") * 2000, encoding="utf-8")
        with patch.object(self.inventory, "describe_columns", side_effect=AssertionError("over-limit columns were described")):
            result = self.inventory.inventory_selection(self.root, [{"relativePath": "", "fileName": "large.csv"}]).public()
        self.assertEqual(result["errors"][0]["code"], "REQUEST_LIMIT")
        self.assertEqual(result["sheets"], [])

    def test_xlsx_summary_counts_native_typed_columns_across_sheet_group(self):
        result = self.inventory.inventory_selection(self.root, [{"relativePath": "", "fileName": "b.xlsx"}]).public()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["files"][0]["fileSummary"], {
            "columnCount": 6, "kinds": {"number": 3, "date": 1, "text": 2},
            "encoding": None, "delimiter": None, "headerRow": None,
        })
        self.assertEqual([sheet["sourceName"] for sheet in result["sheets"]], ["Orders", "Rates"])

    def test_malformed_xlsx_metadata_and_deflate_are_isolated(self):
        member = "xl/workbook.xml"
        contents = preparation_workbook(source=True)
        invalid = BytesIO()
        compressed = BytesIO()
        with ZipFile(BytesIO(contents)) as source, ZipFile(invalid, "w") as target, ZipFile(
                compressed, "w", ZIP_DEFLATED) as deflated:
            for name in source.namelist():
                data = source.read(name)
                deflated.writestr(name, data)
                if name == member:
                    data = data.replace(b'localSheetId="1"', 'localSheetId="²"'.encode())
                target.writestr(name, data)
            offset = deflated.getinfo(member).header_offset
        damaged = bytearray(compressed.getvalue())
        name_length, extra_length = unpack_from("<HH", damaged, offset + 26)
        block_start = offset + 30 + name_length + extra_length
        damaged[block_start] = 0b00000111  # Reserved DEFLATE block type.
        (self.root / "invalid.xlsx").write_bytes(invalid.getvalue())
        (self.root / "damaged.xlsx").write_bytes(damaged)
        items = [{"relativePath": "", "fileName": name} for name in ("invalid.xlsx", "damaged.xlsx", "a.csv")]
        result = self.inventory.inventory_selection(self.root, items).public()
        self.assertEqual([(entry["fileName"], entry["code"]) for entry in result["errors"]],
                         [("invalid.xlsx", "INVALID_XLSX"), ("damaged.xlsx", "INVALID_XLSX")])
        self.assertEqual([entry["proposedName"] for entry in result["sheets"]], ["a"])


if __name__ == "__main__":
    unittest.main()
