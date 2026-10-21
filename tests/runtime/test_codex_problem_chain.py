from copy import deepcopy
import os
import time
import unittest
from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import CodexProblemChainPlanner, ProblemChainStore
from tests.support.problem_chain import FakeContinuationPlanner, typed_plan

from tests.support.structured_requests import (FailingPlanner, KeepProductCodePlanner, NoOpPlanner, StructuredRequestHarness)

class LiveCodexProblemChainTests(StructuredRequestHarness):
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

