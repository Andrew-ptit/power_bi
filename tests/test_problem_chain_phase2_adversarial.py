from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import time
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import (
    MAX_REVISIONS,
    ProblemChainStore,
    canonical_json,
    compute_history_hash,
    validate_document,
)


def _plan() -> dict:
    columns = [
        {"columnId": "col_order", "name": "OrderID", "inferredType": "text", "nullable": False, "ordinal": 0},
        {"columnId": "col_qty", "name": "Qty", "inferredType": "integer", "nullable": False, "ordinal": 1},
    ]
    source = {
        "sourceId": "src_sales", "kind": "excelTable", "sheetName": "Sales",
        "objectName": "tblSales", "schemaHash": "sha256:" + "1" * 64,
        "sampleOnly": False, "totalRows": 2, "totalColumns": 2,
        "columns": columns,
    }
    return {
        "snapshotId": "snap_phase2_oracle", "summary": "Read the sales source.",
        "questions": [], "assumptions": [], "warnings": [], "sources": [source],
        "steps": [{
            "stepId": "stp_source", "position": 1, "variableName": "SalesSource",
            "actionDescription": "Read tblSales.",
            "operation": {"type": "source.workbookTable", "parameters": {"sourceId": "src_sales"}},
            "inputs": [],
            "outputContract": {"kind": "table", "schemaHash": "sha256:" + "2" * 64, "columns": columns},
        }],
        "finalOutputStepId": "stp_source", "changeSet": [],
    }


