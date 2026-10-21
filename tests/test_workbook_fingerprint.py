from __future__ import annotations

from io import BytesIO
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from pbip_assistant.workbook_fingerprint import MAIN, workbook_data_fingerprint
from tests.test_excel_plan import FIXTURE_ROOT


def repack(payload: bytes, *, change_cell: bool = False) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(payload)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if change_cell and item.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(data)
                cell = next(node for node in root.iter(f"{{{MAIN}}}c") if node.find(f"{{{MAIN}}}v") is not None)
                value = cell.find(f"{{{MAIN}}}v")
                value.text = "999999" if value.text != "999999" else "888888"
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item.filename, data)
    return output.getvalue()


class WorkbookFingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = (FIXTURE_ROOT / "excel_mcp_sales_input.xlsx").read_bytes()

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
