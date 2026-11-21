"""Unit boundaries for deterministic WL2 assembly over synthetic raw tables."""

from __future__ import annotations

from copy import deepcopy
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_profile import build_snapshot, snapshot_hash
from pbip_assistant.sources.assistant_understand import build_understand, understand_hash


def inputs() -> tuple[list[dict], dict]:
    definitions = (
        ("Transactions", ["OrderID", "CustomerID", "ProductID", "Amount"],
         [["O1", "C1", "P1", "10"], ["O2", "C1", "P2", "20"], ["O3", "C2", "P1", "30"], ["O4", "C2", "P2", "40"]]),
        ("Customers", ["CustomerID", "Label"], [["C1", "First"], ["C2", "Second"]]),
        ("Products", ["ProductID", "Label"], [["P1", "Item1"], ["P2", "Item2"]]),
    )
    sources, tables = [], []
    for name, header, rows in definitions:
        source_id = "src_" + canonical_hash(name)[7:19]
        origin = name + ".csv"
        sources.append({"id": source_id, "name": origin, "type": "csv", "origin": origin,
                        "hash": canonical_hash({"header": header, "rows": rows}), "addedAt": "2026-10-26T09:00:00Z"})
        tables.append({"sourceId": source_id, "name": name,
                       "locator": {"kind": "file", "sheet": None, "range": None, "path": origin, "fileCount": 1},
                       "header": header, "rows": rows})
    ingested = {"sources": sources, "tables": tables, "errors": [], "warnings": [], "csvOptions": [], "requiresRename": [], "sessionBytes": 0}
    return tables, build_snapshot(ingested)


def rehash(snapshot: dict) -> None:
    snapshot["snapshotHash"] = snapshot_hash(snapshot)


