from __future__ import annotations
import base64
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore
from pbip_assistant.pq_typed import DESTINATION_MARKER, TypedPlanStore, build_source_catalog, compile_m
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakePQRunner
from tests.support.workbook_fingerprint import repack

from tests.support.pq_typed import (FakeTypedPlanner, CatalogTypedPlanner, InvalidSingleSourcePlanner, InvalidMultiSourcePlanner, ValidButWrongSingleSourcePlanner, WrongKindSingleSourcePlanner, ReversedSelectPlanner, ValidWrongSingleSourcePlanner)

class TypedStepsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.path = Path(self.temp.name) / fixture.name
        self.payload = fixture.read_bytes()
        self.path.write_bytes(self.payload)
        self.workbook = office_snapshot(self.path)
        self.runner = FakePQRunner()
        self.preview_store = PQPreviewStore(self.runner)
        self.addCleanup(self.preview_store.close)
        self.planner = FakeTypedPlanner()
        self.store = TypedPlanStore(self.planner, self.preview_store)
        self.addCleanup(self.store.close)

    def test_select_columns_preserves_upstream_order_even_when_planner_reverses_ids(self) -> None:
        store = TypedPlanStore(ReversedSelectPlanner(), self.runner)
        plan = store.create_plan(
            "Keep the first three columns.", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        source_step, selected_step = plan["steps"]
        expected = [item["name"] for item in source_step["outputContract"]["columns"][:3]]
        actual = [item["name"] for item in selected_step["outputContract"]["columns"]]
        self.assertEqual(actual, expected)
        selected_ids = selected_step["operation"]["parameters"]["columnIds"]
        self.assertEqual(
            selected_ids,
            [item["columnId"] for item in source_step["outputContract"]["columns"][:3]],
        )

    def test_runtime_compiler_restores_source_order_after_column_recreation(self) -> None:
        plan = self.create_plan()
        source = plan["steps"][0]
        source_columns = deepcopy(source["outputContract"]["columns"])
        original_names = [item["name"] for item in source_columns]
        target = source_columns[1]
        remaining = [deepcopy(item) for item in source_columns if item["columnId"] != target["columnId"]]
        replacement = {
            "columnId": "col_recreated_target",
            "name": target["name"],
            "inferredType": target["inferredType"],
            "nullable": target["nullable"],
            "ordinal": len(remaining),
        }
        recreated = remaining + [replacement]
        removed = {
            "stepId": "stp_removed_target",
            "position": 2,
            "variableName": "RemovedOriginalColumn",
            "actionDescription": "Remove the original column before recreating it.",
            "operation": {
                "type": "table.removeColumns",
                "parameters": {"columnIds": [target["columnId"]]},
            },
            "inputs": [{"kind": "step", "ref": source["stepId"]}],
            "outputContract": {"kind": "table", "schemaHash": "sha256:" + "0" * 64, "columns": remaining},
        }
        step = {
            "stepId": "stp_recreated",
            "position": 3,
            "variableName": "RecreatedColumn",
            "actionDescription": "Recreate one existing column.",
            "operation": {
                "type": "table.addColumn",
                "parameters": {
                    "newColumnName": target["name"], "newColumnId": replacement["columnId"],
                    "dataType": target["inferredType"],
                    "expression": {"kind": "literal", "valueType": "text", "value": "normalized"},
                    "onEvaluationError": "block",
                },
            },
            "inputs": [{"kind": "step", "ref": removed["stepId"]}],
            "outputContract": {"kind": "table", "schemaHash": "sha256:" + "0" * 64, "columns": recreated},
        }
        probe = {"sources": plan["sources"], "steps": [source, removed, step], "finalOutputStepId": step["stepId"]}
        semantic = compile_m(probe)
        runtime = compile_m(probe, enforce_source_order=True)
        self.assertNotIn("Table.ReorderColumns", semantic)
        self.assertIn("Table.ReorderColumns", runtime)
        expected_order = "{" + ", ".join('"' + name + '"' for name in original_names) + "}"
        self.assertIn(expected_order, runtime)

    def test_runtime_compiler_keeps_genuinely_new_columns_at_end(self) -> None:
        plan = self.create_plan()
        runtime = compile_m(plan, enforce_source_order=True)
        self.assertNotIn("Table.ReorderColumns", runtime)
        self.assertEqual(plan["steps"][2]["outputContract"]["columns"][-1]["name"], "Profit")

    def test_runtime_compiler_preserves_renamed_column_lineage_position(self) -> None:
        plan = self.create_plan()
        source = deepcopy(plan["steps"][0])
        source_columns = deepcopy(source["outputContract"]["columns"])
        target = source_columns[1]
        renamed_columns = deepcopy(source_columns)
        renamed_columns[1]["name"] = "RenamedExistingColumn"
        renamed = {
            "stepId": "stp_renamed_existing",
            "position": 2,
            "variableName": "RenamedExistingColumnStep",
            "actionDescription": "Rename one existing column.",
            "operation": {
                "type": "table.renameColumns",
                "parameters": {"renames": [{"columnId": target["columnId"], "newName": "RenamedExistingColumn"}]},
            },
            "inputs": [{"kind": "step", "ref": source["stepId"]}],
            "outputContract": {"kind": "table", "schemaHash": "sha256:" + "0" * 64, "columns": renamed_columns},
        }
        probe = {"sources": plan["sources"], "steps": [source, renamed], "finalOutputStepId": renamed["stepId"]}
        runtime = compile_m(probe, enforce_source_order=True)
        self.assertNotIn("Table.ReorderColumns", runtime)

    def create_plan(self) -> dict:
        return self.store.create_plan(
            "Lọc Gross Revenue > 1000, thêm Profit rồi sắp xếp giảm dần",
            self.workbook, {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )

    def test_draft_is_normalized_to_authoritative_ids_and_compiled(self) -> None:
        plan = self.create_plan()
        self.assertEqual(plan["schemaVersion"], "2.0")
        self.assertEqual(plan["planStatus"], "reviewReady")
        self.assertTrue(plan["revision"]["revisionId"].startswith("rev_"))
        self.assertTrue(all(step["stepId"].startswith("stp_") for step in plan["steps"]))
        profit = plan["steps"][2]
        self.assertTrue(profit["operation"]["parameters"]["newColumnId"].startswith("col_"))
        self.assertEqual(profit["outputContract"]["columns"][-1]["name"], "Profit")
        self.assertEqual(plan["validation"]["overall"], "passed")
        self.assertRegex(plan["validation"]["compiledMHash"], r"^sha256:[a-f0-9]{64}$")
        code = compile_m(plan)
        self.assertIn("Table.SelectRows", code)
        self.assertIn("Table.AddColumn", code)
        self.assertIn("Table.Sort", code)
        self.assertIn('Record.Field(_, "Gross Revenue")', code)
        self.assertNotIn("Record.Field(_row", code)
        self.assertNotIn("Web.Contents", code)
        self.assertNotIn("File.Contents", code)
        self.assertNotIn("mCode", str(plan))

    def test_invalid_single_source_id_is_bound_only_to_explicit_selection(self) -> None:
        store = TypedPlanStore(InvalidSingleSourcePlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan(
            "Use the selected sales table", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        selected_source = next(source for source in plan["sources"] if source.get("objectName") == "SalesTable")
        self.assertEqual(plan["planStatus"], "reviewReady")
        self.assertEqual(plan["steps"][0]["operation"]["parameters"]["sourceId"], selected_source["sourceId"])
        self.assertTrue(any("explicitly selected" in warning for warning in plan["warnings"]))

    def test_invalid_multi_source_id_remains_blocked_without_guessing(self) -> None:
        store = TypedPlanStore(InvalidMultiSourcePlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan(
            "Merge two sources", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        self.assertEqual(plan["planStatus"], "blocked")
        self.assertIn("PQV2_SOURCE_NOT_FOUND", {item["code"] for item in plan["hardBlockers"]})

    def test_valid_but_wrong_single_source_is_rebound_to_explicit_selection(self) -> None:
        store = TypedPlanStore(ValidButWrongSingleSourcePlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan(
            "Use only the selected sales table", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        selected = next(source for source in plan["sources"] if source.get("objectName") == "SalesTable")
        self.assertEqual(plan["planStatus"], "reviewReady")
        self.assertEqual(plan["steps"][0]["operation"]["parameters"]["sourceId"], selected["sourceId"])
        self.assertTrue(any("explicitly selected" in warning for warning in plan["warnings"]))

    def test_single_source_kind_mismatch_is_blocked_without_rebinding(self) -> None:
        store = TypedPlanStore(WrongKindSingleSourcePlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan(
            "Use only the selected sales table", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        self.assertEqual(plan["planStatus"], "blocked")
        source_issues = [item for item in plan["hardBlockers"] if item["code"] == "PQV2_SOURCE_NOT_FOUND"]
        self.assertEqual(len(source_issues), 1)
        self.assertEqual(source_issues[0]["path"], "steps[0].parameters.sourceId")

    def test_single_source_plan_cannot_switch_to_another_valid_table(self) -> None:
        store = TypedPlanStore(ValidWrongSingleSourcePlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan(
            "Use only the selected sales table", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        selected_source = next(source for source in plan["sources"] if source.get("objectName") == "SalesTable")
        self.assertEqual(plan["planStatus"], "reviewReady")
        self.assertEqual(plan["steps"][0]["operation"]["parameters"]["sourceId"], selected_source["sourceId"])

    def test_table_source_identity_survives_sheet_move_and_declared_types_survive_sample_representation(self) -> None:
        original = deepcopy(self.workbook)
        moved = deepcopy(self.workbook)
        sales_original = next(item for item in original["tables"] if item["name"] == "SalesTable")
        sales_moved = next(item for item in moved["tables"] if item["name"] == "SalesTable")
        sales_original["inferredTypes"] = ["text", "text", "text", "date", "number", "number", "number", "integer", "integer"]
        sales_moved["inferredTypes"] = list(sales_original["inferredTypes"])
        sales_moved["sheet"] = "Archive"
        sales_moved["rows"][0][3] = "2026-09-01"
        _, original_sources, _ = build_source_catalog(original)
        _, moved_sources, _ = build_source_catalog(moved)
        first = next(source for source in original_sources if source.get("objectName") == "SalesTable")
        second = next(source for source in moved_sources if source.get("objectName") == "SalesTable")
        self.assertEqual(first["sourceId"], second["sourceId"])
        self.assertEqual(first["columns"], second["columns"])
        self.assertEqual(second["columns"][3]["inferredType"], "date")

    def test_used_range_identity_and_declared_types_do_not_depend_on_sample_values(self) -> None:
        numeric_sample = {
            "name": "UsedRange.xlsx", "url": "", "activeSheet": "Raw",
            "tables": [],
            "sheets": [{
                "name": "Raw", "headerRow": 5, "columnLetters": ["B", "C"],
                "headers": ["OrderDate", "Qty"], "rows": [[45949, "7"]],
                "inferredTypes": ["date", "integer"],
                "totalRows": 25, "totalColumns": 2,
            }],
        }
        text_sample = deepcopy(numeric_sample)
        text_sample["sheets"][0]["rows"] = [["2025-10-19", 7]]

        _, first_catalog, _ = build_source_catalog(numeric_sample)
        _, second_catalog, _ = build_source_catalog(text_sample)
        first, second = first_catalog[0], second_catalog[0]

        self.assertEqual(first["kind"], "usedRange")
        self.assertEqual(first["sourceId"], second["sourceId"])
        self.assertEqual(first["schemaHash"], second["schemaHash"])
        self.assertEqual(
            [column["inferredType"] for column in second["columns"]],
            ["date", "integer"],
        )

    def test_declared_type_shape_is_validated_before_catalog_creation(self) -> None:
        workbook = deepcopy(self.workbook)
        sales = next(item for item in workbook["tables"] if item["name"] == "SalesTable")
        sales["inferredTypes"] = ["text"]
        with self.assertRaises(InputError) as captured:
            build_source_catalog(workbook)
        self.assertEqual(captured.exception.code, "INVALID_WORKBOOK")
        self.assertEqual(captured.exception.path, "workbook.tables[0].inferredTypes")

    def test_delete_producer_creates_blocked_revision_and_repair_patch(self) -> None:
        plan = self.create_plan()
        producer = plan["steps"][2]
        failed = plan["steps"][3]
        broken = self.store.create_revision({
            "baseRevisionId": plan["revision"]["revisionId"],
            "changeReason": "Delete Profit producer",
            "changes": [{"type": "deleteStep", "stepId": producer["stepId"]}],
        })
        self.assertEqual(broken["planStatus"], "blocked")
        self.assertIn("PQV2_DEPENDENCY_INVALID", {item["code"] for item in broken["hardBlockers"]})
        repair = self.store.repair(
            broken["revision"]["revisionId"], broken["snapshotId"],
            {"code": "COLUMN_NOT_FOUND", "message": "Profit is missing", "failedStepId": failed["stepId"]},
        )
        self.assertEqual(repair["status"], "repairProposed")
        self.assertLessEqual(len(repair["patchOptions"]), 3)
        self.assertEqual(repair["recommendedPatchId"], repair["patchOptions"][0]["patchId"])
        restored = self.store.create_revision({
            "baseRevisionId": broken["revision"]["revisionId"],
            "patchId": repair["recommendedPatchId"],
            "changeReason": "Restore Profit producer",
        })
        self.assertEqual(restored["planStatus"], "reviewReady")
        self.assertEqual(restored["preview"], None)
        self.assertEqual(restored["approval"], {"status": "notRequested"})

    def test_preview_approval_prepare_and_readback_are_revision_bound(self) -> None:
        plan = self.create_plan()
        encoded = base64.b64encode(self.payload).decode("ascii")
        preview = self.store.preview(plan["revision"]["revisionId"], self.workbook, encoded)
        self.assertEqual(preview["status"], "excelRuntimePreview")
        self.assertNotIn("resultWorkbookBase64", preview)
        self.assertIn("sources", self.runner.requests[0])
        self.assertIn("Table.AddColumn", self.runner.requests[0]["mCode"])
        approval = self.store.approve(
            plan["revision"]["revisionId"], preview["previewId"], DESTINATION_MARKER,
        )
        prepared = self.store.prepare_apply(
            approval["approvalId"], base64.b64encode(repack(self.payload)).decode("ascii"),
            {"marker": DESTINATION_MARKER},
        )
        self.assertTrue(base64.b64decode(prepared["resultWorkbookBase64"]).startswith(b"PK"))
        with self.assertRaises(InputError) as replay:
            self.store.prepare_apply(approval["approvalId"], encoded, {"marker": DESTINATION_MARKER})
        self.assertEqual(replay.exception.code, "PQV2_APPROVAL_USED")
        completed = self.store.complete_apply(prepared["applyId"], {
            "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
            "rowCount": prepared["expectedRows"], "columnCount": prepared["expectedColumns"],
        })
        self.assertEqual(completed["status"], "applied")

    def test_changed_workbook_and_edit_after_preview_invalidate_write(self) -> None:
        plan = self.create_plan()
        encoded = base64.b64encode(self.payload).decode("ascii")
        preview = self.store.preview(plan["revision"]["revisionId"], self.workbook, encoded)
        approval = self.store.approve(plan["revision"]["revisionId"], preview["previewId"], DESTINATION_MARKER)
        changed = base64.b64encode(repack(self.payload, change_cell=True)).decode("ascii")
        with self.assertRaises(InputError) as stale_source:
            self.store.prepare_apply(approval["approvalId"], changed, {"marker": DESTINATION_MARKER})
        self.assertEqual(stale_source.exception.code, "PQV2_SOURCE_CHANGED")

        preview = self.store.preview(plan["revision"]["revisionId"], self.workbook, encoded)
        approval = self.store.approve(plan["revision"]["revisionId"], preview["previewId"], DESTINATION_MARKER)
        self.store.create_revision({
            "baseRevisionId": plan["revision"]["revisionId"], "changeReason": "Move display step",
            "changes": [{"type": "moveStep", "stepId": plan["steps"][3]["stepId"], "position": 4}],
        })
        with self.assertRaises(InputError) as stale_revision:
            self.store.prepare_apply(approval["approvalId"], encoded, {"marker": DESTINATION_MARKER})
        self.assertEqual(stale_revision.exception.code, "PQV2_APPROVAL_MISMATCH")

    def test_catalog_operations_compile_from_lineage_not_raw_m(self) -> None:
        store = TypedPlanStore(CatalogTypedPlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan("Catalog cross-check", self.workbook)
        self.assertEqual(plan["planStatus"], "reviewReady", plan["hardBlockers"])
        code = compile_m(plan)
        for function in [
            "Table.SelectColumns", "Table.RemoveColumns", "Table.RenameColumns",
            "Table.TransformColumnTypes", "Table.Distinct", "Table.Group",
            "Table.Combine", "Table.NestedJoin", "Table.ExpandTableColumn",
        ]:
            self.assertIn(function, code)
        self.assertNotIn("Web.Contents", code)
        self.assertNotIn("File.Contents", code)
        aggregate = next(step for step in plan["steps"] if step["operation"]["type"] == "table.aggregateRows")
        edited = store.create_revision({
            "baseRevisionId": plan["revision"]["revisionId"],
            "changes": [{"type": "setFinalOutput", "stepId": aggregate["stepId"]}],
        })
        self.assertEqual(edited["planStatus"], "reviewReady", edited["hardBlockers"])

    def test_merge_cannot_be_final_until_nested_table_is_expanded(self) -> None:
        class MergeOnlyPlanner(CatalogTypedPlanner):
            def propose(self, payload: dict) -> dict:
                draft = super().propose(payload)
                draft["steps"] = [
                    step for step in draft["steps"] if step["clientRef"] != "expand"
                ]
                draft["finalOutputRef"] = "merge"
                return draft

        store = TypedPlanStore(MergeOnlyPlanner(), self.preview_store)
        self.addCleanup(store.close)
        blocked = store.create_plan("Merge without expand", self.workbook)
        self.assertEqual(blocked["planStatus"], "blocked")
        self.assertIn(
            "PQV2_NESTED_TABLE_NOT_EXPANDED",
            {issue["code"] for issue in blocked["hardBlockers"]},
        )
        self.assertIsNone(blocked["validation"]["compiledMHash"])

        valid = TypedPlanStore(CatalogTypedPlanner(), self.preview_store)
        self.addCleanup(valid.close)
        expanded = valid.create_plan("Merge and expand", self.workbook)
        merge_step = next(
            step for step in expanded["steps"]
            if step["operation"]["type"] == "table.mergeTables"
        )
        tampered = deepcopy(expanded)
        tampered["finalOutputStepId"] = merge_step["stepId"]
        with self.assertRaises(InputError) as caught:
            compile_m(tampered)
        self.assertEqual(caught.exception.code, "PQV2_NESTED_TABLE_NOT_EXPANDED")

    def test_initial_planner_repairs_one_missing_final_draft(self) -> None:
        class MissingFinalThenValidPlanner(FakeTypedPlanner):
            def __init__(self) -> None:
                super().__init__()
                self.calls: list[dict] = []

            def propose(self, payload: dict) -> dict:
                self.calls.append(deepcopy(payload))
                draft = super().propose(payload)
                if len(self.calls) == 1:
                    draft["finalOutputRef"] = None
                return draft

        planner = MissingFinalThenValidPlanner()
        store = TypedPlanStore(planner, self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan(
            "Create a valid flat result", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        self.assertEqual(plan["planStatus"], "reviewReady", plan["hardBlockers"])
        self.assertEqual(len(planner.calls), 2)
        self.assertEqual(
            planner.calls[1]["validationFeedback"]["codes"],
            ["PQV2_FINAL_OUTPUT_NOT_TABLE"],
        )

    def test_raw_m_and_unknown_ai_fields_are_rejected_before_compile(self) -> None:
        class RawMPlanner(FakeTypedPlanner):
            def propose(self, payload: dict) -> dict:
                draft = super().propose(payload)
                draft["steps"][1]["parameters"]["mCode"] = "Web.Contents(\"https://example.test\")"
                return draft

        raw_store = TypedPlanStore(RawMPlanner(), self.preview_store)
        self.addCleanup(raw_store.close)
        blocked = raw_store.create_plan("Inject raw M", self.workbook)
        self.assertEqual(blocked["planStatus"], "blocked")
        self.assertIn("PQV2_POLICY_VIOLATION", {issue["code"] for issue in blocked["hardBlockers"]})
        self.assertIsNone(blocked["validation"]["compiledMHash"])

        class UnknownFieldPlanner(FakeTypedPlanner):
            def propose(self, payload: dict) -> dict:
                draft = super().propose(payload)
                draft["steps"][0]["approval"] = {"status": "approved"}
                return draft

        unknown_store = TypedPlanStore(UnknownFieldPlanner(), self.preview_store)
        self.addCleanup(unknown_store.close)
        with self.assertRaises(InputError) as invalid:
            unknown_store.create_plan("Forge approval", self.workbook)
        self.assertEqual(invalid.exception.code, "PQV2_JSON_INVALID")

    def test_known_expression_type_mismatch_blocks_preview(self) -> None:
        class MismatchPlanner(FakeTypedPlanner):
            def propose(self, payload: dict) -> dict:
                draft = super().propose(payload)
                draft["steps"][1]["parameters"]["predicate"]["right"] = {
                    "kind": "literal", "valueType": "text", "value": "one thousand",
                }
                return draft

        store = TypedPlanStore(MismatchPlanner(), self.preview_store)
        self.addCleanup(store.close)
        plan = store.create_plan("Compare number to text", self.workbook)
        self.assertEqual(plan["planStatus"], "blocked")
        self.assertIn("PQV2_TYPE_MISMATCH", {issue["code"] for issue in plan["hardBlockers"]})

    def test_cycle_and_unknown_operation_are_hard_blockers(self) -> None:
        plan = self.create_plan()
        source, final = plan["steps"][0], plan["steps"][-1]
        cyclic = self.store.create_revision({
            "baseRevisionId": plan["revision"]["revisionId"],
            "changes": [{
                "type": "updateStep", "stepId": source["stepId"],
                "stepDraft": {"inputs": [{"kind": "step", "ref": final["stepId"]}]},
            }],
        })
        self.assertEqual(cyclic["planStatus"], "blocked")
        self.assertIn("PQV2_DEPENDENCY_CYCLE", {issue["code"] for issue in cyclic["hardBlockers"]})

        other = self.store.create_plan("Create a second plan", self.workbook)
        unknown = self.store.create_revision({
            "baseRevisionId": other["revision"]["revisionId"],
            "changes": [{
                "type": "updateStep", "stepId": other["steps"][1]["stepId"],
                "stepDraft": {"operationType": "table.executeRawM", "parameters": {}},
            }],
        })
        self.assertEqual(unknown["planStatus"], "blocked")
        self.assertIn("PQV2_OPERATION_UNSUPPORTED", {issue["code"] for issue in unknown["hardBlockers"]})


if __name__ == "__main__":
    unittest.main()
