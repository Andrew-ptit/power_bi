"""Synthetic Problem Chain requests; opt-in live Codex probe via PQPC_LIVE_CODEX=1."""

from copy import deepcopy
import os
import time
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import CodexProblemChainPlanner, ProblemChainStore
from tests.test_problem_chain_phase1 import FakeContinuationPlanner, typed_plan


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


class StructuredRequestTests(unittest.TestCase):
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

    def test_branch_from_non_head_is_a_sibling_and_keeps_original_immutable(self) -> None:
        original = deepcopy(self.committed["document"])
        started = time.perf_counter()
        candidate = self.seed_store.create_problem(
            original, self.committed["historyHash"],
            "Lọc Qty lớn hơn 0", base_revision_id=self.root_id,
            creation_mode="branch",
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(candidate["revision"]["parentRevisionId"], self.root_id)
        self.assertEqual(candidate["document"]["revisions"][:2], original["revisions"])
        self.assertEqual(self.seed_store.active_revision(original["headRevisionId"])["revision"]["revisionId"], original["headRevisionId"])
        committed = self.seed_store.commit(candidate["mutationId"], candidate["historyHash"])
        self.assertEqual(committed["document"]["headRevisionId"], candidate["revision"]["revisionId"])
        self.assertEqual(len(committed["document"]["revisions"]), 3)
        print(f"structured synthetic branch: {elapsed_ms:.1f} ms, 3 revisions, 0 original revisions changed")

    def test_planner_error_preserves_head_and_history(self) -> None:
        original = deepcopy(self.committed["document"])
        store = ProblemChainStore(FailingPlanner())
        self.addCleanup(store.close)
        store.load(original)
        started = time.perf_counter()
        with self.assertRaises(InputError) as caught:
            store.create_problem(
                original, self.committed["historyHash"],
                "Lọc Qty lớn hơn 0", base_revision_id=self.root_id,
                creation_mode="branch",
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(caught.exception.code, "CODEX_TIMEOUT")
        self.assertEqual(store.load(original)["document"], original)
        self.assertEqual(store.active_revision(original["headRevisionId"])["revision"]["revisionId"], original["headRevisionId"])
        print(f"structured synthetic failure: {elapsed_ms:.1f} ms, HEAD unchanged")

    def test_no_op_branch_is_rejected_instead_of_copying_parent_steps(self) -> None:
        for question in [None, "Which ProductCode rule should be used?"]:
            with self.subTest(question=question):
                store = ProblemChainStore(NoOpPlanner(question))
                self.addCleanup(store.close)
                original = deepcopy(self.committed["document"])
                store.load(original)
                if question:
                    result = store.create_problem(
                        original, self.committed["historyHash"], "Merge Products",
                        base_revision_id=self.root_id, creation_mode="branch",
                    )
                    self.assertEqual(result["status"], "needsClarification")
                    self.assertEqual(result["questions"], [question])
                    self.assertNotIn("mutationId", result)
                else:
                    with self.assertRaises(InputError) as caught:
                        store.create_problem(
                            original, self.committed["historyHash"], "Merge Products",
                            base_revision_id=self.root_id, creation_mode="branch",
                        )
                    self.assertEqual(caught.exception.code, "PQPC_NO_PIPELINE_CHANGE")
                self.assertEqual(store.load(original)["document"], original)

    @unittest.skipUnless(os.getenv("PQPC_LIVE_CODEX") == "1", "Set PQPC_LIVE_CODEX=1 for one real Codex request")
    def test_live_codex_structured_branch(self) -> None:
        original = deepcopy(self.committed["document"])
        store = ProblemChainStore(CodexProblemChainPlanner(timeout_seconds=90))
        self.addCleanup(store.close)
        store.load(original)
        started = time.perf_counter()
        try:
            candidate = store.create_problem(
                original, self.committed["historyHash"],
                "Từ bảng Sales, lọc những dòng Qty lớn hơn 0; giữ hai cột OrderID và Qty.",
                base_revision_id=self.root_id, creation_mode="branch",
            )
        except InputError as exc:
            print(f"structured live Codex: {time.perf_counter() - started:.1f} s, {exc.code}; HEAD unchanged")
            self.assertEqual(store.active_revision(original["headRevisionId"])["revision"]["revisionId"], original["headRevisionId"])
            raise
        elapsed = time.perf_counter() - started
        self.assertEqual(candidate["revision"]["parentRevisionId"], self.root_id)
        self.assertEqual(candidate["document"]["revisions"][:2], original["revisions"])
        self.assertEqual(candidate["revision"]["validationAtCreation"]["overall"], "passed")
        print(f"structured live Codex: {elapsed:.1f} s, {len(candidate['revision']['steps'])} steps, validation passed")

    @unittest.skipUnless(os.getenv("PQPC_LIVE_CODEX") == "1", "Set PQPC_LIVE_CODEX=1 for one real Codex request")
    def test_live_codex_left_merge_branch(self) -> None:
        sales = typed_plan()
        product_code = {
            "columnId": "col_product", "name": "ProductCode", "inferredType": "text",
            "nullable": False, "ordinal": 2,
        }
        sales["sources"][0]["columns"].append(product_code)
        sales["sources"][0]["totalColumns"] = 3
        products = {
            "sourceId": "src_products", "kind": "excelTable", "sheetName": "Products",
            "objectName": "tblProducts", "schemaHash": "sha256:" + "3" * 64,
            "sampleOnly": False, "totalRows": 3, "totalColumns": 2,
            "columns": [
                {"columnId": "col_products_code", "name": "ProductCode", "inferredType": "text", "nullable": False, "ordinal": 0},
                {"columnId": "col_product_name", "name": "ProductName", "inferredType": "text", "nullable": False, "ordinal": 1},
            ],
        }
        store = ProblemChainStore(CodexProblemChainPlanner(timeout_seconds=90))
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Đọc Sales", typed_plan=sales)
        committed_root = store.commit(root["mutationId"], root["historyHash"])
        store.planner = KeepProductCodePlanner()
        child = store.create_problem(
            committed_root["document"], committed_root["historyHash"],
            "Vấn đề 1.1: chuẩn bị Sales", base_revision_id=committed_root["document"]["headRevisionId"],
        )
        committed = store.commit(child["mutationId"], child["historyHash"])
        base_id = committed["document"]["headRevisionId"]
        store.planner = CodexProblemChainPlanner(timeout_seconds=90)
        started = time.perf_counter()
        try:
            candidate = store.create_problem(
                committed["document"], committed["historyHash"],
                "Left Merge Sales với tblProducts theo ProductCode, mở rộng ProductName thành cột cuối; giữ tất cả dòng Sales.",
                base_revision_id=base_id, creation_mode="branch",
                source_catalog=[sales["sources"][0], products],
            )
        except InputError as exc:
            print(f"structured live Left Merge: {time.perf_counter() - started:.1f} s, {exc.code}; HEAD unchanged")
            self.assertEqual(store.active_revision(base_id)["revision"]["revisionId"], base_id)
            raise
        elapsed = time.perf_counter() - started
        operations = [step["operation"]["type"] for step in candidate["revision"]["steps"]]
        self.assertIn("table.mergeTables", operations)
        self.assertIn("table.expandTableColumn", operations)
        self.assertLess(operations.index("table.mergeTables"), operations.index("table.expandTableColumn"))
        self.assertEqual(candidate["revision"]["validationAtCreation"]["overall"], "passed")
        self.assertEqual(candidate["revision"]["parentRevisionId"], base_id)
        self.assertEqual(committed["document"]["headRevisionId"], base_id)
        print(f"structured live Left Merge: {elapsed:.1f} s, {len(operations)} steps, merge+expand validated")


if __name__ == "__main__":
    unittest.main()
