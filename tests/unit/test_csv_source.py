from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.csv_source import profile_csv
from pbip_assistant.errors import InputError


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "source"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CsvSourceTests(unittest.TestCase):
    def test_profiles_baseline_without_changing_source(self) -> None:
        path = FIXTURES / "orders_synthetic.csv"
        before = digest(path)
        result = profile_csv(path)
        self.assertEqual(result["encoding"], "utf-8")
        self.assertEqual(result["delimiter"], ",")
        self.assertEqual(result["row_count"], 6)
        self.assertEqual(result["valid_row_count"], 6)
        self.assertEqual(len(result["columns"]), 17)
        self.assertTrue(result["mapping_ready"])
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["source_sha256"], before)
        self.assertEqual(digest(path), before)
        quantity = next(column for column in result["columns"] if column["name"] == "Quantity")
        self.assertEqual(quantity["data_types"], {"integer": 6})
        city = next(column for column in result["columns"] if column["name"] == "City")
        self.assertEqual(city["null_count"], 1)
        order_id = next(column for column in result["columns"] if column["name"] == "OrderID")
        self.assertEqual(len(order_id["sample"]), 5)
        self.assertEqual(len(order_id["sample"]), len(set(order_id["sample"])))

    def test_detects_bom_semicolon_and_quoted_multiline(self) -> None:
        bom = profile_csv(FIXTURES / "orders_utf8_bom.csv")
        self.assertEqual(bom["encoding"], "utf-8-sig")
        self.assertEqual(bom["columns"][0]["name"], "OrderID")
        semi = profile_csv(FIXTURES / "orders_semicolon.csv")
        self.assertEqual(semi["delimiter"], ";")
        multiline = profile_csv(FIXTURES / "orders_quoted_multiline.csv")
        self.assertEqual(multiline["row_count"], 2)
        self.assertEqual(multiline["invalid_row_count"], 0)

    def test_reports_short_and_wide_rows_without_dropping_their_count(self) -> None:
        for filename, actual in (("orders_short_row.csv", 16), ("orders_wide_row.csv", 18)):
            with self.subTest(filename=filename):
                result = profile_csv(FIXTURES / filename)
                self.assertEqual(result["row_count"], 1)
                self.assertEqual(result["valid_row_count"], 0)
                self.assertEqual(result["invalid_row_count"], 1)
                self.assertFalse(result["mapping_ready"])
                self.assertEqual(result["row_errors"][0]["record_number"], 2)
                self.assertEqual(result["row_errors"][0]["actual_columns"], actual)
                self.assertEqual(result["row_errors"][0]["expected_columns"], 17)

    def test_invalid_encoding_and_duplicate_header_are_blocking(self) -> None:
        with self.assertRaises(InputError) as encoding_error:
            profile_csv(FIXTURES / "orders_invalid_utf8.csv")
        self.assertEqual(encoding_error.exception.code, "CSV_ENCODING")
        with self.assertRaises(InputError) as header_error:
            profile_csv(FIXTURES / "orders_duplicate_header.csv")
        self.assertEqual(header_error.exception.code, "CSV_DUPLICATE_HEADER")

    def test_ambiguous_delimiter_blocks_auto_mapping_but_explicit_choice_works(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous.csv"
            path.write_text("A,B;C\n1,2;3\n", encoding="utf-8", newline="")
            with self.assertRaises(InputError) as caught:
                profile_csv(path)
            self.assertEqual(caught.exception.code, "CSV_AMBIGUOUS_DELIMITER")
            selected = profile_csv(path, delimiter=",")
            self.assertEqual(selected["delimiter"], ",")
            self.assertTrue(selected["mapping_ready"])

    def test_consistent_competing_delimiters_are_not_guessed_by_column_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous.csv"
            path.write_text("A,B;C;D\nx,y;z;w\n", encoding="utf-8", newline="")
            with self.assertRaises(InputError) as caught:
                profile_csv(path)
            self.assertEqual(caught.exception.code, "CSV_AMBIGUOUS_DELIMITER")
            selected = profile_csv(path, delimiter=";")
            self.assertEqual([column["name"] for column in selected["columns"]], ["A,B", "C", "D"])

    def test_header_selection_uses_logical_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preamble.csv"
            path.write_text("Generated report\nName,Amount\nAlpha,10\n", encoding="utf-8", newline="")
            result = profile_csv(path, delimiter=",", header_row=2)
            self.assertEqual(result["header_row"], 2)
            self.assertEqual(result["row_count"], 1)
            self.assertEqual([column["name"] for column in result["columns"]], ["Name", "Amount"])

    def test_formula_like_values_stay_text_and_are_only_warned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "formula.csv"
            path.write_text("Name,Value\nSafe,-10\nRisk,=2+2\nAt,@SUM(A1)\n", encoding="utf-8", newline="")
            result = profile_csv(path)
            value = result["columns"][1]
            self.assertEqual(value["formula_like_count"], 2)
            self.assertEqual(value["data_types"], {"integer": 1, "formula_like_text": 2})
            self.assertEqual(value["sample"], ["-10", "=2+2", "@SUM(A1)"])
            self.assertIn("remain inert CSV text", result["issues"][0])

    def test_limits_are_explicit_and_header_only_is_valid(self) -> None:
        header_only = profile_csv(FIXTURES / "orders_header_only.csv")
        self.assertEqual(header_only["row_count"], 0)
        self.assertTrue(header_only["mapping_ready"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.csv"
            path.write_bytes(b"A,B\n1,2\n")
            with patch("pbip_assistant.csv_source.MAX_BYTES", 4):
                with self.assertRaises(InputError) as caught:
                    profile_csv(path)
            self.assertEqual(caught.exception.code, "CSV_LIMIT")
            header = Path(directory) / "header.csv"
            header.write_text(f"{'A' * 11},B\n1,2\n", encoding="utf-8")
            with patch("pbip_assistant.csv_source.MAX_CELL_CHARS", 10):
                with self.assertRaises(InputError) as caught:
                    profile_csv(header)
            self.assertEqual(caught.exception.code, "CSV_LIMIT")


if __name__ == "__main__":
    unittest.main()
