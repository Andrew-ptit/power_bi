import tempfile
import unittest
from pathlib import Path

from pbip_assistant.errors import InputError
from pbip_assistant.xlsx import profile_workbook
from tests.fixtures import make_xlsx


class WorkbookProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_profiles_rows_nulls_duplicates_and_types(self):
        result = profile_workbook(make_xlsx(self.root / "Sales.xlsx"))
        sales = result["sheets"][0]
        self.assertEqual(sales["name"], "Sales")
        self.assertEqual(sales["row_count"], 3)
        self.assertEqual(sales["columns"][0]["duplicate_count"], 1)
        self.assertEqual(sales["columns"][2]["null_count"], 1)
        self.assertEqual(sales["columns"][2]["data_types"], {"number": 2})

    def test_formula_is_marked_cached_not_verified(self):
        result = profile_workbook(make_xlsx(self.root / "Formula.xlsx", formula=True))
        self.assertIn("cached results", result["sheets"][0]["issues"][0])

    def test_duplicate_headers_are_reported(self):
        path = make_xlsx(self.root / "Duplicate.xlsx", rows=[["Amount", "Amount"], [1, 2]])
        result = profile_workbook(path)
        self.assertIn("Header contains duplicate column names", result["sheets"][0]["issues"])

    def test_invalid_zip_has_specific_error(self):
        path = self.root / "Broken.xlsx"
        path.write_bytes(b"not an xlsx")
        with self.assertRaises(InputError) as caught:
            profile_workbook(path)
        self.assertEqual(caught.exception.code, "INVALID_XLSX")

    def test_other_extension_is_rejected(self):
        path = self.root / "Old.xls"
        path.write_bytes(b"test")
        with self.assertRaises(InputError) as caught:
            profile_workbook(path)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_EXCEL")


if __name__ == "__main__":
    unittest.main()
