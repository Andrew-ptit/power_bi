"""Kiểm compiler WL4: lựa chọn tường minh, graph đóng và chặn nhân dòng."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_decisions import build_decisions
from pbip_assistant.sources.assistant_execution import compile_steps, order_steps, verify_graph
from pbip_assistant.sources.assistant_pack import load_pack


_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "assistant"
_METADATA = {"decidedBy": "user", "decidedAt": "2026-10-28T09:00:00+07:00"}


def _read(pack, name):
    return json.loads((_FIXTURES / pack / name).read_text(encoding="utf-8"))


def _inputs(pack="tp-fin", *, overrides=None, omit=None, risk=None, metadata=_METADATA):
    brief = _read(pack, "wl3_brief.json")
    choices = {problem["id"]: "A" for problem in brief["subProblems"]
               if problem["status"] != "missing_data"}
    acknowledgements = {problem["id"]: "out_of_scope" for problem in brief["subProblems"]
                        if problem["status"] == "missing_data"}
    choices.update(overrides or {})
    if omit:
        choices.pop(omit)
    if risk:
        choices.pop(risk)
        acknowledgements[risk] = "risk"
    decisions = build_decisions(brief, choices=choices, acknowledgements=acknowledgements,
                                decision_metadata=metadata)
    return brief, decisions, load_pack("fin-pl-v1" if pack == "tp-fin" else "generic")


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class AssistantExecutionTests(unittest.TestCase):
    def assert_graph_error(self, steps, code="AF_EXECUTION_INVALID"):
        before = deepcopy(steps)
        with self.assertRaises(InputError) as raised:
            verify_graph(steps)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(steps, before)

    def test_fin_and_sales_match_golden_structure(self):
        for pack, count in (("tp-fin", 14), ("tp-sales", 10)):
            with self.subTest(pack=pack):
                steps = compile_steps(*_inputs(pack))
                golden = _read(pack, "wl4_execution_spec.json")["steps"]
                self.assertEqual(len(steps), count)
                for field in ("kind", "decisionRefs", "status", "guard"):
                    self.assertEqual([step[field] for step in steps], [step[field] for step in golden])
                verify_graph(steps)
                previous = set()
                for step in steps:
                    if previous:
                        self.assertTrue(previous.intersection(step["inputs"]))
                    previous.add(step["output"])

    def test_compile_is_byte_equal_and_preserves_all_inputs(self):
        for pack in ("tp-fin", "tp-sales"):
            with self.subTest(pack=pack):
                inputs = _inputs(pack)
                before = deepcopy(inputs)
                self.assertEqual(_serialized(compile_steps(*inputs)), _serialized(compile_steps(*inputs)))
                self.assertEqual(inputs, before)

    def test_every_executable_choice_has_bound_behavior(self):
        for pack in ("tp-fin", "tp-sales"):
            with self.subTest(pack=pack):
                inputs = _inputs(pack)
                choices = {entry["subProblemId"]: entry["optionId"] for entry in inputs[1]["decisions"]}
                seen = set()
                for step in compile_steps(*inputs):
                    for identifier in step["decisionRefs"]:
                        seen.add(identifier)
                        self.assertEqual(step["params"]["chosenOptions"][identifier], choices[identifier])
                        self.assertTrue(step["params"]["policyModes"][identifier])
                self.assertEqual(seen, set(choices))

    def test_sp1_b_binds_scalar_and_revenue_mode(self):
        steps_a = compile_steps(*_inputs())
        steps_b = compile_steps(*_inputs(overrides={"SP-1": "B"}))
        step = next(step for step in steps_b if "SP-1" in step["decisionRefs"])
        self.assertEqual(step["params"]["chosenOptionId"], "B")
        self.assertEqual(step["params"]["policyModes"]["SP-1"], "present_rebate_below_gross_profit")
        self.assertNotEqual(_serialized(steps_a), _serialized(steps_b))

    def test_mixed_choices_preserve_both_refs_and_null_scalar(self):
        inputs = _inputs(overrides={"SP-2": "B", "SP-8": "A"})
        steps = compile_steps(*inputs)
        step = steps[7]
        self.assertEqual(step["decisionRefs"], ["SP-2", "SP-8"])
        self.assertEqual(step["params"]["chosenOptions"], {"SP-2": "B", "SP-8": "A"})
        self.assertIsNone(step["params"]["chosenOptionId"])
        self.assertEqual(step["params"]["policyModes"]["SP-2"], "reallocate_fx_into_op")
        self.assertEqual(_serialized(steps), _serialized(compile_steps(*inputs)))

    def test_same_choices_have_scalar(self):
        step = compile_steps(*_inputs(overrides={"SP-2": "B", "SP-8": "B"}))[7]
        self.assertEqual(step["params"]["chosenOptionId"], "B")
        self.assertEqual(step["params"]["policyModes"]["SP-8"], "require_complete_rate_catalog")

    def test_alternate_policies_change_closed_modes(self):
        expected = {"SP-3": "keep_intercompany_flagged", "SP-4": "keep_duplicates_and_normalize_sign",
                    "SP-5": "unmapped_bucket"}
        steps = compile_steps(*_inputs(overrides={identifier: "B" for identifier in expected}))
        modes = {identifier: mode for step in steps for identifier, mode in step["params"]["policyModes"].items()}
        for identifier, mode in expected.items():
            self.assertEqual(modes[identifier], mode)

    def test_missing_choice_is_not_implicitly_selected(self):
        inputs = _inputs(omit="SP-3")
        self.assertTrue(inputs[1]["freezeBlocked"])
        with self.assertRaises(InputError) as raised:
            compile_steps(*inputs)
        self.assertEqual(raised.exception.code, "AF_MISSING_DATA")

    def test_risk_acknowledgement_does_not_replace_execution_choice(self):
        inputs = _inputs(risk="SP-3")
        with self.assertRaises(InputError) as raised:
            compile_steps(*inputs)
        self.assertEqual(raised.exception.code, "AF_MISSING_DATA")

    def test_draft_without_explicit_user_and_time_cannot_compile_final_steps(self):
        for metadata in (None, {"decidedBy": "user"}, {"decidedAt": _METADATA["decidedAt"]}):
            with self.subTest(metadata=metadata):
                inputs = _inputs(metadata=metadata)
                self.assertTrue(inputs[1]["freezeBlocked"])
                with self.assertRaises(InputError):
                    compile_steps(*inputs)

    def test_generated_sources_are_explicit_aliases_without_invented_table_ids(self):
        for step in compile_steps(*_inputs()):
            self.assertIsNone(step["params"]["tableId"])
            for source in step["inputs"]:
                if source.startswith("source:"):
                    self.assertEqual(source, "source:" + step["params"]["sourceAlias"])

    def test_swapped_group_budget_raises_exact_fanout_code_without_mutation(self):
        steps = compile_steps(*_inputs())
        steps[10], steps[11] = steps[11], steps[10]
        self.assert_graph_error(steps, "AF_FANOUT_RISK")

    def test_budget_cannot_bypass_group_data_path(self):
        for field in ("inputs", "dependsOn"):
            with self.subTest(field=field):
                steps = compile_steps(*_inputs())
                steps[11][field] = [steps[9]["output"] if field == "inputs" else steps[9]["id"]]
                self.assert_graph_error(steps, "AF_FANOUT_RISK")

    def test_budget_grain_mismatch_is_fanout_risk(self):
        steps = compile_steps(*_inputs())
        steps[11]["params"]["rightGrain"] = ["UnmatchedGrain"]
        self.assert_graph_error(steps, "AF_FANOUT_RISK")

    def test_forged_kind_cannot_disable_budget_guard(self):
        steps = compile_steps(*_inputs())
        steps[11]["kind"] = "lookup"
        self.assert_graph_error(steps)

    def test_forward_cycle_missing_and_orphan_refs_are_rejected(self):
        mutations = (
            lambda steps: steps[1]["dependsOn"].append(steps[2]["id"]),
            lambda steps: steps[1]["dependsOn"].append("st_missing"),
            lambda steps: steps[1]["inputs"].append(steps[2]["output"]),
            lambda steps: steps[1].update(inputs=[], dependsOn=[]),
            lambda steps: steps[1]["inputs"].append("q_missing"),
            lambda steps: steps[1].update(id=steps[0]["id"]),
            lambda steps: steps[1].update(output=steps[0]["output"]),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                steps = compile_steps(*_inputs("tp-sales"))
                mutate(steps)
                self.assert_graph_error(steps)

    def test_malformed_fields_raise_inputerror_instead_of_typeerror(self):
        mutations = (
            lambda step: step.update(params=None),
            lambda step: step.update(inputs=None),
            lambda step: step.update(dependsOn=None),
            lambda step: step.update(kind=[]),
            lambda step: step.update(status=[]),
            lambda step: step.update(guard=[]),
            lambda step: step["params"].update(operation=[]),
            lambda step: step["params"].update(sourceAlias=[]),
            lambda step: step["params"].update(chosenOptions={"SP-2": [], "SP-8": "A"}),
            lambda step: step["params"].update(policyModes={"SP-2": [], "SP-8": "mode"}),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                steps = compile_steps(*_inputs())
                mutate(steps[7])
                self.assert_graph_error(steps)

    def test_forged_source_or_scalar_is_rejected(self):
        for patch in ({"sourceAlias": "orders"}, {"chosenOptionId": "B"}):
            with self.subTest(patch=patch):
                steps = compile_steps(*_inputs())
                steps[7]["params"].update(patch)
                self.assert_graph_error(steps)

    def test_forged_policy_mode_or_decision_refs_is_rejected(self):
        steps = compile_steps(*_inputs())
        steps[7]["params"]["policyModes"]["SP-2"] = "unsupported_mode"
        self.assert_graph_error(steps)
        steps = compile_steps(*_inputs())
        steps[7]["decisionRefs"] = ["SP-1"]
        self.assert_graph_error(steps)

    def test_missing_data_source_request_cannot_be_silently_skipped(self):
        brief, document, pack = _inputs()
        choices = {entry["subProblemId"]: entry["optionId"] for entry in document["decisions"]}
        choices["SP-7"] = "B"
        acknowledgements = {entry["subProblemId"]: entry["acknowledged"]
                            for entry in document["acknowledgements"] if entry["subProblemId"] != "SP-7"}
        try:
            decisions = build_decisions(brief, choices=choices, acknowledgements=acknowledgements,
                                        decision_metadata=_METADATA)
        except InputError:
            return
        with self.assertRaises(InputError):
            compile_steps(brief, decisions, pack)

    def test_order_steps_sorts_valid_dag_and_returns_independent_copy(self):
        steps = compile_steps(*_inputs())
        shuffled = list(reversed(deepcopy(steps)))
        before = deepcopy(shuffled)
        ordered = order_steps(shuffled)
        self.assertEqual(ordered, steps)
        self.assertEqual(shuffled, before)
        ordered[0]["params"]["operation"] = "changed"
        self.assertEqual(shuffled, before)

    def test_order_steps_rejects_cycle_and_missing_dependency(self):
        for identifier in ("st_missing", "st_10"):
            with self.subTest(dependency=identifier):
                steps = compile_steps(*_inputs("tp-sales"))
                steps[0]["dependsOn"] = [identifier]
                with self.assertRaises(InputError):
                    order_steps(steps)

    def test_tampered_brief_or_wrong_pack_is_rejected(self):
        inputs = list(_inputs())
        inputs[0]["prompt"] += " changed"
        with self.assertRaises(InputError):
            compile_steps(*inputs)
        brief, decisions, _ = _inputs()
        with self.assertRaises(InputError):
            compile_steps(brief, decisions, load_pack("generic"))


if __name__ == "__main__":
    unittest.main()
