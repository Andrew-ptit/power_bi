from __future__ import annotations

from datetime import date
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.step_diagnostic_sampler import (
    MAX_SAMPLE_ROWS,
    SAMPLER_POLICY_VERSION,
    SourceProfileCache,
    build_source_sample,
)


class StepDiagnosticSamplerTests(unittest.TestCase):
    def rows(self) -> list[list[object]]:
        rows: list[list[object]] = [[f"normal-{index}", index, date(2026, 1, 1)] for index in range(60)]
        rows[22][0] = None
        rows[31][0] = "x" * 180
        rows[38][0] = "control\u0001value"
        rows[44][1] = -10000
        rows[52][1] = 999999
        rows[40][2] = date(1990, 1, 1)
        rows[55][2] = date(2099, 12, 31)
        return rows

    def sample(self, rows=None, **kwargs):
        return build_source_sample(
            self.rows() if rows is None else rows,
            source_id="src_sales",
            source_data_fingerprint="sha256:" + "1" * 64,
            column_names=["Text", "Amount", "When"] if rows is None else kwargs.pop("column_names", None),
            column_types=["text", "number", "date"] if rows is None else kwargs.pop("column_types", None),
            **kwargs,
        )

    def test_sample_is_bounded_repeatable_and_includes_hard_cases(self) -> None:
        first = self.sample(selected_column_indices=[0, 1, 2])
        second = self.sample(selected_column_indices=[0, 1, 2])
        self.assertEqual(first, second)
        self.assertEqual(first["samplerPolicyVersion"], SAMPLER_POLICY_VERSION)
        self.assertLessEqual(len(first["sampleRows"]), MAX_SAMPLE_ROWS)
        self.assertEqual(first["columnCount"], 3)
        ordinals = {row["ordinal"] for row in first["sampleRows"]}
        self.assertTrue({1, 2, 30, 31, 59, 60}.issubset(ordinals))
        self.assertTrue({23, 32, 39}.issubset(ordinals))
        for reason in ("blank", "longText", "unusualText", "numericExtreme", "dateExtreme"):
            self.assertEqual(first["coverage"][reason], "selected")
        self.assertTrue(all(row["reasonCodes"] for row in first["sampleRows"]))

    def test_seed_changes_with_source_identity_fingerprint_or_policy(self) -> None:
        first = self.sample()
        changed_source = build_source_sample(
            self.rows(), source_id="src_other",
            source_data_fingerprint="sha256:" + "1" * 64,
        )
        changed_fingerprint = build_source_sample(
            self.rows(), source_id="src_sales",
            source_data_fingerprint="sha256:" + "2" * 64,
        )
        self.assertNotEqual(first["seed"], changed_source["seed"])
        self.assertNotEqual(first["seed"], changed_fingerprint["seed"])

    def test_missing_hard_categories_are_explicit_not_found(self) -> None:
        result = build_source_sample(
            [["plain", 1], ["also plain", 2]],
            source_id="src", source_data_fingerprint="fp",
        )
        self.assertEqual(result["coverage"]["blank"], "notFound")
        self.assertEqual(result["coverage"]["longText"], "notFound")
        self.assertEqual(result["coverage"]["unusualText"], "notFound")

    def test_iso_date_extremes_use_declared_column_type(self) -> None:
        result = build_source_sample(
            [["2026-05-01"], ["1999-01-01"], ["2099-12-31"]],
            source_id="src", source_data_fingerprint="fp", column_types=["date"],
        )
        self.assertEqual(result["coverage"]["dateExtreme"], "selected")

    def test_small_and_empty_sources_have_unique_original_ordinals(self) -> None:
        small = build_source_sample(
            [["a"], ["b"], ["c"]], source_id="src", source_data_fingerprint="fp",
        )
        self.assertEqual([row["ordinal"] for row in small["sampleRows"]], [1, 2, 3])
        empty = build_source_sample([], source_id="src", source_data_fingerprint="fp")
        self.assertEqual(empty["sampleRows"], [])
        self.assertEqual(empty["columnCount"], 0)

    def test_selected_columns_are_validated_and_wide_source_is_blocked(self) -> None:
        with self.assertRaises(InputError) as invalid:
            build_source_sample([[1]], source_id="src", source_data_fingerprint="fp", selected_column_indices=[1])
        self.assertEqual(invalid.exception.code, "TSD_SAMPLE_INVALID")
        with self.assertRaises(InputError) as wide:
            build_source_sample([[None] * 201], source_id="src", source_data_fingerprint="fp")
        self.assertEqual(wide.exception.code, "TSD_SAMPLE_COLUMN_LIMIT")

    def test_errors_never_echo_raw_cell_values(self) -> None:
        sentinel = "DO_NOT_LOG_THIS_CELL"
        with self.assertRaises(InputError) as captured:
            build_source_sample([[sentinel]], source_id="src", source_data_fingerprint="fp", column_names=[])
        self.assertNotIn(sentinel, str(captured.exception))


class SourceProfileCacheTests(unittest.TestCase):
    def request(self, cache: SourceProfileCache, **overrides):
        values = {
            "workbook_identity": "book-a", "source_id": "src-sales",
            "source_data_fingerprint": "fp-a", "data_version": 0,
            "rows": [["a"], ["b"]], "column_names": ["Value"],
        }
        values.update(overrides)
        return cache.get_or_build(**values)

    def test_same_key_is_hit_and_result_is_defensively_copied(self) -> None:
        cache = SourceProfileCache()
        first, first_hit = self.request(cache)
        self.assertFalse(first_hit)
        first["sampleRows"][0]["values"][0] = "mutated"
        second, second_hit = self.request(cache, rows=[["ignored-new-value"]])
        self.assertTrue(second_hit)
        self.assertEqual(second["sampleRows"][0]["values"][0], "a")

    def test_prelookup_avoids_rebuilding_and_is_defensively_copied(self) -> None:
        cache = SourceProfileCache()
        self.request(cache)
        lookup = {
            "workbook_identity": "book-a", "source_id": "src-sales",
            "source_data_fingerprint": "fp-a", "data_version": 0,
        }
        first = cache.get_cached(**lookup)
        self.assertIsNotNone(first)
        first["sampleRows"][0]["values"][0] = "mutated"
        self.assertEqual(cache.get_cached(**lookup)["sampleRows"][0]["values"][0], "a")
        self.assertIsNone(cache.get_cached(**{**lookup, "data_version": 1}))

    def test_fingerprint_version_workbook_and_source_are_independent_keys(self) -> None:
        cache = SourceProfileCache()
        self.request(cache)
        for overrides in (
            {"source_data_fingerprint": "fp-b"}, {"data_version": 1},
            {"workbook_identity": "book-b"}, {"source_id": "src-other"},
        ):
            _, hit = self.request(cache, **overrides)
            self.assertFalse(hit)
        self.assertEqual(len(cache), 5)

    def test_fifo_limit_and_clear(self) -> None:
        cache = SourceProfileCache(max_entries=2)
        self.request(cache, source_id="one")
        self.request(cache, source_id="two")
        self.request(cache, source_id="three")
        self.assertEqual(len(cache), 2)
        _, old_hit = self.request(cache, source_id="one")
        self.assertFalse(old_hit)
        cache.clear()
        self.assertEqual(len(cache), 0)


if __name__ == "__main__":
    unittest.main()
