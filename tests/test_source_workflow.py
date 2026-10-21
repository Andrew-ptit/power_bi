from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pbip_assistant.csv_source import profile_csv
from pbip_assistant.errors import InputError
from pbip_assistant.source_workflow import profile_sources_only
from pbip_assistant.xlsx import profile_workbook
from tests.fixtures import make_xlsx


FIXTURES = Path(__file__).parent / "fixtures_source"


class SourceOnlyWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_profiles_xlsx_and_csv_without_pbip(self) -> None:
        excel = make_xlsx(
            self.root / "Sales.xlsx",
            rows=[["OrderID", "Amount"], ["A-1", 10], ["A-2", 20]],
        )
        csv_path = self.root / "More.csv"
        csv_path.write_text("OrderID,Amount\nA-3,30\n", encoding="utf-8")

        result = profile_sources_only(
            [excel, csv_path],
            include_preview=True,
            preview_limit=10,
        )

        self.assertEqual(result["state"], "profile_ready")
        self.assertEqual(result["summary"]["file_count"], 2)
        self.assertEqual(result["summary"]["row_count"], 3)
        self.assertTrue(result["summary"]["mapping_ready"])
        self.assertEqual(
            result["workbooks"][0]["sheets"][0]["preview"]["rows"][0],
            ["A-1", 10],
        )
        self.assertEqual(
            result["csv_files"][0]["preview"]["rows"][0],
            ["A-3", "30"],
        )
        self.assertEqual(result["validation"]["pbip"], "not_run")

    def test_preview_is_opt_in_and_bounded(self) -> None:
        csv_path = FIXTURES / "orders_synthetic.csv"
        self.assertNotIn("preview", profile_csv(csv_path))
        preview = profile_csv(csv_path, include_preview=True, preview_limit=2)["preview"]
        self.assertEqual(len(preview["rows"]), 2)
        self.assertTrue(preview["truncated"])

        excel = make_xlsx(self.root / "Sales.xlsx")
        self.assertNotIn("preview", profile_workbook(excel)["sheets"][0])
        self.assertIn(
            "preview",
            profile_workbook(excel, include_preview=True)["sheets"][0],
        )
        with self.assertRaises(InputError) as caught:
            profile_workbook(excel, include_preview=True, preview_limit=51)
        self.assertEqual(caught.exception.code, "PREVIEW_LIMIT")

    def test_blocking_csv_error_keeps_partial_profile(self) -> None:
        result = profile_sources_only(
            [FIXTURES / "orders_short_row.csv"],
            include_preview=True,
        )
        self.assertEqual(result["state"], "needs_input_fix")
        self.assertFalse(result["summary"]["mapping_ready"])
        self.assertEqual(
            result["errors"][0]["code"],
            "CSV_READING_NEEDS_CONFIRMATION",
        )
        self.assertEqual(result["csv_files"][0]["invalid_row_count"], 1)

    def test_ambiguous_csv_can_be_retried_with_explicit_delimiter(self) -> None:
        path = self.root / "Ambiguous.csv"
        path.write_text("A,B;C\n1,2;3\n", encoding="utf-8")
        blocked = profile_sources_only([path])
        self.assertEqual(
            blocked["errors"][0]["code"],
            "CSV_AMBIGUOUS_DELIMITER",
        )

        ready = profile_sources_only(
            [path],
            source_options={str(path): {"delimiter": ","}},
        )
        self.assertEqual(ready["state"], "profile_ready")


if __name__ == "__main__":
    unittest.main()
