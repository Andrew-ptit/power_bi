"""Synthetic Problem Chain requests; opt-in live Codex probe via PQPC_LIVE_CODEX=1."""

from copy import deepcopy
import os
import time
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import CodexProblemChainPlanner, ProblemChainStore
from tests.support.problem_chain import FakeContinuationPlanner, typed_plan


class FailingPlanner:
    def propose(self, _payload: dict) -> dict:
        raise InputError("CODEX_TIMEOUT", "codex", "Synthetic planner deadline")


class KeepProductCodePlanner:
    def propose(self, _payload: dict) -> dict:
        return {
            "summary": "Giữ các cột để nối bảng.", "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Prepared Sales columns",
            "changes": [
                {"type": "insertStep", "afterStepId": "stp_source", "stepDraft": {
                    "clientRef": "prepared", "variableName": "PreparedSales",
                    "actionDescription": "Giữ OrderID, Qty và ProductCode.",
                    "operationType": "table.selectColumns",
                    "parameters": {"columnIds": ["col_order", "col_qty", "col_product"]},
                    "inputs": ["stp_source"],
                }},
                {"type": "setFinalOutput", "stepId": "prepared"},
            ],
        }


class NoOpPlanner:
    def __init__(self, question: str | None = None) -> None:
        self.question = question

    def propose(self, payload: dict) -> dict:
        return {
            "summary": "No pipeline change", "questions": [self.question] if self.question else [],
            "assumptions": [], "warnings": [], "changeReason": "No-op delta",
            "changes": [{"type": "setFinalOutput", "stepId": payload["baseRevision"]["finalOutputStepId"]}],
        }


class StructuredRequestHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.seed_store = ProblemChainStore(FakeContinuationPlanner())
        self.addCleanup(self.seed_store.close)
        root = self.seed_store.create_problem(None, None, "Đọc bảng Sales", typed_plan=typed_plan())
        committed_root = self.seed_store.commit(root["mutationId"], root["historyHash"])
        self.root_id = committed_root["document"]["headRevisionId"]
        child = self.seed_store.create_problem(
            committed_root["document"], committed_root["historyHash"],
            "Chỉ giữ OrderID và Qty", base_revision_id=self.root_id,
        )
        self.committed = self.seed_store.commit(child["mutationId"], child["historyHash"])

