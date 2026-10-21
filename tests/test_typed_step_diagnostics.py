from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore, _static_values_payload
from pbip_assistant.pq_typed import (
    TypedPlanStore,
    compile_m_to_step,
    dependency_closure_steps,
    diagnostic_step_cache_keys,
)
from tests.test_excel_plan import FIXTURE_ROOT, office_snapshot
from tests.test_pq_code_m import FakePQRunner
from tests.test_pq_typed import FakeTypedPlanner


class TypedStepDiagnosticTests(unittest.TestCase):
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
        self.chain_id = "chain_diagnostics"
        self.store.bind_problem_chain(self.chain_id, self.workbook)
        self.encoded = base64.b64encode(self.payload).decode("ascii")

    def test_prefix_compiler_stops_at_selected_step(self) -> None:
        selected = self.plan["steps"][2]["stepId"]
        code, closure = compile_m_to_step(self.plan, selected)
        self.assertEqual([item["stepId"] for item in closure], [item["stepId"] for item in self.plan["steps"][:3]])
        self.assertIn("Table.AddColumn", code)
        self.assertNotIn("Table.Sort", code)
        self.assertEqual(dependency_closure_steps(self.plan, selected)[-1]["stepId"], selected)
        keys = diagnostic_step_cache_keys(self.plan, "sha256:source", selected)
        self.assertEqual(set(keys), {item["stepId"] for item in self.plan["steps"][:3]})

    def test_run_confirm_inspect_and_version_stale(self) -> None:
        revision_id = self.plan["revision"]["revisionId"]
        selected = self.plan["steps"][2]["stepId"]
        staged = self.store.run_step_diagnostic(
            revision_id, selected, self.workbook, self.encoded,
            problem_chain_id=self.chain_id, run_version=0,
        )
        self.assertEqual(staged["status"], "ready")
        self.assertNotIn("resultWorkbookBase64", staged)
        self.assertEqual(staged["metricStatus"], "available")
        self.assertEqual(staged["blankCells"], 0)
        self.assertEqual(staged["errorCells"], 0)
        self.assertIn("Table.AddColumn", self.runner.requests[-1]["mCode"])
        self.assertNotIn("Table.Sort", self.runner.requests[-1]["mCode"])
        confirmed = self.store.confirm_step_diagnostic(
            staged["stagingId"], revision_id, selected, self.workbook, self.encoded,
            problem_chain_id=self.chain_id, run_version=0,
        )
        self.assertEqual(confirmed["status"], "confirmed")
        hit = self.store.inspect_step_cache(
            revision_id, selected, self.workbook, self.encoded,
            problem_chain_id=self.chain_id, run_version=0,
        )
        self.assertEqual(hit["status"], "hit")
        self.store.increment_problem_data_version(self.chain_id)
        stale = self.store.inspect_step_cache(
            revision_id, selected, self.workbook, self.encoded,
            problem_chain_id=self.chain_id, run_version=1,
        )
        self.assertEqual(stale["status"], "stale")

    def test_cancel_preserves_confirmed_cache(self) -> None:
        revision_id = self.plan["revision"]["revisionId"]
        selected = self.plan["steps"][1]["stepId"]
        staged = self.store.run_step_diagnostic(
            revision_id, selected, self.workbook, self.encoded,
            problem_chain_id=self.chain_id, run_version=0,
        )
        cancelled = self.store.cancel_step_diagnostic(staged["stagingId"])
        self.assertEqual(cancelled, {"stagingId": staged["stagingId"], "status": "cancelled"})
        self.assertEqual(self.store.cancel_step_diagnostic(staged["stagingId"]), cancelled)

    def test_diagnostic_column_limit_is_independent(self) -> None:
        path = Path(self.temp.name) / "values.xlsx"
        self.runner.apply({"resultWorkbookPath": str(path)})
        with self.assertRaises(InputError) as caught:
            _static_values_payload(
                path, 3, 76, max_rows=100_000, max_columns=75,
                max_cells=1_000_000, limit_code="TSD_RESULT_LIMIT",
            )
        self.assertEqual(caught.exception.code, "TSD_RESULT_LIMIT")


if __name__ == "__main__":
    unittest.main()
