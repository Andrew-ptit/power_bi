"""Kiểm Decision Record từ artifact runtime synthetic, không sửa nguồn/golden."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_delta import compute_delta
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_preview import build_preview, result_rows
from pbip_assistant.sources.assistant_profile import build_snapshot
from pbip_assistant.sources.assistant_reconcile import build_reconciliation
from pbip_assistant.sources import assistant_record as engine
from pbip_assistant.sources.assistant_record import build_record, detect_stale, mark_stale, record_hash
from tests.support.paths import FIXTURES
from tests.unit.test_assistant_brief import inputs, make
from tests.unit.test_assistant_preview import marker, read_source_evidence
from tests.unit.test_assistant_spec import create, load, model


STAMP = "2026-10-29T10:05:00+07:00"


def context(scenario="tp-fin"):
    data = inputs(scenario)
    brief = make(data, prompt=load(scenario, "wl3_brief.json")["prompt"])
    decision_model = model(scenario, brief=brief)
    decisions, pack = decision_model[1:]
    spec = create(decision_model, scenario)
    result = result_rows(data[0]["tables"], spec, decisions, pack)
    evidence = read_source_evidence(scenario)
    sheet = "PnL_Preview" if scenario == "tp-fin" else "Sales_Preview"
    preview = build_preview(result, spec, data[1], sheet=sheet, marker=marker(spec, sheet), source_evidence=evidence)
    reconciliation = build_reconciliation(preview, spec, data[0]["tables"], result)
    delta = compute_delta(data[0]["tables"], result, spec, scenario=scenario)
    return {"data": data, "snapshot": data[1], "brief": brief, "decisions": decisions, "spec": spec,
            "reconciliation": reconciliation, "delta": delta, "source_evidence": evidence,
            "preview": preview, "result": result}


def build(data, **changes):
    values = {key: data[key] for key in ("snapshot", "brief", "decisions", "spec", "reconciliation", "delta")}
    values.update(created_at=STAMP, source_evidence=data["source_evidence"])
    values.update(changes)
    return build_record(**values)


def rehash(value, key="reconcileHash"):
    value[key] = canonical_hash({field: value[field] for field in value["hashBasis"]})
    return value


class AssistantRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contexts = {scenario: context(scenario) for scenario in ("tp-fin", "tp-sales")}
        cls.records = {scenario: build(data) for scenario, data in cls.contexts.items()}

    def test_runtime_record_shape_bindings_lengths_and_exact_artifact_projections(self):
        for scenario, data in self.contexts.items():
            record = self.records[scenario]
            golden = load(scenario, "wl7_decision_record.json")
            self.assertEqual(set(record), set(golden))
            self.assertEqual([len(record[key]) for key in ("decisions", "assumptions", "steps", "reconciliations")],
                             [8, 5, 14, 1] if scenario == "tp-fin" else [4, 3, 10, 1])
            self.assertEqual(record["snapshot"]["snapshotHash"], data["snapshot"]["snapshotHash"])
            self.assertEqual(record["snapshot"]["sourceFingerprint"], golden["snapshot"]["sourceFingerprint"])
            self.assertEqual(record["brief"], {key: data["brief"][key] for key in ("briefHash", "prompt")})
            self.assertEqual(record["decisions"], data["decisions"]["decisions"])
            self.assertEqual(record["assumptions"], data["brief"]["assumptions"])
            self.assertEqual(record["steps"], data["spec"]["steps"])
            self.assertEqual(record["reconciliations"], [{key: value for key, value in data["reconciliation"].items()
                             if key not in {"hashBasis", "variantOf", "variantReason"}}])
            self.assertEqual(set(record["labels"]), set(golden["labels"]))
            self.assertFalse(record["stale"])

    def test_identity_and_hash_determinism_include_all_metadata_without_hidden_clock(self):
        for scenario, data in self.contexts.items():
            first, second = build(data), build(data)
            self.assertEqual(first, second)
            self.assertRegex(first["id"], r"^rec_[a-f0-9]{24}$")
            expected = canonical_hash({"snapshotHash": data["snapshot"]["snapshotHash"],
                                       "briefHash": data["brief"]["briefHash"],
                                       "decisionsHash": data["decisions"]["decisionsHash"]})
            self.assertEqual(first["id"], "rec_" + expected[7:31])
            later = build(data, created_at="2026-10-29T11:00:00+07:00")
            self.assertEqual(later["id"], first["id"])
            self.assertNotEqual(later["hash"], first["hash"])
            self.assertEqual(first["hash"], record_hash(first))

    def test_canonical_json_roundtrip_keeps_hash_and_all_artifact_fields(self):
        for record in self.records.values():
            serialized = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            loaded = json.loads(serialized)
            self.assertEqual(loaded, record)
            self.assertEqual(record_hash(loaded), record["hash"])
            self.assertEqual(record["hash"], canonical_hash({k: record[k] for k in record["hashBasis"]}))

    def test_hash_basis_is_closed_complete_and_cannot_hide_unbound_fields(self):
        original = self.records["tp-fin"]
        for field in ("decisions", "steps", "snapshot", "delta", "labels", "variantReason"):
            changed = deepcopy(original)
            changed["hashBasis"].remove(field)
            with self.subTest(field=field), self.assertRaises(InputError):
                record_hash(changed)
        with self.assertRaises(InputError):
            record_hash({**original, "unboundPolicy": "B"})

    def test_source_amount_mutation_rebuilds_snapshot_and_marks_record_stale(self):
        data = self.contexts["tp-fin"]
        changed = deepcopy(data["data"][0])
        ledger = next(table for table in changed["tables"] if "DebitCredit" in table["header"])
        ledger["rows"][0][ledger["header"].index("Amount")] = "1234567"
        for source in changed["sources"]:
            source["hash"] = canonical_hash([{"header": table["header"], "rows": table["rows"]}
                for table in changed["tables"] if table["sourceId"] == source["id"]])
        snapshot = build_snapshot(changed)
        before = deepcopy(self.records["tp-fin"])
        diagnostic = detect_stale(before, current_snapshot=snapshot)
        self.assertEqual(diagnostic, {"code": "AF_SPEC_STALE", "severity": "blocker", "reason": "sourceChanged"})
        stale = mark_stale(before, diagnostic["reason"])
        self.assertTrue(stale["stale"])
        self.assertIn("stale", stale["labels"])
        self.assertNotEqual(stale["hash"], before["hash"])
        self.assertEqual(stale["hash"], record_hash(stale))
        self.assertEqual(before, self.records["tp-fin"])

    def test_same_full_snapshot_and_verified_sales_evidence_do_not_false_positive_stale(self):
        for scenario, data in self.contexts.items():
            record = self.records[scenario]
            self.assertIsNone(detect_stale(record, current_snapshot=data["snapshot"]))
            self.assertIsNone(detect_stale(record, current_snapshot=data["snapshot"],
                                           current_source_evidence=data["source_evidence"]))
            self.assertIsNone(detect_stale(record, current_snapshot=record["snapshot"]))

    def test_explicit_source_fingerprint_change_is_stale_even_at_same_snapshot_reference(self):
        record = self.records["tp-sales"]
        current = {**record["snapshot"], "sourceFingerprint": canonical_hash("synthetic changed content")}
        self.assertEqual(detect_stale(record, current_snapshot=current)["reason"], "sourceChanged")

    def test_source_hash_or_original_material_tamper_is_not_treated_as_current(self):
        record = self.records["tp-sales"]
        data = self.contexts["tp-sales"]
        snapshot = deepcopy(data["snapshot"])
        snapshot["sources"][0]["hash"] = canonical_hash("changed")
        self.assertEqual(detect_stale(record, current_snapshot=snapshot)["reason"], "sourceChanged")
        evidence = deepcopy(data["source_evidence"])
        evidence[next(iter(evidence))] += "\n"
        self.assertEqual(detect_stale(record, current_snapshot=data["snapshot"],
                                      current_source_evidence=evidence)["reason"], "sourceChanged")

    def test_capture_timestamp_changes_excluded_by_wl1_hash_do_not_fake_source_change(self):
        for scenario, data in self.contexts.items():
            current = deepcopy(data["snapshot"])
            current["snapshot"]["createdAt"] = "2026-10-29T12:00:00Z"
            for source in current["sources"]:
                source["addedAt"] = "2026-10-29T12:00:00Z"
            self.assertIsNone(detect_stale(self.records[scenario], current_snapshot=current))

    def test_changed_sp1_decision_hash_is_detected_from_bound_record_identity(self):
        for scenario, data in self.contexts.items():
            changed = model(scenario, brief=data["brief"], overrides={"SP-1": "B"})[1]
            self.assertIsNone(detect_stale(self.records[scenario], current_decisions=data["decisions"]))
            self.assertEqual(detect_stale(self.records[scenario], current_decisions=changed),
                             {"code": "AF_SPEC_STALE", "severity": "blocker", "reason": "decisionChanged"})
            self.assertEqual(detect_stale(self.records[scenario], current_decisions={"decisionsHash": changed["decisionsHash"]})["reason"],
                             "decisionChanged")
            wrong_basis = deepcopy(data["decisions"])
            wrong_basis["hashBasis"] = ["decisionsHash"]
            self.assertEqual(detect_stale(self.records[scenario], current_decisions=wrong_basis)["reason"], "decisionChanged")

    def test_mark_stale_is_copy_recomputed_and_does_not_revalidate_already_stale_record(self):
        for reason in ("sourceChanged", "decisionChanged"):
            original = self.records["tp-fin"]
            before = deepcopy(original)
            stale = mark_stale(original, reason)
            self.assertNotEqual(stale["hash"], original["hash"])
            self.assertEqual(stale["variantReason"], reason)
            self.assertEqual(detect_stale(stale), {"code": "AF_SPEC_STALE", "severity": "blocker", "reason": reason})
            self.assertEqual(mark_stale(stale, reason), stale)
            stale["delta"]["rowsOut"] += 1
            self.assertEqual(original, before)

    def test_cached_hash_tamper_is_rejected_by_freshness_and_marking(self):
        record = deepcopy(self.records["tp-fin"])
        record["brief"]["prompt"] += " Revision khác"
        self.assertNotEqual(record["hash"], record_hash(record))
        for action in (lambda: detect_stale(record), lambda: mark_stale(record, "sourceChanged")):
            with self.assertRaises(InputError):
                action()

    def test_created_at_requires_explicit_iso_timezone_and_preserves_caller_metadata(self):
        for stamp in (None, "", 123, "invalid", "2026-10-29", "2026-10-29T12:00:00"):
            with self.subTest(stamp=stamp), self.assertRaises(InputError):
                build(self.contexts["tp-fin"], created_at=stamp)
        self.assertEqual(self.records["tp-fin"]["createdAt"], STAMP)

    def test_different_decisions_or_brief_cannot_be_attached_to_existing_spec(self):
        data = self.contexts["tp-fin"]
        changed = model(brief=data["brief"], overrides={"SP-1": "B"})[1]
        with self.assertRaises(InputError) as caught:
            build(data, decisions=changed)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        brief = deepcopy(data["brief"])
        brief["prompt"] += " changed"
        with self.assertRaises(InputError):
            build(data, brief=brief)

    def test_failed_or_mismatched_reconciliation_cannot_become_final_record(self):
        data = self.contexts["tp-fin"]
        changed = deepcopy(data["reconciliation"])
        changed["specFingerprint"] = canonical_hash("another spec")
        rehash(changed)
        with self.assertRaises(InputError) as caught:
            build(data, reconciliation=changed)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        failed = build_reconciliation(data["preview"], data["spec"], data["data"][0]["tables"],
                                      data["result"], injected_drift=1)
        with self.assertRaises(InputError):
            build(data, reconciliation=failed)

    def test_delta_counts_duplicates_and_lineage_must_match_artifacts(self):
        for field, value in (("rowsOut", 99), ("rowsIn", 33), ("duplicatesBefore", 2), ("duplicatesAfter", 1),
                             ("changedColumns", ["Unknown→madeUp"])):
            delta = deepcopy(self.contexts["tp-fin"]["delta"])
            delta[field] = value
            with self.subTest(field=field), self.assertRaises(InputError):
                build(self.contexts["tp-fin"], delta=delta)

    def test_no_verified_label_or_status_can_exist_anywhere_in_record(self):
        for location in ("labels", "step_label", "step_status", "nested_labels"):
            record = deepcopy(self.records["tp-fin"])
            if location == "labels":
                record["labels"] = ["verified"]
            elif location == "step_label":
                record["steps"][0]["label"] = "Verified"
            elif location == "step_status":
                record["steps"][0]["status"] = "verified"
            else:
                record["reconciliations"][0]["labels"] = ["verified"]
            with self.subTest(location=location), self.assertRaises(InputError):
                record_hash(record)
        for record in self.records.values():
            self.assertTrue(set(record["labels"]) <= {"unverified", "assumed", "out_of_scope", "stale"})
            self.assertIn("unverified", record["labels"])

    def test_record_rejects_raw_cells_binary_base64_absolute_paths_and_unbound_fields(self):
        samples = ["C:\\private\\source.xlsx", "/private/source.xlsx", "base64:AAAA", b"binary",
                   "data:application/octet-stream;base64,AAAA", "A" * 300, "invalid\x00text",
                   "Nguồn nằm tại /private/synthetic/source.xlsx trong ví dụ.",
                   r"Nguồn nằm tại \\synthetic-server\share\source.xlsx trong ví dụ.",
                   "Nguồn: '/dữ_liệu/synthetic.xlsx'.", "Nguồn=//synthetic-server/share/source.xlsx",
                   "Nguồn: '/(synthetic)/source.xlsx' trong ví dụ."]
        for sample in samples:
            record = deepcopy(self.records["tp-fin"])
            record["brief"]["prompt"] = sample
            with self.subTest(kind=type(sample).__name__), self.assertRaises(InputError):
                record_hash(record)
        for sample in samples[-5:]:
            record = deepcopy(self.records["tp-fin"])
            record["assumptions"][0]["evidence"] = [
                {"kind": "source", "value": sample, "ref": None, "formulaId": None}]
            with self.subTest(location="evidence"), self.assertRaises(InputError):
                record_hash(record)
        for text in ("actual / budget", "A/B", "NetRevenue/COGS", "1/2", "(actual)/(budget)",
                     "Tỷ lệ: actual / budget và nợ/có; kỳ 29/10/2026.", "Nguồn public https://example.test/guide"):
            record = deepcopy(self.records["tp-fin"])
            record["brief"]["prompt"] = text
            self.assertRegex(record_hash(record), r"^sha256:[a-f0-9]{64}$")
        record = deepcopy(self.records["tp-fin"])
        record["assumptions"][0]["rawCells"] = [["private"]]
        with self.assertRaises(InputError):
            record_hash(record)
        with patch.object(engine, "MAX_RECORD_BYTES", 1), self.assertRaises(InputError):
            record_hash(self.records["tp-fin"])

    def test_projected_reconciliation_hash_remains_checked_after_roundtrip(self):
        record = deepcopy(self.records["tp-fin"])
        record["reconciliations"][0]["controlTotalResult"] = "0"
        with self.assertRaises(InputError):
            record_hash(record)

    def test_record_and_mark_stale_results_share_no_mutable_state_with_inputs(self):
        data = self.contexts["tp-fin"]
        before = deepcopy(data)
        result = build(data)
        result["steps"][0]["params"]["operation"] = "changed"
        result["assumptions"][0]["statement"] = "changed"
        result["decisions"][0]["rationale"] = "changed"
        self.assertEqual(data, before)

    def test_malformed_record_inputs_and_unknown_stale_reasons_raise_inputerror(self):
        for value in (None, {}, [], "record"):
            with self.assertRaises(InputError):
                record_hash(value)
        for reason in (None, [], {}, "unknown", "C:\\private\\source"):
            with self.assertRaises(InputError):
                mark_stale(self.records["tp-fin"], reason)
        for field, value in (("source", []), ("risk", [])):
            record = deepcopy(self.records["tp-fin"])
            record["assumptions"][0][field] = value
            with self.assertRaises(InputError):
                record_hash(record)

    def test_source_evidence_is_optional_verified_and_never_stored(self):
        data = self.contexts["tp-sales"]
        default = build(data, source_evidence=None)
        self.assertEqual(default["snapshot"]["sourceFingerprint"],
                         canonical_hash([source["hash"] for source in data["snapshot"]["sources"]]))
        self.assertNotIn("source_evidence", self.records["tp-sales"])
        evidence = deepcopy(data["source_evidence"])
        evidence[next(iter(evidence))] += "\n"
        with self.assertRaises(InputError):
            build(data, source_evidence=evidence)
        with self.assertRaises(InputError):
            detect_stale(self.records["tp-sales"], current_source_evidence=data["source_evidence"])

    def test_source_sha_mtime_and_engine_no_file_or_network_io(self):
        root = FIXTURES / "assistant"
        paths = [path for scenario in self.contexts for path in (root / scenario / "source").rglob("*.csv")]
        paths += [root / scenario / "wl1_snapshot.json" for scenario in self.contexts]
        state = lambda: {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        before = state()
        with patch("builtins.open", side_effect=AssertionError("Record không mở file")):
            with patch.object(Path, "open", side_effect=AssertionError("Record không mở file")):
                with patch.object(socket.socket, "connect", side_effect=AssertionError("Record không gọi mạng")):
                    for data in self.contexts.values():
                        record = build(data)
                        self.assertEqual(record["hash"], record_hash(record))
                        self.assertIsNone(detect_stale(record, current_snapshot=data["snapshot"], current_decisions=data["decisions"]))
                        self.assertTrue(mark_stale(record, "sourceChanged")["stale"])
        self.assertEqual(state(), before)


if __name__ == "__main__":
    unittest.main()
