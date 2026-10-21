"""Independent guards for session-only full-result restoration."""

from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore
from pbip_assistant.pq_typed import DESTINATION_MARKER, TypedPlanStore
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakePQRunner
from tests.support.pq_typed import FakeTypedPlanner
from tests.support.workbook_fingerprint import repack


class ProblemResultCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.payload = fixture.read_bytes()
        workbook_path = Path(temporary.name) / fixture.name
        workbook_path.write_bytes(self.payload)
        self.workbook = office_snapshot(workbook_path)
        previews = PQPreviewStore(FakePQRunner())
        self.addCleanup(previews.close)
        self.store = TypedPlanStore(FakeTypedPlanner(), previews)
        self.addCleanup(self.store.close)
        self.encoded = base64.b64encode(self.payload).decode("ascii")
        self.plan = self.store.create_plan(
            "Filter sales", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        self.revision_id = self.plan["revision"]["revisionId"]
        self.review_hash = self.plan["revision"]["reviewHash"]
        self.store.bind_problem_chain("chain_test", self.workbook)

    def _preview_and_cache(self, chain_id: str = "chain_test") -> None:
        preview = self.store.preview(
            self.revision_id, self.workbook, self.encoded,
            problem_chain_id=chain_id, run_version=self.store.problem_data_version(chain_id),
        )
        approval = self.store.approve(self.revision_id, preview["previewId"], DESTINATION_MARKER)
        prepared = self.store.prepare_apply(
            approval["approvalId"], self.encoded, {"marker": DESTINATION_MARKER},
        )
        confirmed = self.store.complete_apply(prepared["applyId"], {
            "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
            "rowCount": prepared["expectedRows"], "columnCount": prepared["expectedColumns"],
        })
        self.assertTrue(confirmed["resultCached"])

    def _prepare(self, encoded: str | None = None, workbook: dict | None = None) -> dict:
        return self.store.prepare_cached_problem_result(
            chain_id="chain_test", revision_id=self.revision_id,
            review_hash=self.review_hash, workbook=workbook or self.workbook,
            workbook_base64=encoded or self.encoded, destination_marker=DESTINATION_MARKER,
        )

    def test_checkout_invalidates_old_approval_but_full_result_can_be_restored(self) -> None:
        self._preview_and_cache()
        self.store.invalidate_runtime()
        prepared = self._prepare()
        self.assertTrue(base64.b64decode(prepared["resultWorkbookBase64"]).startswith(b"PK"))
        self.assertGreater(prepared["expectedRows"], 0)
        self.assertEqual(self.store.complete_apply(prepared["applyId"], {
            "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
            "rowCount": prepared["expectedRows"], "columnCount": prepared["expectedColumns"],
        })["status"], "applied")
        # The user may revisit the same revision again; the apply token is not reused.
        self.assertNotEqual(self._prepare()["applyId"], prepared["applyId"])

    def test_changed_source_or_workbook_identity_never_returns_write_payload(self) -> None:
        self._preview_and_cache()
        changed = base64.b64encode(repack(self.payload, change_cell=True)).decode("ascii")
        with self.assertRaises(InputError) as stale:
            self._prepare(changed)
        self.assertEqual(stale.exception.code, "PQPC_RESULT_CACHE_STALE")
        with self.assertRaises(InputError) as saved_as:
            self._prepare(workbook={**self.workbook, "name": "SaveAs.xlsx"})
        self.assertEqual(saved_as.exception.code, "PQPC_RESULT_CACHE_STALE")
        with self.assertRaises(InputError) as wrong_hash:
            self.store.prepare_cached_problem_result(
                chain_id="chain_test", revision_id=self.revision_id,
                review_hash="sha256:" + "0" * 64, workbook=self.workbook,
                workbook_base64=self.encoded, destination_marker=DESTINATION_MARKER,
            )
        self.assertEqual(wrong_hash.exception.code, "PQPC_RESULT_CACHE_STALE")

    def test_version_increment_keeps_old_result_until_new_confirmation(self) -> None:
        self._preview_and_cache()
        old = self.store._problem_result_cache[("chain_test", self.revision_id)]
        self.assertEqual(old["dataVersion"], 0)
        self.assertEqual(self.store.increment_problem_data_version("chain_test"), 1)
        self.assertIs(self.store._problem_result_cache[("chain_test", self.revision_id)], old)
        with self.assertRaises(InputError) as stale:
            self._prepare()
        self.assertEqual(stale.exception.code, "PQPC_RESULT_CACHE_STALE")
        preview = self.store.preview(
            self.revision_id, self.workbook, self.encoded,
            problem_chain_id="chain_test", run_version=1,
        )
        self.assertIs(self.store._problem_result_cache[("chain_test", self.revision_id)], old,
                      "staging must not replace the confirmed result")
        self.store.cancel_problem_preview("chain_test", self.revision_id, preview["previewId"])
        self.assertIs(self.store._problem_result_cache[("chain_test", self.revision_id)], old,
                      "cancel must preserve the prior result")
        self._preview_and_cache()
        self.assertEqual(self.store._problem_result_cache[("chain_test", self.revision_id)]["dataVersion"], 1)

    def test_fifo_limit_and_explicit_invalidation(self) -> None:
        self._preview_and_cache()
        original = self.store._problem_result_cache[("chain_test", self.revision_id)].copy()
        for index in range(1, 6):
            self.store._problem_result_cache[("chain_test", f"rev_{index}")] = {
                **original, "revisionId": f"rev_{index}",
            }
        # A new preview refreshes its revision and evicts the oldest result.
        self._preview_and_cache()
        self.assertEqual(len(self.store._problem_result_cache), 5)
        self.assertEqual(next(iter(self.store._problem_result_cache))[1], "rev_2")
        self.store.discard_problem_cache("chain_test")
        with self.assertRaises(InputError) as missing:
            self._prepare()
        self.assertEqual(missing.exception.code, "PQPC_RESULT_CACHE_MISS")

    def test_oversized_result_is_not_cached_or_partially_restored(self) -> None:
        preview = self.store.preview(
            self.revision_id, self.workbook, self.encoded,
            problem_chain_id="chain_test", run_version=0,
        )
        approval = self.store.approve(self.revision_id, preview["previewId"], DESTINATION_MARKER)
        prepared = self.store.prepare_apply(approval["approvalId"], self.encoded, {"marker": DESTINATION_MARKER})
        with patch("pbip_assistant.pq_typed.MAX_PROBLEM_RESULT_CACHE_BYTES", 1):
            confirmed = self.store.complete_apply(prepared["applyId"], {
                "marker": DESTINATION_MARKER, "sheetName": "PQ_Typed_Result",
                "rowCount": prepared["expectedRows"], "columnCount": prepared["expectedColumns"],
            })
            self.assertFalse(confirmed["resultCached"])
        self.assertEqual(len(self.store._problem_result_cache), 0)
        with self.assertRaises(InputError) as missing:
            self._prepare()
        self.assertEqual(missing.exception.code, "PQPC_RESULT_CACHE_MISS")


if __name__ == "__main__":
    unittest.main()
