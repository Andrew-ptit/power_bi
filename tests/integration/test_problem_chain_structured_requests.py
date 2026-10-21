from copy import deepcopy
import os
import time
import unittest
from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import CodexProblemChainPlanner, ProblemChainStore
from tests.support.problem_chain import FakeContinuationPlanner, typed_plan

from tests.support.structured_requests import (FailingPlanner, KeepProductCodePlanner, NoOpPlanner, StructuredRequestHarness)

class StructuredRequestTests(StructuredRequestHarness):
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