class BranchPlanner:
    """Prompt-directed delta producer; intentionally independent of product fixtures."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def propose(self, payload: dict) -> dict:
        self.calls.append(deepcopy(payload))
        prompt = payload["userRequest"]
        base = payload["baseRevision"]
        final_step = base["finalOutputStepId"]
        if prompt == "filter qty":
            return {
                "summary": "Filter positive quantities.", "questions": [], "assumptions": [], "warnings": [],
                "changeReason": "Filter Qty", "changes": [{
                    "type": "insertStep", "afterStepId": final_step,
                    "stepDraft": {
                        "clientRef": "filtered_qty", "variableName": "FilteredQty",
                        "actionDescription": "Keep positive Qty.", "operationType": "table.filterRows",
                        "parameters": {
                            "predicate": {
                                "kind": "compare", "operator": "gt",
                                "left": {"kind": "columnRef", "columnId": "col_qty"},
                                "right": {"kind": "literal", "valueType": "number", "value": 0},
                            },
                            "onEvaluationError": "block",
                        },
                        "inputs": [final_step],
                    },
                }, {"type": "setFinalOutput", "stepId": "filtered_qty"}],
            }
        keep = ["col_order"] if prompt in {"branch order only", "edit order only"} else ["col_order", "col_qty"]
        client_ref = "selected_order" if len(keep) == 1 else "selected_both"
        variable = "SelectedOrder" if len(keep) == 1 else "SelectedBoth"
        return {
            "summary": "Select requested columns.", "questions": [], "assumptions": [], "warnings": [],
            "changeReason": prompt, "changes": [{
                "type": "insertStep", "afterStepId": final_step,
                "stepDraft": {
                    "clientRef": client_ref, "variableName": variable,
                    "actionDescription": "Select columns.", "operationType": "table.selectColumns",
                    "parameters": {"columnIds": keep}, "inputs": [final_step],
                },
            }, {"type": "setFinalOutput", "stepId": client_ref}],
        }


def _catalog(document: dict) -> list[dict]:
    return deepcopy(document["revisions"][0]["sources"])


def _assert_no_forbidden_branch_fields(test: unittest.TestCase, value: object) -> None:
    if isinstance(value, dict):
        test.assertNotIn("branchTip", value)
        test.assertNotIn("latestRevisionId", value)
        for child in value.values():
            _assert_no_forbidden_branch_fields(test, child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_branch_fields(test, child)


def _tips(document: dict) -> list[str]:
    parents = {item["parentRevisionId"] for item in document["revisions"] if item["parentRevisionId"] is not None}
    return sorted(item["revisionId"] for item in document["revisions"] if item["revisionId"] not in parents)


def _children(document: dict, parent_id: str) -> list[dict]:
    return sorted(
        [item for item in document["revisions"] if item["parentRevisionId"] == parent_id],
        key=lambda item: (item["createdAt"], item["revisionId"]),
    )


class ProblemChainPhase2AdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = BranchPlanner()
        self.store = ProblemChainStore(self.planner)
        self.addCleanup(self.store.close)

    def _commit(self, candidate: dict) -> dict:
        return self.store.commit(candidate["mutationId"], candidate["historyHash"])

    def _root(self) -> dict:
        return self._commit(self.store.create_problem(
            None, None, "root", typed_plan=_plan(),
        ))

    def _continue(self, committed: dict, prompt: str) -> dict:
        document = committed["document"]
        candidate = self.store.create_problem(
            document, committed["historyHash"], prompt,
            base_revision_id=document["headRevisionId"],
            source_catalog=_catalog(document), creation_mode="continue",
        )
        return self._commit(candidate)

    def test_branch_candidate_preserves_existing_descendant_and_has_no_authority_before_commit(self) -> None:
        root = self._root()
        root_id = root["document"]["headRevisionId"]
        main = self._continue(root, "select both")
        main_id = main["document"]["headRevisionId"]
        main_before = deepcopy(main["document"])

        candidate = self.store.create_problem(
            main["document"], main["historyHash"], "branch order only",
            base_revision_id=root_id, source_catalog=_catalog(main["document"]),
            creation_mode="branch",
        )
        branch_id = candidate["revision"]["revisionId"]
        self.assertEqual(candidate["creationMode"], "branch")
        self.assertEqual(candidate["revision"]["parentRevisionId"], root_id)
        self.assertEqual(candidate["document"]["revisions"][:-1], main_before["revisions"])
        self.assertEqual(candidate["document"]["headRevisionId"], branch_id)
        self.assertEqual(self.store.active_revision(main_id)["revision"]["revisionId"], main_id)
        self.assertIsNone(self.store.active_revision(branch_id))
        _assert_no_forbidden_branch_fields(self, candidate["document"])

        committed = self._commit(candidate)
        self.assertEqual(len(committed["document"]["revisions"]), 3)
        self.assertEqual(_tips(committed["document"]), sorted([main_id, branch_id]))
        siblings = _children(committed["document"], root_id)
        self.assertEqual(siblings, sorted(siblings, key=lambda item: (item["createdAt"], item["revisionId"])))
        with self.assertRaises(InputError) as old_head:
            self.store.active_revision(main_id)
        self.assertEqual(old_head.exception.code, "PQPC_HEAD_MISMATCH")
        self.assertEqual(self.store.active_revision(branch_id)["revision"]["revisionId"], branch_id)

    def test_edit_old_problem_creates_sibling_preserves_descendant_and_only_reports_impact(self) -> None:
        root = self._root()
        root_id = root["document"]["headRevisionId"]
        second = self._continue(root, "select both")
        second_id = second["document"]["headRevisionId"]
        third = self._continue(second, "filter qty")
        third_id = third["document"]["headRevisionId"]
        old_revisions = deepcopy(third["document"]["revisions"])
        calls_before = len(self.planner.calls)

        candidate = self.store.create_problem(
            third["document"], third["historyHash"], "edit order only",
            base_revision_id=root_id, edit_revision_id=second_id,
            source_catalog=_catalog(third["document"]), creation_mode="editProblem",
        )
        replacement_id = candidate["revision"]["revisionId"]
        self.assertEqual(len(self.planner.calls), calls_before + 1)
        self.assertEqual(candidate["creationMode"], "editProblem")
        self.assertEqual(candidate["revision"]["parentRevisionId"], root_id)
        self.assertEqual(candidate["document"]["revisions"][:-1], old_revisions)
        self.assertEqual(candidate["document"]["headRevisionId"], replacement_id)
        report = candidate["impactReport"]
        self.assertIn(third_id, report["affectedRevisionIds"])
        self.assertTrue(report["affectedStepIds"])
        self.assertIn("col_qty", report["affectedColumnIds"])
        self.assertTrue(all(set(issue) == {"code", "revisionId", "stepIds", "columnIds", "reason"}
                            for issue in report["issues"]))
        serialized = canonical_json(candidate["document"])
        self.assertNotIn(b"branchTip", serialized)
        self.assertNotIn(b"latestRevisionId", serialized)

    def test_stale_cas_head_source_and_edit_base_fail_before_planner(self) -> None:
        root = self._root()
        root_id = root["document"]["headRevisionId"]
        second = self._continue(root, "select both")
        second_id = second["document"]["headRevisionId"]
        calls = len(self.planner.calls)

        cases = [
            ({"base_history_hash": "sha256:" + "0" * 64, "base_revision_id": root_id,
              "creation_mode": "branch", "source_catalog": _catalog(second["document"])}, "PQPC_HISTORY_CONFLICT"),
            ({"base_history_hash": second["historyHash"], "base_revision_id": root_id,
              "creation_mode": "continue", "source_catalog": _catalog(second["document"])}, "PQPC_HEAD_MISMATCH"),
            ({"base_history_hash": second["historyHash"], "base_revision_id": root_id,
              "creation_mode": "editProblem", "edit_revision_id": second_id,
              "source_catalog": [{**_catalog(second["document"])[0], "objectName": "MissingTable"}]},
             "PQPC_SOURCE_SCHEMA_CHANGED"),
            ({"base_history_hash": second["historyHash"], "base_revision_id": second_id,
              "creation_mode": "editProblem", "edit_revision_id": second_id,
              "source_catalog": _catalog(second["document"])}, "PQPC_EDIT_BASE_MISMATCH"),
        ]
        for kwargs, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(InputError) as captured:
                    self.store.create_problem(
                        second["document"], kwargs.pop("base_history_hash"), "branch order only", **kwargs,
                    )
                self.assertEqual(captured.exception.code, expected)
        self.assertEqual(len(self.planner.calls), calls)
        self.assertEqual(self.store.active_revision(second_id)["revision"]["revisionId"], second_id)

    def test_fifty_node_branch_tree_validates_quickly_and_limit_blocks_before_planner(self) -> None:
        committed = self._root()
        document = deepcopy(committed["document"])
        root = document["revisions"][0]
        for index in range(1, MAX_REVISIONS):
            sibling = deepcopy(root)
            sibling["revisionId"] = f"rev_{index:024x}"
            if sibling["revisionId"] == root["revisionId"]:
                sibling["revisionId"] = f"rev_{index + MAX_REVISIONS:024x}"
            sibling["parentRevisionId"] = root["revisionId"]
            sibling["createdAt"] = datetime(2026, 1, 1, 0, 0, index, tzinfo=timezone.utc).isoformat()
            document["revisions"].append(sibling)
        document["storageVersion"] = MAX_REVISIONS
        document["headRevisionId"] = document["revisions"][-1]["revisionId"]

        started = time.perf_counter()
        validated = validate_document(document)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(len(validated["revisions"]), MAX_REVISIONS)
        self.assertLess(elapsed_ms, 2000)
        self.store.load(validated)
        calls = len(self.planner.calls)
        with self.assertRaises(InputError) as captured:
            self.store.create_problem(
                validated, compute_history_hash(validated), "branch order only",
                base_revision_id=root["revisionId"], source_catalog=_catalog(validated),
                creation_mode="branch",
            )
        self.assertEqual(captured.exception.code, "PQPC_HISTORY_LIMIT")
        self.assertEqual(len(self.planner.calls), calls)

    def test_untrusted_mode_and_revision_identifiers_fail_closed_before_planner(self) -> None:
        committed = self._root()
        calls = len(self.planner.calls)
        invalid_cases = [
            {"creation_mode": ["branch"]},
            {"creation_mode": "branch", "base_revision_id": {"revisionId": "forged"}},
            {"creation_mode": "editProblem", "edit_revision_id": ["forged"]},
        ]
        for overrides in invalid_cases:
            arguments = {
                "base_revision_id": committed["document"]["headRevisionId"],
                "source_catalog": _catalog(committed["document"]),
                "creation_mode": "continue",
            }
            arguments.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(InputError) as captured:
                    self.store.create_problem(
                        committed["document"], committed["historyHash"], "invalid", **arguments,
                    )
                self.assertEqual(captured.exception.code, "PQPC_DOCUMENT_INVALID")
        self.assertEqual(len(self.planner.calls), calls)

    def test_edit_problem_rejects_manual_revision_target(self) -> None:
        root = self._root()
        root_id = root["document"]["headRevisionId"]
        manual = self.store.create_manual_revision(
            root["document"], root["historyHash"], root_id,
            [{
                "type": "updateStep", "stepId": "stp_source",
                "stepDraft": {"actionDescription": "Manual source description"},
            }],
            "Manual edit", source_catalog=_catalog(root["document"]),
        )
        committed = self._commit(manual)
        manual_id = committed["document"]["headRevisionId"]
        calls = len(self.planner.calls)
        with self.assertRaises(InputError) as captured:
            self.store.create_problem(
                committed["document"], committed["historyHash"], "not a problem event",
                base_revision_id=root_id, edit_revision_id=manual_id,
                source_catalog=_catalog(committed["document"]), creation_mode="editProblem",
            )
        self.assertEqual(captured.exception.code, "PQPC_EDIT_TARGET_INVALID")
        self.assertEqual(len(self.planner.calls), calls)

    def test_delete_internal_problem_removes_only_its_subtree_and_preserves_sibling(self) -> None:
        root = self._root()
        root_id = root["document"]["headRevisionId"]
        second = self._continue(root, "select both")
        second_id = second["document"]["headRevisionId"]
        third = self._continue(second, "filter qty")
        third_id = third["document"]["headRevisionId"]
        branch = self.store.create_problem(
            third["document"], third["historyHash"], "branch order only",
            base_revision_id=root_id, source_catalog=_catalog(third["document"]),
            creation_mode="branch",
        )
        committed = self._commit(branch)
        sibling_id = committed["document"]["headRevisionId"]
        sibling_before = deepcopy(next(
            item for item in committed["document"]["revisions"]
            if item["revisionId"] == sibling_id
        ))
        calls = len(self.planner.calls)

        candidate = self.store.delete_problem(
            committed["document"], committed["historyHash"], second_id,
        )
        self.assertEqual(set(candidate["deletedRevisionIds"]), {second_id, third_id})
        self.assertEqual(candidate["document"]["headRevisionId"], sibling_id)
        self.assertEqual(
            next(item for item in candidate["document"]["revisions"] if item["revisionId"] == sibling_id),
            sibling_before,
        )
        self.assertEqual(len(self.planner.calls), calls)
        deleted = self._commit(candidate)
        self.assertEqual(
            {item["revisionId"] for item in deleted["document"]["revisions"]},
            {root_id, sibling_id},
        )
        _assert_no_forbidden_branch_fields(self, deleted["document"])

    def test_delete_leaf_moves_head_to_parent_without_confirmation_policy_in_domain(self) -> None:
        root = self._root()
        root_id = root["document"]["headRevisionId"]
        second = self._continue(root, "select both")
        second_id = second["document"]["headRevisionId"]
        candidate = self.store.delete_problem(
            second["document"], second["historyHash"], second_id,
        )
        self.assertEqual(candidate["deletedRevisionIds"], [second_id])
        self.assertEqual(candidate["document"]["headRevisionId"], root_id)
        committed = self._commit(candidate)
        self.assertEqual(len(committed["document"]["revisions"]), 1)

    def test_delete_root_unknown_and_stale_fail_without_planner(self) -> None:
        committed = self._root()
        root_id = committed["document"]["headRevisionId"]
        calls = len(self.planner.calls)
        cases = [
            (committed["historyHash"], root_id, "PQPC_DELETE_ROOT_UNSUPPORTED"),
            (committed["historyHash"], "rev_" + "f" * 24, "PQPC_REVISION_NOT_FOUND"),
            ("sha256:" + "0" * 64, root_id, "PQPC_HISTORY_CONFLICT"),
        ]
        for history_hash, revision_id, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(InputError) as captured:
                    self.store.delete_problem(committed["document"], history_hash, revision_id)
                self.assertEqual(captured.exception.code, expected)
        self.assertEqual(len(self.planner.calls), calls)


if __name__ == "__main__":
    unittest.main()
