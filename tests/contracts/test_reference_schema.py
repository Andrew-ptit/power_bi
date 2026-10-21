import csv
import tempfile
import unittest
from pathlib import Path

from pbip_assistant.xlsx import profile_workbook
from tests.support.fixtures import ORDER_HEADERS, make_csv_shaped_xlsx


class ReferenceSchemaTests(unittest.TestCase):
    def test_synthetic_workbook_preserves_return_and_discount_shapes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = profile_workbook(make_csv_shaped_xlsx(Path(directory) / "Orders.xlsx"))
        sheet = result["sheets"][0]
        columns = {column["name"]: column for column in sheet["columns"]}
        self.assertEqual([column["name"] for column in sheet["columns"]], ORDER_HEADERS)
        self.assertEqual(sheet["row_count"], 3)
        self.assertIn(-1, columns["Quantity"]["sample"])
        self.assertIn(0, columns["Quantity"]["sample"])
        self.assertIn(10, columns["Discount"]["sample"])
        self.assertEqual(columns["OrderID"]["duplicate_count"], 0)

    def test_supplied_csv_header_matches_fixture_when_available(self):
        path = Path(__file__).resolve().parents[2] / "clean_final_data.csv"
        if not path.exists():
            self.skipTest("User-supplied CSV is not present")
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(next(csv.reader(stream)), ORDER_HEADERS)


if __name__ == "__main__":
    unittest.main()
