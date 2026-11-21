"""Audit hành vi WL1–WL7; giữ failure thật thay vì thay đổi engine hoặc golden."""

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import sys
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_approval import consume_approval, issue_approval
from pbip_assistant.sources.assistant_brief import brief_hash, build_brief
from pbip_assistant.sources.assistant_decisions import build_decisions, freeze_blocked
from pbip_assistant.sources.assistant_execution import verify_graph
from pbip_assistant.sources.assistant_findings import formulas, measure_set, number
from pbip_assistant.sources.assistant_pack import load_pack, validate_pack
from pbip_assistant.sources.assistant_profile import snapshot_hash
from pbip_assistant.sources.assistant_reconcile import assert_approvable, build_reconciliation
from pbip_assistant.sources.assistant_record import detect_stale, record_hash
from pbip_assistant.sources.assistant_spec import build_spec, spec_fingerprint
from pbip_assistant.sources.assistant_understand import understand_hash
from tests.contracts import test_assistant_e2e as engine_e2e
from tests.support.paths import FIXTURES, ROOT
from tests.unit.test_assistant_record import build, context


STAMP = "2026-10-30T10:00:00+07:00"
HASHES = (("snapshot", "snapshotHash"), ("understand", "understandHash"),
          ("brief", "briefHash"), ("spec", "fingerprint"),
          ("preview", "previewHash"), ("reconciliation", "reconcileHash"))


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def state(paths):
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                   path.stat().st_size) for path in paths}


def artifact_map(data):
    return {**{key: data[key] for key in ("snapshot", "brief", "spec", "preview", "reconciliation")},
            "understand": data["data"][2], "record": build(data)}


class AssistantBehaviorGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {name: context(name) for name in ("tp-fin", "tp-sales")}

    def test_closed_status_provenance_label_and_step_kind_reject_invalid_values(self):
        for key in ("status", "provenance"):
            changed = load_pack("generic")
            changed["policies"][0][key] = "INVALID_ENUM"
            with self.subTest(enum=key), self.assertRaises(InputError):
                validate_pack(changed)
        changed = deepcopy(self.models["tp-fin"]["spec"])
        changed["labels"] = ["INVALID_ENUM"]
        with self.assertRaises(InputError):
            spec_fingerprint(changed)
        changed = deepcopy(self.models["tp-fin"]["spec"]["steps"])
        changed[0]["kind"] = "INVALID_ENUM"
        with self.assertRaises(InputError):
            verify_graph(changed)

    def test_invalid_relationship_cardinality_is_rejected_before_brief(self):
        data = self.models["tp-fin"]["data"]
        changed = deepcopy(data[2])
        changed["relationships"][0]["cardinality"] = "INVALID_CARDINALITY"
        # Hash hợp lệ không thay thế semantic enum validation tại boundary WL2→WL3.
        changed["understandHash"] = understand_hash(changed)
        self.assertNotEqual(changed["understandHash"], data[2]["understandHash"])
        with self.assertRaises((InputError, ValueError)):
            build_brief(data[0]["tables"], data[1], changed, data[3], "Đề bài synthetic.")

    def test_all_supported_relationship_cardinalities_pass_brief_boundary(self):
        data = self.models["tp-fin"]["data"]
        for cardinality in ("1:1", "1:N", "N:1", "N:N"):
            with self.subTest(cardinality=cardinality):
                changed = deepcopy(data[2])
                changed["relationships"][0]["cardinality"] = cardinality
                changed["understandHash"] = understand_hash(changed)
                brief = build_brief(data[0]["tables"], data[1], changed, data[3], "Đề bài synthetic.")
                self.assertEqual(brief["understandHash"], changed["understandHash"])
                self.assertEqual(brief["briefHash"], brief_hash(brief))

    def test_tamper_changes_artifact_hash_and_cached_record_or_spec_is_stale(self):
        data = self.models["tp-fin"]
        record = build(data)
        changed = deepcopy(record)
        changed["assumptions"][0]["statement"] += " Nội dung đã đổi."
        self.assertNotEqual(record_hash(changed), record["hash"])
        with self.assertRaises(InputError):
            detect_stale(changed)
        spec = deepcopy(data["spec"])
        spec["steps"][0]["label"] += " Nội dung đã đổi."
        self.assertNotEqual(spec_fingerprint(spec), spec["fingerprint"])
        with self.assertRaises(InputError) as caught:
            issue_approval(spec, data["preview"], approved_by="user", approved_at=STAMP)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")
        brief = deepcopy(data["brief"])
        brief["prompt"] += " Đề bài khác."
        self.assertNotEqual(brief_hash(brief), brief["briefHash"])
        snapshot = deepcopy(data["snapshot"])
        snapshot["sources"][0]["name"] += "_changed"
        self.assertNotEqual(snapshot_hash(snapshot), snapshot["snapshotHash"])

    def test_all_assistant_source_modules_stay_stdlib_offline_and_never_open_for_write(self):
        modules = sorted((ROOT / "pbip_assistant/sources").glob("assistant_*.py"))
        self.assertGreaterEqual(len(modules), 17)
        forbidden = {"openai", "requests", "http", "urllib", "socket", "subprocess",
                     "win32com", "ctypes", "ssl", "ftplib"}
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(module=path.name):
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots = {entry.name.split(".")[0] for entry in node.names}
                    elif isinstance(node, ast.ImportFrom):
                        roots = set() if node.level else {(node.module or "").split(".")[0]}
                    else:
                        roots = set()
                    self.assertFalse(roots & forbidden)
                    self.assertTrue(roots <= (sys.stdlib_module_names | {"pbip_assistant"}))
                    if not isinstance(node, ast.Call):
                        continue
                    name = node.func.id if isinstance(node.func, ast.Name) else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else "")
                    self.assertNotIn(name, {"write_bytes", "write_text", "system", "exec", "eval", "__import__"})
                    if name == "open":
                        index = 1 if isinstance(node.func, ast.Name) else 0
                        mode = next((item.value for item in node.keywords if item.arg == "mode"),
                                    node.args[index] if len(node.args) > index else ast.Constant("r"))
                        self.assertIsInstance(mode, ast.Constant)
                        self.assertIn(mode.value, {"r", "rb", "rt"})

    def test_all_seven_artifacts_repeat_with_identical_hashes_and_content(self):
        for scenario, first_data in self.models.items():
            first = artifact_map(first_data)
            second = artifact_map(context(scenario))
            with self.subTest(scenario=scenario):
                for name, field in (*HASHES, ("record", "hash")):
                    self.assertEqual(first[name][field], second[name][field], name)
                    self.assertEqual(first[name], second[name], name)
                self.assertEqual(first["record"]["hash"], record_hash(first["record"]))

    def test_complete_positive_journeys_preserve_every_fixture_byte_and_mtime(self):
        paths = sorted(path for path in FIXTURES.rglob("*") if path.is_file())
        before = state(paths)
        # Dùng hành trình bytes thật có source/read-back/temp cleanup assertions đã có.
        journey = engine_e2e.AssistantEngineE2ETests()
        journey.positive_flow("tp-fin", (23, 9), "PnL_Result")
        journey.positive_flow("tp-sales", (4, 4), "Sales_Result")
        self.assertEqual(state(paths), before)
        self.assertEqual(sorted(path for path in FIXTURES.rglob("*") if path.is_file()), paths)

    def test_every_formula_value_matches_engine_and_packs_cannot_supply_money(self):
        for scenario, data in self.models.items():
            measures = measure_set(data["data"][0]["tables"], data["snapshot"])
            registry = {entry["formulaId"]: entry for entry in formulas(measures)}
            seen = 0
            for node in walk(data["brief"]):
                formula = node.get("formulaId")
                if formula is not None:
                    self.assertIn(formula, registry)
                    if node.get("value") is not None:
                        measured = measures[formula.removeprefix("fm_")]
                        self.assertIsNotNone(measured)
                        self.assertEqual(Decimal(str(node["value"])),
                                         Decimal(number(measured, registry[formula]["unit"])))
                        seen += 1
            self.assertGreater(seen, 0, scenario)
            for node in walk(build(data)):
                if "labels" in node:
                    self.assertTrue(set(node["labels"]) <= {"unverified", "assumed", "out_of_scope", "stale"})
                for key in ("label", "status"):
                    self.assertNotEqual(node.get(key), "verified")
        for amount in (Decimal("1234567"), "1234567 VND"):
            pack = load_pack("generic")
            pack["insights"][0]["statement"] = str(amount) + " VND"
            with self.assertRaises(InputError):
                validate_pack(pack)

    def test_failed_reconciliation_and_reused_approval_do_not_grant_write(self):
        data = self.models["tp-fin"]
        failed = build_reconciliation(data["preview"], data["spec"], data["data"][0]["tables"],
                                      data["result"], injected_drift="1234560")
        with self.assertRaises(InputError) as caught:
            assert_approvable(failed)
        self.assertEqual(caught.exception.code, "AF_RECONCILE_FAILED")
        approval = issue_approval(data["spec"], data["preview"], approved_by="user", approved_at=STAMP)
        consume_approval(approval)
        with self.assertRaises(InputError) as caught:
            consume_approval(approval)
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_nopack_and_unresolved_policies_fail_closed_without_finance_fabrication(self):
        data = self.models["tp-fin"]["data"]
        with patch("pbip_assistant.sources.assistant_brief.measure_set",
                   side_effect=AssertionError("Không đo số khi pack không khớp.")):
            with self.assertRaises(InputError) as caught:
                build_brief(data[0]["tables"], data[1], data[2], load_pack("generic"), "Đề bài synthetic.")
        self.assertEqual(caught.exception.code, "AF_BRIEF_INVALID")
        unresolved = {"SP-1", "SP-2", "SP-3"}
        brief = build_brief(data[0]["tables"], data[1], data[2], data[3], "Đề bài synthetic.",
                            policy_unresolved=unresolved)
        decisions = build_decisions(brief, choices={}, acknowledgements={},
                                   decision_metadata={"decidedBy": "user", "decidedAt": STAMP})
        self.assertEqual(decisions["decisions"], [])
        self.assertTrue(freeze_blocked(brief, decisions)["blocked"])
        self.assertTrue(all(item["chosenOptionId"] is None for item in brief["subProblems"]
                            if item["id"] in unresolved))
        with self.assertRaises(InputError) as caught:
            build_spec(brief, decisions, data[3], created_at=STAMP)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")


if __name__ == "__main__":
    unittest.main()
