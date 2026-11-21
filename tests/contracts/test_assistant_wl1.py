"""Golden and behavioral contracts for the read-only Assistant WL1 engine slice."""

from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.sources import assistant_ingest as ingest
from pbip_assistant.sources.assistant_profile import build_snapshot, profile_table, snapshot_hash
from tests.support.paths import FIXTURES


ASSISTANT = FIXTURES / "assistant"
SOURCE = FIXTURES / "source"
ROOT = FIXTURES.parents[1]
SOURCE_FIELDS = ("name", "type", "origin")
TABLE_FIELDS = ("name", "rowCount", "columnCount", "headerHash", "sampleHash", "fingerprint")
COLUMN_FIELDS = ("name", "nullRate", "distinctCount", "distinctRatio", "sample")


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def selection(scenario: str) -> tuple[dict, list[dict]]:
    base = ASSISTANT / scenario
    requests = [{"kind": "csv", "path": "source/" + path.name}
                for path in sorted((base / "source").glob("*.csv"))]
    if scenario == "tp-sales":
        requests.append({"kind": "folder", "path": "source/orders", "name": "Orders"})
    return {"root": base}, requests


def file_state(paths: list[Path]) -> dict[Path, tuple[str, int, int]]:
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                   path.stat().st_size) for path in paths}


