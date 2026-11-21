"""Handwritten numeric oracles for generic controls and branch execution."""

from copy import deepcopy
from decimal import Context, ROUND_DOWN, localcontext
import json
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.powerquery.typed_local import execute_plan
from pbip_assistant.sources.assistant_ingest import canonical_hash
from pbip_assistant.sources.assistant_session import AssistantSessionStore
from pbip_assistant.sources.assistant_reconcile_v2 import (
    build_preview, reconcile_v2, build_ab_delta, ab_identity_passed, bind_ab_identity,
)
from tests.support.assistant_flow import AssistantBranchPlanner


def step(ref, variable, operation, inputs, parameters):
    return {"clientRef": ref, "variableName": variable, "actionDescription": operation,
            "operationType": operation, "inputs": inputs, "parameters": parameters}


def basis_plan(source_id="transactions"):
    return {"steps": [{"stepId": "read", "operation": {"type": "source.workbookTable", "parameters": {"sourceId": source_id}}, "inputs": []}],
            "finalOutputStepId": "read", "sources": [{"sourceId": source_id, "columns": [{"name": "Amount", "columnId": "amount"}]}]}


class Planner:
    def __init__(self, change=None):
        self.change = change
    def propose(self, payload):
        result = AssistantBranchPlanner().propose(payload)
        if self.change:
            self.change(result, payload)
        return result


