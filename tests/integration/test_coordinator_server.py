from __future__ import annotations

import base64
from contextlib import redirect_stdout
import http.client
from io import StringIO
import json
from pathlib import Path
import tempfile
import threading
import unittest

from pbip_assistant.coordinator_runtime import TempWorkspaceManager
from pbip_assistant.errors import InputError
from pbip_assistant.excel_addin_server import create_server
from pbip_assistant.pq_code_m import ADVANCED_M_POLICY_ID
from tests.support.codex_excel import FakeCodex, workbook as codex_workbook
from tests.support.excel_plan import FIXTURE_ROOT, office_snapshot
from tests.support.pq_code_m import FakePQRunner


class FakeClock:
    def __init__(self, value: float = 1_800_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class BlockingCodex(FakeCodex):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.fail = False

    def analyze(self, payload: dict) -> dict:
        self.calls += 1
        self.entered.set()
        if not self.release.wait(5):
            raise InputError("CODEX_TIMEOUT", "codex", "Synthetic timeout")
        if self.fail:
            raise InputError("CODEX_FAILED", "codex", "Synthetic sanitized failure")
        return super().analyze(payload)


class BlockingPQ(FakePQRunner):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def apply(self, request: dict) -> dict:
        self.calls += 1
        self.entered.set()
        if not self.release.wait(5):
            raise InputError("PQV2_PREVIEW_FAILED", "runtime", "Synthetic timeout")
        return super().apply(request)


class CoordinatorServerCrossCheckTests(unittest.TestCase):
    """HTTP-level oracles independent from the runtime primitive test suite."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.temp_root = Path(self.temp.name)
        self.clock = FakeClock()
        self.workspace_manager = TempWorkspaceManager(
            root=self.temp_root / "local-data-copilot",
            system_temp_root=self.temp_root,
            clock=self.clock,
            start_janitor=False,
            cleanup_backoff_seconds=0,
        )
        fixture = FIXTURE_ROOT / "excel_mcp_sales_input.xlsx"
        self.source_path = self.temp_root / fixture.name
        self.source_bytes = fixture.read_bytes()
        self.source_path.write_bytes(self.source_bytes)
        self.workbook = office_snapshot(self.source_path)
        self.codex = BlockingCodex()
        self.pq = BlockingPQ()
        self.server = create_server(
            "127.0.0.1",
            0,
            codex_runner=self.codex,
            pq_runner=self.pq,
            session_clock=self.clock,
            idle_timeout_seconds=5,
            absolute_timeout_seconds=12,
            temp_workspaces=self.workspace_manager,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        status, _, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.token = bootstrap["token"]
        self.session_id = bootstrap["session"]["sessionId"]

    def tearDown(self) -> None:
        self.codex.release.set()
        self.pq.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        token: str | None = None,
    ) -> tuple[int, dict[str, str], dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers: dict[str, str] = {}
        if token is not None:
            headers = {
                "X-Local-Token": token,
                "Origin": f"http://127.0.0.1:{self.port}",
            }
        payload = None if body is None else json.dumps(body).encode("utf-8")
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        response_body = json.loads(response.read().decode("utf-8"))
        response_headers = dict(response.getheaders())
        status = response.status
        connection.close()
        return status, response_headers, response_body

    def codex_request(self) -> tuple[int, dict[str, str], dict]:
        return self.request(
            "POST",
            "/api/excel/analyze",
            {"prompt": "synthetic", "workbook": codex_workbook(), "formulaListSeparator": ";"},
            token=self.token,
        )

    def pq_request(self) -> tuple[int, dict[str, str], dict]:
        return self.request(
            "POST",
            "/api/pq/run-sheet",
            {
                "workbook": self.workbook,
                "source": {"kind": "table", "sheet": "Sales", "name": "SalesTable"},
                "mCode": 'let Source = Excel.CurrentWorkbook(){[Name="SalesTable"]}[Content] in Source',
                "riskAccepted": True,
                "riskPolicyId": ADVANCED_M_POLICY_ID,
                "workbookBase64": base64.b64encode(self.source_bytes).decode("ascii"),
            },
            token=self.token,
        )

    def _seed_session_state(self) -> None:
        app = self.server.app
        app.pq_typed._revisions["rev_sentinel"] = {"secret": True}
        app.pq_typed._approvals["apr_sentinel"] = {"secret": True}
        app.pq_previews._sessions["prv_sentinel"] = {"status": "active"}

    def _assert_session_state_empty(self) -> None:
        app = self.server.app
        self.assertEqual(app.pq_typed._revisions, {})
        self.assertEqual(app.pq_typed._approvals, {})
        self.assertEqual(app.pq_previews._sessions, {})

    def test_exact_idle_and_absolute_expiry_reject_old_tokens_and_reset_stores(self) -> None:
        # A request immediately before idle expiry slides the idle deadline.
        self.clock.advance(4.999)
        status, _, _ = self.request("POST", "/api/excel/plan", {}, token=self.token)
        self.assertEqual(status, 400)
        self._seed_session_state()
        self.clock.advance(5)
        status, _, expired = self.request("POST", "/api/excel/plan", {}, token=self.token)
        self.assertEqual(status, 401)
        self.assertEqual(expired["error"]["code"], "TOKEN_EXPIRED")
        self._assert_session_state_empty()

        status, _, replacement = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertNotEqual(replacement["token"], self.token)
        self.assertNotEqual(replacement["session"]["sessionId"], self.session_id)
        old_token = self.token
        self.token = replacement["token"]
        status, _, old = self.request("POST", "/api/excel/plan", {}, token=old_token)
        self.assertEqual((status, old["error"]["code"]), (401, "TOKEN_EXPIRED"))

        # Frequent valid requests cannot move the fixed absolute boundary.
        absolute = self.clock.value + 12
        for target in (self.clock.value + 4, self.clock.value + 8, absolute - 0.001):
            self.clock.value = target
            status, _, _ = self.request("POST", "/api/excel/plan", {}, token=self.token)
            self.assertEqual(status, 400)
        self._seed_session_state()
        self.clock.value = absolute
        status, _, expired = self.request("POST", "/api/excel/plan", {}, token=self.token)
        self.assertEqual((status, expired["error"]["code"]), (401, "TOKEN_EXPIRED"))
        self._assert_session_state_empty()

    def test_session_close_invalidates_token_and_clears_state(self) -> None:
        self._seed_session_state()
        status, _, body = self.request("POST", "/api/session/close", token=self.token)
        self.assertEqual((status, body), (200, {"status": "closed"}))
        self._assert_session_state_empty()
        status, _, expired = self.request("POST", "/api/excel/plan", {}, token=self.token)
        self.assertEqual((status, expired["error"]["code"]), (401, "TOKEN_EXPIRED"))

    def test_session_close_defers_cleanup_until_inflight_job_releases(self) -> None:
        invalidated = threading.Event()
        sessions = self.server.app.runtime.sessions
        original_invalidate = sessions._on_invalidate

        def observe_invalidation(session_id: str, reason: str) -> None:
            original_invalidate(session_id, reason)
            invalidated.set()

        sessions._on_invalidate = observe_invalidation
        outcome: list[int] = []
        worker = threading.Thread(target=lambda: outcome.append(self.codex_request()[0]))
        worker.start()
        self.assertTrue(self.codex.entered.wait(2))
        self._seed_session_state()
        status, _, body = self.request("POST", "/api/session/close", token=self.token)
        self.assertEqual((status, body), (200, {"status": "closed"}))
        self.assertIn("rev_sentinel", self.server.app.pq_typed._revisions)
        status, _, rejected = self.request("POST", "/api/excel/plan", {}, token=self.token)
        self.assertEqual((status, rejected["error"]["code"]), (401, "TOKEN_EXPIRED"))
        bootstrap_status, bootstrap_headers, bootstrap_body = self.request("GET", "/api/bootstrap")
        self.assertEqual(bootstrap_status, 429)
        self.assertEqual(bootstrap_headers.get("Retry-After"), "2")
        self.assertEqual(bootstrap_body["error"]["code"], "COORDINATOR_BUSY")
        self.assertIn("rev_sentinel", self.server.app.pq_typed._revisions)
        self.codex.release.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, [200])
        # Client receipt precedes the handler's finally/job.release boundary.
        # Observe completed server cleanup instead of racing that boundary.
        self.assertTrue(invalidated.wait(2), "in-flight job did not release and invalidate session")
        self._assert_session_state_empty()
        replacement_status, _, replacement = self.request("GET", "/api/bootstrap")
        self.assertEqual(replacement_status, 200)
        self.assertNotEqual(replacement["session"]["sessionId"], self.session_id)

    def test_same_slot_returns_429_with_retry_after_and_does_not_enter_runner_twice(self) -> None:
        result: list[tuple[int, dict[str, str], dict]] = []
        first = threading.Thread(target=lambda: result.append(self.pq_request()))
        first.start()
        self.assertTrue(self.pq.entered.wait(2))
        status, headers, busy = self.pq_request()
        self.assertEqual(status, 429)
        self.assertEqual(headers.get("Retry-After"), "2")
        self.assertEqual(busy["error"]["code"], "COORDINATOR_BUSY")
        self.assertEqual(self.pq.calls, 1)
        self.pq.release.set()
        first.join(5)
        self.assertFalse(first.is_alive())
        self.assertEqual(result[0][0], 200)

    def test_codex_and_excel_enter_independent_slots_concurrently(self) -> None:
        outcomes: list[int] = []
        codex_thread = threading.Thread(target=lambda: outcomes.append(self.codex_request()[0]))
        excel_thread = threading.Thread(target=lambda: outcomes.append(self.pq_request()[0]))
        codex_thread.start()
        excel_thread.start()
        self.assertTrue(self.codex.entered.wait(2))
        self.assertTrue(self.pq.entered.wait(2))
        self.assertEqual((self.codex.calls, self.pq.calls), (1, 1))
        self.codex.release.set()
        self.pq.release.set()
        codex_thread.join(5)
        excel_thread.join(5)
        self.assertEqual(sorted(outcomes), [200, 200])

    def test_runner_error_releases_slot_and_logs_do_not_expose_request_secrets(self) -> None:
        prompt = "PROMPT_SENTINEL_8f44"
        cell = "CELL_SENTINEL_5921"
        workbook_blob = "WORKBOOK_BASE64_SENTINEL"
        absolute_temp_path = str(self.workspace_manager.root)
        self.codex.fail = True
        self.codex.release.set()
        capture = StringIO()
        with redirect_stdout(capture):
            status, _, failure = self.request(
                "POST",
                "/api/excel/analyze",
                {
                    "prompt": prompt,
                    "workbook": {
                        **codex_workbook(),
                        "sheets": [{**codex_workbook()["sheets"][0], "rows": [[cell, workbook_blob, ""]]}],
                    },
                },
                token=self.token,
            )
        self.assertEqual((status, failure["error"]["code"]), (502, "CODEX_FAILED"))
        logged = capture.getvalue()
        for secret in (self.token, prompt, cell, workbook_blob, absolute_temp_path):
            self.assertNotIn(secret, logged)

        # The failure path's finally block must release the Codex semaphore.
        self.codex.fail = False
        status, _, _ = self.codex_request()
        self.assertEqual(status, 200)
        self.assertEqual(self.codex.calls, 2)

    def test_temp_manager_never_deletes_outside_or_unmarked_directories(self) -> None:
        outside = self.temp_root / "user-result"
        outside.mkdir()
        (outside / "result.xlsx").write_bytes(b"user-owned")
        unmarked = self.workspace_manager.root / ("run_" + "a" * 32)
        unmarked.mkdir()
        (unmarked / "keep.xlsx").write_bytes(b"keep")
        self.clock.advance(7200)
        result = self.workspace_manager.cleanup_stale()
        self.assertEqual(result["runDirectories"], 0)
        self.assertEqual((outside / "result.xlsx").read_bytes(), b"user-owned")
        self.assertEqual((unmarked / "keep.xlsx").read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
