"""Unit contracts for WL1 profiles over synthetic in-memory raw tables."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import unittest

from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_profile import build_snapshot, profile_table, snapshot_hash


def raw_table(*, name: str = "Data", source_id: str = "src_123456abcdef", rows: list | None = None) -> dict:
    return {
        "sourceId": source_id,
        "name": name,
        "locator": {"kind": "file", "sheet": None, "range": None, "path": "source/data.csv", "fileCount": 1},
        "header": ["Code", "Amount"],
        "rows": [["A", "001.00"], ["", "-2"], ["A", ""], [" ", "0"]] if rows is None else rows,
    }


def ingest_result(*, name: str = "Data", source_id: str = "src_123456abcdef") -> dict:
    return {
        "sources": [{"id": source_id, "name": name + ".csv", "type": "csv", "origin": "source/data.csv", "hash": canonical_hash("synthetic"), "addedAt": "2026-10-26T09:00:00Z"}],
        "tables": [raw_table(name=name, source_id=source_id)],
        "csvOptions": [], "errors": [], "warnings": [], "sessionBytes": 25, "requiresRename": [],
    }


class AssistantProfileTests(unittest.TestCase):
    def test_raw_column_statistics_preserve_strings_and_exclude_only_empty_cells(self) -> None:
        raw = raw_table()
        original = deepcopy(raw)
        result = profile_table(raw)
        self.assertEqual((result["rowCount"], result["columnCount"]), (4, 2))
        code, amount = result["columns"]
        self.assertEqual((code["nullRate"], code["distinctCount"], code["distinctRatio"]), (0.25, 2, 0.5))
        self.assertEqual((amount["nullRate"], amount["distinctCount"], amount["distinctRatio"]), (0.25, 3, 0.75))
        self.assertEqual(amount["sample"], ["001.00", "-2", "", "0"])
        self.assertEqual(raw, original, "profile must not mutate input")
        for column in result["columns"]:
            self.assertEqual((column["type"], column["role"], column["roleStatus"], column["evidence"]), ("text", None, "unknown", []))

    def test_ratios_use_decimal_round_half_up_to_three_places(self) -> None:
        rows = [["", "x"]] + [["a", "x"] for _ in range(15)]
        columns = profile_table(raw_table(rows=rows))["columns"]
        self.assertEqual(columns[0]["nullRate"], 0.063, "1/16 must round half up")
        self.assertEqual(columns[0]["distinctRatio"], 0.063)
        self.assertEqual(Decimal(str(columns[1]["distinctRatio"])), Decimal("0.063"))

    def test_samples_are_bounded_while_statistics_use_every_row(self) -> None:
        rows = [[str(index), ""] for index in range(25)]
        result = profile_table(raw_table(rows=rows))
        self.assertEqual(result["rowCount"], 25)
        self.assertEqual(result["columns"][0]["distinctCount"], 25)
        self.assertEqual(result["columns"][0]["sample"], [str(index) for index in range(20)])
        self.assertEqual(result["columns"][1]["nullRate"], 1.0)
        expected_hash = "sha256:" + hashlib.sha256(json.dumps(rows[:20], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        self.assertEqual(result["sampleHash"], expected_hash)

    def test_profile_hashes_bind_header_sample_and_table_name_in_order(self) -> None:
        raw = raw_table()
        result = profile_table(raw)
        self.assertEqual(result["headerHash"], canonical_hash(raw["header"]))
        self.assertEqual(result["sampleHash"], canonical_hash(raw["rows"]))
        self.assertEqual(result["fingerprint"], canonical_hash({"name": "Data", "header": raw["header"], "sample": raw["rows"]}))
        expected_id = "tbl_" + hashlib.sha256((raw["sourceId"] + "Data").encode("utf-8")).hexdigest()[:12]
        self.assertEqual(result["id"], expected_id)
        reversed_rows = deepcopy(raw)
        reversed_rows["rows"].reverse()
        self.assertNotEqual(profile_table(reversed_rows)["fingerprint"], result["fingerprint"])
        self.assertNotEqual(profile_table(raw_table(name="Other"))["fingerprint"], result["fingerprint"])

    def test_empty_data_has_zero_rates_and_no_samples(self) -> None:
        result = profile_table(raw_table(rows=[]))
        self.assertEqual(result["rowCount"], 0)
        self.assertEqual(result["sampleHash"], canonical_hash([]))
        for column in result["columns"]:
            self.assertEqual((column["nullRate"], column["distinctCount"], column["distinctRatio"], column["sample"]), (0.0, 0, 0.0, []))

    def test_malformed_raw_tables_fail_without_coercion_or_row_loss(self) -> None:
        invalid = [None, {}, {**raw_table(), "rows": [["short"]]}, {**raw_table(), "rows": [["a", 1]]}, {**raw_table(), "header": ["x", "x"]}, {**raw_table(), "header": []}, {**raw_table(), "rows": "invalid"}, {**raw_table(), "locator": None}]
        for candidate in invalid:
            with self.subTest(shape=type(candidate).__name__):
                with self.assertRaises(ValueError):
                    profile_table(candidate)

    def test_profile_and_snapshot_do_not_share_mutable_input_state(self) -> None:
        raw = raw_table()
        profile = profile_table(raw)
        profile["locator"]["path"] = "changed"
        profile["columns"][0]["sample"][0] = "changed"
        self.assertEqual(raw["locator"]["path"], "source/data.csv")
        self.assertEqual(raw["rows"][0][0], "A")
        ingested = ingest_result()
        before = deepcopy(ingested)
        result = build_snapshot(ingested)
        result["sources"][0]["name"] = "changed"
        self.assertEqual(ingested, before)

    def test_snapshot_is_sorted_and_reproducible_with_content_derived_ids(self) -> None:
        left = ingest_result(name="Zeta", source_id="src_abcdef123456")
        right = ingest_result(name="Alpha", source_id="src_123456abcdef")
        left["sources"] += right["sources"]
        left["tables"] += right["tables"]
        result = build_snapshot(left)
        reversed_input = deepcopy(left)
        reversed_input["sources"].reverse()
        reversed_input["tables"].reverse()
        self.assertEqual(build_snapshot(reversed_input), result)
        self.assertEqual([source["name"] for source in result["sources"]], ["Alpha.csv", "Zeta.csv"])
        self.assertEqual([table["name"] for table in result["tables"]], ["Alpha", "Zeta"])
        self.assertEqual((result["snapshot"]["sourceCount"], result["snapshot"]["tableCount"]), (2, 2))
        self.assertRegex(result["snapshot"]["snapshotId"], r"^snap_[a-f0-9]{24}$")
        self.assertRegex(result["snapshot"]["sessionId"], r"^sess_[a-f0-9]{12}$")
        self.assertEqual(result["snapshotHash"], snapshot_hash(result))
        self.assertEqual(result["hashBasis"], ["snapshot", "sources", "tables"])

    def test_snapshot_timestamp_projection_retains_metadata_and_binds_data(self) -> None:
        result = build_snapshot(ingest_result(), created_at="2026-10-27T01:00:00Z")
        other = deepcopy(result)
        other["snapshot"]["createdAt"] = "2026-10-28T01:00:00Z"
        other["sources"][0]["addedAt"] = "2026-10-28T00:00:00Z"
        self.assertEqual(snapshot_hash(other), result["snapshotHash"])
        self.assertEqual(result["snapshot"]["createdAt"], "2026-10-27T01:00:00Z")
        content = deepcopy(result)
        content["snapshot"].pop("createdAt")
        for source in content["sources"]:
            source.pop("addedAt")
        self.assertEqual(result["snapshotHash"], canonical_hash({key: content[key] for key in result["hashBasis"]}))
        for section, key in (("snapshot", "sourceCount"), ("sources", "hash"), ("tables", "fingerprint")):
            changed = deepcopy(result)
            if section == "snapshot":
                changed[section][key] = 999
            else:
                changed[section][0][key] = "changed"
            self.assertNotEqual(snapshot_hash(changed), result["snapshotHash"], section + "." + key)

    def test_explicit_snapshot_id_is_validated_and_hash_bound(self) -> None:
        identifier = "snap_" + "a" * 24
        result = build_snapshot(ingest_result(), snapshot_id=identifier)
        self.assertEqual(result["snapshot"]["snapshotId"], identifier)
        self.assertNotEqual(result["snapshotHash"], build_snapshot(ingest_result())["snapshotHash"])
        with self.assertRaises(ValueError):
            build_snapshot(ingest_result(), snapshot_id="invalid")

    def test_snapshot_rejects_ingest_blockers_dangling_sources_and_duplicates(self) -> None:
        candidates = []
        for key, problem in (("errors", [{"code": "AF_INGEST_FAILED"}]), ("requiresRename", [{"tableName": "Data"}]), ("csvOptions", [{"needsClarification": True}])):
            candidate = ingest_result()
            candidate[key] = problem
            candidates.append(candidate)
        candidate = ingest_result()
        candidate["sources"] = []
        candidates.append(candidate)
        candidate = ingest_result()
        candidate["tables"] *= 2
        candidates.append(candidate)
        candidate = ingest_result()
        candidate["sources"] *= 2
        candidates.append(candidate)
        for candidate in candidates:
            with self.assertRaises(ValueError):
                build_snapshot(candidate)
        with self.assertRaises(ValueError):
            snapshot_hash({"hashBasis": []})

    def test_empty_snapshot_is_deterministic_and_has_no_invented_sources(self) -> None:
        ingested = {**ingest_result(), "sources": [], "tables": []}
        result = build_snapshot(ingested)
        self.assertEqual(result["snapshot"]["sourceCount"], 0)
        self.assertEqual(result["snapshot"]["tableCount"], 0)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["tables"], [])
        self.assertEqual(result, build_snapshot(ingested))


if __name__ == "__main__":
    unittest.main()