class AssistantReconcileV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AssistantSessionStore()
        self.addCleanup(self.store.close)
        self.store.bind_root(self.temp.name)
        self.prepare()

    def selection(self, name, header, rows, mode="compute", total=None):
        return {"kind": "workbook", "mode": mode, "payload": {"name": name,
            "origin": "Workbook!Data!" + name, "sheet": "Data", "table": True,
            "header": header, "rows": rows, "sampleOrdinals": list(range(len(rows))),
            "totalRows": len(rows) if total is None else total}}

    def prepare(self, mode="compute", rows=None, extras=()):
        rows = rows if rows is not None else [["a", "12"], ["b", "-3"], ["c", "3"]]
        self.store.ingest([self.selection("Transactions", ["ID", "Amount"], rows, mode), *extras])
        self.store.understand()

    def draft(self, change=None):
        return self.store.plan_draft("Sum Amount and compare positive rows", [], True, Planner(change))

    def execute_both(self, change=None):
        self.draft(change)
        return self.store.run_branches(self.store.state()["planningHash"])

    def reconciliation(self, identifier="A", alter=None):
        branch = deepcopy(next(branch for branch in self.store._planning["branches"] if branch["id"] == identifier))
        result = execute_plan(branch["plan"], self.store._raw_tables)
        if alter:
            alter(result)
        preview = build_preview(self.store._snapshot["snapshotHash"], branch, result)
        return reconcile_v2(preview, branch, self.store._raw_tables, result)

    def join_plan(self, limit="1", control=None, after_filter=False, zero_left=False):
        def change(response, payload):
            ids = {source["name"]: source["sourceId"] for source in payload["sources"]}
            steps = [step("left", "Left", "source.workbookTable", [], {"sourceId": ids["Transactions"]}),
                step("typed", "Typed", "table.changeTypes", ["left"], {"conversions": [{"column": "Amount", "targetType": "number"}]}),
                step("right", "Right", "source.workbookTable", [], {"sourceId": ids["Lookup"]})]
            left = "typed"
            if zero_left:
                steps.append(step("empty", "Empty", "table.filterRows", [left], {"predicate": {
                    "kind": "compare", "operator": "gt", "left": {"kind": "columnRef", "column": "Amount"},
                    "right": {"kind": "literal", "valueType": "number", "value": 100}}}))
                left = "empty"
            steps.extend([step("join", "Joined", "table.mergeTables", [left, "right"], {
                "keyPairs": [{"leftColumn": "ID", "rightColumn": "LookupID"}], "joinKind": "rightOuter" if zero_left else "inner", "nestedColumnName": "Details"}),
                step("expand", "Expanded", "table.expandTableColumn", ["join"], {"nestedColumn": "Details", "columns": [{"column": "Label", "newName": "Label"}]})])
            final = "expand"
            if after_filter:
                steps.append(step("filter", "Filtered", "table.filterRows", [final], {"predicate": {
                    "kind": "compare", "operator": "eq", "left": {"kind": "columnRef", "column": "Label"},
                    "right": {"kind": "literal", "valueType": "text", "value": "x"}}}))
                final = "filter"
            branch = response["branches"][0]
            branch.update(controlTotal=control, maxFanOut=limit)
            branch["plan"].update(steps=steps, finalOutputRef=final)
        return change

    def prepare_join(self):
        lookup = self.selection("Lookup", ["LookupID", "Label"], [["a", "x"], ["a", "y"], ["b", "z"]])
        self.prepare(rows=[["a", "10"], ["b", "20"]], extras=[lookup])

    def test_control_total_matches_source_after_filter(self):
        result = self.execute_both()
        a, b = result["branches"]
        self.assertEqual(a["rows"], [["12"]])
        self.assertEqual(b["rows"], [["15"]])
        self.assertEqual(a["reconciliation"]["controlTotalSource"], "12")
        self.assertEqual(b["reconciliation"]["controlTotalSource"], "15")
        self.assertTrue(a["reconciliation"]["passed"])
        self.assertTrue(b["reconciliation"]["passed"])

    def test_drift_is_a_hard_non_overridable_failure(self):
        self.draft()
        result = self.reconciliation(alter=lambda result: result.update(rows=[["13"]]))
        self.assertTrue(result["controlTotalApplicable"])
        self.assertFalse(result["controlTotalPassed"])
        self.assertFalse(result["hardChecksPassed"])
        self.assertFalse(result["selectable"])
        self.assertEqual(result["blockers"][0]["code"], "AF_RECONCILE_FAILED")

    def test_tolerance_uses_decimal(self):
        self.draft()
        within = self.reconciliation(alter=lambda result: result.update(rows=[["12.005"]]))
        beyond = self.reconciliation(alter=lambda result: result.update(rows=[["12.02"]]))
        self.assertTrue(within["controlTotalPassed"])
        self.assertFalse(beyond["controlTotalPassed"])

    def test_missing_control_total_requires_acknowledgement_without_claiming_pass(self):
        result = self.execute_both(lambda response, payload: response["branches"][0].update(controlTotal=None))
        a = result["branches"][0]
        self.assertFalse(a["reconciliation"]["controlTotalApplicable"])
        self.assertFalse(a["reconciliation"]["passed"])
        self.assertTrue(a["reconciliation"]["hardChecksPassed"])
        self.assertTrue(a["reconciliation"]["acknowledgementRequired"])
        self.assertTrue(a["selectable"])
        self.assertIsNone(a["error"])

    def test_before_filters_contract_does_not_reuse_filtered_result_as_source(self):
        result = self.execute_both(lambda response, payload: response["branches"][1]["controlTotal"].update(afterFilters=False))
        b = result["branches"][1]
        self.assertEqual(b["reconciliation"]["controlTotalSource"], "12")
        self.assertEqual(b["reconciliation"]["controlTotalResult"], "15")
        self.assertFalse(b["selectable"])

    def test_renamed_column_and_explicit_culture_reconcile_independently(self):
        self.prepare(rows=[["a", "1.234,50"], ["b", "-34,25"]])
        def change(response, payload):
            for branch in response["branches"]:
                plan = branch["plan"]
                source = plan["steps"][0]
                plan["steps"] = [source,
                    step("rename", "Renamed", "table.renameColumns", ["source"], {"renames": [{"column": "Amount", "newName": "Money"}]}),
                    step("typed", "Typed", "table.changeTypes", ["rename"], {"conversions": [{"column": "Money", "targetType": "number", "culture": "vi-VN"}]}),
                    step("total", "Total", "table.aggregateRows", ["typed"], {"aggregations": [{"function": "sum", "column": "Money", "outputName": "Total"}]})]
                plan["finalOutputRef"] = "total"
        result = self.execute_both(change)
        self.assertEqual(result["branches"][0]["rows"], [["1200.25"]])
        self.assertEqual(result["branches"][0]["reconciliation"]["controlTotalSource"], "1200.25")
        self.assertTrue(result["branches"][0]["reconciliation"]["passed"])

    def test_filter_empty_source_total_is_zero_without_fabricating_result_values(self):
        self.prepare(rows=[["a", "-1"], ["b", "-2"]])
        result = self.execute_both()
        b = result["branches"][1]
        self.assertEqual(b["rows"], [[None]])
        self.assertEqual(b["reconciliation"]["controlTotalSource"], "0")
        self.assertEqual(b["reconciliation"]["controlTotalResult"], "0")
        self.assertTrue(b["reconciliation"]["passed"])

    def test_shape_rejects_duplicate_columns_wrong_width_or_row_count(self):
        self.draft()
        mutations = [lambda result: result.update(rowCount=9), lambda result: result.update(rows=[[]]),
                     lambda result: result.update(columns=[{"name": "Total", "type": "number"}, {"name": "Total", "type": "number"}], rows=[["6", "6"]])]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                reconciliation = self.reconciliation(alter=mutation)
                self.assertFalse(reconciliation["checks"][0]["passed"])
                self.assertFalse(reconciliation["selectable"])

    def test_fanout_over_declared_limit_blocks(self):
        self.prepare_join()
        result = self.execute_both(self.join_plan())
        a, b = result["branches"]
        self.assertEqual(a["totalRows"], 3)
        self.assertFalse(a["reconciliation"]["fanOutPassed"])
        self.assertFalse(a["selectable"])
        self.assertEqual(a["error"]["code"], "AF_FANOUT_RISK")
        self.assertTrue(b["selectable"])

    def test_declared_fanout_does_not_self_validate_duplicated_source_totals(self):
        self.prepare_join()
        control = {"resultColumn": "Amount", "sourceColumn": "Amount", "aggregation": "sum", "afterFilters": True}
        result = self.execute_both(self.join_plan("2", control))
        a = result["branches"][0]
        self.assertTrue(a["reconciliation"]["fanOutPassed"])
        self.assertEqual(a["reconciliation"]["controlTotalSource"], "30")
        self.assertEqual(a["reconciliation"]["controlTotalResult"], "40")
        self.assertFalse(a["selectable"])

    def test_after_join_filter_is_honestly_unverified(self):
        self.prepare_join()
        control = {"resultColumn": "Amount", "sourceColumn": "Amount", "aggregation": "sum", "afterFilters": True}
        result = self.execute_both(self.join_plan("2", control, after_filter=True))
        a = result["branches"][0]
        self.assertFalse(a["reconciliation"]["controlTotalApplicable"])
        self.assertFalse(a["reconciliation"]["passed"])
        self.assertIn("Bộ lọc sau", a["reconciliation"]["controlTotalReason"])
        self.assertTrue(a["selectable"])

    def test_zero_left_with_right_rows_is_fanout_risk_for_every_finite_limit(self):
        self.prepare_join()
        result = self.execute_both(self.join_plan("100000", zero_left=True))
        a = result["branches"][0]
        self.assertFalse(a["reconciliation"]["fanOutPassed"])
        self.assertEqual(a["error"]["code"], "AF_FANOUT_RISK")

    def test_missing_join_metrics_cannot_pass(self):
        self.prepare_join()
        self.draft(self.join_plan("2"))
        reconciliation = self.reconciliation(alter=lambda result: result.update(fanOut=None))
        self.assertFalse(reconciliation["fanOutPassed"])

    def test_ab_identity_holds_for_handwritten_expected_difference(self):
        result = self.execute_both()
        self.assertEqual(result["delta"]["a"], "12")
        self.assertEqual(result["delta"]["b"], "15")
        self.assertEqual(result["delta"]["value"], "-3")
        self.assertTrue(result["abIdentityPassed"])
        for branch in result["branches"]:
            self.assertEqual(branch["reconciliation"]["abDeltaHash"], result["delta"]["deltaHash"])

    def test_changed_ab_delta_is_rejected_and_reconciliation_hash_changes(self):
        result = self.execute_both()
        delta = deepcopy(result["delta"])
        delta["value"] = "999"
        self.assertFalse(ab_identity_passed(delta))
        old = result["branches"][0]["reconciliation"]
        changed = bind_ab_identity(old, delta)
        self.assertFalse(changed["selectable"])
        self.assertNotEqual(changed["reconcileHash"], old["reconcileHash"])

    def test_different_control_sources_with_same_output_name_have_no_comparable_delta(self):
        a = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["12"]]},
             "controlTotal": {"resultColumn": "Total", "sourceColumn": "Amount"}}
        b = {**deepcopy(a), "controlTotal": {"resultColumn": "Total", "sourceColumn": "Quantity"}}
        self.assertFalse(build_ab_delta(a, b)["applicable"])

    def test_decimal_context_is_independent_of_host_precision_and_exponent_limits(self):
        control = {"resultColumn": "Total", "sourceColumn": "Amount"}
        a = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["100000000000000000000.3"]]}, "controlTotal": control, "plan": basis_plan()}
        b = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["100000000000000000000.1"]]}, "controlTotal": control, "plan": basis_plan()}
        expected = build_ab_delta(a, b)
        with localcontext(Context(prec=2, rounding=ROUND_DOWN, Emin=-3, Emax=3, traps=[])):
            actual = build_ab_delta(a, b)
            self.assertEqual(actual["value"], "0.2")
            self.assertTrue(ab_identity_passed(actual))
        self.assertEqual(actual, expected)

    def test_same_named_controls_from_different_catalog_sources_are_not_comparable(self):
        control = {"resultColumn": "Total", "sourceColumn": "Amount"}
        a = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["12"]]}, "controlTotal": control, "plan": basis_plan("money")}
        b = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["3"]]}, "controlTotal": control, "plan": basis_plan("stock")}
        delta = build_ab_delta(a, b)
        self.assertFalse(delta["applicable"])
        self.assertIsNone(delta["value"])
        self.assertIn("bảng hoặc cột nguồn khác nhau", delta["reason"])
        b["plan"] = basis_plan("money")
        self.assertEqual(build_ab_delta(a, b)["value"], "9")

    def test_same_output_name_without_two_source_controls_does_not_prove_common_measure(self):
        a = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["12"]]},
             "controlTotal": {"resultColumn": "Total", "sourceColumn": "Amount"}}
        b = {"result": {"columns": [{"name": "Total", "type": "number"}], "rows": [["3"]]}, "controlTotal": None}
        for controls in ((a["controlTotal"], None), (None, None), (None, a["controlTotal"])):
            with self.subTest(controls=controls):
                a["controlTotal"], b["controlTotal"] = controls
                delta = build_ab_delta(a, b)
                self.assertFalse(delta["applicable"])
                self.assertIsNone(delta["value"])
                self.assertIsNone(ab_identity_passed(delta))

    def test_missing_one_control_leaves_both_individual_branches_selectable_without_comparable_delta(self):
        def change(response, payload):
            response["branches"][1]["controlTotal"] = None
        result = self.execute_both(change)
        self.assertFalse(result["delta"]["applicable"])
        self.assertIsNone(result["abIdentityPassed"])
        self.assertTrue(all(branch["selectable"] for branch in result["branches"]))
        self.assertTrue(result["branches"][0]["reconciliation"]["passed"])
        self.assertFalse(result["branches"][1]["reconciliation"]["passed"])

    def test_reconcile_hash_is_deterministic_and_binds_changed_source_cells(self):
        self.draft()
        first, repeated = self.reconciliation(), self.reconciliation()
        self.assertEqual(first, repeated)
        branch = deepcopy(self.store._planning["branches"][0])
        result = execute_plan(branch["plan"], self.store._raw_tables)
        preview = build_preview(self.store._snapshot["snapshotHash"], branch, result)
        tables = deepcopy(self.store._raw_tables)
        tables[0]["rows"][0][1] = "13"
        changed = reconcile_v2(preview, branch, tables, result)
        self.assertNotEqual(first["reconcileHash"], changed["reconcileHash"])

    def test_both_branches_run_on_same_snapshot(self):
        result = self.execute_both()
        a, b = result["branches"]
        self.assertEqual(a["snapshotHash"], b["snapshotHash"])
        self.assertEqual(a["snapshotHash"], result["snapshotHash"])
        self.assertNotEqual(a["previewHash"], b["previewHash"])
        self.assertEqual(a["engine"]["parityChecked"], "none")
        self.assertEqual(result["engine"]["executor"], "typed_local")
        self.assertIn("decimal-money", result["engine"]["knownDifferences"])

    def test_execute_on_discover_snapshot_requires_full_read(self):
        self.prepare(mode="discover")
        self.draft()
        with patch("pbip_assistant.sources.assistant_session.execute_plan") as execute:
            with self.assertRaises(InputError) as raised:
                self.store.run_branches()
        self.assertEqual(raised.exception.code, "AF_SAMPLE_ONLY")
        execute.assert_not_called()

    def test_cache_is_result_only_and_response_copies_cannot_mutate_authority(self):
        self.draft()
        raw = deepcopy(self.store._raw_tables)
        with patch("pbip_assistant.sources.assistant_session.execute_plan", wraps=execute_plan) as execute:
            first = self.store.run_branches()
            first["branches"][0]["rows"][0][0] = "999"
            second = self.store.run_branches()
        self.assertEqual(execute.call_count, 2)
        self.assertTrue(all(branch["cached"] for branch in second["branches"]))
        self.assertEqual(second["branches"][0]["rows"], [["12"]])
        self.assertEqual(self.store._raw_tables, raw)
        self.assertLessEqual(len(self.store._execution_cache), 2)

    def test_cache_reconciles_current_fanout_policy_again_without_reexecution(self):
        self.prepare_join()
        with patch("pbip_assistant.sources.assistant_session.execute_plan", wraps=execute_plan) as execute:
            first = self.execute_both(self.join_plan("1"))
            second = self.execute_both(self.join_plan("2"))
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(first["branches"][0]["planHash"], second["branches"][0]["planHash"])
        self.assertNotEqual(first["planningHash"], second["planningHash"])
        self.assertFalse(first["branches"][0]["selectable"])
        self.assertTrue(second["branches"][0]["selectable"])
        self.assertFalse(second["branches"][0]["reconciliation"]["passed"])
        self.assertTrue(second["branches"][0]["cached"])
        self.assertNotEqual(first["branches"][0]["reconciliation"]["reconcileHash"], second["branches"][0]["reconciliation"]["reconcileHash"])

    def test_cache_byte_cap_can_disable_cache_without_changing_results(self):
        self.draft()
        with patch("pbip_assistant.sources.assistant_session._CACHE_MAX_BYTES", 1), patch("pbip_assistant.sources.assistant_session.execute_plan", wraps=execute_plan) as execute:
            first, second = self.store.run_branches(), self.store.run_branches()
        self.assertEqual(execute.call_count, 4)
        self.assertEqual(first["branches"][0]["resultDigest"], second["branches"][0]["resultDigest"])
        self.assertEqual(self.store._cache_bytes, 0)
        self.assertEqual(self.store._execution_cache, {})

    def test_source_mutation_during_execution_is_never_published_to_cache(self):
        self.draft()
        def mutate(plan, tables):
            result = execute_plan(plan, tables)
            tables[0]["rows"][0][1] = "999"
            return result
        with patch("pbip_assistant.sources.assistant_session.execute_plan", side_effect=mutate):
            with self.assertRaises(InputError) as raised:
                self.store.run_branches()
        self.assertEqual(raised.exception.code, "AF_SOURCE_LOST")
        self.assertEqual(self.store._execution_cache, {})
        self.store._raw_tables[0]["rows"][0][1] = "12"
        with patch("pbip_assistant.sources.assistant_session.execute_plan", wraps=execute_plan) as execute:
            self.store.run_branches()
        self.assertEqual(execute.call_count, 2)

    def test_preview_is_bounded_but_digest_and_private_result_bind_all_rows(self):
        rows = [[str(index), "1"] for index in range(250)]
        self.prepare(rows=rows)
        def change(response, payload):
            for branch in response["branches"]:
                branch["plan"]["steps"] = branch["plan"]["steps"][:2]
                branch["plan"]["finalOutputRef"] = "typed"
                branch["controlTotal"]["resultColumn"] = "Amount"
        result = self.execute_both(change)
        for branch in result["branches"]:
            self.assertEqual(len(branch["rows"]), 200)
            self.assertEqual(branch["totalRows"], 250)
            self.assertTrue(branch["truncated"])
            self.assertEqual(len(self.store._branch_results[branch["id"]]["result"]["rows"]), 250)
            expected = canonical_hash({"columns": [{"name": "ID", "type": "text"}, {"name": "Amount", "type": "number"}], "rows": rows})
            self.assertEqual(branch["resultDigest"], expected)
        self.assertEqual(result["delta"]["value"], "0")

    def test_one_executor_failure_keeps_the_other_branch_selectable(self):
        self.draft()
        def fail_a(plan, tables):
            if len(plan["steps"]) == 3:
                raise InputError("AF_EXECUTOR_LIMIT", "tables", "Synthetic limit")
            return execute_plan(plan, tables)
        with patch("pbip_assistant.sources.assistant_session.execute_plan", side_effect=fail_a):
            result = self.store.run_branches()
        a, b = result["branches"]
        self.assertEqual(a["error"]["code"], "AF_EXECUTOR_LIMIT")
        self.assertFalse(a["selectable"])
        self.assertTrue(b["selectable"])
        self.assertTrue(b["reconciliation"]["passed"])
        self.assertFalse(result["allBlocked"])
        self.assertFalse(result["delta"]["applicable"])

    def test_both_executor_failures_keep_errors_and_block_selection(self):
        self.draft()
        with patch("pbip_assistant.sources.assistant_session.execute_plan", side_effect=InputError("AF_EXECUTOR_INVALID", "plan", "Synthetic invalid")):
            result = self.store.run_branches()
        self.assertTrue(result["allBlocked"])
        self.assertEqual(len(result["branches"]), 2)
        self.assertTrue(all(not branch["selectable"] for branch in result["branches"]))

    def test_expected_hash_and_tampered_source_reject_before_execution(self):
        self.draft()
        with patch("pbip_assistant.sources.assistant_session.execute_plan") as execute:
            with self.assertRaises(InputError) as raised:
                self.store.run_branches("sha256:" + "0" * 64)
            self.assertEqual(raised.exception.code, "AF_SPEC_STALE")
            self.store._raw_tables[0]["rows"][-1][1] = "999"
            with self.assertRaises(InputError) as raised:
                self.store.run_branches()
            self.assertEqual(raised.exception.code, "AF_SPEC_STALE")
        execute.assert_not_called()

    def test_reconciliation_policy_cannot_be_transplanted_without_new_planning_hash(self):
        self.draft()
        self.store._planning["branches"][0]["maxFanOut"] = "2"
        with self.assertRaises(InputError) as raised:
            self.store.run_branches()
        self.assertEqual(raised.exception.code, "AF_SPEC_STALE")


if __name__ == "__main__":
    unittest.main()
