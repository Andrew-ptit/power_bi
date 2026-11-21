"""Golden and mutation contracts for the deterministic half of WL3."""

from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import re
import socket
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_brief import build_brief, brief_hash, build_unresolved_decisions
from pbip_assistant.sources.assistant_findings import formulas, measure_set, number
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_pack import validate_pack
from tests.support.json_schema_oracle import validate
from tests.support.paths import FIXTURES, ROOT
from tests.unit.test_assistant_brief import inputs, mutated_inputs, make, values


GOLDEN = FIXTURES / "assistant"
STATUSES = {"verified", "inferred", "assumed", "unknown", "missing_data", "conflict"}


def load(scenario: str) -> dict:
    name = "wl3_brief_unresolved.json" if scenario == "tp-unknown" else "wl3_brief.json"
    return json.loads((GOLDEN / scenario / name).read_text(encoding="utf-8"))


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def states(paths) -> dict:
    return {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns, p.stat().st_size) for p in paths}


class AssistantWL3ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = {scenario: inputs(scenario) for scenario in ("tp-fin", "tp-sales")}
        cls.briefs = {scenario: make(cls.data[scenario], prompt=load(scenario)["prompt"]) for scenario in cls.data}
        cls.unknown = make(cls.data["tp-fin"], prompt=load("tp-unknown")["prompt"],
                           policy_unresolved={"SP-1", "SP-2", "SP-3"})

    def eq(self, actual, expected, field: str) -> None:
        self.assertEqual(actual, expected, field)

    def golden(self, scenario: str, actual: dict) -> None:
        expected = load(scenario)
        found = {item["value"]["formulaId"]: item["value"] for item in actual["findings"]}
        self.eq(len(found), len(actual["findings"]), scenario + ": finding formula IDs unique")
        for item in expected["findings"]:
            value = item["value"]
            self.assertIn(value["formulaId"], found, scenario + ": required finding")
            self.eq(found[value["formulaId"]], value, scenario + ": numeric finding " + value["formulaId"])
        self.eq(len(actual["subProblems"]), len(expected["subProblems"]), scenario + ": SP count")
        for actual_sp, expected_sp in zip(actual["subProblems"], expected["subProblems"], strict=True):
            field = scenario + ": " + expected_sp["id"]
            for key in ("id", "status", "provenance", "blocker", "proposedOptionId"):
                self.eq(actual_sp[key], expected_sp[key], field + "." + key)
            self.eq(len(actual_sp["options"]), len(expected_sp["options"]), field + ": option count")
            for option, expected_option in zip(actual_sp["options"], expected_sp["options"], strict=True):
                self.eq(option["id"], expected_option["id"], field + ": option ID")
                self.eq(option["consequence"]["value"], expected_option["consequence"]["value"], field + ": consequence")
        self.eq([{k: s[k] for k in ("id", "values")} for s in actual["scenarios"]],
                [{k: s[k] for k in ("id", "values")} for s in expected["scenarios"]], scenario + ": scenario arithmetic")
        self.eq(actual["delta"], expected["delta"], scenario + ": delta")
        for key in ("grain", "currency"):
            self.eq(actual["outputContract"][key], expected["outputContract"][key], scenario + ": output " + key)
        self.eq([x["name"] for x in actual["outputContract"]["measures"]],
                [x["name"] for x in expected["outputContract"]["measures"]], scenario + ": output measure names")
        for key in ("from", "to"):
            self.eq(actual["outputContract"]["period"][key], expected["outputContract"]["period"][key], scenario + ": period " + key)
        self.eq(set(actual["labels"]), set(expected["labels"]), scenario + ": labels")
        schema = json.loads((GOLDEN / "schema/brief.schema.json").read_text(encoding="utf-8"))
        self.eq(validate(actual, schema), [], scenario + ": core brief schema")

    def test_golden_fin_numeric_policies_and_scenarios_match(self) -> None:
        self.golden("tp-fin", self.briefs["tp-fin"])

    def test_golden_sales_numeric_policies_and_no_fx_match(self) -> None:
        self.golden("tp-sales", self.briefs["tp-sales"])

    def test_golden_unknown_numeric_policies_and_scenarios_match(self) -> None:
        self.golden("tp-unknown", self.unknown)

    def test_af_bf_001_output_contract_is_complete_and_bounded_override_is_supported(self) -> None:
        for scenario, brief in self.briefs.items():
            self.eq(set(brief["outputContract"]), {"grain", "measures", "filters", "period", "currency"}, scenario + ": contract fields")
            self.assertTrue(brief["outputContract"]["filters"], scenario + ": filters")
        override = {"grain": ["pnlLine"]}
        changed = make(self.data["tp-fin"], output_contract_override=override)
        self.eq(changed["outputContract"]["grain"], ["pnlLine"], "AF-BF-001: editable supported grain")
        with self.assertRaises(InputError, msg="AF-BF-001: reject uncalculated currency change"):
            make(self.data["tp-fin"], output_contract_override={"currency": "USD"})

    def test_af_bf_002_all_findings_use_current_engine_values_and_registry(self) -> None:
        for scenario, brief in self.briefs.items():
            data = self.data[scenario]
            measured = measure_set(data[0]["tables"], data[1])
            registry = {x["formulaId"]: x for x in formulas(measured)}
            for finding in brief["findings"]:
                value = finding["value"]
                self.assertIn(value["formulaId"], registry, scenario + ": formula registry")
                self.eq(value["value"], number(measured[value["formulaId"][3:]], value["unit"]), scenario + ": engine recompute")
                self.assertTrue(finding["evidence"], scenario + ": finding evidence")

    def test_af_bf_003_exact_policy_ids_have_ab_options_and_consequences(self) -> None:
        for scenario, count in (("tp-fin", 10), ("tp-sales", 5)):
            problems = self.briefs[scenario]["subProblems"]
            self.eq([x["id"] for x in problems], [f"SP-{i}" for i in range(1, count + 1)], scenario + ": SP identifiers")
            for problem in problems:
                self.assertGreaterEqual(len(problem["options"]), 2, scenario + problem["id"])
                self.assertTrue(all(option["consequence"]["statement"] for option in problem["options"]), scenario + ": consequences")

    def test_af_bf_004_both_insight_kinds_are_authored_pack_content(self) -> None:
        for scenario, brief in self.briefs.items():
            self.eq({x["kind"] for x in brief["insightCases"]}, {"hypothesis", "slice"}, scenario + ": insight kinds")
            self.assertTrue(all(x["provenance"] == "pack" and x["status"] != "verified" for x in brief["insightCases"]), scenario + ": authored prose")

    def test_af_bf_005_status_is_single_enum_and_only_measured_rule_is_verified(self) -> None:
        for scenario, brief in self.briefs.items():
            for problem in brief["subProblems"]:
                self.assertIn(problem["status"], STATUSES, scenario + ": status enum")
                self.assertIsInstance(problem["status"], str, scenario + ": one status")
                if problem["status"] == "verified":
                    self.eq((scenario, problem["id"], problem["provenance"]), ("tp-fin", "SP-4", "data"), "measured-only verified")
                    self.assertTrue(any(e["kind"] == "exact_duplicates" and e["formulaId"] for e in problem["evidence"]), "measured verification")
            self.assertTrue(all(p["status"] != "verified" for p in self.data[scenario][3]["policies"]), "pack has no verified template")

    def test_af_bf_006_missing_sources_never_receive_invented_numbers(self) -> None:
        for scenario, brief in self.briefs.items():
            missing = [p for p in brief["subProblems"] if p["status"] == "missing_data"]
            self.assertTrue(missing, scenario + ": explicit missing sources")
            for problem in missing:
                self.assertIn("out_of_scope", problem["labels"], scenario + ": scope label")
                self.assertTrue(all(o["consequence"]["value"] is None for o in problem["options"]), scenario + ": no invented values")

    def test_af_bf_007_scenarios_have_engine_values_and_delta_not_a_revaluation_claim(self) -> None:
        brief = self.briefs["tp-fin"]
        self.eq([x["id"] for x in brief["scenarios"]], ["A", "B"], "AF-BF-007: A/B")
        scenarios = [{v["name"]: Decimal(v["value"]) for v in s["values"]} for s in brief["scenarios"]]
        self.eq(Decimal(brief["delta"]["value"]), abs(scenarios[0]["FX"] - scenarios[1]["FX"]), "AF-BF-007: measured delta")
        self.eq(Decimal(brief["delta"]["value"]), Decimal("1276000000"), "AF-BF-007: independent anchor")
        self.eq(scenarios[0]["FX"] + scenarios[0]["Op"], scenarios[1]["FX"] + scenarios[1]["Op"], "scenario B reallocates same total")
        policy = next(p for p in self.data["tp-fin"][3]["policies"] if p["subProblemId"] == "SP-2")
        label = next(o["label"] for o in policy["options"] if o["id"] == "B")
        self.eq(brief["scenarios"][1]["label"], label, "scenario prose comes from pack, arithmetic remains engine-owned")

    def test_af_bf_008_hash_recomputes_deterministically_and_prompt_is_bound(self) -> None:
        for scenario, first in self.briefs.items():
            repeated = make(self.data[scenario], prompt=first["prompt"])
            self.eq(first, repeated, scenario + ": deterministic model")
            self.eq(first["briefHash"], canonical_hash({k: first[k] for k in first["hashBasis"]}), scenario + ": independent hash")
            self.eq(first["briefHash"], brief_hash(first), scenario + ": hash API")
            self.assertNotEqual(make(self.data[scenario], prompt="Bài toán đã sửa")["briefHash"], first["briefHash"], scenario + ": prompt bound")

    def test_af_bf_br_001_pack_has_no_money_and_every_numeric_value_has_engine_formula(self) -> None:
        for scenario, data in self.data.items():
            pack, brief = data[3], self.briefs[scenario]
            validate_pack(pack)
            for obj in walk(pack):
                for value in obj.values():
                    self.assertFalse(isinstance(value, (int, float)) and not isinstance(value, bool), "pack has no numeric JSON")
            bad = deepcopy(pack)
            bad["metrics"][0]["statement"] = "Doanh thu 92000000 VND."
            with self.assertRaises(InputError, msg="money hidden in prose blocked"):
                validate_pack(bad)
            registry = {x["formulaId"] for x in formulas(measure_set(data[0]["tables"], data[1]))}
            for obj in walk(brief):
                if obj.get("formulaId") is not None:
                    self.assertIn(obj["formulaId"], registry, scenario + ": registered numeric formula")
                if "unit" in obj and "value" in obj:
                    self.assertIsInstance(obj.get("formulaId"), str, scenario + ": no unbound number")
                    self.assertTrue(Decimal(obj["value"]).is_finite(), scenario + ": finite decimal")
                self.assertNotEqual(obj.get("provenance"), "llm", scenario + ": no LLM provenance")

    def test_mutation_independently_changes_rebate_net_sp1_variance_and_hash(self) -> None:
        before = values(self.briefs["tp-fin"])
        mutated = make(mutated_inputs(self.data["tp-fin"][0]))
        after = values(mutated)
        self.eq(after["fm_rebate_actual"], Decimal("-102000000"), "mutation rebate")
        self.eq(after["fm_net_revenue_actual"], before["fm_net_revenue_actual"] - Decimal("10000000"), "mutation net")
        self.eq(after["fm_sp1_option_b_delta"], Decimal("102000000"), "mutation SP1")
        self.eq(after["fm_variance"], before["fm_variance"] - Decimal("10000000"), "mutation variance")
        self.eq(after["fm_op"] + after["fm_fx"], after["fm_bridge_total"], "mutation bridge")
        self.assertNotEqual(mutated["briefHash"], self.briefs["tp-fin"]["briefHash"], "mutation hash")

    def test_unknown_helper_preserves_uncertainty_and_blocks_freeze(self) -> None:
        self.assertIn("unverified", self.unknown["labels"], "unknown label")
        self.assertTrue(all(p["chosenOptionId"] is None for p in self.unknown["subProblems"][:3]), "no forced policies")
        decision = build_unresolved_decisions(self.unknown)
        self.eq(decision["decisions"], [], "no fabricated user choices")
        self.eq(decision["freezeBlocked"], True, "freeze blocked")
        self.assertGreaterEqual(len(decision["checklist"]), 3, "policy checklist")
        self.assertTrue(any(b["code"] == "AF_MISSING_DATA" and b["severity"] == "warning" for b in decision["blockers"]), "explicit unresolved warning")

    def test_sources_remain_readonly_and_engine_uses_no_network_or_eval(self) -> None:
        paths = [p for s in self.data for p in (GOLDEN / s / "source").rglob("*.csv")]
        paths += [GOLDEN / s / "wl3_brief.json" for s in self.data]
        before = states(paths)
        for scenario, data in self.data.items():
            original = deepcopy(data)
            with patch.object(socket, "socket", side_effect=AssertionError("WL3 must not use network")):
                make(data)
            self.eq(data, original, scenario + ": no mutation of inputs")
        self.eq(states(paths), before, "all source bytes, mtime and size preserved")
        for name in ("assistant_pack.py", "assistant_findings.py", "assistant_brief.py"):
            tree = ast.parse((ROOT / "pbip_assistant/sources" / name).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(x.name.split('.')[0] in {"socket", "subprocess", "urllib", "requests", "openai"} for x in node.names), name + ": no network dependency")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"eval", "exec", "__import__"}, name + ": no executed pack expressions")


if __name__ == "__main__":
    unittest.main()
