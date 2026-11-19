"""Unit tests cho csv_typing — feature 003, T302.

Mỗi test khoá một luật của spec §6; kỳ vọng lấy từ oracle viết tay độc lập.
"""

import unittest

from pbip_assistant.sources.preparation.csv_typing import (
    build_typed_frame,
    describe_columns,
)
from tests.support import csv_typing_oracle as oracle


def frame(headers, rows, date_system=1900):
    return build_typed_frame(headers, rows, date_system=date_system)


class NumberRulesTest(unittest.TestCase):
    def test_plain_integers_and_decimals_become_numbers(self):
        result = frame(["n"], [["1"], ["2.5"], ["-3"]])
        self.assertEqual(oracle.column(result, 0), [1, 2.5, -3])
        self.assertEqual(oracle.formats(result, 0), [oracle.NUMBER] * 3)
        self.assertEqual(result["values"][0], ["n"])

    def test_group_separator_comma_is_integer(self):
        result = frame(["n"], [["1,234"]])
        self.assertEqual(oracle.column(result, 0), [1234])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.GROUP_SEPARATOR)

    def test_group_separator_dot_is_integer_when_all_three_digit_groups(self):
        result = frame(["n"], [["1.234"], ["12.345.678"]])
        self.assertEqual(oracle.column(result, 0), [1234, 12345678])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.GROUP_SEPARATOR)

    def test_decimal_comma_column(self):
        result = frame(["n"], [["1,5"], ["2,25"]])
        self.assertEqual(oracle.column(result, 0), [1.5, 2.25])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.DECIMAL_COMMA)

    def test_single_dot_in_each_grouped_value(self):
        result = frame(["n"], [["1.234"], ["2.345"]])
        self.assertEqual(oracle.column(result, 0), [1234, 2345])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.GROUP_SEPARATOR)

    def test_negative_localized_numbers(self):
        for raw, expected, reason in (
            ("-1,234", -1234, oracle.GROUP_SEPARATOR),
            ("-12.345.678", -12345678, oracle.GROUP_SEPARATOR),
            ("-1,25", -1.25, oracle.DECIMAL_COMMA),
        ):
            with self.subTest(raw=raw):
                result = frame(["n"], [[raw]])
                self.assertEqual(oracle.column(result, 0), [expected])
                self.assertEqual(oracle.reason_of(result, "n"), reason)

    def test_group_separator_with_ungrouped_integer_rows(self):
        for grouped in ("1,234", "1.234"):
            with self.subTest(grouped=grouped):
                result = frame(["qty"], [[grouped], ["12"]])
                self.assertEqual(oracle.column(result, 0), [1234, 12])
                self.assertEqual(oracle.reason_of(result, "qty"), oracle.GROUP_SEPARATOR)

    def test_plain_integers_keep_default_number_reason(self):
        result = frame(["n"], [["1234"], ["12"]])
        self.assertEqual(oracle.column(result, 0), [1234, 12])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.DECIMAL_DOT)

    def test_grouped_integer_part_and_decimal_part(self):
        result = frame(["n"], [["1,234.567"]])
        self.assertEqual(oracle.column(result, 0), [1234.567])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.DECIMAL_DOT)

    def test_leading_zero_stays_text(self):
        result = frame(["code"], [["00123"], ["00456"]])
        self.assertEqual(oracle.column(result, 0), ["00123", "00456"])
        self.assertEqual(oracle.formats(result, 0), [oracle.TEXT] * 2)
        self.assertEqual(oracle.reason_of(result, "code"), oracle.LEADING_ZERO_TEXT)

    def test_precision_over_15_digits_stays_text(self):
        result = frame(["n"], [["1234567890123456"]])
        self.assertEqual(oracle.column(result, 0), ["1234567890123456"])
        self.assertEqual(oracle.reason_of(result, "n"), oracle.PRECISION_TEXT)


