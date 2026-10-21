from __future__ import annotations
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pbip_assistant.codex_excel import analyze_workbook, find_codex_executable
from pbip_assistant.errors import InputError

from tests.support.codex_excel import (FakeCodex, workbook)

class CodexExcelAnalysisTests(unittest.TestCase):
    def test_codex_is_found_when_excel_process_path_omits_npm(self) -> None:
        with TemporaryDirectory() as folder:
            candidate = Path(folder) / "npm" / "codex.cmd"
            candidate.parent.mkdir()
            candidate.write_text("@echo off\n", encoding="utf-8")
            with patch("pbip_assistant.codex_excel.shutil.which", return_value=None):
                with patch.dict("os.environ", {"APPDATA": folder, "USERPROFILE": folder}):
                    self.assertEqual(find_codex_executable(), str(candidate))

    def test_standalone_codex_exe_is_found_without_terminal_path(self) -> None:
        with TemporaryDirectory() as folder:
            candidate = Path(folder) / ".vscode" / "extensions" / "openai.chatgpt-test" / "bin" / "windows-x86_64" / "codex.exe"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"test")
            with patch("pbip_assistant.codex_excel.shutil.which", return_value=None):
                with patch.dict("os.environ", {"APPDATA": folder, "USERPROFILE": folder}):
                    self.assertEqual(find_codex_executable(), str(candidate))

    def test_no_table_and_remote_workbook_can_be_analyzed_read_only(self) -> None:
        runner = FakeCodex()
        result = analyze_workbook("Tách cột B sang D", workbook(), runner)
        self.assertEqual(result["status"], "analysis_only")
        self.assertFalse(result["canApply"])
        self.assertEqual(result["operations"][0]["targetSheet"], "Raw_Orders")
        self.assertEqual(result["preview"]["beforeRows"][0][1], "SPENTA-123")
        self.assertTrue(result["preview"]["afterUnavailable"])
        self.assertNotIn("url", runner.payload["workbook"])
        self.assertNotIn("tenant.sharepoint.com", str(runner.payload))
        self.assertEqual(runner.payload["formulaListSeparator"], ";")
        self.assertEqual(result["formulaListSeparator"], ";")
        self.assertEqual(result["codeBlocks"][0]["language"], "m")
        self.assertIn("let Source", result["codeBlocks"][0]["code"])
        self.assertNotIn("let Source", " ".join(result["warnings"]))

    def test_invalid_code_block_is_rejected(self) -> None:
        runner = FakeCodex()
        runner.response["codeBlocks"][0]["code"] = " "
        with self.assertRaises(InputError) as error:
            analyze_workbook("Làm sạch", workbook(), runner)
        self.assertEqual(error.exception.code, "CODEX_RESPONSE_INVALID")

    def test_formula_separator_is_part_of_revision_and_rejects_unknown_value(self) -> None:
        semicolon = analyze_workbook("Tách cột B sang D", workbook(), FakeCodex(), ";")
        comma_runner = FakeCodex()
        comma = analyze_workbook("Tách cột B sang D", workbook(), comma_runner, ",")
        self.assertEqual(comma_runner.payload["formulaListSeparator"], ",")
        self.assertNotEqual(semicolon["planRevisionId"], comma["planRevisionId"])
        with self.assertRaises(InputError) as error:
            analyze_workbook("Tách cột B sang D", workbook(), FakeCodex(), "|")
        self.assertEqual(error.exception.code, "INVALID_FORMULA_SEPARATOR")

    def test_missing_business_rule_becomes_question_not_approval(self) -> None:
        runner = FakeCodex({
            "summary": "Chưa rõ quy tắc tách.", "questions": ["Nếu có nhiều dấu '-' thì chọn phần nào?"],
            "assumptions": [], "warnings": [], "operations": [],
        })
        result = analyze_workbook("Tách mã", workbook(), runner)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertFalse(result["canApply"])

    def test_hallucinated_sheet_and_missing_prompt_are_rejected(self) -> None:
        bad = FakeCodex()
        bad.response["operations"][0]["targetSheet"] = "Invented"
        with self.assertRaises(InputError) as error:
            analyze_workbook("Tách mã", workbook(), bad)
        self.assertEqual(error.exception.code, "CODEX_RESPONSE_INVALID")
        with self.assertRaises(InputError) as error:
            analyze_workbook(" ", workbook(), FakeCodex())
        self.assertEqual(error.exception.code, "PROMPT_REQUIRED")

    def test_bounded_snapshot_rejects_excess_rows(self) -> None:
        sample = workbook()
        sample["sheets"][0]["rows"] = [[None, None, None]] * 21
        with self.assertRaises(InputError) as error:
            analyze_workbook("Tách mã", sample, FakeCodex())
        self.assertEqual(error.exception.code, "INVALID_WORKBOOK")


if __name__ == "__main__":
    unittest.main()
