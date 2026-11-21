"""Hand-derived cleanup results, including formula and locale boundaries."""
import unittest

from pbip_assistant.errors import InputError


class PreparationCleaningTests(unittest.TestCase):
    def setUp(self):
        try:
            from pbip_assistant.sources.preparation import cleaning
            from pbip_assistant.sources.preparation.model import SourceSnapshot, AnswerRevision
        except ImportError:
            self.fail("Local preparation cleaning engine is unavailable")
        self.cleaning, self.snapshot, self.answers = cleaning, SourceSnapshot, AnswerRevision

    def scan(self, headers, rows, **options):
        source = self.snapshot("source_01", "{sheet_01}", tuple(headers), tuple(tuple(r) for r in rows), **options)
        return self.cleaning.scan_sources(self.cleaning.bind_sources([source]), [source])

    def answer_all(self, scan, choice):
        return self.answers(1, {q["questionId"]: {"choice": choice, "reason": None} for q in scan.questions})

    def test_ascii_edge_trim_preserves_internal_whitespace_ids_and_formula_cells(self):
        scan = self.scan(["Code", "Description", "Calculated"], [[" 00123 ", "A  B ", " formula result "]],
                         formula_cells=frozenset({(0, 2)}), column_kinds=("identifier", "text", "text"))
        preview = self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "keep_text"))
        self.assertEqual([(c["row"], c["column"], c["before"], c["after"]) for c in preview.changes],
                         [(0, 0, " 00123 ", "00123"), (0, 1, "A  B ", "A  B")])
        self.assertEqual(len(scan.sources[0].rows[0]), 3)
        self.assertEqual(scan.sources[0].rows[0][0], " 00123 ")

    def test_ambiguous_date_stays_pending_until_explicit_dmy_or_mdy(self):
        scan = self.scan(["Date"], [["03/04/2026"]])
        with self.assertRaises(InputError) as caught:
            self.cleaning.build_cleanup_preview(scan, self.answers(0, {}))
        self.assertEqual(caught.exception.code, "DP_AMBIGUOUS_FORMAT")
        dmy = self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "DMY"))
        mdy = self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "MDY"))
        self.assertEqual(dmy.changes[0]["after"], 46115)
        self.assertEqual(mdy.changes[0]["after"], 46085)
        self.assertEqual(dmy.changes[0]["numberFormat"], "yyyy-mm-dd")
        self.assertNotEqual(dmy.review_hash, mdy.review_hash)

    def test_number_formats_are_explicit_and_invalid_grouping_is_not_guessed(self):
        scan = self.scan(["Amount"], [["1.234,50"]])
        preview = self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "decimal_comma"))
        self.assertEqual(preview.changes[0]["after"], 1234.5)
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "decimal_dot"))
        scan = self.scan(["Amount"], [["1,2,3"]])
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "decimal_dot"))

    def test_invalid_date_requires_fix_or_explicit_keep_text(self):
        scan = self.scan(["Date"], [["31/02/2026"]])
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "DMY"))
        preview = self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "keep_text"))
        self.assertEqual(preview.changes, ())

    def test_dates_respect_1904_system_and_excel_leap_bug(self):
        scan = self.scan(["Date"], [["01/01/1904"]], date_system="1904")
        self.assertEqual(self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "DMY")).changes[0]["after"], 0)
        scan = self.scan(["Date"], [["01/01/1900"]])
        self.assertEqual(self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "DMY")).changes[0]["after"], 1)
        scan = self.scan(["Date"], [["29/02/1900"]])
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "DMY"))

    def test_missing_duplicates_and_formula_errors_are_only_findings(self):
        scan = self.scan(["Code", "Computed"], [["A", "#DIV/0!"], ["A", None], ["A", None]],
                         formula_cells=frozenset({(0, 1)}), column_kinds=("text", "text"))
        kinds = {f["kind"] for f in scan.findings}
        self.assertTrue({"missing", "duplicate_row", "formula_error"} <= kinds)
        self.assertEqual(self.cleaning.build_cleanup_preview(scan, self.answers(0, {})).changes, ())

    def test_precision_loss_and_unknown_answers_block_conversion(self):
        scan = self.scan(["Amount"], [["1234567890123456"]])
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "decimal_dot"))
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answers(1, {"invented": {"choice": "DMY", "reason": None}}))

    def test_examples_bounded_and_counts_from_full_scan(self):
        scan = self.scan(["Text"], [[" x "] for _ in range(30)], column_kinds=("text",))
        finding = next(f for f in scan.findings if f["kind"] == "trim")
        self.assertEqual(finding["count"], 30)
        self.assertEqual(finding["coverage"], "full")
        self.assertLessEqual(sum(len(f["examples"]) for f in scan.findings), 20)
        self.assertEqual(len(self.cleaning.build_cleanup_preview(scan, self.answers(0, {})).changes), 30)

    def test_preview_examples_truncate_display_without_truncating_actual_diff(self):
        scan = self.scan(["Text"], [[" " + "x" * 300 + " "]], column_kinds=("text",))
        preview = self.cleaning.build_cleanup_preview(scan, self.answers(0, {}))
        self.assertEqual(len(preview.changes[0]["after"]), 300)
        self.assertLessEqual(len(preview.public()["examples"][0]["after"]), 256)
        self.assertTrue(preview.public()["examples"][0]["displayTruncated"])

    def test_numeric_underflow_is_not_silently_converted_to_zero(self):
        scan = self.scan(["Amount"], [["0." + "0" * 400 + "1"]])
        with self.assertRaises(InputError):
            self.cleaning.build_cleanup_preview(scan, self.answer_all(scan, "decimal_dot"))

    def test_review_diff_uses_actual_used_range_origin(self):
        scan = self.scan(["Text"], [[" x "]], column_kinds=("text",), row_offset=5, column_offset=2)
        preview = self.cleaning.build_cleanup_preview(scan, self.answers(0, {}))
        self.assertEqual(preview.changes[0]["address"], "C6")


if __name__ == "__main__":
    unittest.main()