class AssistantUnderstandTests(unittest.TestCase):
    def test_assembler_generic_shape_has_one_measured_fact_and_only_used_sources(self) -> None:
        raw, snapshot = inputs()
        result = build_understand(raw, snapshot)
        self.assertEqual(set(result), {"schemaVersion", "snapshotHash", "pack", "roles", "relationships", "assumptions", "warnings", "hashBasis", "understandHash", "variantOf", "variantReason"})
        self.assertEqual(result["snapshotHash"], snapshot["snapshotHash"])
        self.assertTrue(result["pack"]["genericMode"])
        self.assertIn("kém chính xác hơn", result["pack"]["notice"])
        facts = [role for role in result["roles"] if role["structural"] == "fact"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["tableId"], next(t["id"] for t in snapshot["tables"] if t["name"] == "Transactions"))
        self.assertEqual({entry["source"] for entry in result["assumptions"]}, {"data"})
        self.assertEqual(result["warnings"], [])

    def test_inputs_and_returned_state_do_not_share_mutable_objects(self) -> None:
        raw, snapshot = inputs()
        before = deepcopy((raw, snapshot))
        result = build_understand(raw, snapshot)
        self.assertEqual((raw, snapshot), before)
        result["pack"]["notice"] = "changed"
        result["relationships"][0]["fromColumns"].append("changed")
        result["assumptions"][0]["evidence"][0]["value"] = "changed"
        self.assertEqual((raw, snapshot), before)
        self.assertNotEqual(result, build_understand(raw, snapshot))

    def test_repeated_and_reordered_inputs_have_the_same_complete_hash(self) -> None:
        raw, snapshot = inputs()
        first = build_understand(raw, snapshot)
        other = deepcopy(snapshot)
        other["tables"].reverse()
        other["sources"].reverse()
        rehash(other)
        # Snapshot identity is deliberately bound; only raw traversal order is irrelevant.
        self.assertEqual(build_understand(list(reversed(raw)), snapshot), first)
        self.assertEqual(build_understand(raw, snapshot), first)
        self.assertEqual(first["understandHash"], canonical_hash({key: first[key] for key in first["hashBasis"]}))
        self.assertEqual(understand_hash(first), first["understandHash"])
        self.assertNotEqual(build_understand(raw, other)["understandHash"], first["understandHash"])

    def test_snapshot_content_and_identity_are_hash_bound(self) -> None:
        raw, snapshot = inputs()
        first = build_understand(raw, snapshot)
        changed = deepcopy(snapshot)
        changed["sources"][0]["hash"] = canonical_hash("new source bytes")
        rehash(changed)
        second = build_understand(raw, changed)
        self.assertEqual(second["snapshotHash"], changed["snapshotHash"])
        self.assertNotEqual(first["understandHash"], second["understandHash"])
        for key in first["hashBasis"]:
            altered = deepcopy(first)
            altered[key] = {"changed": True}
            self.assertNotEqual(understand_hash(altered), first["understandHash"], key)

    def test_stale_raw_counts_headers_samples_and_statistics_are_rejected(self) -> None:
        raw, snapshot = inputs()
        candidates = []
        changed = deepcopy(raw)
        changed[0]["rows"][0][0] = "different"
        candidates.append(changed)
        changed = deepcopy(raw)
        changed[0]["rows"].append(deepcopy(changed[0]["rows"][0]))
        candidates.append(changed)
        changed = deepcopy(raw)
        changed[0]["header"][0] = "Different"
        candidates.append(changed)
        candidates.extend((raw[:-1], raw + [deepcopy(raw[0])]))
        for candidate in candidates:
            with self.assertRaises(ValueError):
                build_understand(candidate, snapshot)
        changed = deepcopy(snapshot)
        changed["tables"][0]["columns"][0]["distinctCount"] = 999
        rehash(changed)
        with self.assertRaises(ValueError):
            build_understand(raw, changed)

    def test_bad_snapshot_digest_basis_ids_counts_and_source_references_fail_closed(self) -> None:
        raw, snapshot = inputs()
        candidates = []
        changed = deepcopy(snapshot)
        changed["snapshotHash"] = canonical_hash("stale")
        candidates.append(changed)
        changed = deepcopy(snapshot)
        changed["hashBasis"] = ["snapshot"]
        candidates.append(changed)
        for field, value in (("id", "invalid"), ("sourceId", "src_" + "0" * 12)):
            changed = deepcopy(snapshot)
            changed["tables"][0][field] = value
            rehash(changed)
            candidates.append(changed)
        changed = deepcopy(snapshot)
        changed["snapshot"]["tableCount"] = 99
        rehash(changed)
        candidates.append(changed)
        changed = deepcopy(snapshot)
        changed["tables"][0]["name"] = changed["tables"][1]["name"]
        rehash(changed)
        candidates.append(changed)
        for candidate in candidates:
            with self.assertRaises(ValueError):
                build_understand(raw, candidate)

    def test_explicit_snapshot_table_ids_are_bound_only_on_verified_copies(self) -> None:
        raw, snapshot = inputs()
        altered = deepcopy(snapshot)
        original_ids = set()
        for index, table in enumerate(altered["tables"]):
            original_ids.add(table["id"])
            table["id"] = "tbl_" + format(index, "012x")
        rehash(altered)
        result = build_understand(raw, altered)
        expected = {table["id"] for table in altered["tables"]}
        self.assertEqual({role["tableId"] for role in result["roles"]}, expected)
        self.assertTrue(all(link["fromTable"] in expected and link["toTable"] in expected for link in result["relationships"]))
        self.assertTrue(all("id" not in table for table in raw))
        self.assertTrue(original_ids.isdisjoint(expected))

    def test_unsupported_pack_source_and_missing_finance_schema_are_rejected(self) -> None:
        raw, snapshot = inputs()
        for options in ({"pack_id": "unknown"}, {"pack_id": []}, {"pack_id": "fin-pl-v1"}, {"created_from": "llm"}):
            with self.assertRaises(ValueError):
                build_understand(raw, snapshot, **options)

    def test_hash_rejects_omitted_business_fields_and_undeclared_extensions(self) -> None:
        raw, snapshot = inputs()
        result = build_understand(raw, snapshot)
        for candidate in ({**result, "hashBasis": ["snapshotHash"]}, {**result, "hiddenPolicy": "unbound"}):
            with self.assertRaises(ValueError):
                understand_hash(candidate)
        missing = deepcopy(result)
        missing.pop("warnings")
        with self.assertRaises(ValueError):
            understand_hash(missing)

    def test_engine_does_not_open_network_connections(self) -> None:
        raw, snapshot = inputs()
        with patch.object(socket, "socket", side_effect=AssertionError("WL2 must remain local")):
            result = build_understand(raw, snapshot)
        self.assertEqual(result["snapshotHash"], snapshot["snapshotHash"])


if __name__ == "__main__":
    unittest.main()
