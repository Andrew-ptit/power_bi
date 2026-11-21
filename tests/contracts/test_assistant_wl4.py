"""Golden chọn lọc và chống compile tĩnh cho engine WL4 tất định."""

import ast
from copy import deepcopy
import hashlib
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_decisions import (
    decisions_hash, freeze_blocked, invalidate_message, validate_decisions,
)
from pbip_assistant.sources.assistant_execution import compile_steps, verify_graph
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_spec import spec_fingerprint
from tests.support.paths import ROOT
from tests.unit.test_assistant_brief import inputs, make
from tests.unit.test_assistant_spec import GOLDEN, create, load, model


def states(paths):
    return {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns,
                   path.stat().st_size) for path in paths}


class AssistantWL4ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = {scenario: inputs(scenario) for scenario in ("tp-fin", "tp-sales")}
        cls.briefs = {scenario: make(data, prompt=load(scenario, "wl3_brief.json")["prompt"])
                      for scenario, data in cls.data.items()}
        cls.models = {scenario: model(scenario, brief=brief) for scenario, brief in cls.briefs.items()}
        cls.specs = {scenario: create(data, scenario) for scenario, data in cls.models.items()}

    def golden(self, scenario, count):
        result = self.specs[scenario]
        expected = load(scenario, "wl4_execution_spec.json")
        decisions = self.models[scenario][1]
        golden_decisions = load(scenario, "wl3_decisions.json")
        self.assertEqual(len(result["steps"]), count)
        for field in ("kind", "decisionRefs", "status", "guard"):
            self.assertEqual([step[field] for step in result["steps"]],
                             [step[field] for step in expected["steps"]], scenario + ": " + field)
        for field in ("decisions", "acknowledgements", "freezeBlocked"):
            self.assertEqual(decisions[field], golden_decisions[field], scenario + ": " + field)
        self.assertFalse(freeze_blocked(self.briefs[scenario], decisions)["blocked"])
        self.assertEqual(result["snapshotHash"], self.data[scenario][1]["snapshotHash"])
        self.assertEqual(result["briefHash"], self.briefs[scenario]["briefHash"])
        self.assertEqual(result["decisionsHash"], decisions["decisionsHash"])
        verify_graph(result["steps"])

    def test_golden_fin_14_steps_kinds_refs_status_and_decision_audit(self):
        self.golden("tp-fin", 14)

    def test_golden_sales_10_steps_kinds_refs_status_and_decision_audit(self):
        self.golden("tp-sales", 10)

    def test_af_fz_001_spec_binds_valid_current_snapshot_brief_and_decisions(self):
        for scenario, (brief, decisions, _) in self.models.items():
            validate_decisions(brief, decisions)
            result = self.specs[scenario]
            self.assertEqual(result["snapshotHash"], brief["snapshotHash"])
            self.assertEqual(result["briefHash"], brief["briefHash"])
            self.assertEqual(result["decisionsHash"], decisions_hash(decisions))
            self.assertFalse(decisions["freezeBlocked"])
            self.assertFalse(result["stale"])
            self.assertIsNone(result["variantOf"])
            self.assertIsNone(result["variantReason"])

    def test_af_fz_002_every_executable_decision_maps_to_step_and_chosen_parameter(self):
        for scenario, (_, decisions, _) in self.models.items():
            choices = {entry["subProblemId"]: entry["optionId"] for entry in decisions["decisions"]}
            seen = set()
            for step in self.specs[scenario]["steps"]:
                expected = {identifier: choices[identifier] for identifier in step["decisionRefs"]}
                self.assertEqual(step["params"]["chosenOptions"], expected)
                selected = set(expected.values())
                self.assertEqual(step["params"]["chosenOptionId"], next(iter(selected)) if len(selected) == 1 else None)
                seen.update(expected)
            self.assertEqual(seen, set(choices))

    def test_af_fz_003_dependencies_and_inputs_precede_consumers_without_orphans(self):
        for result in self.specs.values():
            seen, outputs = set(), set()
            for index, step in enumerate(result["steps"]):
                self.assertTrue(set(step["dependsOn"]) <= seen)
                if index:
                    self.assertTrue(outputs.intersection(step["inputs"]))
                else:
                    self.assertEqual(step["dependsOn"], [])
                self.assertNotIn(step["id"], seen)
                self.assertNotIn(step["output"], outputs)
                seen.add(step["id"])
                outputs.add(step["output"])
        steps = self.specs["tp-fin"]["steps"]
        group_index = next(i for i, step in enumerate(steps) if step["kind"] == "group")
        budget_index = next(i for i, step in enumerate(steps) if step["params"]["operation"] == "join_budget")
        self.assertLess(group_index, budget_index)
        self.assertIn(steps[group_index]["id"], steps[budget_index]["dependsOn"])
        self.assertIn(steps[group_index]["output"], steps[budget_index]["inputs"])
        self.assertEqual(steps[group_index]["params"]["columns"], steps[budget_index]["params"]["rightGrain"])

    def test_af_fz_004_changed_decision_invalidates_old_spec_immutably(self):
        original = self.specs["tp-fin"]
        before = deepcopy(original)
        changed = model(brief=self.briefs["tp-fin"], overrides={"SP-1": "B"})[1]
        diagnostic = invalidate_message(original, changed)
        self.assertEqual(diagnostic["code"], "AF_SPEC_STALE")
        self.assertTrue(diagnostic["stale"])
        self.assertEqual(diagnostic["severity"], "blocker")
        self.assertEqual(diagnostic["expected"], original["decisionsHash"])
        self.assertEqual(diagnostic["actual"], changed["decisionsHash"])
        self.assertEqual(original, before)

    def test_af_fz_005_same_inputs_and_creation_metadata_compile_idempotently(self):
        for scenario, data in self.models.items():
            repeated = create(data, scenario)
            self.assertEqual(repeated, self.specs[scenario])
            self.assertEqual(repeated["fingerprint"], self.specs[scenario]["fingerprint"])

    def test_af_fz_006_unresolved_assumptions_have_unverified_label_and_existing_ids(self):
        for scenario, result in self.specs.items():
            identifiers = {entry["id"] for entry in self.briefs[scenario]["assumptions"]}
            self.assertTrue(result["unverifiedAssumptions"])
            self.assertTrue(set(result["unverifiedAssumptions"]) <= identifiers)
            self.assertEqual(len(set(result["unverifiedAssumptions"])), len(result["unverifiedAssumptions"]))
            self.assertIn("unverified", result["labels"])
            self.assertNotIn("verified", result["labels"])

    def test_antistatic_sp1_b_changes_fingerprint_and_actual_step_option(self):
        changed = create(model(brief=self.briefs["tp-fin"], overrides={"SP-1": "B"}))
        self.assertNotEqual(changed["fingerprint"], self.specs["tp-fin"]["fingerprint"])
        bound = [step for step in changed["steps"] if "SP-1" in step["decisionRefs"]]
        self.assertTrue(bound)
        self.assertTrue(all(step["params"]["chosenOptionId"] == "B" for step in bound))
        self.assertTrue(all(step["params"]["chosenOptions"]["SP-1"] == "B" for step in bound))

    def test_antistatic_invalidation_matches_variant_code_and_stale_semantics(self):
        expected = load("variants", "fin_spec_invalidated.json")
        changed = model(brief=self.briefs["tp-fin"], overrides={"SP-1": "B"})[1]
        actual = invalidate_message(self.specs["tp-fin"], changed)
        self.assertTrue(expected["stale"])
        self.assertEqual(actual["stale"], expected["stale"])
        self.assertEqual(actual["code"], expected["code"])
        self.assertEqual(actual["invalidatedBy"], expected["invalidatedBy"])

    def test_antistatic_swapped_group_and_budget_raise_fanout_without_repair(self):
        steps = deepcopy(self.specs["tp-fin"]["steps"])
        group = next(i for i, step in enumerate(steps) if step["kind"] == "group")
        budget = next(i for i, step in enumerate(steps) if step["params"]["operation"] == "join_budget")
        steps[group], steps[budget] = steps[budget], steps[group]
        before = deepcopy(steps)
        with self.assertRaises(InputError) as caught:
            verify_graph(steps)
        self.assertEqual(caught.exception.code, "AF_FANOUT_RISK")
        self.assertEqual(steps, before)

    def test_antistatic_missing_sp3_blocks_freeze_and_never_chooses_recommended_a(self):
        data = model(brief=self.briefs["tp-fin"], omit="SP-3")
        self.assertTrue(next(p for p in data[0]["subProblems"] if p["id"] == "SP-3")["blocker"])
        self.assertTrue(freeze_blocked(data[0], data[1])["blocked"])
        before = deepcopy(data)
        with self.assertRaises(InputError) as caught:
            compile_steps(*data)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")
        with self.assertRaises(InputError):
            create(data)
        self.assertEqual(data, before)

    def test_fingerprint_recomputes_with_canonical_declared_basis_for_both_packs(self):
        for result in self.specs.values():
            self.assertEqual(result["fingerprint"], canonical_hash({k: result[k] for k in result["hashBasis"]}))
            self.assertEqual(result["fingerprint"], spec_fingerprint(result))

    def test_legacy_golden_decision_artifact_binds_its_actual_eight_field_hash(self):
        for scenario in self.specs:
            brief = load(scenario, "wl3_brief.json")
            golden_decisions = load(scenario, "wl3_decisions.json")
            pack = self.models[scenario][2]
            self.assertEqual(golden_decisions["decisionsHash"], decisions_hash(golden_decisions))
            validate_decisions(brief, golden_decisions)
            result = create((brief, golden_decisions, pack), scenario)
            self.assertEqual(result["decisionsHash"], golden_decisions["decisionsHash"])
            self.assertEqual(result["snapshotHash"], brief["snapshotHash"])
            self.assertEqual(result["briefHash"], brief["briefHash"])

    def test_mixed_fx_options_keep_per_sp_map_without_inventing_scalar(self):
        result = create(model(brief=self.briefs["tp-fin"], overrides={"SP-2": "B", "SP-8": "A"}))
        fx = next(step for step in result["steps"] if step["params"]["operation"] == "lookup_fx")
        self.assertEqual(fx["params"]["chosenOptions"], {"SP-2": "B", "SP-8": "A"})
        self.assertIsNone(fx["params"]["chosenOptionId"])
        self.assertNotEqual(result["fingerprint"], self.specs["tp-fin"]["fingerprint"])

    def test_complete_choices_without_audit_metadata_remain_draft_and_block_final_spec(self):
        data = model(brief=self.briefs["tp-fin"], metadata=False)
        validate_decisions(data[0], data[1])
        self.assertTrue(data[1]["freezeBlocked"])
        with self.assertRaises(InputError) as caught:
            create(data)
        self.assertEqual(caught.exception.code, "AF_MISSING_DATA")

    def test_current_brief_revision_changes_spec_and_cannot_reuse_previous_decisions(self):
        changed_brief = make(self.data["tp-fin"], prompt="Bài toán synthetic revision mới")
        changed = create(model(brief=changed_brief))
        self.assertNotEqual(changed["briefHash"], self.specs["tp-fin"]["briefHash"])
        self.assertNotEqual(changed["fingerprint"], self.specs["tp-fin"]["fingerprint"])
        with self.assertRaises(InputError) as caught:
            create((changed_brief, self.models["tp-fin"][1], self.models["tp-fin"][2]))
        self.assertEqual(caught.exception.code, "AF_SPEC_STALE")

    def test_golden_and_sources_remain_byte_size_and_mtime_identical_without_network(self):
        paths = [path for path in GOLDEN.rglob("*") if path.is_file()]
        before = states(paths)
        with patch.object(socket, "create_connection", side_effect=AssertionError("Không được gọi network")):
            with patch.object(socket.socket, "connect", side_effect=AssertionError("Không được gọi network")):
                for scenario in self.specs:
                    data = inputs(scenario)
                    brief = make(data)
                    create(model(scenario, brief=brief), scenario)
        self.assertEqual(states(paths), before)

    def test_engine_imports_no_ai_network_excel_and_never_emits_llm_provenance(self):
        forbidden = {"openai", "requests", "http", "urllib", "socket", "subprocess", "win32com", "ctypes"}
        for name in ("assistant_decisions", "assistant_execution", "assistant_spec"):
            source = (ROOT / "pbip_assistant/sources" / (name + ".py")).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({alias.name.split(".")[0] for alias in node.names} & forbidden)
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], forbidden)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "compile"})
            self.assertNotIn(".artifacts", source)
        def walk(value):
            if isinstance(value, dict):
                self.assertNotEqual(value.get("provenance"), "llm")
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        for result in self.specs.values():
            walk(result)


if __name__ == "__main__":
    unittest.main()
