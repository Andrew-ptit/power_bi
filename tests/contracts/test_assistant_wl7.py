"""Golden chọn lọc và sáu phép kiểm chống Record giả cho WL7."""

import ast
from copy import deepcopy
from decimal import Decimal
import json
import math
import re
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_decisions import build_decisions
from pbip_assistant.sources.assistant_delta import changed_columns, compute_delta
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_profile import build_snapshot
from pbip_assistant.sources.assistant_reconcile import build_reconciliation
from pbip_assistant.sources.assistant_record import detect_stale, mark_stale, record_hash
from tests.support.paths import ROOT
from tests.unit.test_assistant_record import build, context
from tests.unit.test_assistant_spec import load


LABELS = {"unverified", "assumed", "out_of_scope", "stale"}
DROP = {"hashBasis", "variantOf", "variantReason"}
RAW_KEYS = {"rows", "cells", "sample", "samples", "raw", "rawcells", "raw_tables",
            "rawtables", "binary", "base64", "workbook", "workbook_bytes", "source_evidence"}


def changed_snapshot(data):
    """Nguồn mới chỉ nằm trong memory; fingerprint được dựng lại từ input đã đổi."""
    changed = deepcopy(data["data"][0])
    ledger = next(table for table in changed["tables"] if "DebitCredit" in table["header"])
    index = ledger["header"].index("Amount")
    ledger["rows"][0][index] = str(Decimal(ledger["rows"][0][index]) + Decimal("1"))
    for source in changed["sources"]:
        source["hash"] = canonical_hash([{"header": table["header"], "rows": table["rows"]}
            for table in changed["tables"] if table["sourceId"] == source["id"]])
    return build_snapshot(changed)


