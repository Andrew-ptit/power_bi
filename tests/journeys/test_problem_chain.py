from __future__ import annotations
from copy import deepcopy
from io import BytesIO
import base64
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import zipfile
from xml.etree import ElementTree as ET
from pbip_assistant.errors import InputError
from pbip_assistant.excel_addin_server import ExcelAddinApp, create_server
from pbip_assistant.excel_connector import PowerShellExcelRunner
from pbip_assistant.pq_typed import DESTINATION_MARKER
from pbip_assistant.problem_chain import (
    MAX_CANONICAL_JSON_BYTES,
    ProblemChainStore,
    canonical_json,
    compute_history_hash,
    compute_review_hash,
    source_schema_fingerprint,
    validate_document,
)
from pbip_assistant.workbook_fingerprint import MAIN, workbook_data_fingerprint
from tests.support.excel_plan import FIXTURE_ROOT
from tests.support.excel_plan import office_snapshot
from tests.support.pq_code_m import FakePQRunner
from tests.support.pq_typed import FakeTypedPlanner
from tests.support.problem_chain import typed_plan
from tests.support.workbook_fingerprint import repack

from tests.support.problem_chain_journey import (_independent_hash, _review_basis, _mutate_first_cell, CountingPlanner, BlockingContinuationPlanner, _two_step_plan, PipelineResetPlanner, ClientRefCollisionPlanner, UnknownChangeFieldPlanner, DynamicContinuationPlanner, LeftMergeContinuationPlanner, CountingTypedPlanner, ProblemChainHttpHarness)