class DateRulesTest(unittest.TestCase):
    def test_dates_dmy_detected_by_day_gt_12(self):
        result = frame(["d"], [["25/12/2024"], ["01/02/2024"]])
        self.assertEqual(oracle.column(result, 0),
                         [oracle.serial(2024, 12, 25, 1900), oracle.serial(2024, 2, 1, 1900)])
        self.assertEqual(oracle.formats(result, 0), [oracle.DATE] * 2)
        self.assertEqual(oracle.reason_of(result, "d"), oracle.DATE_ORDER_DETECTED)

    def test_dates_mdy_detected_by_month_gt_12(self):
        result = frame(["d"], [["12/25/2024"], ["02/01/2024"]])
        self.assertEqual(oracle.column(result, 0),
                         [oracle.serial(2024, 12, 25, 1900), oracle.serial(2024, 2, 1, 1900)])
        self.assertEqual(oracle.reason_of(result, "d"), oracle.DATE_ORDER_DETECTED)

    def test_dates_ambiguous_default_dmy_with_reason(self):
        result = frame(["d"], [["01/02/2024"]])
        self.assertEqual(oracle.column(result, 0), [oracle.serial(2024, 2, 1, 1900)])
        self.assertEqual(oracle.reason_of(result, "d"), oracle.DATE_DMY_DEFAULT)

    def test_invalid_date_column_stays_text(self):
        result = frame(["d"], [["31/02/2024"]])
        self.assertEqual(oracle.column(result, 0), ["31/02/2024"])
        self.assertEqual(oracle.formats(result, 0), [oracle.TEXT])
        self.assertEqual(oracle.reason_of(result, "d"), oracle.INVALID_DATE_TEXT)

    def test_two_digit_year_is_unsupported(self):
        result = frame(["d"], [["01/02/24"]])
        self.assertEqual(oracle.reason_of(result, "d"), oracle.DATE_UNSUPPORTED_TEXT)

    def test_1900_and_1904_serials(self):
        a = frame(["d"], [["01/01/2024"]], date_system="1900")
        b = frame(["d"], [["01/01/2024"]], date_system="1904")
        self.assertEqual(a["values"][1][0] - b["values"][1][0], 1462)


class TextRulesTest(unittest.TestCase):
    def test_minus_expression_keeps_whole_column_as_text(self):
        result = frame(["f"], [["-2,25"], ["-2+1"]])
        self.assertEqual(oracle.column(result, 0), ["-2,25", "-2+1"])
        self.assertEqual(oracle.formats(result, 0), [oracle.TEXT] * 2)
        self.assertEqual(oracle.reason_of(result, "f"), oracle.FORMULA_LIKE_TEXT)

    def test_formula_like_never_numeric(self):
        result = frame(["f"], [["=1+1"], ["+A1"], ["@x"]])
        self.assertEqual(oracle.column(result, 0), ["=1+1", "+A1", "@x"])
        self.assertEqual(oracle.formats(result, 0), [oracle.TEXT] * 3)
        self.assertEqual(oracle.reason_of(result, "f"), oracle.FORMULA_LIKE_TEXT)

    def test_mixed_column_stays_text_with_exception(self):
        result = frame(["m"], [["1"], ["abc"], ["2024-01-01"]])
        self.assertEqual(oracle.column(result, 0), ["1", "abc", "2024-01-01"])
        self.assertEqual(oracle.reason_of(result, "m"), oracle.MIXED_TYPE_TEXT)

    def test_empty_cells_and_empty_column(self):
        result = frame(["a", "b"], [["", "1"], ["", "2"]])
        self.assertEqual(oracle.column(result, 0), ["", ""])
        self.assertEqual(oracle.formats(result, 0), [oracle.TEXT, oracle.TEXT])
        self.assertEqual(oracle.reason_of(result, "a"), oracle.EMPTY_COLUMN)
        self.assertEqual(oracle.column(result, 1), [1, 2])


class ShapeAndBoundsTest(unittest.TestCase):
    def test_header_row_is_always_text(self):
        result = frame(["1", "2.5"], [["x", "1"]])
        self.assertEqual(result["numberFormats"][0], [oracle.TEXT, oracle.TEXT])
        self.assertEqual(result["values"][0], ["1", "2.5"])

    def test_deterministic_twice_identical(self):
        first = frame(["n", "d"], [["1,234", "01/02/2024"]])
        second = frame(["n", "d"], [["1,234", "01/02/2024"]])
        self.assertEqual(first, second)

    def test_report_bounds(self):
        headers = [f"c{index}" for index in range(250)]
        row = [str(index + 1) for index in range(250)]
        result = frame(headers, [row])
        self.assertLessEqual(len(result["decisions"]), oracle.MAX_DECISIONS)
        for decision in result["decisions"]:
            self.assertLessEqual(len(decision["samples"]), oracle.MAX_SAMPLES)
            for sample in decision["samples"]:
                self.assertLessEqual(len(sample), oracle.MAX_SAMPLE_CHARS)

    def test_describe_columns_counts_kinds(self):
        info = describe_columns(["n", "d", "t"], [["1", "01/02/2024", "x"]])
        self.assertEqual(info["columnCount"], 3)
        self.assertEqual(info["kinds"], {"number": 1, "date": 1, "text": 1})


if __name__ == "__main__":
    unittest.main()
