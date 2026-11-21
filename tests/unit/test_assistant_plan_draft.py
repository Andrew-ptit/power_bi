"""Assistant plans are revalidated locally and never supply calculated data."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pbip_assistant.adapters.codex import assistant_plan as adapter
from pbip_assistant.coordinator.endpoints.assistant_plan import AssistantPlanEndpoints
from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_session import AssistantSessionStore
from tests.support.assistant_flow import AssistantBranchPlanner


def step(ref, variable, operation, inputs, parameters):
    return {"clientRef": ref, "variableName": variable, "actionDescription": operation,
            "operationType": operation, "inputs": inputs, "parameters": parameters}


class FakeRunner:
    def __init__(self, change=None):
        self.calls = []
        self.change = change

    def propose(self, payload):
        self.calls.append(deepcopy(payload))
        result = AssistantBranchPlanner().propose(payload)
        if self.change:
            self.change(result)
        return result


class AssistantPlanDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AssistantSessionStore()
        self.addCleanup(self.store.close)
        self.store.bind_root(self.temp.name)
        self.store.ingest([self.selection()])
        self.store.understand()

    def selection(self, name="Transactions", count=20, mode="discover", total=50):
        ordinals = list(range(count))
        return {"kind": "workbook", "mode": mode, "payload": {
            "header": ["ID", "Amount"], "rows": [[str(n), str(n * 10)] for n in range(count)],
            "sampleOrdinals": ordinals, "totalRows": count if mode == "compute" else total,
            "name": name, "origin": "Workbook!Data!" + name, "sheet": "Data", "table": True}}

    def draft(self, runner=None, acknowledged=True):
        return self.store.plan_draft("Sum Amount with two explicit alternatives", [], acknowledged, runner or FakeRunner())

    def assert_invalid(self, change, code="AF_PLAN_INVALID", path=None):
        with self.assertRaises(InputError) as raised:
            self.draft(FakeRunner(change))
        self.assertEqual(raised.exception.code, code)
        if path:
            self.assertIn(path, raised.exception.path)
        self.assertEqual(self.store.state()["stage"], "understood")
        return raised.exception

    def test_two_branches_required(self):
        for count in (0, 1, 3):
            with self.subTest(count=count):
                self.assert_invalid(lambda response: response.update(branches=(response["branches"] * 2)[:count]), path="branches")

    def test_duplicate_and_invalid_branch_ids_rejected(self):
        for value in ("A", "C", [], None):
            with self.subTest(value=value):
                self.assert_invalid(lambda response: response["branches"][1].update(id=value))

    def test_codex_plan_is_revalidated_and_rejects_unknown_column(self):
        self.assert_invalid(lambda response: response["branches"][0]["plan"]["steps"][-1]["parameters"]["aggregations"][0].update(column="Missing"), path="branches[0].plan.steps[2]")

    def test_codex_plan_rejects_unsupported_operation(self):
        self.assert_invalid(lambda response: response["branches"][0]["plan"]["steps"][-1].update(operationType="table.executeCode"),
                            code="PQV2_OPERATION_UNSUPPORTED", path="steps[2]")

    def test_codex_plan_rejects_wrong_types(self):
        self.assert_invalid(lambda response: response["branches"][0]["plan"]["steps"].pop(1), path="steps")

    def test_codex_plan_rejects_hardcoded_totals(self):
        def change(response):
            branch = response["branches"][0]
            branch["controlTotal"] = None
            branch["plan"]["steps"] = branch["plan"]["steps"][:1] + [
                step("constant", "Constant", "table.addColumn", ["source"], {"newColumnName": "Total", "dataType": "number",
                     "expression": {"kind": "literal", "valueType": "number", "value": 90000}})]
            branch["plan"]["finalOutputRef"] = "constant"
        self.assert_invalid(change, path="parameters.expression")

    def test_indirect_hardcoded_total_through_rename_and_group_is_rejected(self):
        def change(response):
            plan = response["branches"][0]["plan"]
            plan["steps"] = plan["steps"][:1] + [
                step("constant", "Constant", "table.addColumn", ["source"], {"newColumnName": "Injected", "dataType": "text",
                     "expression": {"kind": "literal", "valueType": "text", "value": "90000"}}),
                step("rename", "Renamed", "table.renameColumns", ["constant"], {"renames": [{"column": "Injected", "newName": "Measure"}]}),
                step("cast", "Cast", "table.changeTypes", ["rename"], {"conversions": [{"column": "Measure", "targetType": "number"}]}),
                step("total", "Total", "table.groupRows", ["cast"], {"keyColumns": [], "aggregations": [
                    {"function": "sum", "column": "Measure", "outputName": "Total"}]})]
        self.assert_invalid(change, path="aggregations")

    def test_literal_string_cast_to_numeric_total_is_rejected(self):
        def change(response):
            plan = response["branches"][0]["plan"]
            plan["steps"] = plan["steps"][:1] + [
                step("constant", "Constant", "table.addColumn", ["source"], {"newColumnName": "Injected", "dataType": "text",
                     "expression": {"kind": "literal", "valueType": "text", "value": "90000"}}),
                step("cast", "Cast", "table.changeTypes", ["constant"], {"conversions": [{"column": "Injected", "targetType": "number"}]}),
                step("total", "Total", "table.aggregateRows", ["cast"], {"aggregations": [
                    {"function": "sum", "column": "Injected", "outputName": "Total"}]})]
        self.assert_invalid(change, path="aggregations")

    def test_source_condition_cannot_disguise_literal_measure(self):
        def change(response):
            plan = response["branches"][0]["plan"]
            plan["steps"] = plan["steps"][:2] + [
                step("constant", "Constant", "table.addColumn", ["typed"], {"newColumnName": "Total", "dataType": "number",
                    "expression": {"kind": "ifThenElse", "condition": {"kind": "compare", "operator": "gt",
                        "left": {"kind": "columnRef", "column": "Amount"}, "right": {"kind": "literal", "valueType": "number", "value": 0}},
                        "then": {"kind": "literal", "valueType": "number", "value": 90000},
                        "else": {"kind": "literal", "valueType": "number", "value": 1}}})]
            plan["finalOutputRef"] = "constant"
        self.assert_invalid(change)

    def test_literal_filter_threshold_and_source_arithmetic_are_allowed(self):
        def change(response):
            plan = response["branches"][0]["plan"]
            plan["steps"] = plan["steps"][:2] + [
                step("computed", "Computed", "table.addColumn", ["typed"], {"newColumnName": "Total", "dataType": "number",
                     "expression": {"kind": "arithmetic", "operator": "multiply", "left": {"kind": "columnRef", "column": "Amount"},
                                    "right": {"kind": "literal", "valueType": "number", "value": 2}}})]
            plan["finalOutputRef"] = "computed"
        self.assertEqual(self.draft(FakeRunner(change))["stage"], "planning")

    def test_text_category_with_numeric_filter_threshold_is_allowed(self):
        def change(response):
            branch = response["branches"][0]
            branch["controlTotal"] = None
            plan = branch["plan"]
            plan["steps"] = plan["steps"][:2] + [step("category", "Category", "table.addColumn", ["typed"],
                {"newColumnName": "Category", "dataType": "text", "expression": {"kind": "ifThenElse",
                    "condition": {"kind": "compare", "operator": "gt", "left": {"kind": "columnRef", "column": "Amount"},
                                  "right": {"kind": "literal", "valueType": "number", "value": 0}},
                    "then": {"kind": "literal", "valueType": "text", "value": "Positive"},
                    "else": {"kind": "literal", "valueType": "text", "value": "Other"}}})]
            plan["finalOutputRef"] = "category"
        self.assertEqual(self.draft(FakeRunner(change))["stage"], "planning")

    def test_disclosure_required_before_codex(self):
        for value in (False, None, 1, "true"):
            runner = FakeRunner()
            with self.subTest(value=value), self.assertRaises(InputError) as raised:
                self.draft(runner, value)
            self.assertEqual(raised.exception.code, "AF_DISCLOSURE_REQUIRED")
            self.assertEqual(runner.calls, [])

    def test_request_has_twenty_rows_total_no_metadata_samples_or_evidence(self):
        self.store.ingest([self.selection("First"), self.selection("Second")])
        self.store.understand()
        with self.store._lock:
            self.store._understand["warnings"].append({"code": "TEST", "severity": "warning",
                "message": "UNSAMPLED_WARNING_VALUE", "evidence": [{"value": "UNSAMPLED_CELL"}]})
            from pbip_assistant.sources.assistant_understand import understand_hash
            self.store._understand["understandHash"] = understand_hash(self.store._understand)
        runner = FakeRunner()
        self.draft(runner)
        request = runner.calls[0]
        self.assertEqual(len(request["sampleRows"]), 20)
        self.assertEqual(len(request["sampleOrdinals"]), 20)
        self.assertEqual(len({ordinal["sourceId"] for ordinal in request["sampleOrdinals"]}), 2)
        for descriptor in request["sources"]:
            self.assertNotIn("rows", descriptor)
            self.assertTrue(all("sample" not in column for column in descriptor["columns"]))
        rendered = json.dumps(request)
        for secret in ("UNSAMPLED_CELL", "UNSAMPLED_WARNING_VALUE", self.temp.name, '"evidence"', '"locator"'):
            self.assertNotIn(secret, rendered)

    def test_compute_samples_match_actual_ordinals_and_do_not_send_tail(self):
        self.store.ingest([self.selection(count=50, mode="compute")])
        self.store.understand()
        runner = FakeRunner()
        self.draft(runner)
        request = runner.calls[0]
        self.assertEqual(len(request["sampleRows"]), 20)
        for row, ordinal in zip(request["sampleRows"], request["sampleOrdinals"]):
            self.assertEqual(row, [str(ordinal["ordinal"]), str(ordinal["ordinal"] * 10)])
        self.assertEqual(request["sampleOrdinals"][-1]["ordinal"], 49)

    def test_understand_relationships_resolve_to_source_and_columns(self):
        self.store.ingest([self.selection("First"), self.selection("Second")])
        self.store.understand()
        snapshot = self.store.state()["snapshot"]
        source_ids = [table["id"] for table in snapshot["tables"]]
        understand = {"roles": [{"tableId": source_ids[0], "structural": "fact", "evidence": [{"value": "PRIVATE"}]}],
            "relationships": [{"id": "rel_test", "fromTable": source_ids[0], "toTable": source_ids[1],
                "fromColumns": ["ID"], "toColumns": ["ID"], "cardinality": "1:1", "evidence": [{"value": "PRIVATE"}]}]}
        runner = FakeRunner()
        adapter.draft_branch_plans("Sum Amount", snapshot, understand, [], True, runner)
        request = runner.calls[0]
        mapping = {source["tableId"]: source for source in request["sources"]}
        self.assertIn(request["understand"]["roles"][0]["tableId"], mapping)
        relationship = request["understand"]["relationships"][0]
        for endpoint, columns in (("fromTable", "fromColumns"), ("toTable", "toColumns")):
            self.assertTrue(set(relationship[columns]) <= {column["name"] for column in mapping[relationship[endpoint]]["columns"]})
        self.assertNotIn("PRIVATE", json.dumps(request))

    def test_source_tampering_is_rejected_before_codex(self):
        runner = FakeRunner()
        with self.store._lock:
            self.store._raw_tables[0]["rows"][-1][1] = "999999"
        with self.assertRaises(InputError) as raised:
            self.draft(runner)
        self.assertEqual(raised.exception.code, "AF_PLAN_INVALID")
        self.assertFalse(runner.calls)

    def test_more_than_two_hundred_source_columns_rejects_without_truncation(self):
        selection = self.selection(count=1)
        selection["payload"].update(header=[f"Column{n}" for n in range(201)], rows=[[str(n) for n in range(201)]])
        self.store.ingest([selection])
        self.store.understand()
        runner = FakeRunner()
        with self.assertRaises(InputError) as raised:
            self.draft(runner)
        self.assertEqual(raised.exception.code, "AF_PLAN_INVALID")
        self.assertIn("200", raised.exception.detail)
        self.assertFalse(runner.calls)

    def test_embedded_absolute_paths_rejected_before_codex(self):
        for value in (r"please read C:\private\secret.xlsx", r"source=C:\private\secret.xlsx",
                      r"folder \\server\private\sheet.xlsx", "please read /home/private/secret.csv"):
            runner = FakeRunner()
            with self.subTest(value=value), self.assertRaises(InputError) as raised:
                self.store.plan_draft(value, [], True, runner)
            self.assertEqual(raised.exception.code, "AF_PLAN_INVALID")
            self.assertFalse(runner.calls)

    def test_plan_hash_is_deterministic_and_response_has_only_cards(self):
        first, second = self.draft(), self.draft()
        self.assertEqual(first, second)
        self.assertEqual(first["stage"], "planning")
        self.assertEqual(first["draftInputs"]["prompt"], "Sum Amount with two explicit alternatives")
        self.assertEqual(self.store.state()["draftInputs"], first["draftInputs"])
        self.assertEqual([branch["id"] for branch in first["branches"]], ["A", "B"])
        self.assertNotEqual(first["branches"][0]["planHash"], first["branches"][1]["planHash"])
        for branch in first["branches"]:
            self.assertNotIn("plan", branch)
            self.assertNotIn("rows", branch)
            self.assertTrue(branch["steps"])
        self.assertLess(len(json.dumps(first).encode()), 64 * 1024)
        self.assertNotIn("draft", self.store.state()["branches"][0])

    def test_fanout_policy_defaults_and_accepts_declared_bounded_decimal(self):
        initial = self.draft()
        self.assertEqual([branch["maxFanOut"] for branch in initial["branches"]], ["1", "1"])
        declared = self.draft(FakeRunner(lambda response: response["branches"][0].update(maxFanOut="2.5")))
        self.assertEqual(declared["branches"][0]["maxFanOut"], "2.5")
        self.assertEqual(initial["branches"][0]["planHash"], declared["branches"][0]["planHash"])
        self.assertNotEqual(initial["planningHash"], declared["planningHash"], "policy must bind the planning revision independently of execution cache keys")

    def test_fanout_policy_rejects_nonfinite_out_of_range_or_nonstring(self):
        for value in (None, 2, True, "NaN", "Infinity", "0", "0.999", "100000.1", "-1", ""):
            with self.subTest(value=value):
                self.assert_invalid(lambda response: response["branches"][0].update(maxFanOut=value), path="maxFanOut")

    def test_control_total_policy_changes_planning_hash_without_changing_result_plan(self):
        initial = self.draft()
        changed = self.draft(FakeRunner(lambda response: response["branches"][0]["controlTotal"].update(tolerance="0.5")))
        self.assertEqual(initial["branches"][0]["planHash"], changed["branches"][0]["planHash"])
        self.assertNotEqual(initial["planningHash"], changed["planningHash"])

    def test_compute_ingest_preserves_and_revalidates_plans_with_same_schema(self):
        original = self.draft()
        computed = self.store.ingest([self.selection(count=50, mode="compute")], original["planningHash"])
        self.assertEqual(computed["stage"], "planning")
        self.assertEqual(computed["mode"], "compute")
        self.assertEqual([branch["planHash"] for branch in computed["branches"]], [branch["planHash"] for branch in original["branches"]])
        self.assertEqual(computed["understand"]["snapshotHash"], computed["snapshotHash"])

    def test_compute_ingest_without_expected_planning_binding_discards_plans(self):
        self.draft()
        computed = self.store.ingest([self.selection(count=50, mode="compute")])
        self.assertEqual(computed["stage"], "ingested")
        self.assertEqual(computed["branches"], [])
        self.assertIsNone(computed["planningHash"])
        self.assertIsNone(self.store._planning)

    def test_stale_expected_planning_hash_rejects_before_source_mutation(self):
        first = self.draft()
        snapshot_hash = self.store.state()["snapshotHash"]
        second = self.store.plan_draft("A different goal with identical plan steps", [], True, FakeRunner())
        self.assertNotEqual(first["planningHash"], second["planningHash"])
        with self.assertRaises(InputError) as raised:
            self.store.ingest([self.selection(count=50, mode="compute")], first["planningHash"])
        self.assertEqual(raised.exception.code, "AF_SPEC_STALE")
        self.assertEqual(self.store.state()["snapshotHash"], snapshot_hash)
        self.assertEqual(self.store.state()["planningHash"], second["planningHash"])

    def test_current_question_definitions_bind_submitted_answers_without_evidence(self):
        question = self.store.state()["questions"][0]
        runner = FakeRunner()
        self.store.plan_draft("Sum Amount", [{"questionId": question["id"], "answer": "Confirmed synthetic policy"}], True, runner)
        payload = runner.calls[0]
        definition = next(item for item in payload["questions"] if item["id"] == question["id"])
        self.assertEqual(definition["question"], question["question"])
        self.assertNotIn("evidence", definition)
        self.assertEqual(payload["answers"][0]["questionId"], definition["id"])
        unknown = FakeRunner()
        with self.assertRaises(InputError) as raised:
            self.store.plan_draft("Sum Amount", [{"questionId": "q_unknown", "answer": "yes"}], True, unknown)
        self.assertEqual(raised.exception.code, "AF_PLAN_INVALID")
        self.assertFalse(unknown.calls)

    def test_oversized_sample_request_is_rejected_before_codex_without_truncation(self):
        selection = self.selection()
        selection["payload"].update(header=["Amount", *[f"Column{n}" for n in range(59)]],
                                    rows=[["x" * 1000] * 60 for _ in range(20)])
        self.store.ingest([selection])
        self.store.understand()
        runner = FakeRunner()
        with self.assertRaises(InputError) as raised:
            self.draft(runner)
        self.assertEqual(raised.exception.code, "AF_PLAN_INVALID")
        self.assertIn("512 KiB", raised.exception.detail)
        self.assertFalse(runner.calls)

    def test_changed_schema_or_reset_invalidates_private_plans(self):
        self.draft()
        changed = self.selection(count=50, mode="compute")
        changed["payload"]["header"][1] = "Quantity"
        result = self.store.ingest([changed])
        self.assertEqual(result["stage"], "ingested")
        self.assertEqual(result["branches"], [])
        self.store.reset()
        self.assertIsNone(self.store._planning)

    def test_controls_are_bound_to_actual_output_and_input(self):
        for name, value in (("resultColumn", "Missing"), ("sourceColumn", "Missing"), ("afterFilters", "true"), ("aggregation", "average"), ("tolerance", "NaN"), ("tolerance", "-1")):
            with self.subTest(name=name, value=value):
                self.assert_invalid(lambda response: response["branches"][0]["controlTotal"].update({name: value}), path="controlTotal")

    def test_exact_typed_draft_contract_is_required(self):
        self.assert_invalid(lambda response: response["branches"][0]["plan"].update(schemaVersion="1.0"))
        self.assert_invalid(lambda response: response["branches"][0]["plan"].update(finalOutputRef=None))
        self.assert_invalid(lambda response: response["branches"][0]["plan"]["steps"][0].update(inputs=[{}]))

    def test_more_than_twenty_steps_rejected(self):
        def change(response):
            plan = response["branches"][0]["plan"]
            for index in range(19):
                ref = "extra_" + str(index)
                plan["steps"].append(step(ref, "Extra" + str(index), "table.selectColumns", [plan["finalOutputRef"]], {"columns": ["Total"]}))
                plan["finalOutputRef"] = ref
        self.assert_invalid(change, path="steps")

    def test_union_cannot_exceed_two_hundred_fifty_six_output_columns(self):
        selections = [self.selection("First", count=1), self.selection("Second", count=1)]
        for offset, selection in enumerate(selections):
            selection["payload"].update(header=[f"Column{offset}_{n}" for n in range(130)], rows=[[str(n) for n in range(130)]])
        self.store.ingest(selections)
        self.store.understand()
        sources = adapter.assistant_source_catalog(self.store.state()["snapshot"])
        class UnionRunner:
            def propose(inner, payload):
                plan = {"summary": "Union schemas", "questions": [], "assumptions": [], "warnings": [], "finalOutputRef": "union", "steps": [
                    step("first", "First", "source.workbookTable", [], {"sourceId": sources[0]["sourceId"]}),
                    step("second", "Second", "source.workbookTable", [], {"sourceId": sources[1]["sourceId"]}),
                    step("union", "Union", "table.appendTables", ["first", "second"], {"schemaMode": "union"})]}
                return {"summary": "Two plans", "questions": [], "assumptions": [], "branches": [
                    {"id": id_, "label": id_, "rationale": "Union all columns", "controlTotal": None, "plan": deepcopy(plan)} for id_ in ("A", "B")]}
        with self.assertRaises(InputError) as raised:
            self.draft(UnionRunner())
        self.assertEqual(raised.exception.code, "AF_PLAN_INVALID")
        self.assertIn("256", raised.exception.detail)

    def test_constant_cannot_be_hidden_in_append_with_real_source_measures(self):
        def change(response):
            plan = response["branches"][0]["plan"]
            plan["steps"] = plan["steps"][:2] + [
                step("constant", "Constant", "table.addColumn", ["source"], {"newColumnName": "Fake", "dataType": "text",
                    "expression": {"kind": "literal", "valueType": "text", "value": "90000"}}),
                step("remove", "Removed", "table.removeColumns", ["constant"], {"columns": ["Amount"]}),
                step("rename", "Renamed", "table.renameColumns", ["remove"], {"renames": [{"column": "Fake", "newName": "Amount"}]}),
                step("cast", "Cast", "table.changeTypes", ["rename"], {"conversions": [{"column": "Amount", "targetType": "number"}]}),
                step("append", "Appended", "table.appendTables", ["typed", "cast"], {"schemaMode": "strict"}),
                step("total", "Total", "table.aggregateRows", ["append"], {"aggregations": [{"function": "sum", "column": "Amount", "outputName": "Total"}]})]
        self.assert_invalid(change, path="aggregations")

    def test_oversized_cards_fail_without_publishing_or_truncating_plans(self):
        def change(response):
            response["summary"] = "😀" * 3000
            for branch in response["branches"]:
                branch["rationale"] = "😀" * 3000
                plan = branch["plan"]
                while len(plan["steps"]) < 20:
                    ref = "extra_" + str(len(plan["steps"]))
                    plan["steps"].append(step(ref, "Extra" + str(len(plan["steps"])), "table.selectColumns", [plan["finalOutputRef"]], {"columns": ["Total"]}))
                    plan["finalOutputRef"] = ref
                for item in plan["steps"]:
                    item["actionDescription"] = "😀" * 500
        self.assert_invalid(change, path="branches")
        self.assertIsNone(self.store._planning)

    def test_six_join_kinds_and_expanded_numeric_lineage_validate(self):
        self.store.ingest([self.selection("Left"), self.selection("Right")])
        self.store.understand()
        for kind in ("inner", "leftOuter", "rightOuter", "fullOuter", "leftAnti", "rightAnti"):
            for aggregate in (False, True):
                runner = FakeRunner()
                snapshot = self.store.state()["snapshot"]
                sources = adapter.assistant_source_catalog(snapshot)
                def change(response):
                    for branch in response["branches"]:
                        branch["controlTotal"] = None
                        steps = [step("left", "Left", "source.workbookTable", [], {"sourceId": sources[0]["sourceId"]}),
                            step("right", "Right", "source.workbookTable", [], {"sourceId": sources[1]["sourceId"]}),
                            step("typed", "Typed", "table.changeTypes", ["right"], {"conversions": [{"column": "Amount", "targetType": "number"}]}),
                            step("joined", "Joined", "table.mergeTables", ["left", "typed"], {"keyPairs": [{"leftColumn": "ID", "rightColumn": "ID"}], "joinKind": kind, "nestedColumnName": "Details"}),
                            step("expanded", "Expanded", "table.expandTableColumn", ["joined"], {"nestedColumn": "Details", "columns": [{"column": "Amount", "newName": "JoinedAmount"}]})]
                        if aggregate:
                            steps.append(step("total", "Total", "table.aggregateRows", ["expanded"], {"aggregations": [{"function": "sum", "column": "JoinedAmount", "outputName": "Total"}]}))
                        branch["plan"].update(steps=steps, finalOutputRef="total" if aggregate else "expanded")
                runner.change = change
                with self.subTest(kind=kind, aggregate=aggregate):
                    self.assertEqual(self.draft(runner)["stage"], "planning")

    def test_runner_failure_does_not_retry_or_publish_plans(self):
        runner = FakeRunner()
        runner.propose = lambda payload: (_ for _ in ()).throw(InputError("CODEX_RATE_LIMITED", "codex", "limited"))
        with self.assertRaises(InputError) as raised:
            self.draft(runner)
        self.assertEqual(raised.exception.code, "CODEX_RATE_LIMITED")
        self.assertIsNone(self.store._planning)

    def test_endpoint_preserves_codex_errors_for_outer_cooldown_handler(self):
        class Endpoint(AssistantPlanEndpoints):
            app = SimpleNamespace(assistant=self.store, assistant_plan_runner=FakeRunner())
            def _read_json(handler, maximum):
                return {"prompt": "Sum Amount", "answers": [], "acknowledged": True}
            def _assistant_error(handler, exc):
                raise AssertionError("Codex errors must reach central policy")
        with patch.object(self.store, "plan_draft", side_effect=InputError("CODEX_RATE_LIMITED", "codex", "limited")):
            with self.assertRaises(InputError) as raised:
                Endpoint()._post_assistant_plan_draft()
        self.assertEqual(raised.exception.code, "CODEX_RATE_LIMITED")

    def test_endpoint_default_runner_uses_managed_temporary_workspaces(self):
        manager = object()
        class Endpoint(AssistantPlanEndpoints):
            app = SimpleNamespace(assistant=self.store, assistant_plan_runner=None,
                                  runtime=SimpleNamespace(temp_workspaces=manager))
            def _read_json(handler, maximum):
                return {"prompt": "Sum Amount", "answers": [], "acknowledged": True}
            def _json(handler, status, result):
                self.assertEqual(status, 200)
                self.assertEqual(result["stage"], "planning")
        with patch("pbip_assistant.coordinator.endpoints.assistant_plan.CodexAssistantPlanRunner", return_value=FakeRunner()) as runner:
            Endpoint()._post_assistant_plan_draft()
        runner.assert_called_once_with(workspace_manager=manager)

    def test_default_runner_uses_structured_isolated_cli_without_mutating_typed_runner(self):
        snapshot = self.store.state()["snapshot"]
        payload = adapter._request("Sum Amount", snapshot, self.store.state()["understand"], [], adapter.assistant_source_catalog(snapshot))
        response = AssistantBranchPlanner().propose(payload)
        def run(command, **kwargs):
            schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            self.assertEqual(schema["properties"]["branches"]["minItems"], 2)
            self.assertEqual(schema["properties"]["branches"]["maxItems"], 2)
            self.assertIn("--ephemeral", command)
            self.assertIn("--ignore-user-config", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertIn("Never return computed values", kwargs["input"])
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")
        with patch.object(adapter, "find_codex_executable", return_value="synthetic-codex"), patch.object(adapter.subprocess, "run", side_effect=run) as process:
            result = self.draft(adapter.CodexAssistantPlanRunner())
        self.assertEqual(result["stage"], "planning")
        self.assertEqual(process.call_count, 1)


if __name__ == "__main__":
    unittest.main()
