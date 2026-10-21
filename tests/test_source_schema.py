import tempfile
import unittest
from pathlib import Path

from pbip_assistant.workflow import import_sources
from tests.fixtures import make_pbip, make_xlsx


class CrossSourceSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_pbip(self.root / "Retail")

    def test_csv_and_xlsx_schema_are_compared_without_forcing_csv_into_sheet(self):
        workbook = make_xlsx(self.root / "Orders.xlsx", rows=[["Id", "Amount"], ["A", 10]])
        csv_path = self.root / "Orders.csv"
        csv_path.write_text("Id,Amount\nB,20\n", encoding="utf-8", newline="")
        result = import_sources(self.project, [workbook, csv_path])
        self.assertEqual(result["schema_comparison"]["status"], "consistent")
        self.assertEqual([item["kind"] for item in result["schema_comparison"]["comparisons"]], ["xlsx", "csv"])

    def test_cross_source_drift_lists_missing_added_order_and_type_changes(self):
        workbook = make_xlsx(self.root / "Orders.xlsx", rows=[["Id", "Amount"], ["A", 10]])
        csv_path = self.root / "Orders.csv"
        csv_path.write_text("Amount,Region\nten,South\n", encoding="utf-8", newline="")
        result = import_sources(self.project, [workbook, csv_path])
        drift = result["schema_comparison"]["comparisons"][1]
        self.assertEqual(result["schema_comparison"]["status"], "schema_drift")
        self.assertEqual(drift["missing_columns"], ["Id"])
        self.assertEqual(drift["added_columns"], ["Region"])
        self.assertIn("Amount", drift["type_changes"])

    def test_wide_xlsx_row_blocks_workflow_and_remains_visible(self):
        workbook = make_xlsx(self.root / "Wide.xlsx", rows=[["A", "B"], [1, 2, 3]])
        result = import_sources(self.project, [workbook])
        self.assertEqual(result["state"], "needs_input_fix")
        self.assertEqual(result["errors"][0]["code"], "XLSX_READING_NEEDS_CONFIRMATION")
        self.assertEqual(result["workbooks"][0]["sheets"][0]["row_errors"][0]["actual_columns"], 3)


if __name__ == "__main__":
    unittest.main()
