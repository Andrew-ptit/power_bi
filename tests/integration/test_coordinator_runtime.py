from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pbip_assistant.codex_excel import CodexExecRunner
from pbip_assistant.codex_pq import CodexMRunner
from pbip_assistant.coordinator_runtime import (
    CoordinatorBusy,
    ExecutionSlots,
    SessionManager,
    TempWorkspaceManager,
)
from pbip_assistant.errors import InputError
from pbip_assistant.excel_connector import PowerShellExcelRunner
from pbip_assistant.pq_code_m import PQPreviewStore


class FakeClock:
    def __init__(self, value: float = 1_700_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SessionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.invalidated: list[tuple[str, str]] = []
        self.manager = SessionManager(
            idle_timeout_seconds=30,
            absolute_timeout_seconds=100,
            clock=self.clock,
            on_invalidate=lambda session_id, reason: self.invalidated.append((session_id, reason)),
        )

    def test_bootstrap_uses_256_bit_token_and_public_expiry_metadata(self) -> None:
        issued = self.manager.bootstrap()
        self.assertGreaterEqual(len(issued.token), 43)
        self.assertEqual(issued.session.idle_timeout_seconds, 30)
        self.assertEqual(issued.session.absolute_timeout_seconds, 100)
        self.assertEqual(issued.session.idle_expires_at, self.clock.value + 30)
        public = issued.public_dict()
        self.assertEqual(public["session"]["sessionId"], issued.session.session_id)
        self.assertTrue(public["session"]["issuedAt"].endswith("Z"))
        self.assertNotIn(issued.token, json.dumps(public["session"]))

    def test_authentication_slides_idle_but_never_absolute_expiry(self) -> None:
        issued = self.manager.bootstrap()
        self.clock.advance(29)
        first = self.manager.authenticate(issued.token)
        self.assertEqual(first.idle_expires_at, self.clock.value + 30)
        self.clock.advance(29)
        self.manager.authenticate(issued.token)
        self.clock.advance(29)
        second = self.manager.authenticate(issued.token)
        self.assertEqual(second.idle_expires_at, issued.session.absolute_expires_at)
        self.clock.advance(13)
        with self.assertRaises(InputError) as raised:
            self.manager.authenticate(issued.token)
        self.assertEqual(raised.exception.code, "TOKEN_EXPIRED")
        self.assertEqual(self.invalidated, [(issued.session.session_id, "expired")])

    def test_exact_idle_boundary_expires_and_bootstrap_returns_clean_session(self) -> None:
        first = self.manager.bootstrap()
        self.clock.advance(30)
        with self.assertRaises(InputError) as raised:
            self.manager.authenticate(first.token)
        self.assertEqual(raised.exception.code, "TOKEN_EXPIRED")
        second = self.manager.bootstrap()
        self.assertNotEqual(second.token, first.token)
        self.assertNotEqual(second.session.session_id, first.session.session_id)
        with self.assertRaises(InputError) as old:
            self.manager.authenticate(first.token)
        self.assertEqual(old.exception.code, "TOKEN_EXPIRED")

    def test_started_job_finishes_after_expiry_then_invalidates_once(self) -> None:
        issued = self.manager.bootstrap()
        job = self.manager.begin_job(issued.token)
        self.clock.advance(101)
        with self.assertRaises(InputError) as raised:
            self.manager.authenticate(issued.token)
        self.assertEqual(raised.exception.code, "TOKEN_EXPIRED")
        self.assertEqual(self.invalidated, [])
        job.release()
        job.release()
        self.assertEqual(self.invalidated, [(issued.session.session_id, "expired")])

    def test_close_waits_for_active_job_and_rejects_new_work(self) -> None:
        issued = self.manager.bootstrap()
        job = self.manager.begin_job(issued.token)
        self.manager.close(issued.token)
        with self.assertRaises(InputError) as raised:
            self.manager.begin_job(issued.token)
        self.assertEqual(raised.exception.code, "TOKEN_EXPIRED")
        self.assertEqual(self.invalidated, [])
        with self.assertRaises(CoordinatorBusy) as busy:
            self.manager.bootstrap()
        self.assertEqual(busy.exception.code, "COORDINATOR_BUSY")
        job.release()
        self.assertEqual(self.invalidated, [(issued.session.session_id, "closed")])
        replacement = self.manager.bootstrap()
        self.assertNotEqual(replacement.session.session_id, issued.session.session_id)

    def test_missing_or_forged_token_is_not_reported_as_expired(self) -> None:
        self.manager.bootstrap()
        for token in ("", "forged"):
            with self.subTest(token=token), self.assertRaises(InputError) as raised:
                self.manager.authenticate(token)
            self.assertEqual(raised.exception.code, "TOKEN_REQUIRED")


class ExecutionSlotsTests(unittest.TestCase):
    def test_same_slot_fails_fast_without_waiting(self) -> None:
        slots = ExecutionSlots(retry_after_seconds=2)
        with slots.acquire("excel"):
            with self.assertRaises(CoordinatorBusy) as raised:
                with slots.acquire("excel"):
                    pass
        self.assertEqual(raised.exception.code, "COORDINATOR_BUSY")
        self.assertEqual(raised.exception.retry_after_seconds, 2)

    def test_codex_and_excel_slots_are_independent(self) -> None:
        slots = ExecutionSlots()
        with slots.acquire("codex"):
            with slots.acquire("excel"):
                pass

    def test_slot_is_released_when_runner_raises(self) -> None:
        slots = ExecutionSlots()
        with self.assertRaisesRegex(RuntimeError, "runner"):
            with slots.acquire("codex"):
                raise RuntimeError("runner failed")
        with slots.acquire("codex"):
            pass

    def test_only_one_concurrent_worker_enters_each_slot(self) -> None:
        slots = ExecutionSlots()
        entered = threading.Event()
        release = threading.Event()

        def holder() -> None:
            with slots.acquire("codex"):
                entered.set()
                release.wait(2)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(CoordinatorBusy):
                with slots.acquire("codex"):
                    pass
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())


class TempWorkspaceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.system_temp = Path(self.temp.name)
        self.root = self.system_temp / "local-data-copilot"
        self.clock = FakeClock()

    def manager(self, **overrides: object) -> TempWorkspaceManager:
        options = {
            "root": self.root,
            "system_temp_root": self.system_temp,
            "clock": self.clock,
            "stale_run_seconds": 60,
            "legacy_stale_seconds": 120,
            "start_janitor": False,
            "cleanup_backoff_seconds": 0,
        }
        options.update(overrides)
        manager = TempWorkspaceManager(**options)
        self.addCleanup(manager.close)
        return manager

    def test_workspace_is_marked_and_removed_after_success_or_error(self) -> None:
        manager = self.manager()
        with manager.workspace() as workspace:
            path = workspace.path
            marker_files = list(path.glob(".local-data-copilot-run.json"))
            self.assertEqual(len(marker_files), 1)
            marker = json.loads(marker_files[0].read_text(encoding="utf-8"))
            self.assertEqual(marker["kind"], "local-data-copilot-temp-v1")
            self.assertNotIn("token", marker)
            self.assertNotIn("path", marker)
        self.assertFalse(path.exists())

        with self.assertRaisesRegex(RuntimeError, "original"):
            with manager.workspace() as failed:
                failed_path = failed.path
                raise RuntimeError("original operation error")
        self.assertFalse(failed_path.exists())

    def test_cleanup_failure_does_not_replace_original_operation_error(self) -> None:
        manager = self.manager()
        original_remove = manager._remove_tree

        def fail_cleanup(path: Path) -> bool:
            if path.name.startswith("run_"):
                return False
            return original_remove(path)

        with patch.object(manager, "_remove_tree", side_effect=fail_cleanup):
            with self.assertRaisesRegex(RuntimeError, "business failure"):
                with manager.workspace():
                    raise RuntimeError("business failure")

    def test_stale_marker_is_removed_but_fresh_invalid_and_active_are_kept(self) -> None:
        manager = self.manager()
        abandoned = manager._create_workspace()
        with manager._lock:
            manager._active.remove(abandoned)
        active = manager._create_workspace()
        invalid = self.root / ("run_" + "f" * 32)
        invalid.mkdir()
        (invalid / ".local-data-copilot-run.json").write_text("{}", encoding="utf-8")
        self.clock.advance(61)
        result = manager.cleanup_stale()
        self.assertEqual(result["runDirectories"], 1)
        self.assertFalse(abandoned.exists())
        self.assertTrue(active.exists())
        self.assertTrue(invalid.exists())
        with manager._lock:
            manager._active.remove(active)
        manager._remove_tree(active)

    def test_heartbeat_extends_lifetime(self) -> None:
        manager = self.manager()
        path = manager._create_workspace()
        self.clock.advance(50)
        manager.heartbeat(path)
        with manager._lock:
            manager._active.remove(path)
        self.clock.advance(50)
        manager.cleanup_stale()
        self.assertTrue(path.exists())
        self.clock.advance(11)
        manager.cleanup_stale()
        self.assertFalse(path.exists())

    def test_crashed_process_workspace_is_reaped_after_stale_threshold(self) -> None:
        script = (
            "import os,sys; "
            "from pbip_assistant.coordinator_runtime import TempWorkspaceManager; "
            "m=TempWorkspaceManager(root=sys.argv[1],system_temp_root=sys.argv[2],start_janitor=False); "
            "m._create_workspace(); os._exit(17)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, str(self.root), str(self.system_temp)],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 17)
        abandoned = list(self.root.glob("run_*"))
        self.assertEqual(len(abandoned), 1)
        marker = abandoned[0] / ".local-data-copilot-run.json"
        os.utime(marker, (self.clock.value - 61, self.clock.value - 61))
        manager = self.manager()
        self.assertFalse(abandoned[0].exists())

    def test_only_old_safe_legacy_directories_are_removed(self) -> None:
        manager = self.manager()
        old_safe = self.system_temp / "pbip-excel-request-deadbeef"
        old_safe.mkdir()
        (old_safe / "request.json").write_text("{}", encoding="utf-8")
        fresh = self.system_temp / "pq-codex-fresh"
        fresh.mkdir()
        unsafe = self.system_temp / "pq-code-m-unsafe"
        unsafe.mkdir()
        (unsafe / "keep.txt").write_text("keep", encoding="utf-8")
        unrelated = self.system_temp / "other-old-directory"
        unrelated.mkdir()
        for item in (old_safe, old_safe / "request.json"):
            os.utime(item, (self.clock.value - 121, self.clock.value - 121))
        os.utime(fresh, (self.clock.value, self.clock.value))
        os.utime(unsafe, (self.clock.value - 121, self.clock.value - 121))
        os.utime(unrelated, (self.clock.value - 121, self.clock.value - 121))
        result = manager.cleanup_stale()
        self.assertEqual(result["legacyDirectories"], 1)
        self.assertFalse(old_safe.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(unsafe.exists())
        self.assertTrue(unrelated.exists())

    def test_unavailable_root_returns_sanitized_error(self) -> None:
        blocked = self.system_temp / "blocked"
        blocked.write_text("file", encoding="utf-8")
        with self.assertRaises(InputError) as raised:
            TempWorkspaceManager(root=blocked, system_temp_root=self.system_temp, start_janitor=False)
        self.assertEqual(raised.exception.code, "TEMP_STORAGE_UNAVAILABLE")
        self.assertNotIn(str(blocked), raised.exception.detail)

    def test_root_outside_system_temp_boundary_is_rejected(self) -> None:
        outside = self.system_temp.parent / "outside-coordinator-temp"
        with self.assertRaises(InputError) as raised:
            TempWorkspaceManager(root=outside, system_temp_root=self.system_temp, start_janitor=False)
        self.assertEqual(raised.exception.code, "TEMP_STORAGE_UNAVAILABLE")
        self.assertFalse(outside.exists())


class WorkspaceInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.system_temp = Path(self.temp.name)
        self.root = self.system_temp / "local-data-copilot"
        self.manager = TempWorkspaceManager(
            root=self.root, system_temp_root=self.system_temp, start_janitor=False
        )
        self.addCleanup(self.manager.close)

    def assert_marked_workspace(self, cwd: str) -> None:
        path = Path(cwd)
        self.assertEqual(path.parent, self.root)
        self.assertTrue((path / ".local-data-copilot-run.json").is_file())

    def test_codex_runners_use_injected_marked_workspace_and_clean_it(self) -> None:
        seen: list[str] = []

        def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
            cwd = str(kwargs["cwd"])
            self.assert_marked_workspace(cwd)
            seen.append(cwd)
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")

        with (
            patch("pbip_assistant.codex_excel.find_codex_executable", return_value="codex"),
            patch("pbip_assistant.codex_excel.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(CodexExecRunner(workspace_manager=self.manager).analyze({}), {})
        with (
            patch("pbip_assistant.codex_pq.find_codex_executable", return_value="codex"),
            patch("pbip_assistant.codex_pq.subprocess.run", side_effect=fake_run),
        ):
            self.assertEqual(CodexMRunner(workspace_manager=self.manager).propose({}), {})
        self.assertEqual(len(seen), 2)
        self.assertFalse(any(Path(item).exists() for item in seen))

    def test_excel_runner_request_workspace_is_marked_and_cleaned(self) -> None:
        script = self.system_temp / "helper.ps1"
        script.write_text("# fixture", encoding="utf-8")
        seen: list[Path] = []

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            request_path = Path(command[-1])
            self.assert_marked_workspace(str(request_path.parent))
            self.assertTrue(request_path.is_file())
            seen.append(request_path.parent)
            return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

        with patch("pbip_assistant.excel_connector.subprocess.run", side_effect=fake_run):
            result = PowerShellExcelRunner(script, workspace_manager=self.manager).apply({"version": 1})
        self.assertTrue(result["ok"])
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].exists())

    def test_preview_store_holds_one_marked_workspace_until_close(self) -> None:
        store = PQPreviewStore(object(), workspace_manager=self.manager)  # runner is unused by this lifecycle oracle
        path = store._temp_path
        self.assert_marked_workspace(str(path))
        store.close()
        self.assertFalse(path.exists())

    def test_temp_allocation_error_occurs_before_any_subprocess(self) -> None:
        blocked = self.system_temp / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        with self.assertRaises(InputError) as raised:
            manager = TempWorkspaceManager(root=blocked, system_temp_root=self.system_temp, start_janitor=False)
        self.assertEqual(raised.exception.code, "TEMP_STORAGE_UNAVAILABLE")

        class FailingManager:
            def workspace(self) -> object:
                raise InputError("TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Unavailable")

        with (
            patch("pbip_assistant.codex_excel.find_codex_executable", return_value="codex"),
            patch("pbip_assistant.codex_excel.subprocess.run") as subprocess_run,
            self.assertRaises(InputError) as codex_error,
        ):
            CodexExecRunner(workspace_manager=FailingManager()).analyze({})  # type: ignore[arg-type]
        self.assertEqual(codex_error.exception.code, "TEMP_STORAGE_UNAVAILABLE")
        subprocess_run.assert_not_called()

        script = self.system_temp / "helper.ps1"
        script.write_text("# fixture", encoding="utf-8")
        with (
            patch("pbip_assistant.excel_connector.subprocess.run") as excel_run,
            self.assertRaises(InputError) as excel_error,
        ):
            PowerShellExcelRunner(script, workspace_manager=FailingManager()).apply({})  # type: ignore[arg-type]
        self.assertEqual(excel_error.exception.code, "TEMP_STORAGE_UNAVAILABLE")
        excel_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