class AssistantWL7ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {scenario: context(scenario) for scenario in ("tp-fin", "tp-sales")}
        cls.records = {scenario: build(data) for scenario, data in cls.models.items()}

    def assert_golden(self, scenario, lengths):
        data, record = self.models[scenario], self.records[scenario]
        golden = load(scenario, "wl7_decision_record.json")
        self.assertEqual(set(record), set(golden))
        self.assertEqual(record["delta"], golden["delta"])
        self.assertEqual(record["snapshot"]["snapshotHash"], data["snapshot"]["snapshotHash"])
        self.assertEqual(record["snapshot"]["sourceFingerprint"], golden["snapshot"]["sourceFingerprint"])
        self.assertEqual(record["brief"], {key: data["brief"][key] for key in ("briefHash", "prompt")})
        self.assertEqual(record["decisions"], data["decisions"]["decisions"])
        self.assertEqual(record["assumptions"], data["brief"]["assumptions"])
        self.assertTrue({item["id"] for item in record["assumptions"]} <=
                        {item["id"] for item in data["brief"]["assumptions"]})
        self.assertEqual(record["steps"], data["spec"]["steps"])
        self.assertEqual(record["reconciliations"], [{key: value for key, value in data["reconciliation"].items()
                         if key not in DROP}])
        self.assertEqual([len(record[key]) for key in ("decisions", "assumptions", "steps", "reconciliations")], lengths)
        self.assertEqual(set(record["labels"]), set(golden["labels"]))
        self.assertIs(record["stale"], False)
        self.assertIsNone(record["variantOf"])
        self.assertIsNone(record["variantReason"])

    def test_golden_fin_record_uses_five_runtime_assumptions_as_user_confirmed(self):
        # Chỉ mốc assumptions FIN được người dùng đổi từ 8 sang 5; golden không bị sửa.
        self.assert_golden("tp-fin", [8, 5, 14, 1])
        self.assertEqual(len(load("tp-fin", "wl7_decision_record.json")["assumptions"]), 8)

    def test_golden_sales_record_exact_numeric_delta_refs_and_array_counts(self):
        self.assert_golden("tp-sales", [4, 3, 10, 1])

    def test_af_vf_001_delta_numbers_and_lineage_come_from_current_raw_result_and_spec(self):
        for scenario, data in self.models.items():
            delta = compute_delta(data["data"][0]["tables"], data["result"], data["spec"], scenario=scenario)
            self.assertEqual(delta, load(scenario, "wl7_decision_record.json")["delta"])
            self.assertEqual(set(delta["changedColumns"]), set(changed_columns(data["spec"])))
            self.assertTrue(all(type(delta[key]) is int for key in
                                ("rowsIn", "rowsOut", "duplicatesBefore", "duplicatesAfter")))
            declared = deepcopy(data["spec"])
            operation = "normalize_sign" if scenario == "tp-fin" else "resolve_territory"
            declared["steps"] = [step for step in declared["steps"] if step["params"]["operation"] != operation]
            self.assertNotEqual(set(changed_columns(declared)), set(delta["changedColumns"]))

    def test_af_vf_002_record_contains_bound_runtime_arrays_and_derived_metadata_only(self):
        for scenario, record in self.records.items():
            self.assertEqual(set(record), set(load(scenario, "wl7_decision_record.json")))
            self.assertEqual(record["decisions"], self.models[scenario]["decisions"]["decisions"])
            self.assertEqual(record["steps"], self.models[scenario]["spec"]["steps"])
            self.assertEqual(len(record["reconciliations"]), 1)
            self.assertFalse(DROP & set(record["reconciliations"][0]))
            self.assertRegex(record["id"], r"^rec_[a-f0-9]{24}$")
            self.assertEqual(record["brief"]["prompt"], self.models[scenario]["brief"]["prompt"])

    def scan_record(self, value):
        if isinstance(value, dict):
            self.assertFalse({key.casefold() for key in value} & RAW_KEYS)
            if "labels" in value:
                self.assertTrue(set(value["labels"]) <= LABELS)
            for key in ("label", "status"):
                if isinstance(value.get(key), str):
                    self.assertNotEqual(value[key].strip().casefold(), "verified")
            for child in value.values():
                self.scan_record(child)
        elif isinstance(value, list):
            for child in value:
                self.scan_record(child)
        elif isinstance(value, str):
            self.assertIsNone(re.search(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]", value))
            self.assertFalse(value.startswith(("/", "\\\\")))
            self.assertIsNone(re.search(r"(?<![\w:)/])/(?!/)[^\s]+", value))
            self.assertIsNone(re.search(r"(?<![\w:])//\S", value))
            self.assertNotIn("\\\\", value)
            self.assertNotIn("file://", value.casefold())
            self.assertNotIn(";base64,", value.casefold())
            self.assertIsNone(re.fullmatch(r"[A-Za-z0-9+/]{256,}={0,2}", value))
        else:
            self.assertTrue(value is None or type(value) in {bool, int, float})
            if type(value) is float:
                self.assertTrue(math.isfinite(value))

    def test_af_vf_003_recursive_record_never_labels_or_marks_status_verified(self):
        for record in self.records.values():
            self.scan_record(record)
            self.assertIn("unverified", record["labels"])
            for key in ("labels", "nested_label", "nested_status"):
                changed = deepcopy(record)
                if key == "labels":
                    changed["labels"] = ["verified"]
                else:
                    changed["assumptions"][0]["evidence"][0]["value"] = {
                        "label" if key == "nested_label" else "status": "verified"}
                with self.subTest(key=key), self.assertRaises(InputError):
                    record_hash(changed)

    def test_af_vf_004_hash_basis_is_complete_recomputable_and_json_audit_reopens(self):
        for record in self.records.values():
            self.assertEqual(set(record["hashBasis"]), set(record) - {"schemaVersion", "hashBasis", "hash"})
            self.assertEqual(len(record["hashBasis"]), len(set(record["hashBasis"])))
            self.assertEqual(record["hash"], canonical_hash({key: record[key] for key in record["hashBasis"]}))
            self.assertEqual(record_hash(record), record["hash"])
            serialized = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            reopened = json.loads(serialized)
            self.assertEqual(reopened, record)
            self.assertEqual(record_hash(reopened), record["hash"])

    def test_af_vf_005_source_change_returns_stale_and_mark_rehashes_immutable_copy(self):
        record = self.records["tp-fin"]
        before = deepcopy(record)
        diagnostic = detect_stale(record, current_snapshot=changed_snapshot(self.models["tp-fin"]))
        variant = load("variants", "fin_record_stale.json")
        self.assertEqual(diagnostic, {"code": variant["code"], "severity": "blocker", "reason": "sourceChanged"})
        marked = mark_stale(record, diagnostic["reason"])
        self.assertEqual(marked["stale"], variant["stale"])
        self.assertEqual(set(marked["labels"]), set(variant["labels"]))
        self.assertEqual(marked["variantReason"], "sourceChanged")
        self.assertNotEqual(marked["hash"], record["hash"])
        self.assertEqual(marked["hash"], record_hash(marked))
        self.assertEqual(record, before)
        self.assertEqual(detect_stale(marked), diagnostic)

    def test_antifake_delete_result_row_changes_delta_and_real_control_total(self):
        data = self.models["tp-fin"]
        result = deepcopy(data["result"])
        result["rows"].pop(next(i for i, row in enumerate(result["rows"]) if row[4] != 0))
        delta = compute_delta(data["data"][0]["tables"], result, data["spec"], scenario="tp-fin")
        self.assertEqual(delta["rowsOut"], self.records["tp-fin"]["delta"]["rowsOut"] - 1)
        reconcile = build_reconciliation(data["preview"], data["spec"], data["data"][0]["tables"], result)
        self.assertFalse(reconcile["controlTotalPassed"])
        self.assertFalse(reconcile["passed"])

    def test_antifake_blank_mapped_output_cells_increase_measured_null_after(self):
        for scenario, source, target in (("tp-fin", "PartnerEntity", "pnlLine"),
                                          ("tp-sales", "TerritoryID", "region"),
                                          ("tp-sales", "CustomerID", "customerCount")):
            data = self.models[scenario]
            result = deepcopy(data["result"])
            result["rows"][0][result["columns"].index(target)] = None
            delta = compute_delta(data["data"][0]["tables"], result, data["spec"], scenario=scenario)
            self.assertEqual(delta["nullsAfter"][source], data["delta"]["nullsAfter"][source] + 1)
            self.assertEqual(delta["nullsBefore"], data["delta"]["nullsBefore"])

    def test_antifake_changed_decision_hash_invalidates_original_record(self):
        data = self.models["tp-fin"]
        choices = {entry["subProblemId"]: entry["optionId"] for entry in data["decisions"]["decisions"]}
        choices["SP-1"] = "B"
        acks = {entry["subProblemId"]: entry["acknowledged"] for entry in data["decisions"]["acknowledgements"]}
        original = data["decisions"]["decisions"][0]
        metadata = {key: original[key] for key in ("decidedBy", "decidedAt", "rationale")}
        metadata["acknowledgementNotes"] = {entry["subProblemId"]: entry["note"]
                                           for entry in data["decisions"]["acknowledgements"]}
        changed = build_decisions(data["brief"], choices=choices, acknowledgements=acks,
                                  decision_metadata=metadata)
        expected = deepcopy(data["decisions"]["decisions"])
        next(entry for entry in expected if entry["subProblemId"] == "SP-1")["optionId"] = "B"
        self.assertEqual(changed["decisions"], expected)
        self.assertEqual(changed["acknowledgements"], data["decisions"]["acknowledgements"])
        self.assertNotEqual(changed["decisionsHash"], data["decisions"]["decisionsHash"])
        diagnostic = detect_stale(self.records["tp-fin"], current_decisions=changed)
        self.assertEqual(diagnostic, {"code": "AF_SPEC_STALE", "severity": "blocker", "reason": "decisionChanged"})
        marked = mark_stale(self.records["tp-fin"], diagnostic["reason"])
        self.assertNotEqual(marked["hash"], self.records["tp-fin"]["hash"])
        self.assertEqual(marked["hash"], record_hash(marked))

    def test_antifake_same_input_builds_same_id_hash_and_reopened_ref_checks_stay_valid(self):
        for scenario, data in self.models.items():
            first, second = build(data), build(data)
            self.assertEqual(first, second)
            reopened = json.loads(json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True))
            self.assertIsNone(detect_stale(reopened, current_snapshot=data["snapshot"],
                                         current_decisions=data["decisions"],
                                         current_source_evidence=data["source_evidence"]))
            self.assertEqual(record_hash(reopened), first["hash"])

    def test_record_has_no_raw_binary_source_material_or_absolute_path(self):
        for record in self.records.values():
            self.scan_record(record)
            for forbidden in (b"binary", {"rows": [["raw"]]}, "file:///private/source",
                              "Tham chiếu /synthetic/source.csv ở đây.",
                              "Tham chiếu /(synthetic)/source.csv ở đây.",
                              "Tham chiếu //synthetic-host/share/source.csv ở đây.",
                              r"Tham chiếu \\synthetic-host\share\source.csv ở đây."):
                changed = deepcopy(record)
                changed["assumptions"][0]["evidence"][0]["value"] = forbidden
                with self.assertRaises(InputError):
                    record_hash(changed)

    def test_changed_record_content_without_rehash_is_rejected_before_freshness_check(self):
        changed = deepcopy(self.records["tp-fin"])
        changed["delta"]["nullsAfter"]["PartnerEntity"] += 1
        with self.assertRaises(InputError):
            detect_stale(changed)

    def test_engine_offline_no_ai_com_or_file_io_during_record_build(self):
        forbidden = {"openai", "requests", "http", "urllib", "socket", "subprocess", "win32com", "ctypes"}
        for name in ("assistant_delta", "assistant_record"):
            source = (ROOT / "pbip_assistant/sources" / (name + ".py")).read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    self.assertFalse({alias.name.split(".")[0] for alias in node.names} & forbidden)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], forbidden)
            self.assertNotIn(".artifacts", source)
        with patch("builtins.open", side_effect=AssertionError("Engine không được mở file")):
            with patch("pathlib.Path.open", side_effect=AssertionError("Engine không được mở file")):
                with patch.object(socket.socket, "connect", side_effect=AssertionError("Không được gọi mạng")):
                    for data in self.models.values():
                        self.assertEqual(build(data)["hash"], record_hash(build(data)))


if __name__ == "__main__":
    unittest.main()