class AssistantWL1ContractTests(unittest.TestCase):
    def eq(self, actual: object, expected: object, field: str) -> None:
        self.assertEqual(actual, expected, field)

    def golden(self, scenario: str) -> None:
        golden = json.loads((ASSISTANT / scenario / "wl1_snapshot.json").read_text(encoding="utf-8"))
        session, requests = selection(scenario)
        raw = ingest.resolve(session, requests)
        self.eq(raw["errors"], [], scenario + ": ingest blockers")
        self.eq(raw["requiresRename"], [], scenario + ": duplicate names")
        actual = build_snapshot(raw)
        for key in ("sourceCount", "tableCount"):
            self.eq(actual["snapshot"][key], golden["snapshot"][key], scenario + ".snapshot." + key)
        expected_sources = sorted(golden["sources"], key=lambda item: item["name"])
        self.eq([item["name"] for item in actual["sources"]], sorted(item["name"] for item in actual["sources"]), scenario + ": source order")
        self.eq([{key: item[key] for key in SOURCE_FIELDS} for item in actual["sources"]],
                [{key: item[key] for key in SOURCE_FIELDS} for item in expected_sources], scenario + ": source identity fields")
        expected_tables = sorted(golden["tables"], key=lambda item: item["name"])
        self.eq([table["name"] for table in actual["tables"]], [table["name"] for table in expected_tables], scenario + ": table order/names")
        for table, expected in zip(actual["tables"], expected_tables, strict=True):
            field = scenario + ".tables." + table["name"]
            for key in TABLE_FIELDS:
                self.eq(table[key], expected[key], field + "." + key)
            for key in ("kind", "fileCount"):
                self.eq(table["locator"][key], expected["locator"][key], field + ".locator." + key)
            self.eq(len(table["columns"]), len(expected["columns"]), field + ": column count")
            for column, expected_column in zip(table["columns"], expected["columns"], strict=True):
                for key in COLUMN_FIELDS:
                    self.eq(column[key], expected_column[key], field + ".columns." + column["name"] + "." + key)

    def test_golden_fin_matches_all_owned_fields_without_fixture_changes(self) -> None:
        self.golden("tp-fin")

    def test_golden_sales_matches_all_owned_fields_without_fixture_changes(self) -> None:
        self.golden("tp-sales")

    def test_t_wl1_01_four_connector_kinds_produce_raw_tables_and_profiles(self) -> None:
        requests = [
            {"kind": "csv", "path": "tests/fixtures/source/orders_synthetic.csv", "name": "CsvOrders"},
            {"kind": "xlsx", "path": "tests/fixtures/source/orders_synthetic.xlsx", "name": "ExcelOrders", "options": {"table": "OrdersTable"}},
            {"kind": "folder", "path": "tests/fixtures/assistant/tp-sales/source/orders", "name": "Orders"},
            {"kind": "workbook", "payload": {"name": "SelectedValues", "sheet": "Synthetic", "range": "A1:B3", "header": ["Code", "Amount"], "rows": [["A", "001.00"], ["B", ""]]}},
        ]
        payload_before = deepcopy(requests[-1]["payload"])
        raw = ingest.resolve({"root": ROOT}, requests)
        self.eq(raw["errors"], [], "T-WL1-01: connector errors")
        self.eq(raw["requiresRename"], [], "T-WL1-01: unique table names")
        self.eq({source["type"] for source in raw["sources"]}, {"csv", "xlsx", "folder", "workbook"}, "T-WL1-01: four connectors")
        snapshot = build_snapshot(raw)
        self.eq((snapshot["snapshot"]["sourceCount"], snapshot["snapshot"]["tableCount"]), (4, 4), "T-WL1-01: counts")
        self.eq(requests[-1]["payload"], payload_before, "T-WL1-01: workbook payload unchanged")
        for table in snapshot["tables"]:
            self.assertGreater(table["columnCount"], 0, table["name"] + ": schema")
            self.assertRegex(table["fingerprint"], r"^sha256:[a-f0-9]{64}$", table["name"] + ": fingerprint")
            for column in table["columns"]:
                self.assertLessEqual(len(column["sample"]), 20, table["name"] + ": bounded sample")
        for source in raw["sources"]:
            if source["type"] in {"csv", "xlsx"}:
                self.eq(source["hash"], digest((ROOT / source["origin"]).read_bytes().hex()), source["name"] + ": source byte hash")

    def test_t_wl1_02_true_csv_ambiguity_requires_choice_and_recovers_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "ambiguous.csv"
            path.write_bytes(b"Key,Amount;Code\na,1;X\nb,2;Y\n")
            before = file_state([path])
            session = {"root": root}
            pending = ingest.resolve(session, [{"kind": "csv", "path": path.name}])
            self.eq((pending["sources"], pending["tables"]), ([], []), "T-WL1-02: unresolved source not admitted")
            self.eq(pending["errors"], [], "T-WL1-02: pending choice is not a fabricated parse")
            self.assertTrue(pending["csvOptions"][0]["needsClarification"], "T-WL1-02: clarification required")
            self.assertGreaterEqual(len(pending["csvOptions"][0]["candidates"]), 2, "T-WL1-02: multiple candidates")
            with self.assertRaises(ValueError, msg="T-WL1-02: snapshot blocked until choice"):
                build_snapshot(pending)
            resolved = ingest.resolve(session, [{"kind": "csv", "path": path.name, "options": {"delimiter": ";"}}])
            self.eq(resolved["errors"], [], "T-WL1-02: explicit choice errors")
            self.eq(len(resolved["csvOptions"]), 1, "T-WL1-02: replaced pending profile")
            self.assertFalse(resolved["csvOptions"][0]["needsClarification"], "T-WL1-02: no old pending option")
            chosen = build_snapshot(resolved)["tables"][0]
            other = profile_table(ingest.add_csv(path, delimiter=",")["tables"][0])
            self.assertNotEqual(chosen["fingerprint"], other["fingerprint"], "T-WL1-02: different explicit readings bind different fingerprints")
            self.eq(file_state([path]), before, "T-WL1-02: source read-only")
        source = SOURCE / "orders_ambiguous_discount.csv"
        automatic = ingest.add_csv(source)
        manual = ingest.add_csv(source, delimiter=";")
        self.assertFalse(automatic["csvOptions"][0]["needsClarification"], "T-WL1-02: discount semantics are outside WL1")
        self.eq(profile_table(automatic["tables"][0])["fingerprint"], profile_table(manual["tables"][0])["fingerprint"], "T-WL1-02: same delimiter/data retains fingerprint")

    def test_t_wl1_03_folder_appends_three_months_in_filename_order(self) -> None:
        folder = ASSISTANT / "tp-sales" / "source" / "orders"
        expected_rows = []
        for path in sorted(folder.glob("*.csv")):
            with path.open(encoding="utf-8", newline="") as handle:
                expected_rows.extend(list(csv.reader(handle))[1:])
        raw = ingest.add_folder(folder, name="Orders")
        self.eq(raw["errors"], [], "T-WL1-03: folder errors")
        self.eq(len(raw["tables"]), 1, "T-WL1-03: one table")
        self.eq(raw["tables"][0]["rows"], expected_rows, "T-WL1-03: every row in filename order")
        table = build_snapshot(raw)["tables"][0]
        self.eq((table["name"], table["rowCount"], table["locator"]["kind"], table["locator"]["fileCount"]), ("Orders", 12, "folder", 3), "T-WL1-03: folder counts and locator")

    def test_t_wl1_04_repeated_ingest_keeps_all_table_fingerprints(self) -> None:
        for scenario in ("tp-fin", "tp-sales"):
            left_session, requests = selection(scenario)
            right_session, _ = selection(scenario)
            first = build_snapshot(ingest.resolve(left_session, requests))
            second = build_snapshot(ingest.resolve(right_session, requests))
            self.eq([{k: table[k] for k in ("name", "headerHash", "sampleHash", "fingerprint")} for table in first["tables"]], [{k: table[k] for k in ("name", "headerHash", "sampleHash", "fingerprint")} for table in second["tables"]], "T-WL1-04: " + scenario)

    def test_t_wl1_05_invalid_extension_traversal_and_oversize_are_blocked_without_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root / "selected"
            selected.mkdir()
            (selected / "bad.exe").write_bytes(b"inert")
            (selected / "valid.csv").write_bytes(b"A,B\na,b\n")
            outside = root / "outside.csv"
            outside.write_bytes(b"A,B\na,b\n")
            large = selected / "oversize.csv"
            with large.open("wb") as handle:
                handle.truncate(64 * 1024 * 1024 + 1)
            before = {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*")}
            for path in ("bad.exe", "nested/../valid.csv", "oversize.csv", outside):
                with self.subTest(case=Path(path).name):
                    result = ingest.resolve({"root": selected}, [{"kind": "csv", "path": path}])
                    self.eq((result["sources"], result["tables"]), ([], []), "T-WL1-05: no source admitted")
                    self.assertTrue(result["errors"], "T-WL1-05: explicit blocker")
                    self.eq((result["errors"][0]["code"], result["errors"][0]["severity"]), ("AF_INGEST_FAILED", "blocker"), "T-WL1-05: error category")
            after = {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*")}
            self.eq(after, before, "T-WL1-05: no temporary artifact or source write")

    def test_t_wl1_06_duplicate_names_preserve_both_tables_and_block_snapshot(self) -> None:
        session = {"root": SOURCE}
        first = ingest.resolve(session, [{"kind": "csv", "path": "orders_synthetic.csv", "name": "Repeated"}])
        original = deepcopy(first["tables"][0])
        second = ingest.resolve(session, [{"kind": "csv", "path": "orders_semicolon.csv", "name": "Repeated"}])
        self.eq(second["errors"], [], "T-WL1-06: rename instead of overwrite")
        self.eq(len(second["tables"]), 2, "T-WL1-06: both tables retained")
        self.assertIn(original, second["tables"], "T-WL1-06: original table unchanged")
        self.eq(second["requiresRename"], [{"tableName": "Repeated", "sources": [table["sourceId"] for table in second["tables"]]}], "T-WL1-06: rename request binds both sources")
        with self.assertRaises(ValueError, msg="T-WL1-06: unresolved duplicate blocks snapshot"):
            build_snapshot(second)

    def test_t_wl1_07_snapshot_hash_repeats_and_excludes_only_capture_timestamps(self) -> None:
        session, requests = selection("tp-fin")
        second_session, _ = selection("tp-fin")
        first = build_snapshot(ingest.resolve(session, requests))
        second = build_snapshot(ingest.resolve(second_session, list(reversed(requests))))
        self.eq(first["snapshotHash"], second["snapshotHash"], "T-WL1-07: request-order independent snapshot")
        projected = {key: deepcopy(first[key]) for key in first["hashBasis"]}
        projected["snapshot"].pop("createdAt")
        for source in projected["sources"]:
            source.pop("addedAt")
        self.eq(first["snapshotHash"], digest(projected), "T-WL1-07: independent timestamp-free hash recipe")
        changed = deepcopy(first)
        changed["snapshot"]["createdAt"] = "2026-10-28T00:00:00Z"
        for source in changed["sources"]:
            source["addedAt"] = "2026-10-28T00:00:00Z"
        self.eq(snapshot_hash(changed), first["snapshotHash"], "T-WL1-07: timestamps retained but not hashed")
        changed["sources"][0]["hash"] = digest("changed-content")
        self.assertNotEqual(snapshot_hash(changed), first["snapshotHash"], "T-WL1-07: source content still bound")

    def test_br_001_all_used_source_bytes_and_mtimes_survive_ingest_profile_and_close(self) -> None:
        paths = sorted((ASSISTANT / "tp-fin" / "source").rglob("*.csv")) + sorted((ASSISTANT / "tp-sales" / "source").rglob("*.csv"))
        paths += [SOURCE / name for name in ("orders_synthetic.csv", "orders_synthetic.xlsx", "orders_ambiguous_discount.csv", "orders_semicolon.csv")]
        before = file_state(paths)
        for scenario in ("tp-fin", "tp-sales"):
            session, requests = selection(scenario)
            session["callerOwned"] = {"keep": True}
            build_snapshot(ingest.resolve(session, requests))
            ingest.close(session)
            self.eq(session["callerOwned"], {"keep": True}, "BR-001: close preserves caller state")
            self.assertNotIn("_assistant_ingest", session, "BR-001: owned memory released")
        for path in paths[-4:]:
            result = ingest.add_excel(path, table="OrdersTable") if path.suffix == ".xlsx" else ingest.add_csv(path)
            self.eq(result["errors"], [], "BR-001: reader accepted existing synthetic source")
            build_snapshot(result)
        self.eq(file_state(paths), before, "BR-001: all source SHA256/mtime/size unchanged")

    def test_br_003_production_limits_bound_samples_and_reject_session_overflow(self) -> None:
        self.eq((ingest.MAX_BYTES_PER_FILE, ingest.MAX_BYTES_PER_SESSION, ingest.MAX_PREVIEW_ROWS), (64 * 1024 * 1024, 128 * 1024 * 1024, 20), "BR-003: production limits unchanged")
        session, requests = selection("tp-fin")
        raw = ingest.resolve(session, requests)
        gl = next(table for table in raw["tables"] if table["name"] == "GL_Actuals_2026-09")
        self.eq(len(gl["rows"]), 31, "BR-003: full source rows preserved")
        table = profile_table(gl)
        for index, column in enumerate(table["columns"]):
            self.eq(column["sample"], [row[index] for row in gl["rows"][:20]], "BR-003: sample is exactly first twenty values")
        near_limit = {"sources": [], "tables": [], "csvOptions": [], "errors": [], "warnings": [], "sessionBytes": 128 * 1024 * 1024 - 1, "requiresRename": []}
        rejected = ingest.resolve({"root": SOURCE, "_assistant_ingest": near_limit}, [{"kind": "csv", "path": "orders_synthetic.csv"}])
        self.eq(rejected["sources"], [], "BR-003: overflow source not admitted")
        self.eq(rejected["sessionBytes"], near_limit["sessionBytes"], "BR-003: failed admission consumes no bytes")
        self.eq((rejected["errors"][0]["code"], rejected["errors"][0]["severity"]), ("AF_INGEST_FAILED", "blocker"), "BR-003: overflow blocker")


if __name__ == "__main__":
    unittest.main()
