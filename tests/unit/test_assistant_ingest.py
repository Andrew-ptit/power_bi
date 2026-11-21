"""Unit contracts for the read-only Assistant WL1 ingest adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.sources import assistant_ingest as ingest
from tests.support.paths import FIXTURES


SOURCE = FIXTURES / "source"
ORDERS = SOURCE / "orders_synthetic.csv"
WORKBOOK = SOURCE / "orders_synthetic.xlsx"


class AssistantIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_canonical_hash_uses_exact_recipe_and_rejects_nonfinite(self) -> None:
        value = {"b": ["a"], "a": 1}
        expected = "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        self.assertEqual(ingest.canonical_hash(value), expected)
        self.assertEqual(ingest.canonical_hash(value), ingest.canonical_hash({"a": 1, "b": ["a"]}))
        with self.assertRaises(ValueError):
            ingest.canonical_hash(float("nan"))

    def test_csv_adapts_existing_reader_and_preserves_every_raw_row(self) -> None:
        with patch.object(ingest.csv_source, "profile_csv", wraps=ingest.csv_source.profile_csv) as reader:
            result = ingest.add_csv(ORDERS)
        self.assertFalse(result["errors"])
        reader.assert_called_once()
        raw = result["tables"][0]
        self.assertEqual(len(raw["rows"]), 6)
        self.assertTrue(all(isinstance(value, str) for row in raw["rows"] for value in row))
        self.assertEqual(raw["header"][0], "OrderID")
        self.assertEqual(raw["name"], "orders_synthetic")
        self.assertEqual(result["sources"][0]["hash"], ingest.canonical_hash(ORDERS.read_bytes().hex()))
        self.assertEqual(result["sessionBytes"], ORDERS.stat().st_size)
        self.assertEqual(result["csvOptions"][0]["delimiter"], ",")

    def test_csv_preserves_duplicate_and_empty_rows_without_dedupe(self) -> None:
        source = self.root / "raw.csv"
        source.write_bytes(b"Key,Amount\na,001.00\na,001.00\n,\n")
        result = ingest.add_csv(source)
        self.assertFalse(result["errors"])
        self.assertEqual(result["tables"][0]["rows"], [["a", "001.00"], ["a", "001.00"], ["", ""]])

    def test_bom_semicolon_and_multiline_use_existing_csv_support(self) -> None:
        for filename, delimiter, count in (("orders_utf8_bom.csv", ",", 6),
                ("orders_semicolon.csv", ";", 6), ("orders_quoted_multiline.csv", ",", 2)):
            with self.subTest(file=filename):
                result = ingest.add_csv(SOURCE / filename)
                self.assertFalse(result["errors"])
                self.assertEqual(len(result["tables"][0]["rows"]), count)
                self.assertEqual(result["csvOptions"][0]["delimiter"], delimiter)

    def test_structurally_ambiguous_csv_requires_choice_before_admitting_source(self) -> None:
        source = self.root / "ambiguous.csv"
        source.write_bytes(b"Key,Amount;Code\na,1;X\nb,2;Y\n")
        pending = ingest.add_csv(source)
        self.assertFalse(pending["errors"])
        self.assertEqual(pending["sources"], [])
        self.assertEqual(pending["tables"], [])
        self.assertTrue(pending["csvOptions"][0]["needsClarification"])
        self.assertEqual({option["delimiter"] for option in pending["csvOptions"][0]["candidates"]}, {",", ";"})
        comma = ingest.add_csv(source, delimiter=",")
        semi = ingest.add_csv(source, delimiter=";")
        self.assertFalse(comma["errors"] or semi["errors"])
        self.assertNotEqual(comma["tables"][0]["header"], semi["tables"][0]["header"])

    def test_discount_semantics_do_not_create_false_csv_ambiguity(self) -> None:
        source = SOURCE / "orders_ambiguous_discount.csv"
        automatic, manual = ingest.add_csv(source), ingest.add_csv(source, delimiter=";")
        self.assertFalse(automatic["errors"] or manual["errors"])
        self.assertFalse(automatic["csvOptions"][0]["needsClarification"])
        self.assertEqual(automatic["tables"], manual["tables"])

    def test_pending_csv_can_be_resolved_in_same_rooted_session(self) -> None:
        folder = self.root / "source"
        folder.mkdir()
        (folder / "ambiguous.csv").write_bytes(b"Key,Amount;Code\na,1;X\nb,2;Y\n")
        session = {"root": self.root}
        pending = ingest.resolve(session, [{"kind": "csv", "path": "source/ambiguous.csv"}])
        self.assertTrue(pending["csvOptions"][0]["needsClarification"])
        self.assertEqual(pending["sources"], [])
        resolved = ingest.resolve(session, [{"kind": "csv", "path": "source/ambiguous.csv",
                                            "options": {"delimiter": ";"}}])
        self.assertFalse(resolved["errors"])
        self.assertEqual(len(resolved["tables"]), 1)
        self.assertEqual(len(resolved["csvOptions"]), 1)
        self.assertFalse(resolved["csvOptions"][0]["needsClarification"])
        self.assertEqual(resolved["csvOptions"][0]["sourceId"], resolved["sources"][0]["id"])
        self.assertEqual(resolved["sources"][0]["origin"], "source/ambiguous.csv")
        self.assertEqual(resolved["warnings"], [])

    def test_malformed_width_and_invalid_encoding_are_atomic_blockers(self) -> None:
        for filename in ("orders_short_row.csv", "orders_wide_row.csv", "orders_invalid_utf8.csv", "orders_duplicate_header.csv"):
            with self.subTest(file=filename):
                result = ingest.add_csv(SOURCE / filename)
                self.assertEqual(result["sources"], [])
                self.assertEqual(result["tables"], [])
                self.assertEqual(result["sessionBytes"], 0)
                self.assertEqual(result["errors"][0]["code"], "AF_INGEST_FAILED")
                self.assertEqual(result["errors"][0]["severity"], "blocker")

    def test_header_row_option_selects_logical_record_without_stripping_values(self) -> None:
        source = self.root / "header.csv"
        source.write_bytes(b"metadata\nKey,Amount\n value ,001.00\n")
        result = ingest.add_csv(source, delimiter=",", header_row=2)
        self.assertFalse(result["errors"])
        self.assertEqual(result["tables"][0]["header"], ["Key", "Amount"])
        self.assertEqual(result["tables"][0]["rows"], [[" value ", "001.00"]])

    def test_excel_reuses_readonly_reader_and_selects_one_sheet_or_table(self) -> None:
        with patch.object(ingest.xlsx, "profile_workbook", wraps=ingest.xlsx.profile_workbook) as reader:
            sheet = ingest.add_excel(WORKBOOK, sheet="Orders")
        self.assertFalse(sheet["errors"])
        reader.assert_called_once()
        self.assertIsNone(reader.call_args.kwargs["preview_limit"])
        self.assertEqual(len(sheet["tables"][0]["rows"]), 6)
        self.assertEqual(sheet["tables"][0]["locator"]["kind"], "sheet")
        table = ingest.add_excel(WORKBOOK, table="OrdersTable")
        self.assertFalse(table["errors"])
        self.assertEqual(table["tables"][0]["name"], "OrdersTable")
        self.assertEqual(table["tables"][0]["locator"]["range"], "A1:Q7")
        self.assertEqual(table["sources"][0]["hash"], ingest.canonical_hash(WORKBOOK.read_bytes().hex()))
        self.assertTrue(all(isinstance(value, str) for row in table["tables"][0]["rows"] for value in row))

    def test_excel_missing_selection_and_invalid_package_are_blocked(self) -> None:
        missing = ingest.add_excel(WORKBOOK, sheet="Missing")
        self.assertTrue(missing["errors"])
        self.assertEqual(missing["sources"], [])
        bad = self.root / "invalid.xlsx"
        bad.write_bytes(b"not an Office package")
        result = ingest.add_excel(bad)
        self.assertTrue(result["errors"])
        self.assertEqual(result["sources"], [])

    def test_folder_appends_by_filename_and_keeps_all_rows(self) -> None:
        (self.root / "02.csv").write_bytes(b"Key,Amount\nb,2\n")
        (self.root / "01.csv").write_bytes(b"Key,Amount\na,1\na,1\n")
        result = ingest.add_folder(self.root, name="Orders")
        self.assertFalse(result["errors"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["tables"][0]["rows"], [["a", "1"], ["a", "1"], ["b", "2"]])
        self.assertEqual(result["tables"][0]["locator"]["fileCount"], 2)
        self.assertEqual(result["tables"][0]["locator"]["kind"], "folder")
        default_named = ingest.add_folder(self.root)
        self.assertFalse(default_named["errors"])
        self.assertEqual(default_named["tables"][0]["name"], self.root.name)
        self.assertEqual(default_named["sources"][0]["name"], self.root.name)

    def test_folder_header_drift_or_bad_member_discards_whole_selection(self) -> None:
        (self.root / "01.csv").write_bytes(b"Key,Amount\na,1\n")
        bad = self.root / "02.csv"
        for data in (b"Different,Amount\nb,2\n", b"Key,Amount\nb\n"):
            bad.write_bytes(data)
            with self.subTest(case=data[:10]):
                result = ingest.add_folder(self.root)
                self.assertTrue(result["errors"])
                self.assertEqual(result["sources"], [])
                self.assertEqual(result["tables"], [])
                self.assertEqual(result["sessionBytes"], 0)

    def test_folder_rechecks_earlier_members_after_reading_later_members(self) -> None:
        first, second = self.root / "01.csv", self.root / "02.csv"
        first.write_bytes(b"Key,Amount\na,1\n")
        second.write_bytes(b"Key,Amount\nb,2\n")
        original = ingest.add_csv

        def changing_reader(path, **options):
            result = original(path, **options)
            if Path(path).name == "02.csv":
                first.write_bytes(b"Key,Amount\na,9\n")
            return result

        with patch.object(ingest, "add_csv", side_effect=changing_reader):
            result = ingest.add_folder(self.root)
        self.assertTrue(result["errors"])
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sessionBytes"], 0)

    def test_folder_checks_actual_payload_budget_not_only_initial_stat_estimate(self) -> None:
        (self.root / "01.csv").write_bytes(b"Key,Amount\na,1\n")
        original = ingest.add_csv

        def bounded_result(path, **options):
            result = original(path, **options)
            result["sessionBytes"] = ingest.MAX_BYTES_PER_SESSION + 1
            return result

        with patch.object(ingest, "add_csv", side_effect=bounded_result):
            result = ingest.add_folder(self.root)
        self.assertTrue(result["errors"])
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["sessionBytes"], 0)

    def test_workbook_payload_keeps_inert_values_and_rejects_partial_samples(self) -> None:
        payload = {"name": "Selected", "sheet": "Data", "range": "A1:B3",
                   "header": ["Key", "Value"], "rows": [["a", "=SUM(A1:A2)"], ["b", None]]}
        result = ingest.add_open_workbook(payload)
        self.assertFalse(result["errors"])
        self.assertEqual(result["tables"][0]["rows"], [["a", "=SUM(A1:A2)"], ["b", ""]])
        self.assertEqual(payload["rows"][1][1], None)
        self.assertEqual(result["sources"][0]["type"], "workbook")
        for extra in ({"sampleOnly": True}, {"totalRows": 99}, {"totalColumns": 99}):
            with self.subTest(extra=extra):
                rejected = ingest.add_open_workbook({**payload, **extra})
                self.assertTrue(rejected["errors"])
                self.assertEqual(rejected["sources"], [])

    def test_workbook_nonfinite_values_and_bad_width_are_blocked(self) -> None:
        for rows in ([[1, 2]], [[float("nan")]], [[{"not": "scalar"}]]):
            with self.subTest(shape=len(rows[0])):
                result = ingest.add_open_workbook({"header": ["Value"], "rows": rows})
                self.assertTrue(result["errors"])
                self.assertEqual(result["sources"], [])

    def test_unsupported_traversal_oversize_and_outside_root_create_no_files(self) -> None:
        executable = self.root / "source.exe"
        executable.write_bytes(b"blocked")
        huge = self.root / "huge.csv"
        with huge.open("wb") as handle:
            handle.truncate(ingest.MAX_BYTES_PER_FILE + 1)
        before = sorted(p.name for p in self.root.iterdir())
        for path in (executable, self.root / ".." / "source.csv", huge, ORDERS):
            with self.subTest(case=path.name):
                result = ingest.resolve({"root": self.root}, [{"kind": "csv", "path": path}])
                self.assertTrue(result["errors"])
                self.assertEqual(result["sources"], [])
                self.assertEqual(result["errors"][0]["code"], "AF_INGEST_FAILED")
                self.assertEqual(result["errors"][0]["severity"], "blocker")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_session_quota_rejects_before_reader_and_keeps_prior_state(self) -> None:
        previous = ingest._empty()
        previous["sessionBytes"] = ingest.MAX_BYTES_PER_SESSION
        session = {"_assistant_ingest": previous}
        with patch.object(ingest, "add_csv") as reader:
            result = ingest.resolve(session, [{"kind": "csv", "path": ORDERS}])
        reader.assert_not_called()
        self.assertEqual(result["sessionBytes"], 128 * 1024 * 1024)
        self.assertTrue(result["errors"])
        self.assertEqual(result["sources"], [])

    def test_resolve_accumulates_duplicate_names_without_overwrite_and_closes_only_memory(self) -> None:
        session = {"root": SOURCE, "callerState": "retained"}
        first = ingest.resolve(session, [{"kind": "csv", "path": "orders_synthetic.csv", "name": "Orders"}])
        second = ingest.resolve(session, [{"kind": "csv", "path": "orders_semicolon.csv", "name": "Orders"}])
        self.assertFalse(first["errors"] or second["errors"])
        self.assertEqual(len(second["tables"]), 2)
        self.assertEqual(len(second["requiresRename"]), 1)
        self.assertEqual(second["requiresRename"][0]["tableName"], "Orders")
        self.assertEqual(len(second["requiresRename"][0]["sources"]), 2)
        self.assertEqual(first["sources"][0]["origin"], "orders_synthetic.csv")
        ingest.close(session)
        self.assertEqual(session["callerState"], "retained")
        self.assertNotIn("_assistant_ingest", session)
        self.assertTrue(ingest.resolve(session, [])["errors"])

    def test_source_bytes_and_mtime_are_unchanged_and_ids_deterministic(self) -> None:
        paths = (ORDERS, WORKBOOK, SOURCE / "orders_semicolon.csv")
        before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
        first = ingest.add_csv(ORDERS)
        self.assertEqual(first, ingest.add_csv(ORDERS))
        ingest.add_excel(WORKBOOK)
        ingest.add_csv(paths[2])
        after = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
        self.assertEqual(before, after)
        source = first["sources"][0]
        self.assertEqual(source["id"], "src_" + hashlib.sha256((source["name"] + source["origin"]).encode()).hexdigest()[:12])
        self.assertEqual(ingest.MAX_PREVIEW_ROWS, 20)
        self.assertEqual(ingest.MAX_BYTES_PER_FILE, 64 * 1024 * 1024)

    def test_diagnostics_do_not_echo_private_paths_or_raw_headers(self) -> None:
        private = self.root / "private.csv"
        private.write_bytes(b"SecretHeader,SecretHeader\na,b\n")
        result = ingest.add_csv(private)
        diagnostic = json.dumps(result["errors"])
        self.assertNotIn(str(self.root), diagnostic)
        self.assertNotIn("SecretHeader", diagnostic)
        self.assertEqual(result["errors"][0]["path"], "private.csv")


if __name__ == "__main__":
    unittest.main()
