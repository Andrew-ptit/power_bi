"""W-05 acceptance tests for advanced, read-only XLSX profiling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from examples.source_fixtures import build_fixtures
from pbip_assistant.errors import InputError
from pbip_assistant.xlsx import compare_workbook_schemas, profile_workbook, profile_workbooks
from tests.fixtures import make_xlsx


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _workbook(path: Path, *, sheet_data: str = "", protected: bool = False, empty: bool = False, date_1904: bool = False) -> Path:
    workbook_pr = '<workbookPr date1904="1"/>' if date_1904 else ""
    protection = '<workbookProtection lockStructure="1"/>' if protected else ""
    sheets = "" if empty else '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>'
    rel = "" if empty else '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{MAIN}" xmlns:r="{REL}">{workbook_pr}{protection}{sheets}</workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{PKG}">{rel}</Relationships>')
        if not empty:
            archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{MAIN}"><sheetData>{sheet_data}</sheetData></worksheet>')
    return path


def _styled_date_workbook(path: Path, serial: float, *, date_1904: bool = False) -> Path:
    rows = (
        '<row r="1"><c r="A1" t="inlineStr"><is><t>When</t></is></c></row>'
        f'<row r="2"><c r="A2" s="1"><v>{serial}</v></c></row>'
    )
    _workbook(path, sheet_data=rows, date_1904=date_1904)
    with ZipFile(path, "a") as archive:
        archive.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{MAIN}"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
        )
    return path


class AdvancedWorkbookProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_table_metadata_date_style_and_formula_cache_are_profiled(self) -> None:
        path = self.root / "Orders.xlsx"
        path.write_bytes(build_fixtures()["orders_synthetic.xlsx"])
        original = path.read_bytes()

        result = profile_workbook(path)
        sheet = result["sheets"][0]

        self.assertEqual(sheet["tables"][0], {
            "name": "OrdersTable", "display_name": "OrdersTable", "ref": "A1:Q7",
            "columns": [column["name"] for column in sheet["columns"]],
        })
        self.assertEqual(sheet["columns"][2]["data_types"], {"date": 6})
        self.assertEqual(sheet["columns"][2]["sample"][0], "2026-09-01")
        self.assertEqual(sheet["formula_cache"], {"cell_count": 1, "missing_cached_count": 0})
        self.assertIn("cached results", " ".join(sheet["issues"]))
        self.assertEqual(path.read_bytes(), original)

    def test_missing_formula_cache_is_explicit_and_not_calculated(self) -> None:
        path = self.root / "NoCache.xlsx"
        path.write_bytes(build_fixtures()["orders_formula_no_cache.xlsx"])
        sheet = profile_workbook(path)["sheets"][0]

        self.assertEqual(sheet["formula_cache"], {"cell_count": 1, "missing_cached_count": 1})
        self.assertEqual(sheet["columns"][15]["null_count"], 1)
        self.assertIn("no cached result", " ".join(sheet["issues"]))

    def test_locale_date_text_and_percentage_scale_remain_ambiguous(self) -> None:
        path = make_xlsx(self.root / "Ambiguous.xlsx", rows=[
            ["OrderDate", "Discount"],
            ["03/09/2026", 10],
            ["09/03/2026", 0.10],
        ])
        columns = profile_workbook(path)["sheets"][0]["columns"]

        self.assertEqual(columns[0]["data_types"], {"text": 2})
        self.assertEqual(columns[0]["sample"], ["03/09/2026", "09/03/2026"])
        self.assertIn("Ambiguous locale date", columns[0]["issues"][0])
        self.assertIn("Percentage scale is ambiguous", columns[1]["issues"][0])

    def test_date_serial_uses_date_system_and_serial_60_is_not_silently_coerced(self) -> None:
        normal = profile_workbook(_styled_date_workbook(self.root / "Normal.xlsx", 61))["sheets"][0]
        date_1904 = profile_workbook(_styled_date_workbook(self.root / "Date1904.xlsx", 1, date_1904=True))["sheets"][0]
        fictitious = profile_workbook(_styled_date_workbook(self.root / "Serial60.xlsx", 60))["sheets"][0]

        self.assertEqual(normal["columns"][0]["sample"], ["1900-03-01"])
        self.assertEqual(date_1904["columns"][0]["sample"], ["1904-01-02"])
        self.assertEqual(fictitious["columns"][0]["data_types"], {"number": 1})
        self.assertIn("fictitious", " ".join(fictitious["issues"]))

    def test_invalid_iso_date_is_not_silently_typed_as_date(self) -> None:
        rows = '<row r="1"><c r="A1" t="inlineStr"><is><t>When</t></is></c></row><row r="2"><c r="A2" t="d"><v>not-a-date</v></c></row>'
        sheet = profile_workbook(_workbook(self.root / "BadDate.xlsx", sheet_data=rows))["sheets"][0]
        self.assertEqual(sheet["columns"][0]["data_types"], {"text": 1})
        self.assertIn("Invalid ISO date", " ".join(sheet["issues"]))

    def test_duplicate_header_null_and_duplicate_counts_remain_compatible(self) -> None:
        path = make_xlsx(self.root / "Quality.xlsx", rows=[
            ["Key", "Key", "Value"], ["A", "x", 1], ["A", "y", None],
        ])
        sheet = profile_workbook(path)["sheets"][0]

        self.assertIn("Header contains duplicate column names", sheet["issues"])
        self.assertEqual(sheet["columns"][0]["duplicate_count"], 1)
        self.assertEqual(sheet["columns"][2]["null_count"], 1)

    def test_cells_beyond_header_are_reported_and_block_mapping(self) -> None:
        path = make_xlsx(self.root / "WideRow.xlsx", rows=[["A", "B"], [1, 2, 3]])
        sheet = profile_workbook(path)["sheets"][0]

        self.assertFalse(sheet["mapping_ready"])
        self.assertEqual(sheet["row_errors"], [{
            "code": "XLSX_COLUMN_COUNT", "row_number": 2,
            "expected_columns": 2, "actual_columns": 3,
        }])
        self.assertIn("beyond the header", " ".join(sheet["issues"]))

    def test_schema_drift_across_workbooks_reports_columns_order_and_types(self) -> None:
        first = make_xlsx(self.root / "A.xlsx", rows=[["Id", "Amount"], ["A", 10]])
        second = make_xlsx(self.root / "B.xlsx", rows=[["Amount", "Region"], ["ten", "South"]])

        result = profile_workbooks([first, second])
        direct = compare_workbook_schemas(result["workbooks"])
        drift = result["schema_comparison"]["comparisons"][1]

        self.assertEqual(result["schema_comparison"], direct)
        self.assertEqual(result["schema_comparison"]["status"], "schema_drift")
        self.assertEqual(drift["missing_columns"], ["Id"])
        self.assertEqual(drift["added_columns"], ["Region"])
        self.assertIn("Amount", drift["type_changes"])

    def test_empty_sheet_empty_workbook_and_structure_protection_are_visible(self) -> None:
        empty_sheet = profile_workbook(_workbook(self.root / "EmptySheet.xlsx"))
        empty_book = profile_workbook(_workbook(self.root / "EmptyBook.xlsx", empty=True))
        protected = profile_workbook(_workbook(self.root / "Protected.xlsx", protected=True))

        self.assertIn("Sheet is empty", empty_sheet["sheets"][0]["issues"])
        self.assertEqual(empty_book["sheets"], [])
        self.assertIn("no worksheets", " ".join(empty_book["issues"]))
        self.assertIn("protected", " ".join(protected["issues"]))

    def test_sheet_selection_is_explicit_and_missing_sheet_is_rejected(self) -> None:
        first = make_xlsx(self.root / "Selected.xlsx")
        result = profile_workbook(first, sheet_names=["Sales"])
        self.assertEqual(result["selected_sheets"], ["Sales"])
        self.assertEqual([sheet["name"] for sheet in result["sheets"]], ["Sales"])
        with self.assertRaises(InputError) as caught:
            profile_workbook(first, sheet_names=["Missing"])
        self.assertEqual(caught.exception.code, "XLSX_SHEET_NOT_FOUND")

    def test_named_table_selection_profiles_only_its_range(self) -> None:
        path = self.root / "Orders.xlsx"
        path.write_bytes(build_fixtures()["orders_synthetic.xlsx"])
        result = profile_workbook(path, table_name="OrdersTable")
        self.assertEqual(result["selected_table"], "OrdersTable")
        self.assertEqual(result["sheets"][0]["row_count"], 6)
        self.assertEqual(len(result["sheets"][0]["columns"]), 17)
        with self.assertRaises(InputError) as caught:
            profile_workbook(path, table_name="MissingTable")
        self.assertEqual(caught.exception.code, "XLSX_TABLE_NOT_FOUND")

    def test_encrypted_and_locked_workbooks_have_distinct_errors(self) -> None:
        encrypted = self.root / "Encrypted.xlsx"
        encrypted.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"synthetic")
        with self.assertRaises(InputError) as caught:
            profile_workbook(encrypted)
        self.assertEqual(caught.exception.code, "ENCRYPTED_XLSX")

        locked = make_xlsx(self.root / "Locked.xlsx")
        original_open = Path.open

        def deny_only_target(path: Path, *args: object, **kwargs: object):
            if path == locked.resolve():
                raise PermissionError("synthetic lock")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", deny_only_target):
            with self.assertRaises(InputError) as caught:
                profile_workbook(locked)
        self.assertEqual(caught.exception.code, "XLSX_LOCKED")


if __name__ == "__main__":
    unittest.main()
