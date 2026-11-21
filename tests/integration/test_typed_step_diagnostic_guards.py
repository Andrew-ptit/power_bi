"""Characterization tests for the step-diagnostic guards.

These pin the error codes and observables of the staging/cache use cases before
the orchestration is extracted out of `TypedPlanStore`. They deliberately assert
current behaviour rather than a redesign: the extraction must not change which
guard fires, in which order, or what a rejected call leaves behind.
"""

from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import threading
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore
from pbip_assistant.pq_typed import TypedPlanStore
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakePQRunner
from tests.support.pq_typed import FakeTypedPlanner


class TypedStepDiagnosticGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.path = Path(self.temp.name) / fixture.name
        self.payload = fixture.read_bytes()
        self.path.write_bytes(self.payload)
        self.workbook = office_snapshot(self.path)
        self.runner = FakePQRunner()
        self.previews = PQPreviewStore(self.runner)
        self.addCleanup(self.previews.close)
        self.store = TypedPlanStore(FakeTypedPlanner(), self.previews)
        self.addCleanup(self.store.close)
        self.plan = self.store.create_plan(
            "Filter, add profit and sort", self.workbook,
            {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
        )
        self.revision_id = self.plan["revision"]["revisionId"]
        self.selected = self.plan["steps"][2]["stepId"]
        self.chain_id = "chain_guard"
        self.store.bind_problem_chain(self.chain_id, self.workbook)
        self.encoded = base64.b64encode(self.payload).decode("ascii")

    def _run(self, **overrides):
        arguments = {
            "revision_id": self.revision_id, "selected_step_id": self.selected,
            "workbook": self.workbook, "workbook_base64": self.encoded,
            "problem_chain_id": self.chain_id, "run_version": 0,
        }
        arguments.update(overrides)
        return self.store.run_step_diagnostic(**arguments)

    def _confirm(self, staging_id, **overrides):
        arguments = {
            "staging_id": staging_id, "revision_id": self.revision_id,
            "selected_step_id": self.selected, "workbook": self.workbook,
            "workbook_base64": self.encoded, "problem_chain_id": self.chain_id,
            "run_version": 0,
        }
        arguments.update(overrides)
        return self.store.confirm_step_diagnostic(**arguments)

    def _code(self, callable_, **overrides) -> str:
        with self.assertRaises(InputError) as caught:
            callable_(**overrides)
        return caught.exception.code

    def test_unknown_revision_and_unknown_chain_are_rejected(self) -> None:
        self.assertEqual(self._code(self._run, revision_id="rev_missing"), "PQV2_REVISION_NOT_FOUND")
        self.assertEqual(self._code(self._run, problem_chain_id="chain_other"), "TSD_SOURCE_STALE")

    def test_stale_run_version_is_rejected_before_anything_is_staged(self) -> None:
        self.assertEqual(self._code(self._run, run_version=7), "TSD_SOURCE_STALE")
        self.assertIsNone(self.store._step_diagnostic_staging)

    def test_selected_step_must_be_a_string(self) -> None:
        self.assertEqual(self._code(self._run, selected_step_id=None), "TSD_STEP_NOT_FOUND")
        self.assertEqual(self._code(self._run, selected_step_id=3), "TSD_STEP_NOT_FOUND")

    def test_second_run_is_rejected_while_one_is_still_running(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        original = self.previews.preview_diagnostic

        def blocking(**kwargs):
            entered.set()
            self.assertTrue(release.wait(10), "the first diagnostic was never released")
            return original(**kwargs)

        self.previews.preview_diagnostic = blocking
        outcome: dict[str, object] = {}

        def first_run() -> None:
            try:
                outcome["staged"] = self._run()
            except Exception as exc:  # recorded and asserted below
                outcome["error"] = exc

        worker = threading.Thread(target=first_run)
        worker.start()
        self.assertTrue(entered.wait(10), "the first diagnostic never started")
        try:
            self.assertEqual(self._code(self._run), "COORDINATOR_BUSY")
        finally:
            release.set()
            worker.join(10)
        self.assertNotIn("error", outcome, outcome.get("error"))
        self.assertEqual(outcome["staged"]["status"], "ready")

    def test_confirm_requires_the_matching_staging_id(self) -> None:
        staged = self._run()
        self.assertEqual(self._code(self._confirm, staging_id="stage_other"), "TSD_STAGING_STALE")
        self.assertEqual(self._code(self._confirm, staging_id=staged["stagingId"], run_version=4), "TSD_SOURCE_STALE")

    def test_confirm_rejects_a_source_version_change(self) -> None:
        staged = self._run()
        self.store.increment_problem_data_version(self.chain_id)
        self.assertEqual(self._code(self._confirm, staging_id=staged["stagingId"]), "TSD_SOURCE_STALE")

    def test_inspect_is_a_miss_before_any_confirm_and_cancel_rejects_unknown_staging(self) -> None:
        inspected = self.store.inspect_step_cache(
            self.revision_id, self.selected, self.workbook, self.encoded,
            problem_chain_id=self.chain_id, run_version=0,
        )
        self.assertEqual(inspected, {"status": "miss"})
        with self.assertRaises(InputError) as caught:
            self.store.cancel_step_diagnostic("stage_other")
        self.assertEqual(caught.exception.code, "TSD_STAGING_STALE")


if __name__ == "__main__":
    unittest.main()