class ProblemChainHttpIndependentCrosscheck(ProblemChainHttpHarness):
    def test_root_load_commit_and_strict_continuation_contract(self) -> None:
        status, empty = self.request("POST", "/api/pq/v2/problem-chains/load", {
            "document": None, "workbook": self.workbook,
        })
        self.assertEqual((status, empty), (200, {"document": None, "historyHash": None, "dataVersion": 0}))
        root = self.create_root()
        self.assertEqual(len(self.typed_planner.calls), 1)
        self.assertEqual(len(self.continuation_planner.calls), 0)
        root_revision = deepcopy(root["revision"])
        committed = self.commit(root)
        continued = self.continue_from(committed)
        self.assertEqual(len(self.typed_planner.calls), 1, "continuation must not regenerate a full plan")
        self.assertEqual(len(self.continuation_planner.calls), 1)
        self.assertEqual(continued["document"]["revisions"][0], root_revision)
        self.assertEqual(continued["revision"]["parentRevisionId"], root_revision["revisionId"])
        self.assertGreater(len(continued["revision"]["steps"]), len(root_revision["steps"]))

        stale = deepcopy(committed["document"])
        stale["storageVersion"] += 1
        planner_calls = len(self.continuation_planner.calls)
        status, error = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": stale, "baseHistoryHash": committed["historyHash"],
            "baseRevisionId": stale["headRevisionId"], "prompt": "stale",
            "workbook": self.workbook, "source": self.source,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HISTORY_CONFLICT")
        self.assertEqual(len(self.continuation_planner.calls), planner_calls)
    def test_phase2_http_branch_and_edit_are_explicit_and_preserve_old_tree(self) -> None:
        root = self.commit(self.create_root())
        root_id = root["document"]["headRevisionId"]
        second = self.commit(self.continue_from(root, "Continue main branch"))
        second_id = second["document"]["headRevisionId"]
        last_step = second["document"]["revisions"][-1]["steps"][-1]
        status, third_candidate = self.manual_edit(second, [{
            "type": "updateStep", "stepId": last_step["stepId"],
            "stepDraft": {"actionDescription": "Descendant manual refinement"},
        }], "Create an old descendant for impact analysis")
        self.assertEqual(status, 200, third_candidate)
        third = self.commit(third_candidate)
        third_id = third["document"]["headRevisionId"]
        old_revisions = deepcopy(third["document"]["revisions"])

        status, branch = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": third["document"], "baseHistoryHash": third["historyHash"],
            "baseRevisionId": root_id, "creationMode": "branch",
            "editRevisionId": None, "prompt": "Alternative from root",
            "workbook": self.workbook, "source": self.source,
        })
        self.assertEqual(status, 200, branch)
        self.assertEqual(branch["creationMode"], "branch")
        self.assertEqual(branch["revision"]["parentRevisionId"], root_id)
        self.assertEqual(branch["document"]["revisions"][:-1], old_revisions)

        status, edited = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": third["document"], "baseHistoryHash": third["historyHash"],
            "baseRevisionId": root_id, "creationMode": "editProblem",
            "editRevisionId": second_id, "prompt": "Replace old problem",
            "workbook": self.workbook, "source": self.source,
        })
        self.assertEqual(status, 200, edited)
        self.assertEqual(edited["creationMode"], "editProblem")
        self.assertEqual(edited["revision"]["parentRevisionId"], root_id)
        self.assertEqual(edited["document"]["revisions"][:-1], old_revisions)
        self.assertIn(third_id, edited["impactReport"]["affectedRevisionIds"])
        self.assertTrue(edited["impactReport"]["issues"])

        status, deleted = self.request("POST", "/api/pq/v2/problem-chains/problems/delete", {
            "document": third["document"], "baseHistoryHash": third["historyHash"],
            "revisionId": second_id,
        })
        self.assertEqual(status, 200, deleted)
        self.assertEqual(set(deleted["deletedRevisionIds"]), {second_id, third_id})
        self.assertEqual(deleted["document"]["headRevisionId"], root_id)
        self.assertEqual([item["revisionId"] for item in deleted["document"]["revisions"]], [root_id])

        status, root_error = self.request("POST", "/api/pq/v2/problem-chains/problems/delete", {
            "document": third["document"], "baseHistoryHash": third["historyHash"],
            "revisionId": root_id,
        })
        self.assertEqual(status, 409, root_error)
        self.assertEqual(root_error["error"]["code"], "PQPC_DELETE_ROOT_UNSUPPORTED")
    def test_uncommitted_root_seed_cannot_preview_but_committed_head_can(self) -> None:
        candidate = self.create_root()
        seed_ids = list(self.server.app.pq_typed._revisions)
        self.assertEqual(len(seed_ids), 1)
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": seed_ids[0], "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQV2_PREVIEW_STALE")
        self.assertEqual(len(self.pq_runner.requests), 0)

        committed = self.commit(candidate)
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": committed["document"]["headRevisionId"],
            "workbook": self.workbook, "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(self.pq_runner.requests), 1)
    def test_question_does_not_create_head_or_preview_authority(self) -> None:
        class QuestionPlanner(DynamicContinuationPlanner):
            def propose(self, payload: dict) -> dict:
                proposal = super().propose(payload)
                proposal["questions"] = ["Which business rule should handle empty Qty?"]
                return proposal

        committed_root = self.commit(self.create_root())
        self.server.app.problem_chains.planner = QuestionPlanner()
        clarification = self.continue_from(committed_root, "Handle Qty")
        self.assertEqual(clarification["status"], "needsClarification")
        self.assertEqual(len(clarification["questions"]), 1)
        self.assertNotIn("mutationId", clarification)
        self.assertEqual(self.server.app.problem_chains.active_revision(committed_root["document"]["headRevisionId"])["revision"]["revisionId"], committed_root["document"]["headRevisionId"])
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": committed_root["document"]["headRevisionId"], "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(self.pq_runner.requests), 1, "Only the unchanged previous HEAD remains previewable")
    def test_root_question_answer_then_commit_and_preview(self) -> None:
        class QuestionThenAnswerTypedPlanner(CountingTypedPlanner):
            def propose(self, payload: dict) -> dict:
                self.calls.append(deepcopy(payload))
                if "Làm rõ yêu cầu:" not in payload["userRequest"]:
                    return {
                        "summary": "Need a rule for OrderMonth",
                        "questions": ["OrderMonth chưa tồn tại. Tạo từ cột nào và theo định dạng nào?"],
                        "assumptions": [], "warnings": [], "steps": [], "finalOutputRef": None,
                    }
                return FakeTypedPlanner.propose(self, payload)

        planner = QuestionThenAnswerTypedPlanner()
        self.server.app.pq_typed.runner = planner
        original_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        request = {
            "document": None, "baseHistoryHash": None, "baseRevisionId": None,
            "prompt": "Create OrderMonth", "workbook": self.workbook, "source": self.source,
        }
        status, question = self.request("POST", "/api/pq/v2/problem-chains/problems", request)
        question_ms = self.timings_ms[-1]
        self.assertEqual(status, 200, question)
        self.assertEqual(question["status"], "needsClarification")
        self.assertEqual(len(question["questions"]), 1)
        self.assertNotIn("mutationId", question)
        self.assertFalse(self.server.app.pq_typed._revisions)
        self.assertFalse(self.server.app.problem_chains.has_active_chain())
        status, answered = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            **request, "prompt": "Create OrderMonth\n\nLàm rõ yêu cầu:\n1. Hỏi: OrderMonth chưa tồn tại. Tạo từ cột nào và theo định dạng nào?\n   Trả lời: Tạo từ SaleDate theo YYYYMM",
        })
        answer_ms = self.timings_ms[-1]
        self.assertEqual(status, 200, answered)
        self.assertIn("mutationId", answered)
        committed = self.commit(answered)
        self.assertEqual(len(committed["document"]["revisions"]), 1)
        self.assertIn("Trả lời:", committed["document"]["revisions"][0]["problemPrompt"])
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": committed["document"]["headRevisionId"],
            "workbook": self.workbook,
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
        })
        preview_ms = self.timings_ms[-1]
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(self.pq_runner.requests), 1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), original_hash)
        print(f"HTTP root clarification: question={question_ms:.1f}ms answer={answer_ms:.1f}ms preview={preview_ms:.1f}ms revisions=0->1 source_sha256=unchanged")
    def test_branch_question_answer_does_not_mutate_older_revisions(self) -> None:
        class QuestionThenAnswerPlanner(DynamicContinuationPlanner):
            def propose(self, payload: dict) -> dict:
                if "Làm rõ yêu cầu:" not in payload["userRequest"]:
                    self.calls.append(deepcopy(payload))
                    return {
                        "summary": "Need a column rule", "questions": ["Which existing column should be used?"],
                        "assumptions": [], "warnings": [], "changeReason": "Await answer", "changes": [],
                    }
                return super().propose(payload)

        root = self.commit(self.create_root())
        old = self.commit(self.continue_from(root, "Original 1.1"))
        root_id = root["document"]["headRevisionId"]
        prior_revisions = deepcopy(old["document"]["revisions"])
        planner = QuestionThenAnswerPlanner()
        self.server.app.problem_chains.planner = planner
        request = {
            "document": old["document"], "baseHistoryHash": old["historyHash"],
            "baseRevisionId": root_id, "creationMode": "branch",
            "prompt": "Use missing column", "workbook": self.workbook, "source": self.source,
        }
        status, question = self.request("POST", "/api/pq/v2/problem-chains/problems", request)
        question_ms = self.timings_ms[-1]
        self.assertEqual(status, 200, question)
        self.assertEqual(question["status"], "needsClarification")
        self.assertNotIn("mutationId", question)
        self.assertEqual(self.server.app.problem_chains.active_revision(old["document"]["headRevisionId"])["revision"]["revisionId"], old["document"]["headRevisionId"])
        self.assertFalse(self.server.app.pq_typed._problem_result_cache)
        status, candidate = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            **request,
            "prompt": "Use missing column\n\nLàm rõ yêu cầu:\n1. Hỏi: Which existing column should be used?\n   Trả lời: Use SaleID",
        })
        answer_ms = self.timings_ms[-1]
        self.assertEqual(status, 200, candidate)
        self.assertEqual(candidate["document"]["revisions"][:-1], prior_revisions)
        committed = self.commit(candidate)
        self.assertEqual(committed["document"]["revisions"][:-1], prior_revisions)
        self.assertEqual(committed["document"]["revisions"][-1]["parentRevisionId"], root_id)
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": committed["document"]["headRevisionId"],
            "workbook": self.workbook,
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
        })
        preview_ms = self.timings_ms[-1]
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(self.pq_runner.requests), 1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), hashlib.sha256(self.workbook_bytes).hexdigest())
        print(f"HTTP branch clarification: question={question_ms:.1f}ms answer={answer_ms:.1f}ms preview={preview_ms:.1f}ms revisions=2->3 source_sha256=unchanged")
    def test_missing_column_is_clarification_not_a_partial_revision(self) -> None:
        class MissingRootColumnPlanner(CountingTypedPlanner):
            def propose(self, payload: dict) -> dict:
                draft = super().propose(payload)
                last = draft["finalOutputRef"]
                draft["steps"].append({
                    "clientRef": "missing_month", "variableName": "MissingMonth",
                    "actionDescription": "Select a not-yet-defined month.",
                    "operationType": "table.selectColumns", "inputs": [last],
                    "parameters": {"columns": ["OrderMonth"]},
                })
                draft["finalOutputRef"] = "missing_month"
                return draft

        self.server.app.pq_typed.runner = MissingRootColumnPlanner()
        status, question = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": None, "baseHistoryHash": None, "baseRevisionId": None,
            "prompt": "Use OrderMonth", "workbook": self.workbook, "source": self.source,
        })
        self.assertEqual(status, 200, question)
        self.assertEqual(question["status"], "needsClarification")
        self.assertIn("cột", question["questions"][0])
        self.assertNotIn("mutationId", question)
        self.assertFalse(self.server.app.problem_chains.has_active_chain())

        self.server.app.pq_typed.runner = self.typed_planner
        root = self.commit(self.create_root())
        class MissingContinuationColumnPlanner(DynamicContinuationPlanner):
            def propose(self, payload: dict) -> dict:
                proposal = super().propose(payload)
                proposal["changes"][0]["stepDraft"]["parameters"] = {"columnIds": ["col_missing"]}
                return proposal

        self.server.app.problem_chains.planner = MissingContinuationColumnPlanner()
        status, question = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": root["document"], "baseHistoryHash": root["historyHash"],
            "baseRevisionId": root["document"]["headRevisionId"],
            "prompt": "Select OrderMonth", "workbook": self.workbook, "source": self.source,
        })
        self.assertEqual(status, 200, question)
        self.assertEqual(question["status"], "needsClarification")
        self.assertNotIn("mutationId", question)
        self.assertEqual(self.server.app.problem_chains.active_revision(root["document"]["headRevisionId"])["revision"]["revisionId"], root["document"]["headRevisionId"])
        self.assertEqual(len(self.pq_runner.requests), 0)
    def test_legacy_head_that_copied_parent_pipeline_is_not_preview_ready(self) -> None:
        committed = self.commit(self.create_root())
        original = committed["document"]
        copied = deepcopy(original["revisions"][0])
        copied["revisionId"] = "rev_" + "e" * 24
        copied["parentRevisionId"] = original["headRevisionId"]
        copied["problemPrompt"] = "Merge Products, but the planner made no pipeline change"
        copied["changeSet"] = [{"type": "setFinalOutput", "stepId": copied["finalOutputStepId"]}]
        copied["reviewHash"] = compute_review_hash(copied)
        legacy = deepcopy(original)
        legacy["storageVersion"] += 1
        legacy["revisions"].append(copied)
        legacy["headRevisionId"] = copied["revisionId"]
        validate_document(legacy)
        self.server.app.problem_chains.load(legacy)
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": copied["revisionId"], "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_NO_PIPELINE_CHANGE")
        self.assertEqual(len(self.pq_runner.requests), 0)
    def test_typed_revision_endpoint_cannot_fork_committed_problem_head(self) -> None:
        committed = self.commit(self.create_root())
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        head = committed["document"]["revisions"][0]
        head_id = head["revisionId"]
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": head_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        first_step = head["steps"][0]
        status, response = self.request("POST", "/api/pq/v2/revisions", {
            "baseRevisionId": head_id,
            "changes": [{
                "type": "updateStep", "stepId": first_step["stepId"],
                "stepDraft": {"actionDescription": "Unpersisted edit"},
            }],
        })
        self.assertEqual(status, 409, response)
        self.assertEqual(response["error"]["code"], "PQPC_HEAD_MISMATCH")
    def test_manual_edit_is_immutable_and_has_no_runtime_authority_until_commit(self) -> None:
        committed = self.commit(self.create_root())
        original = deepcopy(committed["document"]["revisions"][0])
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        original_id = original["revisionId"]
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": original_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        status, approval = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": original_id, "previewId": preview["previewId"],
            "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual(status, 200, approval)

        target = original["steps"][-1]
        status, candidate = self.manual_edit(committed, [{
            "type": "updateStep", "stepId": target["stepId"],
            "stepDraft": {"actionDescription": "Edited only in the candidate revision"},
        }])
        self.assertEqual(status, 200, candidate)
        self.assertEqual(candidate["revision"]["originKind"], "manualEdit")
        self.assertEqual(candidate["revision"]["parentRevisionId"], original_id)
        self.assertNotEqual(candidate["revision"]["revisionId"], original_id)
        self.assertEqual(candidate["document"]["revisions"][0], original)
        self.assertEqual(committed["document"]["revisions"], [original])
        self.assertEqual(candidate["revision"]["steps"][-1]["actionDescription"], "Edited only in the candidate revision")

        # Merely obtaining the candidate must not make it previewable or
        # approvable. Runtime authority changes only after XML read-back commit.
        candidate_id = candidate["revision"]["revisionId"]
        excel_calls = len(self.pq_runner.requests)
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": candidate_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")
        self.assertEqual(len(self.pq_runner.requests), excel_calls)
        status, error = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": candidate_id, "previewId": preview["previewId"],
            "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")

        updated = self.commit(candidate)
        self.assertEqual(updated["document"]["revisions"][0], original)
        self.assertEqual(updated["document"]["headRevisionId"], candidate_id)
        status, error = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": approval["approvalId"], "workbookBase64": encoded,
            "destination": {"marker": DESTINATION_MARKER},
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQV2_APPROVAL_REQUIRED")
        status, new_preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": candidate_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, new_preview)
    def test_manual_edit_stale_cas_and_legacy_revision_route_fail_closed(self) -> None:
        committed = self.commit(self.create_root())
        head = committed["document"]["revisions"][0]
        step = head["steps"][-1]
        changes = [{
            "type": "updateStep", "stepId": step["stepId"],
            "stepDraft": {"actionDescription": "must not publish"},
        }]
        status, error = self.manual_edit(
            committed, changes, base_history_hash="sha256:" + "0" * 64,
        )
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HISTORY_CONFLICT")
        self.assertIsNotNone(self.server.app.problem_chains.active_revision(head["revisionId"]))

        status, error = self.request("POST", "/api/pq/v2/revisions", {
            "baseRevisionId": head["revisionId"], "changes": changes,
            "changeReason": "legacy bypass",
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")
        self.assertIsNotNone(self.server.app.problem_chains.active_revision(head["revisionId"]))
    def test_delete_producer_persists_blocked_manual_revision_but_never_previews(self) -> None:
        committed = self.commit(self.create_root())
        old_head = deepcopy(committed["document"]["revisions"][0])
        producer = old_head["steps"][2]
        status, candidate = self.manual_edit(committed, [{
            "type": "deleteStep", "stepId": producer["stepId"],
        }], "Delete Profit producer")
        self.assertEqual(status, 200, candidate)
        self.assertEqual(candidate["revision"]["originKind"], "manualEdit")
        self.assertEqual(candidate["revision"]["validationAtCreation"]["overall"], "blocked")
        issue_codes = {item["code"] for item in candidate["revision"]["validationAtCreation"]["issues"]}
        self.assertIn("PQV2_DEPENDENCY_INVALID", issue_codes)
        self.assertEqual(candidate["document"]["revisions"][0], old_head)

        committed_blocked = self.commit(candidate)
        blocked_id = committed_blocked["document"]["headRevisionId"]
        excel_calls = len(self.pq_runner.requests)
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": blocked_id, "workbook": self.workbook,
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
        })
        self.assertEqual(status, 400, error)
        self.assertIn(error["error"]["code"], {"PQV2_DEPENDENCY_INVALID", "PQV2_PREVIEW_REQUIRED"})
        self.assertEqual(len(self.pq_runner.requests), excel_calls)
        status, error = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": blocked_id, "previewId": "prv_" + "0" * 24,
            "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual(status, 400, error)
        self.assertIn(error["error"]["code"], {
            "PQV2_REVISION_NOT_FOUND", "PQV2_PREVIEW_REQUIRED", "PQV2_DEPENDENCY_INVALID",
        })
        status, error = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": "apr_" + "0" * 24,
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
            "destination": {"marker": DESTINATION_MARKER},
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQV2_APPROVAL_REQUIRED")
        self.assertEqual(len(self.pq_runner.requests), excel_calls)
    def test_topologically_invalid_reorder_is_blocked_and_does_not_mutate_parent(self) -> None:
        committed = self.commit(self.create_root())
        parent = deepcopy(committed["document"]["revisions"][0])
        final_step = parent["steps"][-1]
        self.assertTrue(final_step["inputs"], "fixture final step must have a dependency")
        status, candidate = self.manual_edit(committed, [{
            "type": "moveStep", "stepId": final_step["stepId"], "position": 1,
        }], "Move dependent step before producer")
        self.assertEqual(status, 200, candidate)
        self.assertEqual(candidate["revision"]["validationAtCreation"]["overall"], "blocked")
        issues = candidate["revision"]["validationAtCreation"]["issues"]
        self.assertIn("PQV2_DEPENDENCY_INVALID", {item["code"] for item in issues})
        self.assertEqual(candidate["document"]["revisions"][0], parent)
        self.assertEqual(committed["document"]["revisions"][0], parent)
        blocked = self.commit(candidate)
        excel_calls = len(self.pq_runner.requests)
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": blocked["document"]["headRevisionId"],
            "workbook": self.workbook,
            "workbookBase64": base64.b64encode(self.workbook_bytes).decode("ascii"),
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQV2_DEPENDENCY_INVALID")
        self.assertEqual(len(self.pq_runner.requests), excel_calls)
    def test_active_chain_blocks_standalone_plan_and_old_typed_preview(self) -> None:
        status, standalone = self.request("POST", "/api/pq/v2/plans", {
            "prompt": "Standalone draft", "workbook": self.workbook,
            "source": self.source,
        })
        self.assertEqual(status, 200, standalone)
        old_revision_id = standalone["revision"]["revisionId"]
        self.commit(self.create_root())
        planner_calls = len(self.typed_planner.calls)

        status, error = self.request("POST", "/api/pq/v2/plans", {
            "prompt": "Bypass active chain", "workbook": self.workbook,
            "source": self.source,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")
        self.assertEqual(len(self.typed_planner.calls), planner_calls)

        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        excel_calls = len(self.pq_runner.requests)
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": old_revision_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")
        self.assertEqual(len(self.pq_runner.requests), excel_calls)
    def test_inflight_standalone_plan_cannot_publish_after_chain_commit(self) -> None:
        candidate = self.create_root()
        started = threading.Event()
        release = threading.Event()
        normal_propose = self.typed_planner.propose

        def blocked_propose(payload: dict) -> dict:
            started.set()
            if not release.wait(timeout=3):
                raise AssertionError("Typed planner was not released")
            return normal_propose(payload)

        self.typed_planner.propose = blocked_propose
        result: list[tuple[int, dict]] = []
        worker = threading.Thread(target=lambda: result.append(self.request(
            "POST", "/api/pq/v2/plans", {
                "prompt": "Racing standalone draft", "workbook": self.workbook,
                "source": self.source,
            },
        )))
        worker.start()
        try:
            self.assertTrue(started.wait(timeout=2))
            self.commit(candidate)
        finally:
            release.set()
            worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 409, result[0][1])
        self.assertEqual(result[0][1]["error"]["code"], "PQPC_HEAD_MISMATCH")
    def test_catalog_drift_blocks_preplanner_and_only_referenced_new_source_persists(self) -> None:
        committed = self.commit(self.create_root())
        drifted = deepcopy(self.workbook)
        drifted["tables"][0]["headers"][0] = "SaleID_Drifted"
        calls_before = len(self.continuation_planner.calls)
        status, error = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": committed["document"], "baseHistoryHash": committed["historyHash"],
            "baseRevisionId": committed["document"]["headRevisionId"], "prompt": "Continue after drift",
            "workbook": drifted, "source": self.source,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_SOURCE_SCHEMA_CHANGED")
        self.assertEqual(len(self.continuation_planner.calls), calls_before)

        expanded = deepcopy(self.workbook)
        archive = deepcopy(expanded["tables"][0])
        archive.update({"sheet": "Archive", "name": "ArchiveTable"})
        expanded["tables"].append(archive)
        appended = self.continue_from(committed, "Append one additional table", expanded)
        catalog = self.continuation_planner.calls[-1]["sourceCatalog"]
        self.assertEqual(len(catalog), 3, "Sales, Commission and newly added Archive must reach the planner")
        referenced_ids = {source["sourceId"] for source in appended["revision"]["sources"]}
        source_steps = [
            step for step in appended["revision"]["steps"]
            if step["operation"]["type"].startswith("source.")
        ]
        self.assertEqual(referenced_ids, {
            step["operation"]["parameters"]["sourceId"] for step in source_steps
        })
        self.assertEqual(len(referenced_ids), 2, "one unreferenced catalog source must not be persisted")
        append_step = appended["revision"]["steps"][-1]
        self.assertEqual(append_step["operation"]["type"], "table.appendTables")
        self.assertEqual(len(append_step["inputs"]), 2)

        calls_after_append = len(self.continuation_planner.calls)
        tampered = deepcopy(committed["document"])
        tampered["revisions"][0]["summary"] = "tampered without a new review hash"
        status, error = self.request("POST", "/api/pq/v2/problem-chains/problems", {
            "document": tampered, "baseHistoryHash": compute_history_hash(tampered),
            "baseRevisionId": tampered["headRevisionId"], "prompt": "tampered",
            "workbook": self.workbook, "source": self.source,
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQPC_HASH_MISMATCH")
        self.assertEqual(len(self.continuation_planner.calls), calls_after_append)
    def test_committed_head_preview_checkout_invalidates_old_approval(self) -> None:
        root = self.create_root()
        root_committed = self.commit(root)
        continued = self.continue_from(root_committed)
        current = self.commit(continued)
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        head_id = current["document"]["headRevisionId"]
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": head_id, "workbook": self.workbook, "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        status, approval = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": head_id, "previewId": preview["previewId"],
            "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual(status, 200, approval)

        root_id = current["document"]["revisions"][0]["revisionId"]
        status, checkout = self.request("POST", "/api/pq/v2/problem-chains/checkout", {
            "document": current["document"], "baseHistoryHash": current["historyHash"],
            "revisionId": root_id,
        })
        self.assertEqual(status, 200, checkout)
        self.commit(checkout)
        status, error = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": approval["approvalId"], "workbookBase64": encoded,
            "destination": {"marker": DESTINATION_MARKER},
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQV2_APPROVAL_REQUIRED")
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": head_id, "workbook": self.workbook, "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")
    def test_cached_result_restore_is_head_bound_and_rechecks_source(self) -> None:
        root = self.commit(self.create_root())
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        root_id = root["document"]["headRevisionId"]
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": root_id, "workbook": self.workbook, "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview["runVersion"], 0)
        self.assertFalse(self.server.app.pq_typed._problem_result_cache,
                         "Preview must stay in staging until confirmation")
        status, approval = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": root_id, "previewId": preview["previewId"],
            "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual(status, 200, approval)
        status, staged = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": approval["approvalId"], "workbookBase64": encoded,
            "destination": {"marker": DESTINATION_MARKER},
        })
        self.assertEqual(status, 200, staged)
        status, confirmed = self.request("POST", "/api/pq/v2/applies/complete", {
            "applyId": staged["applyId"], "readback": {
                "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
                "rowCount": staged["expectedRows"], "columnCount": staged["expectedColumns"],
            },
        })
        self.assertEqual(status, 200, confirmed)
        self.assertTrue(confirmed["resultCached"])
        status, reloaded = self.request("POST", "/api/pq/v2/problem-chains/load", {
            "document": root["document"], "workbook": self.workbook,
        })
        self.assertEqual(status, 200, reloaded)
        root = reloaded
        current = self.commit(self.continue_from(root))
        status, blocked = self.request("POST", "/api/pq/v2/problem-chains/cached-results/prepare", {
            "revisionId": root_id, "baseHistoryHash": current["historyHash"],
            "sourceDataChanged": False, "workbook": self.workbook,
            "workbookBase64": encoded, "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual((status, blocked["error"]["code"]), (409, "PQPC_HEAD_MISMATCH"))
        status, checkout = self.request("POST", "/api/pq/v2/problem-chains/checkout", {
            "document": current["document"], "baseHistoryHash": current["historyHash"],
            "revisionId": root_id,
        })
        self.assertEqual(status, 200, checkout)
        restored_head = self.commit(checkout)
        requests_before_restore = len(self.pq_runner.requests)
        request = {
            "revisionId": root_id, "baseHistoryHash": restored_head["historyHash"],
            "sourceDataChanged": False, "workbook": self.workbook,
            "workbookBase64": encoded, "destinationMarker": DESTINATION_MARKER,
        }
        status, prepared = self.request("POST", "/api/pq/v2/problem-chains/cached-results/prepare", request)
        self.assertEqual(status, 200, prepared)
        self.assertTrue(base64.b64decode(prepared["resultWorkbookBase64"]).startswith(b"PK"))
        self.assertEqual(len(self.pq_runner.requests), requests_before_restore,
                         "restoring cache must not execute M again")
        status, completed = self.request("POST", "/api/pq/v2/applies/complete", {
            "applyId": prepared["applyId"], "readback": {
                "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
                "rowCount": prepared["expectedRows"], "columnCount": prepared["expectedColumns"],
            },
        })
        self.assertEqual((status, completed["status"]), (200, "applied"))
        changed = base64.b64encode(repack(self.workbook_bytes, change_cell=True)).decode("ascii")
        status, stale = self.request("POST", "/api/pq/v2/problem-chains/cached-results/prepare", {
            **request, "workbookBase64": changed,
        })
        self.assertEqual((status, stale["error"]["code"]), (400, "PQPC_RESULT_CACHE_STALE"))
        status, rejected = self.request("POST", "/api/pq/v2/problem-chains/cached-results/prepare", {
            **request, "sourceDataChanged": True,
        })
        self.assertEqual((status, rejected["error"]["code"]), (400, "PQPC_RESULT_CACHE_STALE"))
        status, advanced = self.request("POST", "/api/pq/v2/problem-chains/data-version/increment", {
            "revisionId": root_id, "baseHistoryHash": restored_head["historyHash"],
            "workbook": self.workbook,
        })
        self.assertEqual(status, 200)
        self.assertEqual(advanced["dataVersion"], 1)
        self.assertIn((restored_head["document"]["chainId"], root_id), self.server.app.pq_typed._problem_result_cache)
        status, old = self.request("POST", "/api/pq/v2/problem-chains/cached-results/prepare", request)
        self.assertEqual((status, old["error"]["code"]), (400, "PQPC_RESULT_CACHE_STALE"))
    def test_load_replacement_and_null_revoke_old_runtime_authority(self) -> None:
        root = self.commit(self.create_root())
        current = self.commit(self.continue_from(root))
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        current_id = current["document"]["headRevisionId"]
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": current_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        status, approval = self.request("POST", "/api/pq/v2/approvals", {
            "revisionId": current_id, "previewId": preview["previewId"],
            "destinationMarker": DESTINATION_MARKER,
        })
        self.assertEqual(status, 200, approval)

        status, _ = self.request("POST", "/api/pq/v2/problem-chains/load", {
            "document": root["document"], "workbook": self.workbook,
        })
        self.assertEqual(status, 200)
        status, error = self.request("POST", "/api/pq/v2/applies/prepare", {
            "approvalId": approval["approvalId"], "workbookBase64": encoded,
            "destination": {"marker": DESTINATION_MARKER},
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQV2_APPROVAL_REQUIRED")
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": current_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_HEAD_MISMATCH")

        root_id = root["document"]["headRevisionId"]
        status, _ = self.request("POST", "/api/pq/v2/problem-chains/load", {
            "document": None, "workbook": self.workbook,
        })
        self.assertEqual(status, 200)
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": root_id, "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["code"], "PQV2_REVISION_NOT_FOUND")
    def test_source_schema_change_blocks_preview_but_history_stays_loadable(self) -> None:
        committed = self.commit(self.create_root())
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        moved = deepcopy(self.workbook)
        moved["tables"][0]["sheet"] = "SalesMoved"
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": committed["document"]["headRevisionId"],
            "workbook": moved, "workbookBase64": encoded,
        })
        self.assertEqual(
            status, 200,
            f"Table identity is workbook-unique and must survive a sheet move: {preview}",
        )

        changed = deepcopy(self.workbook)
        changed["tables"][0]["headers"][0] = "SaleID_Renamed"
        status, loaded = self.request("POST", "/api/pq/v2/problem-chains/load", {
            "document": committed["document"], "workbook": changed,
        })
        self.assertEqual(status, 200, loaded)
        status, error = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": committed["document"]["headRevisionId"],
            "workbook": changed, "workbookBase64": encoded,
        })
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "PQPC_SOURCE_SCHEMA_CHANGED")
    def test_left_merge_branch_http_journey_staging_confirm_reopen_and_recovery(self) -> None:
        self._exercise_left_merge_branch_journey()
    def test_branch_churn_stress_preserves_history_and_rejects_stale_head(self) -> None:
        """Repeated siblings, CAS races and preview after HEAD changes."""
        root = self.commit(self.create_root())
        root_id = root["document"]["headRevisionId"]
        current = root
        sibling_ids: list[str] = []
        stage_ms: list[float] = []
        for index in range(16):
            started = time.perf_counter()
            status, candidate = self.request("POST", "/api/pq/v2/problem-chains/problems", {
                "document": current["document"], "baseHistoryHash": current["historyHash"],
                "baseRevisionId": root_id, "creationMode": "branch",
                "prompt": f"Sibling stress {index}", "workbook": self.workbook, "source": self.source,
            })
            self.assertEqual(status, 200, candidate)
            self.assertEqual(candidate["revision"]["parentRevisionId"], root_id)
            prior = current
            current = self.commit(candidate)
            sibling_ids.append(current["document"]["headRevisionId"])
            self.assertEqual(current["document"]["revisions"][:-1], prior["document"]["revisions"])
            stage_ms.append((time.perf_counter() - started) * 1000)
            status, stale = self.request("POST", "/api/pq/v2/problem-chains/problems", {
                "document": prior["document"], "baseHistoryHash": prior["historyHash"],
                "baseRevisionId": root_id, "creationMode": "branch",
                "prompt": "Stale sibling", "workbook": self.workbook, "source": self.source,
            })
            self.assertEqual(status, 409, stale)
            self.assertEqual(stale["error"]["code"], "PQPC_HISTORY_CONFLICT")
        self.assertEqual(len(set(sibling_ids)), 16)
        self.assertEqual(len(current["document"]["revisions"]), 17)
        self.assertEqual(len(self.continuation_planner.calls), 16)
        encoded = base64.b64encode(self.workbook_bytes).decode("ascii")
        status, stale_preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": sibling_ids[0], "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual((status, stale_preview["error"]["code"]), (409, "PQPC_HEAD_MISMATCH"))
        status, preview = self.request("POST", "/api/pq/v2/previews", {
            "revisionId": sibling_ids[-1], "workbook": self.workbook,
            "workbookBase64": encoded,
        })
        self.assertEqual(status, 200, preview)
        self.assertEqual(len(self.pq_runner.requests), 1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), hashlib.sha256(self.workbook_bytes).hexdigest())
        print(f"HTTP branch stress: 16 siblings, max create+commit={max(stage_ms):.1f}ms, stale CAS=16/16")

