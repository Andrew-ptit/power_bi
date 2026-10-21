from __future__ import annotations

from pathlib import Path
import base64
import shutil
import tempfile
import unittest
from importlib.util import find_spec

from pbip_assistant.excel_connector import PowerShellExcelRunner
from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore, _static_values_payload
from pbip_assistant.pq_typed import TypedPlanStore
from pbip_assistant.xlsx import profile_workbook
from tests.support.excel_plan import office_snapshot
from tests.support.pq_typed import CatalogTypedPlanner, FakeTypedPlanner


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "excel" / "excel_mcp_sales_input.xlsx"
HELPER = ROOT / "tools" / "excel_connector" / "Invoke-PQCodeM.ps1"


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is unavailable")
class PowerQueryRuntimeSmoke(unittest.TestCase):
    def test_typed_compiler_runtime_matches_independent_expected_rows(self) -> None:
        """Cross-check lineage/compiler output against actual Excel Power Query."""
        with tempfile.TemporaryDirectory(prefix="pq-typed-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            shutil.copyfile(FIXTURE, target)
            preview_store = PQPreviewStore(PowerShellExcelRunner(HELPER, timeout_seconds=90))
            self.addCleanup(preview_store.close)
            store = TypedPlanStore(FakeTypedPlanner(), preview_store)
            self.addCleanup(store.close)
            workbook = office_snapshot(target)
            plan = store.create_plan(
                "Filter Gross Revenue above 1000, add Profit and sort descending",
                workbook, {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
            )
            self.assertEqual(plan["planStatus"], "reviewReady", plan["hardBlockers"])
            preview = store.preview(
                plan["revision"]["revisionId"], workbook,
                base64.b64encode(target.read_bytes()).decode("ascii"),
            )
            self.assertEqual(preview["status"], "excelRuntimePreview")
            self.assertEqual(preview["resultRows"], 4)
            sale_index = preview["afterColumns"].index("SaleID")
            profit_index = preview["afterColumns"].index("Profit")
            # This expected result is calculated independently from the compiler
            # templates and therefore catches template/lineage disagreement.
            self.assertEqual(
                [(row[sale_index], row[profit_index]) for row in preview["afterRows"]],
                [("S-005", 2800), ("S-003", 2100), ("S-002", 1400), ("S-006", 1300)],
            )

    def test_typed_aggregate_append_and_merge_match_independent_expectations(self) -> None:
        """Exercise three distinct compiler branches in the real Excel runtime."""
        with tempfile.TemporaryDirectory(prefix="pq-typed-catalog-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            shutil.copyfile(FIXTURE, target)
            preview_store = PQPreviewStore(PowerShellExcelRunner(HELPER, timeout_seconds=90))
            self.addCleanup(preview_store.close)
            store = TypedPlanStore(CatalogTypedPlanner(), preview_store)
            self.addCleanup(store.close)
            workbook = office_snapshot(target)
            encoded = base64.b64encode(target.read_bytes()).decode("ascii")
            plan = store.create_plan("Cross-check aggregate, append and merge", workbook)
            self.assertEqual(plan["planStatus"], "reviewReady", plan["hardBlockers"])

            # The planner's initial final output is merge + expand.
            merged = store.preview(plan["revision"]["revisionId"], workbook, encoded)
            self.assertEqual(merged["resultRows"], 6)
            rate_index = merged["afterColumns"].index("CommissionRate")
            sale_index = merged["afterColumns"].index("SaleID")
            rates = {row[sale_index]: row[rate_index] for row in merged["afterRows"]}
            self.assertEqual(rates["S-001"], 0.07)
            self.assertTrue(all(rates[sale] is None for sale in rates if sale != "S-001"))

            aggregate_step = next(step for step in plan["steps"] if step["operation"]["type"] == "table.aggregateRows")
            aggregate_plan = store.create_revision({
                "baseRevisionId": plan["revision"]["revisionId"],
                "changeReason": "Runtime-check aggregate branch",
                "changes": [{"type": "setFinalOutput", "stepId": aggregate_step["stepId"]}],
            })
            aggregate = store.preview(aggregate_plan["revision"]["revisionId"], workbook, encoded)
            self.assertEqual(aggregate["resultRows"], 1)
            self.assertEqual(aggregate["afterRows"], [[6, 9850]])

            append_step = next(step for step in aggregate_plan["steps"] if step["operation"]["type"] == "table.appendTables")
            append_plan = store.create_revision({
                "baseRevisionId": aggregate_plan["revision"]["revisionId"],
                "changeReason": "Runtime-check append branch",
                "changes": [{"type": "setFinalOutput", "stepId": append_step["stepId"]}],
            })
            appended = store.preview(append_plan["revision"]["revisionId"], workbook, encoded)
            self.assertEqual(appended["resultRows"], 12)
            self.assertEqual(appended["afterRows"][0][0], "S-001")
            self.assertEqual(appended["afterRows"][6][0], "S-001")

    @unittest.skipUnless(find_spec("openpyxl"), "openpyxl is unavailable for fixture generation")
    def test_cleaning_m_keeps_error_rows_and_returns_static_values(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory(prefix="pq-errors-smoke-") as folder:
            target = Path(folder) / "input.xlsx"
            static_result = Path(folder) / "values.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Raw"
            for row in [
                ["Ma_Don_Hang", "Doanh_Thu"],
                ["ORD-1", 10],
                ["ORD-1", 10],
                [None, None],
                ["null", 20],
                ["ORD-2", "#DIV/0!"],
                ["ORD-3", None],
                ["ORD-4", "#REF!"],
                [None, "still has revenue"],
            ]:
                sheet.append(row)
            sheet["B6"].data_type = "e"
            sheet["B8"].data_type = "e"
            workbook.save(target)
            code = (ROOT / "examples" / "pq_clean_orders_with_errors.m").read_text(encoding="utf-8")
            result = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                "version": 1,
                "workbookPath": str(target),
                "resultWorkbookPath": str(static_result),
                "source": {"kind": "sheet", "sheet": "Raw", "headerRow": 1},
                "mCode": code,
            })
            self.assertEqual(result["resultRows"], 4)
            self.assertEqual([row[0] for row in result["rows"]], ["ORD-1", "ORD-2", "ORD-3", "ORD-4"])
            # Excel.CurrentWorkbook exposes these worksheet error cells as null in this runtime.
            self.assertIsNone(result["rows"][1][1])
            self.assertIsNone(result["rows"][3][1])
            self.assertTrue(_static_values_payload(static_result, 4, 2))

    def test_real_excel_reads_external_file_after_risk_ack_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pq-external-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            source = ROOT / "tests" / "fixtures" / "pq" / "external_sample.csv"
            shutil.copyfile(FIXTURE, target)
            escaped = str(source).replace('"', '""')
            code = (
                f'let Source = Csv.Document(File.Contents("{escaped}"), '
                '[Delimiter=",", Columns=2, Encoding=65001, QuoteStyle=QuoteStyle.None]), '
                'Headers = Table.PromoteHeaders(Source) in Headers'
            )
            result = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                "version": 1, "workbookPath": str(target),
                "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
                "mCode": code,
            })
            self.assertEqual(result["resultRows"], 2)
            self.assertEqual(result["columns"], ["id", "value"])
            self.assertEqual(result["rows"], [["E1", "8"], ["E2", "9"]])

    def test_real_excel_blocks_failed_m_refresh(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pq-error-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            shutil.copyfile(FIXTURE, target)
            with self.assertRaises(InputError) as error:
                PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                    "version": 1, "workbookPath": str(target),
                    "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
                    "mCode": 'let Source = error "fixture error" in Source',
                })
            self.assertIn(error.exception.code, {"PQ_REFRESH_FAILED", "PQ_RESULT_NOT_TABLE"})

    @unittest.skipUnless(find_spec("openpyxl"), "openpyxl is unavailable for fixture generation")
    def test_real_excel_cleans_used_range_without_a_table(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory(prefix="pq-usedrange-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Raw_Orders"
            for row in [
                ["Ma_Don_Hang", "Note"],
                [None, None],
                ["A1", "ok"],
                ["A1", "ok"],
                ["null", "bad"],
                ["A2", "ok"],
                ["A2", "different"],
                [" ", "bad"],
            ]:
                sheet.append(row)
            workbook.save(target)
            code = (
                'let Source = Excel.CurrentWorkbook(){[Name="PQ_Input"]}[Content], '
                'Valid = Table.SelectRows(Source, each if [Ma_Don_Hang] = null then false '
                'else let id = Text.Lower(Text.Trim(Text.From([Ma_Don_Hang]))) '
                'in id <> "" and id <> "null"), '
                'Unique = Table.Distinct(Valid) in Unique'
            )
            result = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                "version": 1,
                "workbookPath": str(target),
                "source": {"kind": "sheet", "sheet": "Raw_Orders", "headerRow": 1},
                "mCode": code,
            })
            self.assertEqual(result["resultRows"], 3)
            self.assertEqual(result["columns"], ["Ma_Don_Hang", "Note"])
            self.assertEqual([row[0] for row in result["rows"]], ["A1", "A2", "A2"])

    def test_real_excel_refreshes_query_on_a_temporary_copy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pq-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            static_result = Path(folder) / "values.xlsx"
            shutil.copyfile(FIXTURE, target)
            result = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                "version": 1,
                "workbookPath": str(target),
                "resultWorkbookPath": str(static_result),
                "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
                "mCode": (
                    'let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content], '
                    'Result = Table.FirstN(Source, 2) in Result'
                ),
            })
            self.assertEqual(result["resultRows"], 2)
            self.assertGreater(result["sourceRows"], 2)
            self.assertIn("SaleID", result["columns"])
            self.assertEqual(len(result["rows"]), 2)
            self.assertTrue(static_result.is_file())
            profile = profile_workbook(static_result, include_preview=True)
            self.assertEqual([sheet["name"] for sheet in profile["sheets"]], ["PQ_Result_Values"])
            self.assertEqual(profile["sheets"][0]["row_count"], 2)
            self.assertEqual(profile["sheets"][0]["formula_cache"]["cell_count"], 0)
            numeric = next(column for column in profile["sheets"][0]["columns"] if column["name"] == "Gross Revenue")
            self.assertEqual(numeric["data_types"], {"number": 2})

    def test_static_export_preserves_formula_looking_text_as_value(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pq-text-smoke-") as folder:
            target = Path(folder) / "preview.xlsx"
            static_result = Path(folder) / "values.xlsx"
            shutil.copyfile(FIXTURE, target)
            result = PowerShellExcelRunner(HELPER, timeout_seconds=90).apply({
                "version": 1,
                "workbookPath": str(target),
                "resultWorkbookPath": str(static_result),
                "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
                "mCode": 'let Result = #table({"Text"}, {{"=1+1"}}) in Result',
            })
            self.assertEqual(result["resultRows"], 1)
            profile = profile_workbook(static_result, include_preview=True)
            self.assertEqual(profile["sheets"][0]["formula_cache"]["cell_count"], 0)
            self.assertEqual(profile["sheets"][0]["preview"]["rows"][0][0], "=1+1")


if __name__ == "__main__":
    unittest.main()
