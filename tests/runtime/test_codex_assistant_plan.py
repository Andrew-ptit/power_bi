"""Opt-in real Codex branch planning with bounded synthetic cells only."""

from decimal import Decimal
import os
import tempfile
import time
import unittest

from pbip_assistant.errors import InputError
from pbip_assistant.adapters.codex.assistant_plan import CodexAssistantPlanRunner
from pbip_assistant.coordinator_runtime import TempWorkspaceManager
from pbip_assistant.powerquery.typed_local import execute_plan
from pbip_assistant.sources.assistant_session import AssistantSessionStore


class LiveCodexAssistantPlanTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("PQPC_LIVE_CODEX") == "1", "Set PQPC_LIVE_CODEX=1 for a real bounded Codex call")
    def test_live_codex_drafts_two_validated_plans_without_calculated_values(self):
        started = time.monotonic()
        store = AssistantSessionStore()
        self.addCleanup(store.close)
        workspaces = TempWorkspaceManager()
        self.addCleanup(workspaces.close)
        runner = CodexAssistantPlanRunner(workspace_manager=workspaces)
        with tempfile.TemporaryDirectory(prefix="assistant-codex-synthetic-") as directory:
            store.bind_root(directory)
            selection = {
                "name": "LiveAssistantSynthetic", "origin": "synthetic", "sheet": "Synthetic",
                "table": True, "header": ["Key", "Amount"],
                "rows": [["A", "10"], ["B", "-3"], ["C", "5"]],
                "totalRows": 3, "totalColumns": 2, "sampleOrdinals": [0, 1, 2],
            }
            store.ingest([{"kind": "workbook", "mode": "discover", "payload": selection}])
            store.understand()
            prompt = (
                "Return branch A summing Amount for all rows, and branch B summing Amount only for rows greater than zero. "
                "Explicitly convert Amount from text to number before filtering or summing. Each output must be one numeric "
                "Total column and one row. Declare a sum controlTotal after filters. Use the provided catalog sourceId. "
                "Do not calculate or return any totals: the local engine will calculate them. No business assumptions are needed."
            )
            try:
                public = store.plan_draft(prompt, [], True, runner)
            except InputError as exc:
                print(f"live Assistant Codex: failed code={exc.code}; elapsed={time.monotonic() - started:.3f}s")
                raise
            self.assertEqual(public["stage"], "planning")
            self.assertEqual({branch["id"] for branch in public["branches"]}, {"A", "B"})
            store.ingest([{"kind": "workbook", "mode": "compute", "payload": selection}],
                         expected_planning_hash=public["planningHash"])
            self.assertEqual(store.state()["mode"], "compute")
            # Read only the synthetic store's revalidated normalized plans after
            # a full-data ingest. No discover artifact supplies final results.
            expected = {"A": Decimal("12"), "B": Decimal("15")}
            for branch in store._planning["branches"]:
                actual = execute_plan(branch["plan"], store._raw_tables)
                self.assertEqual([column["name"] for column in actual["columns"]], ["Total"])
                self.assertEqual(actual["rowCount"], 1)
                self.assertEqual(Decimal(actual["rows"][0][0]), expected[branch["id"]])
            print(f"live Assistant Codex: pass branches=2; resultDimensions=1x1 each; elapsed={time.monotonic() - started:.3f}s")
