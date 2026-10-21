import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pbip_assistant.workflow import import_sources
from pbip_assistant.pbip import inventory_pbip
from pbip_assistant.xlsx import profile_workbook
from tests.fixtures import make_pbip, make_xlsx


class ImportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_import_moves_to_proposal_and_keeps_insight_as_hypothesis(self):
        project = make_pbip(self.root / "Retail")
        excel = make_xlsx(self.root / "Sales.xlsx")
        model_file = project / "Retail.SemanticModel" / "definition" / "model.tmdl"
        model_before = model_file.read_bytes()
        excel_before = excel.read_bytes()
        result = import_sources(project, [excel], "Doanh thu miền Nam giảm?")
        self.assertEqual(result["state"], "imported_needs_proposal")
        self.assertEqual(result["bpmn_next"], "N-006")
        self.assertEqual(result["insight"]["status"], "hypothesis")
        self.assertEqual(result["validation"]["desktop"], "not_run")
        self.assertEqual(model_file.read_bytes(), model_before)
        self.assertEqual(excel.read_bytes(), excel_before)

    def test_bad_excel_is_reported_separately_and_blocks_progress(self):
        project = make_pbip(self.root / "Retail")
        good = make_xlsx(self.root / "Sales.xlsx")
        bad = self.root / "Bad.xlsx"
        bad.write_bytes(b"broken")
        result = import_sources(project, [good, bad])
        self.assertEqual(result["state"], "needs_input_fix")
        self.assertEqual(result["bpmn_end"], "N-005")
        self.assertEqual(len(result["workbooks"]), 1)
        self.assertEqual(result["errors"][0]["code"], "INVALID_XLSX")
        self.assertNotIn("snapshot", result)

    def test_no_source_blocks_import(self):
        result = import_sources(self.root, [])
        self.assertEqual(result["errors"][0]["code"], "NO_SOURCES")

    def test_csv_and_xlsx_are_profiled_separately_in_one_snapshot(self):
        project = make_pbip(self.root / "Retail")
        excel = make_xlsx(self.root / "Sales.xlsx")
        csv_path = Path(__file__).parent / "fixtures_source" / "orders_synthetic.csv"
        result = import_sources(project, [excel, csv_path])
        self.assertEqual(result["state"], "imported_needs_proposal")
        self.assertEqual(len(result["workbooks"]), 1)
        self.assertEqual(len(result["csv_files"]), 1)
        self.assertEqual(result["csv_files"][0]["row_count"], 6)
        self.assertEqual(len(result["snapshot"]["source_files"]), 2)

    def test_csv_row_errors_block_mapping_but_keep_profile(self):
        project = make_pbip(self.root / "Retail")
        csv_path = Path(__file__).parent / "fixtures_source" / "orders_short_row.csv"
        result = import_sources(project, [csv_path])
        self.assertEqual(result["state"], "needs_input_fix")
        self.assertEqual(result["errors"][0]["code"], "CSV_READING_NEEDS_CONFIRMATION")
        self.assertEqual(result["csv_files"][0]["invalid_row_count"], 1)
        self.assertNotIn("snapshot", result)

    def test_source_change_during_import_blocks_snapshot(self):
        project = make_pbip(self.root / "Retail")
        excel = make_xlsx(self.root / "Sales.xlsx")

        def changed_after_profile(path):
            result = profile_workbook(path)
            excel.write_bytes(excel.read_bytes() + b"changed")
            return result

        with patch("pbip_assistant.workflow.profile_workbook", side_effect=changed_after_profile):
            result = import_sources(project, [excel])
        self.assertEqual(result["state"], "needs_input_fix")
        self.assertEqual(result["errors"][0]["code"], "SOURCE_CHANGED")

    def test_pbip_change_after_snapshot_is_detected(self):
        project = make_pbip(self.root / "Retail")
        excel = make_xlsx(self.root / "Sales.xlsx")
        model_file = project / "Retail.SemanticModel" / "definition" / "model.tmdl"

        def mutate_after_snapshot(path):
            result = inventory_pbip(path)
            model_file.write_text(model_file.read_text(encoding="utf-8") + "\n// changed", encoding="utf-8")
            return result

        with patch("pbip_assistant.workflow.inventory_pbip", side_effect=mutate_after_snapshot):
            result = import_sources(project, [excel])
        self.assertEqual(result["state"], "needs_input_fix")
        self.assertEqual(result["errors"][0]["code"], "SOURCE_CHANGED")


if __name__ == "__main__":
    unittest.main()
