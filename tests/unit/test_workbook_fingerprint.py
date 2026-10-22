from __future__ import annotations
from copy import deepcopy
from io import BytesIO
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
from pbip_assistant.workbook_fingerprint import MAIN, workbook_data_fingerprint
from tests.support.excel_plan import FIXTURE_ROOT

from tests.support.workbook_fingerprint import (repack)

class WorkbookFingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = (FIXTURE_ROOT / "excel_mcp_sales_input.xlsx").read_bytes()

    def _xml_variant(self, payload: bytes, transform) -> bytes:
        """Change package XML without an Excel/openpyxl serialization round trip."""
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        transform(parts)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in parts.items():
                archive.writestr(name, value)
        return output.getvalue()

    def _source_with_custom_number_format(self) -> bytes:
        def transform(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            formats = ET.Element(f"{{{MAIN}}}numFmts", {"count": "1"})
            ET.SubElement(formats, f"{{{MAIN}}}numFmt", {"numFmtId": "164", "formatCode": "0.0000"})
            styles.insert(0, formats)
            xfs = styles.find(f"{{{MAIN}}}cellXfs")
            custom = deepcopy(xfs[0])
            custom.set("numFmtId", "164")
            custom.set("applyNumberFormat", "1")
            xfs.append(custom)
            xfs.set("count", str(len(xfs)))
            parts["xl/styles.xml"] = ET.tostring(styles)
            sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
            cell = next(cell for cell in sheet.iter(f"{{{MAIN}}}c")
                        if cell.get("t", "n") == "n" and cell.find(f"{{{MAIN}}}v") is not None)
            cell.set("s", str(len(xfs) - 1))
            parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
        return self._xml_variant(self.payload, transform)

    def test_unused_result_styles_do_not_change_source_fingerprint(self) -> None:
        def transform(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            fonts = styles.find(f"{{{MAIN}}}fonts")
            added_font = deepcopy(fonts[0])
            ET.SubElement(added_font, f"{{{MAIN}}}b")
            fonts.append(added_font)
            fonts.set("count", str(len(fonts)))
            xfs = styles.find(f"{{{MAIN}}}cellXfs")
            added_xf = deepcopy(xfs[0])
            added_xf.set("fontId", str(len(fonts) - 1))
            xfs.append(added_xf)
            xfs.set("count", str(len(xfs)))
            parts["xl/styles.xml"] = ET.tostring(styles)
        changed = self._xml_variant(self.payload, transform)
        for include_styles in (True, False):
            with self.subTest(include_styles=include_styles):
                self.assertEqual(workbook_data_fingerprint(self.payload, include_styles=include_styles),
                                 workbook_data_fingerprint(changed, include_styles=include_styles))

    def test_equivalent_reindexed_style_components_are_stable(self) -> None:
        def transform(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            xfs = styles.find(f"{{{MAIN}}}cellXfs")
            for collection, reference in (("fonts", "fontId"), ("fills", "fillId"), ("borders", "borderId")):
                definitions = styles.find(f"{{{MAIN}}}{collection}")
                definitions.append(deepcopy(definitions[0]))
                definitions.set("count", str(len(definitions)))
                for xf in xfs:
                    if xf.get(reference, "0") == "0":
                        xf.set(reference, str(len(definitions) - 1))
            parts["xl/styles.xml"] = ET.tostring(styles)
        changed = self._xml_variant(self.payload, transform)
        self.assertEqual(workbook_data_fingerprint(self.payload), workbook_data_fingerprint(changed))

    def test_implicit_default_style_and_numeric_type_are_equivalent(self) -> None:
        def transform(parts):
            sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
            cell = next(cell for cell in sheet.iter(f"{{{MAIN}}}c")
                        if cell.get("t", "n") == "n" and cell.find(f"{{{MAIN}}}v") is not None)
            cell.set("s", "0")
            cell.set("t", "n")
            parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
        changed = self._xml_variant(self.payload, transform)
        for include_styles in (True, False):
            with self.subTest(include_styles=include_styles):
                self.assertEqual(workbook_data_fingerprint(self.payload, include_styles=include_styles),
                                 workbook_data_fingerprint(changed, include_styles=include_styles))

    def test_custom_number_format_id_renumbering_is_stable_but_format_change_is_stale(self) -> None:
        baseline = self._source_with_custom_number_format()
        def renumber(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            styles.find(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt").set("numFmtId", "190")
            for xf in styles.find(f"{{{MAIN}}}cellXfs"):
                if xf.get("numFmtId") == "164":
                    xf.set("numFmtId", "190")
            parts["xl/styles.xml"] = ET.tostring(styles)
        equivalent = self._xml_variant(baseline, renumber)
        self.assertEqual(workbook_data_fingerprint(baseline), workbook_data_fingerprint(equivalent))
        def change_format(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            styles.find(f"{{{MAIN}}}numFmts/{{{MAIN}}}numFmt").set("formatCode", "yyyy-mm-dd")
            parts["xl/styles.xml"] = ET.tostring(styles)
        changed = self._xml_variant(equivalent, change_format)
        self.assertNotEqual(workbook_data_fingerprint(baseline), workbook_data_fingerprint(changed))

    def test_source_font_and_opaque_style_attributes_remain_guarded(self) -> None:
        def change_font(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            ET.SubElement(styles.find(f"{{{MAIN}}}fonts/{{{MAIN}}}font"), f"{{{MAIN}}}b")
            parts["xl/styles.xml"] = ET.tostring(styles)
        def change_xf(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            styles.find(f"{{{MAIN}}}cellXfs/{{{MAIN}}}xf").set("quotePrefix", "1")
            parts["xl/styles.xml"] = ET.tostring(styles)
        def change_inherited_style(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            styles.find(f"{{{MAIN}}}cellStyleXfs/{{{MAIN}}}xf").set("numFmtId", "14")
            parts["xl/styles.xml"] = ET.tostring(styles)
        for transform in (change_font, change_xf, change_inherited_style):
            changed = self._xml_variant(self.payload, transform)
            self.assertNotEqual(workbook_data_fingerprint(self.payload), workbook_data_fingerprint(changed))

    def test_source_number_date_format_remains_guarded_without_global_styles(self) -> None:
        def change_source_format(parts):
            styles = ET.fromstring(parts["xl/styles.xml"])
            xfs = styles.find(f"{{{MAIN}}}cellXfs")
            date_style = deepcopy(xfs[0])
            date_style.set("numFmtId", "14")
            date_style.set("applyNumberFormat", "1")
            xfs.append(date_style)
            xfs.set("count", str(len(xfs)))
            parts["xl/styles.xml"] = ET.tostring(styles)
            sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
            cell = next(cell for cell in sheet.iter(f"{{{MAIN}}}c")
                        if cell.get("t", "n") == "n" and cell.find(f"{{{MAIN}}}v") is not None)
            cell.set("s", str(len(xfs) - 1))
            parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
        changed = self._xml_variant(self.payload, change_source_format)
        for include_styles in (True, False):
            with self.subTest(include_styles=include_styles):
                self.assertNotEqual(workbook_data_fingerprint(self.payload, include_styles=include_styles),
                                    workbook_data_fingerprint(changed, include_styles=include_styles))

    def test_source_row_and_column_style_references_remain_guarded(self) -> None:
        for reference_kind in ("row", "column"):
            with self.subTest(reference_kind=reference_kind):
                def add_reference(parts):
                    styles = ET.fromstring(parts["xl/styles.xml"])
                    fonts = styles.find(f"{{{MAIN}}}fonts")
                    added_font = deepcopy(fonts[0])
                    ET.SubElement(added_font, f"{{{MAIN}}}b")
                    fonts.append(added_font)
                    fonts.set("count", str(len(fonts)))
                    xfs = styles.find(f"{{{MAIN}}}cellXfs")
                    added_xf = deepcopy(xfs[0])
                    added_xf.set("fontId", str(len(fonts) - 1))
                    xfs.append(added_xf)
                    xfs.set("count", str(len(xfs)))
                    parts["xl/styles.xml"] = ET.tostring(styles)
                    sheet = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
                    if reference_kind == "row":
                        row = sheet.find(f"{{{MAIN}}}sheetData/{{{MAIN}}}row")
                        row.set("s", str(len(xfs) - 1))
                        row.set("customFormat", "1")
                    else:
                        columns = ET.Element(f"{{{MAIN}}}cols")
                        ET.SubElement(columns, f"{{{MAIN}}}col", {"min": "1", "max": "1", "style": str(len(xfs) - 1)})
                        sheet.insert(0, columns)
                    parts["xl/worksheets/sheet1.xml"] = ET.tostring(sheet)
                baseline = self._xml_variant(self.payload, add_reference)
                def change_referenced_style(parts):
                    styles = ET.fromstring(parts["xl/styles.xml"])
                    fonts = styles.find(f"{{{MAIN}}}fonts")
                    ET.SubElement(fonts[-1], f"{{{MAIN}}}i")
                    parts["xl/styles.xml"] = ET.tostring(styles)
                changed = self._xml_variant(baseline, change_referenced_style)
                self.assertNotEqual(workbook_data_fingerprint(baseline), workbook_data_fingerprint(changed))

    def test_result_insertion_keeps_source_defined_name_scope_identity(self) -> None:
        def add_source_name(parts):
            workbook = ET.fromstring(parts["xl/workbook.xml"])
            names = workbook.find(f"{{{MAIN}}}definedNames")
            if names is None:
                names = ET.SubElement(workbook, f"{{{MAIN}}}definedNames")
            sheet_name = workbook.find(f"{{{MAIN}}}sheets")[0].get("name")
            name = ET.SubElement(names, f"{{{MAIN}}}definedName", {"name": "SourceLocal", "localSheetId": "0"})
            name.text = "'" + sheet_name + "'!$A$1"
            parts["xl/workbook.xml"] = ET.tostring(workbook)
        baseline = self._xml_variant(self.payload, add_source_name)
        def insert_result(parts):
            workbook = ET.fromstring(parts["xl/workbook.xml"])
            sheets = workbook.find(f"{{{MAIN}}}sheets")
            result = ET.Element(f"{{{MAIN}}}sheet", {"name": result_name, "sheetId": "999"})
            sheets.insert(0, result)
            for name in workbook.findall(f"{{{MAIN}}}definedNames/{{{MAIN}}}definedName"):
                if name.get("localSheetId") is not None:
                    name.set("localSheetId", str(int(name.get("localSheetId")) + 1))
            parts["xl/workbook.xml"] = ET.tostring(workbook)
        options = {"typed_result_source_sheets": frozenset({"Sales"})}
        for result_name in ("PQ_Typed_Result", "PQ_Typed_Result_2", "PQ_Typed_Result_10"):
            with self.subTest(result_name=result_name):
                changed = self._xml_variant(baseline, insert_result)
                self.assertEqual(workbook_data_fingerprint(baseline, **options), workbook_data_fingerprint(changed, **options))

    def test_repacked_xlsx_has_same_data_fingerprint(self) -> None:
        repacked = repack(self.payload)
        self.assertNotEqual(self.payload, repacked)
        self.assertEqual(workbook_data_fingerprint(self.payload), workbook_data_fingerprint(repacked))

    def test_changed_cell_is_detected(self) -> None:
        changed = repack(self.payload, change_cell=True)
        self.assertNotEqual(workbook_data_fingerprint(self.payload), workbook_data_fingerprint(changed))

    @unittest.skipUnless(find_spec("openpyxl"), "openpyxl is unavailable")
    def test_managed_preview_sheet_can_be_ignored_without_ignoring_source_changes(self) -> None:
        from openpyxl import Workbook, load_workbook

        with tempfile.TemporaryDirectory() as folder:
            baseline_path = Path(folder) / "baseline.xlsx"
            preview_path = Path(folder) / "preview.xlsx"
            workbook = Workbook()
            source = workbook.active
            source.title = "Raw"
            source.append(["OrderID", "Amount"])
            source.append(["A1", 10])
            workbook.save(baseline_path)
            workbook = load_workbook(baseline_path)
            result = workbook.create_sheet("PQ_Result")
            result.append(["OrderID", "Amount"])
            result.append(["A1", 20])
            workbook.save(preview_path)
            baseline = baseline_path.read_bytes()
            preview = preview_path.read_bytes()
            options = {"ignored_sheet_names": frozenset({"PQ_Result"}), "include_styles": False}
            self.assertEqual(workbook_data_fingerprint(baseline, include_styles=False), workbook_data_fingerprint(preview, **options))
            workbook = load_workbook(preview_path)
            workbook["Raw"]["B2"] = 99
            workbook.save(preview_path)
            self.assertNotEqual(workbook_data_fingerprint(baseline, include_styles=False), workbook_data_fingerprint(preview_path.read_bytes(), **options))

    @unittest.skipUnless(find_spec("openpyxl"), "openpyxl is unavailable")
    def test_typed_result_write_does_not_stale_other_revision_cache(self) -> None:
        from openpyxl import Workbook, load_workbook

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.xlsx"
            workbook = Workbook()
            workbook.active.title = "Raw"
            workbook.active.append(["OrderID", "Amount"])
            workbook.active.append(["A1", 10])
            workbook.save(path)
            baseline = path.read_bytes()
            source_sheets = frozenset({"Raw"})
            initial = workbook_data_fingerprint(baseline, typed_result_source_sheets=source_sheets)
            workbook = load_workbook(path)
            result = workbook.create_sheet("PQ_Typed_Result")
            result.append(["OrderID", "Amount"])
            result.append(["A1", 20])
            workbook.save(path)
            self.assertEqual(initial, workbook_data_fingerprint(path.read_bytes(), typed_result_source_sheets=source_sheets))
            workbook["Raw"]["B2"] = 99
            workbook.save(path)
            self.assertNotEqual(initial, workbook_data_fingerprint(path.read_bytes(), typed_result_source_sheets=source_sheets))
            self.assertNotEqual(initial, workbook_data_fingerprint(path.read_bytes(), typed_result_source_sheets=frozenset({"Raw", "PQ_Typed_Result"})))


if __name__ == "__main__":
    unittest.main()
