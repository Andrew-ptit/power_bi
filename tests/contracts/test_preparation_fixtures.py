"""Independent oracle for the disposable preservation gate, never user data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class PreparationFixtureTests(unittest.TestCase):
    def generate(self, folder):
        result = subprocess.run(
            [sys.executable, "-m", "tests.live.create_fixture", str(folder),
             "prep_test_20261114", "--scenario", "preparation"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, "Synthetic preparation scenario is unavailable: " + result.stderr)
        return folder / "preparation_target.xlsx"

    def test_source_group_has_exact_cross_sheet_formula_names_table_and_format_oracle(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            target = self.generate(folder)
            self.assertTrue(target.is_file())
            with ZipFile(folder / "preparation_source.xlsx") as archive:
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                self.assertEqual([x.attrib["name"] for x in workbook.find(MAIN + "sheets")], ["Orders", "Rates"])
                sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                cells = {cell.attrib["r"]: cell for cell in sheet.iter(MAIN + "c")}
                self.assertEqual(cells["D2"].findtext(MAIN + "f"), "B2*Rates!$B$2+TaxRate")
                self.assertEqual(cells["D2"].findtext(MAIN + "v"), "11")
                self.assertEqual(cells["C2"].attrib["s"], "1")
                self.assertEqual(cells["A2"].findtext(MAIN + "is/" + MAIN + "t"), " 00123 ")
                self.assertEqual(sheet.find(MAIN + "mergeCells/" + MAIN + "mergeCell").attrib["ref"], "A4:B4")
                self.assertIn("OrdersTable", archive.read("xl/tables/table1.xml").decode())
                names = {x.attrib["name"]: x.text for x in workbook.find(MAIN + "definedNames")}
                self.assertEqual(names["TaxRate"], "1")
                self.assertEqual(names["LocalRate"], "Rates!$B$2")
            oracle = json.loads((folder / "preparation_oracle.json").read_text(encoding="utf-8"))
            self.assertEqual(oracle["sourceTotal"], 11)
            self.assertEqual(oracle["targetTotal"], 2)

    def test_target_is_marked_and_collides_without_reading_any_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            target = self.generate(folder)
            with ZipFile(target) as archive:
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                self.assertEqual([x.attrib["name"] for x in workbook.find(MAIN + "sheets")], ["Orders"])
                names = {x.attrib["name"]: x.text for x in workbook.find(MAIN + "definedNames")}
                self.assertEqual(names["Gate_Run_Id"], '"prep_test_20261114"')
                self.assertEqual(names["TaxRate"], "100")
                self.assertIn("OrdersTable", archive.read("xl/tables/table1.xml").decode())
            original = target.read_bytes()
            again = subprocess.run(
                [sys.executable, "-m", "tests.live.create_fixture", str(folder),
                 "prep_test_20261114", "--scenario", "preparation"],
                cwd=ROOT, capture_output=True, check=False,
            )
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
