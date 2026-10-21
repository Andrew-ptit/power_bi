"""Coordinator session, concurrency, and temporary-workspace primitives.

This module is deliberately independent of the HTTP coordinator.  The server
owns routing and status-code mapping; these primitives own the state changes
that must remain atomic when ``ThreadingHTTPServer`` handles concurrent calls.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
from threading import BoundedSemaphore, Event, RLock, Thread
import time
from typing import Any

from .errors import InputError


DEFAULT_IDLE_TIMEOUT_SECONDS = 30 * 60
DEFAULT_ABSOLUTE_TIMEOUT_SECONDS = 8 * 60 * 60
DEFAULT_STALE_RUN_SECONDS = 60 * 60
DEFAULT_LEGACY_STALE_SECONDS = 24 * 60 * 60
DEFAULT_JANITOR_INTERVAL_SECONDS = 60

_RUN_NAME = re.compile(r"^run_([0-9a-f]{32})$")
_RUN_MARKER_NAME = ".local-data-copilot-run.json"
_RUN_MARKER_KIND = "local-data-copilot-temp-v1"
_LEGACY_NAME = re.compile(
    r"^(?:excel-codex-analysis|pq-codex|pq-typed-codex|"
    r"pbip-excel-request|pbip-excel-validate|pq-code-m)-[A-Za-z0-9_.-]+$"
)
_LEGACY_FILE_SUFFIXES = frozenset({".json", ".xlsx", ".xlsm", ".tmp"})


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


class CoordinatorBusy(InputError):
    """A fail-fast execution slot is already occupied."""

    def __init__(self, slot: str, retry_after_seconds: int = 2) -> None:
        super().__init__("COORDINATOR_BUSY", slot, f"The {slot} execution slot is busy")
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class SessionView:
    session_id: str
    issued_at: float
    idle_expires_at: float
    absolute_expires_at: float
    idle_timeout_seconds: int
    absolute_timeout_seconds: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "issuedAt": _utc_iso(self.issued_at),
            "idleExpiresAt": _utc_iso(self.idle_expires_at),
            "absoluteExpiresAt": _utc_iso(self.absolute_expires_at),
            "idleTimeoutSeconds": self.idle_timeout_seconds,
            "absoluteTimeoutSeconds": self.absolute_timeout_seconds,
        }


@dataclass
class _SessionState:
    session_id: str
    token: str
    issued_at: float
    idle_expires_at: float
    absolute_expires_at: float
    active_jobs: int = 0
    closing: bool = False
    close_reason: str = "closed"


@dataclass(frozen=True)
class SessionBootstrap:
    token: str
    session: SessionView

    def public_dict(self) -> dict[str, Any]:
        return {"token": self.token, "session": self.session.public_dict()}


class SessionJob:
    """A job authorization that remains valid until its already-started work ends."""

    def __init__(self, manager: SessionManager, session_id: str) -> None:
        self._manager = manager
        self.session_id = session_id
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._manager._finish_job(self.session_id)

    def __enter__(self) -> SessionJob:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


class SessionManager:
    """Issue one-panel sessions with sliding idle and fixed absolute expiry."""

    def __init__(
        self,
        *,
        idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS,
        absolute_timeout_seconds: int = DEFAULT_ABSOLUTE_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.time,
        on_invalidate: Callable[[str, str], None] | None = None,
        retired_token_limit: int = 32,
    ) -> None:
        if idle_timeout_seconds <= 0 or absolute_timeout_seconds <= 0:
            raise ValueError("session timeouts must be positive")
        if idle_timeout_seconds > absolute_timeout_seconds:
            raise ValueError("idle timeout cannot exceed absolute timeout")
        self.idle_timeout_seconds = int(idle_timeout_seconds)
        self.absolute_timeout_seconds = int(absolute_timeout_seconds)
        self._clock = clock
        self._on_invalidate = on_invalidate
        self._retired_token_limit = max(1, int(retired_token_limit))
        self._lock = RLock()
        self._sessions: dict[str, _SessionState] = {}
        self._current_session_id: str | None = None
        self._retired_token_hashes: list[str] = []

    def bootstrap(self) -> SessionBootstrap:
        """Return the current usable session or issue a clean replacement."""

        callbacks: list[tuple[str, str]] = []
        with self._lock:
            now = self._clock()
            current = self._sessions.get(self._current_session_id or "")
            if current is not None and current.closing and current.active_jobs > 0:
                # Session-bound stores are process-wide.  Starting a replacement
                # while an old request can still publish results would let that
                # result leak into (or erase) the new session.  Fail fast until
                # the pinned job releases and the invalidation callback clears
                # the old stores.
                raise CoordinatorBusy("session")
            state = self._current_locked(now, callbacks)
            if state is None:
                state = self._new_locked(now)
            result = SessionBootstrap(token=state.token, session=self._view(state))
        self._notify(callbacks)
        return result

    def authenticate(self, token: str, *, touch: bool = True) -> SessionView:
        callbacks: list[tuple[str, str]] = []
        error: InputError | None = None
        view: SessionView | None = None
        with self._lock:
            now = self._clock()
            state = self._find_token_locked(token)
            if state is None:
                error = self._unknown_token_error(token)
            elif self._is_expired(state, now):
                self._expire_locked(state, callbacks)
                error = InputError("TOKEN_EXPIRED", "token", "Local coordinator session expired")
            elif state.closing:
                error = InputError("TOKEN_EXPIRED", "token", "Local coordinator session is closed")
            else:
                if touch:
                    state.idle_expires_at = min(now + self.idle_timeout_seconds, state.absolute_expires_at)
                view = self._view(state)
        self._notify(callbacks)
        if error is not None:
            raise error
        assert view is not None
        return view

    def begin_job(self, token: str) -> SessionJob:
        """Authorize and pin a job so expiry cannot interrupt in-flight work."""

        callbacks: list[tuple[str, str]] = []
        error: InputError | None = None
        session_id: str | None = None
        with self._lock:
            now = self._clock()
            state = self._find_token_locked(token)
            if state is None:
                error = self._unknown_token_error(token)
            elif self._is_expired(state, now):
                self._expire_locked(state, callbacks)
                error = InputError("TOKEN_EXPIRED", "token", "Local coordinator session expired")
            elif state.closing:
                error = InputError("TOKEN_EXPIRED", "token", "Local coordinator session is closing")
            else:
                state.idle_expires_at = min(now + self.idle_timeout_seconds, state.absolute_expires_at)
                state.active_jobs += 1
                session_id = state.session_id
        self._notify(callbacks)
        if error is not None:
            raise error
        assert session_id is not None
        return SessionJob(self, session_id)

    def close(self, token: str) -> None:
        """Close immediately, or defer invalidation until pinned jobs finish."""

        callbacks: list[tuple[str, str]] = []
        error: InputError | None = None
        with self._lock:
            now = self._clock()
            state = self._find_token_locked(token)
            if state is None:
                error = self._unknown_token_error(token)
            elif self._is_expired(state, now):
                self._expire_locked(state, callbacks)
                error = InputError("TOKEN_EXPIRED", "token", "Local coordinator session expired")
            elif not state.closing:
                state.closing = True
                state.close_reason = "closed"
                if state.active_jobs == 0:
                    self._retire_locked(state, callbacks)
        self._notify(callbacks)
        if error is not None:
            raise error

    def _finish_job(self, session_id: str) -> None:
        callbacks: list[tuple[str, str]] = []
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return
            state.active_jobs = max(0, state.active_jobs - 1)
            now = self._clock()
            if self._is_expired(state, now):
                state.closing = True
                state.close_reason = "expired"
            if state.closing and state.active_jobs == 0:
                self._retire_locked(state, callbacks)
        self._notify(callbacks)

    def _current_locked(self, now: float, callbacks: list[tuple[str, str]]) -> _SessionState | None:
        state = self._sessions.get(self._current_session_id or "")
        if state is None or state.closing:
            return None
        if self._is_expired(state, now):
            self._expire_locked(state, callbacks)
            return None
        return state

    def _new_locked(self, now: float) -> _SessionState:
        session_id = f"ses_{secrets.token_urlsafe(18)}"
        state = _SessionState(
            session_id=session_id,
            token=secrets.token_urlsafe(32),
            issued_at=now,
            idle_expires_at=min(now + self.idle_timeout_seconds, now + self.absolute_timeout_seconds),
            absolute_expires_at=now + self.absolute_timeout_seconds,
        )
        self._sessions[session_id] = state
        self._current_session_id = session_id
        return state

    def _find_token_locked(self, token: str) -> _SessionState | None:
        if not isinstance(token, str) or not token:
            return None
        for state in self._sessions.values():
            if secrets.compare_digest(token, state.token):
                return state
        return None

    def _unknown_token_error(self, token: str) -> InputError:
        if isinstance(token, str) and token:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            if any(secrets.compare_digest(digest, item) for item in self._retired_token_hashes):
                return InputError("TOKEN_EXPIRED", "token", "Local coordinator session expired")
        return InputError("TOKEN_REQUIRED", "token", "Local session token is missing or invalid")

    @staticmethod
    def _is_expired(state: _SessionState, now: float) -> bool:
        return now >= state.idle_expires_at or now >= state.absolute_expires_at

    def _expire_locked(self, state: _SessionState, callbacks: list[tuple[str, str]]) -> None:
        state.closing = True
        state.close_reason = "expired"
        if state.active_jobs == 0:
            self._retire_locked(state, callbacks)

    def _retire_locked(self, state: _SessionState, callbacks: list[tuple[str, str]]) -> None:
        if self._sessions.pop(state.session_id, None) is None:
            return
        digest = hashlib.sha256(state.token.encode("utf-8")).hexdigest()
        self._retired_token_hashes.append(digest)
        del self._retired_token_hashes[:-self._retired_token_limit]
        if self._current_session_id == state.session_id:
            self._current_session_id = None
        callbacks.append((state.session_id, state.close_reason))

    def _view(self, state: _SessionState) -> SessionView:
        return SessionView(
            session_id=state.session_id,
            issued_at=state.issued_at,
            idle_expires_at=state.idle_expires_at,
            absolute_expires_at=state.absolute_expires_at,
            idle_timeout_seconds=self.idle_timeout_seconds,
            absolute_timeout_seconds=self.absolute_timeout_seconds,
        )

    def _notify(self, callbacks: list[tuple[str, str]]) -> None:
        if self._on_invalidate is None:
            return
        for session_id, reason in callbacks:
            self._on_invalidate(session_id, reason)


class ExecutionSlots:
    """Independent, fail-fast Codex and Excel execution slots."""

    VALID_SLOTS = frozenset({"codex", "excel"})

    def __init__(self, *, retry_after_seconds: int = 2) -> None:
        self.retry_after_seconds = retry_after_seconds
        self._semaphores = {name: BoundedSemaphore(1) for name in self.VALID_SLOTS}
        self._state_lock = RLock()

    @contextmanager
    def acquire(self, slot: str) -> Iterator[None]:
        semaphore = self._semaphores.get(slot)
        if semaphore is None:
            raise ValueError(f"unknown execution slot: {slot}")
        if not semaphore.acquire(blocking=False):
            raise CoordinatorBusy(slot, self.retry_after_seconds)
        try:
            yield
        finally:
            semaphore.release()

    @contextmanager
    def state(self) -> Iterator[None]:
        """Serialize short in-memory state transitions, never long runner work."""

        with self._state_lock:
            yield


def _is_reparse_point(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return True
    attributes = getattr(stat, "st_file_attributes", 0)
    reparse_flag = getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


class TempWorkspace:
    def __init__(self, manager: TempWorkspaceManager, path: Path) -> None:
        self._manager = manager
        self.path = path

    def heartbeat(self) -> None:
        self._manager.heartbeat(self.path)

    def __fspath__(self) -> str:
        return str(self.path)


class TempWorkspaceManager:
    """Create marked run directories and conservatively reap abandoned ones."""

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        system_temp_root: str | Path | None = None,
        clock: Callable[[], float] = time.time,
        stale_run_seconds: int = DEFAULT_STALE_RUN_SECONDS,
        legacy_stale_seconds: int = DEFAULT_LEGACY_STALE_SECONDS,
        janitor_interval_seconds: int = DEFAULT_JANITOR_INTERVAL_SECONDS,
        cleanup_retries: int = 4,
        cleanup_backoff_seconds: float = 0.05,
        start_janitor: bool = True,
    ) -> None:
        self._clock = clock
        self.stale_run_seconds = int(stale_run_seconds)
        self.legacy_stale_seconds = int(legacy_stale_seconds)
        self.janitor_interval_seconds = int(janitor_interval_seconds)
        self.cleanup_retries = max(1, int(cleanup_retries))
        self.cleanup_backoff_seconds = max(0.0, float(cleanup_backoff_seconds))
        self.system_temp_root = Path(system_temp_root or tempfile.gettempdir()).resolve()
        self.root = Path(root).resolve() if root is not None else self.system_temp_root / "local-data-copilot"
        self._active: set[Path] = set()
        self._lock = RLock()
        self._stop_event = Event()
        self._janitor: Thread | None = None
        if self.root == self.system_temp_root or self.root.parent != self.system_temp_root:
            raise InputError(
                "TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Temporary storage root is outside its safe boundary"
            )
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InputError(
                "TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Could not initialize temporary storage"
            ) from exc
        if _is_reparse_point(self.root):
            raise InputError(
                "TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Temporary storage root is not a regular directory"
            )
        self.cleanup_stale()
        if start_janitor:
            self.start()

    def start(self) -> None:
        with self._lock:
            if self._janitor is not None and self._janitor.is_alive():
                return
            self._stop_event.clear()
            self._janitor = Thread(target=self._janitor_loop, name="coordinator-temp-janitor", daemon=True)
            self._janitor.start()

    def close(self) -> None:
        self._stop_event.set()
        thread = self._janitor
        if thread is not None:
            thread.join(timeout=min(max(self.janitor_interval_seconds, 1), 5))

    @contextmanager
    def workspace(self) -> Iterator[TempWorkspace]:
        path = self._create_workspace()
        workspace = TempWorkspace(self, path)
        try:
            yield workspace
        finally:
            with self._lock:
                self._active.discard(path)
            # Cleanup failure must not replace the operation's result or exception.
            self._remove_tree(path)

    def heartbeat(self, path: str | Path) -> None:
        candidate = Path(path).resolve()
        with self._lock:
            if candidate not in self._active:
                raise ValueError("workspace is not active")
        marker = candidate / _RUN_MARKER_NAME
        try:
            os.utime(marker, (self._clock(), self._clock()))
        except OSError as exc:
            raise InputError(
                "TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Could not update temporary workspace"
            ) from exc

    def cleanup_stale(self) -> dict[str, int]:
        removed_runs = 0
        removed_legacy = 0
        now = self._clock()
        try:
            children = list(self.root.iterdir())
        except OSError:
            children = []
        for child in children:
            if not child.is_dir() or _is_reparse_point(child):
                continue
            with self._lock:
                if child.resolve() in self._active:
                    continue
            if not self._valid_run_marker(child):
                continue
            marker = child / _RUN_MARKER_NAME
            try:
                stale = now - marker.stat().st_mtime > self.stale_run_seconds
            except OSError:
                continue
            if stale and self._remove_tree(child):
                removed_runs += 1
        if self.root.parent == self.system_temp_root and self.root.name == "local-data-copilot":
            removed_legacy = self._cleanup_legacy(now)
        return {"runDirectories": removed_runs, "legacyDirectories": removed_legacy}

    def _create_workspace(self) -> Path:
        for _ in range(4):
            run_id = secrets.token_hex(16)
            path = self.root / f"run_{run_id}"
            try:
                path.mkdir(mode=0o700)
                marker = {
                    "kind": _RUN_MARKER_KIND,
                    "version": 1,
                    "runId": run_id,
                    "createdAt": _utc_iso(self._clock()),
                }
                marker_path = path / _RUN_MARKER_NAME
                marker_path.write_text(
                    json.dumps(marker, sort_keys=True, separators=(",", ":")), encoding="utf-8"
                )
                os.utime(marker_path, (self._clock(), self._clock()))
                with self._lock:
                    self._active.add(path.resolve())
                return path.resolve()
            except FileExistsError:
                continue
            except OSError as exc:
                self._remove_tree(path)
                raise InputError(
                    "TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Could not create temporary workspace"
                ) from exc
        raise InputError("TEMP_STORAGE_UNAVAILABLE", "temporaryWorkspace", "Could not allocate temporary workspace")

    def _valid_run_marker(self, directory: Path) -> bool:
        match = _RUN_NAME.fullmatch(directory.name)
        if match is None or directory.parent.resolve() != self.root:
            return False
        marker_path = directory / _RUN_MARKER_NAME
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(marker, dict)
            and marker.get("kind") == _RUN_MARKER_KIND
            and marker.get("version") == 1
            and marker.get("runId") == match.group(1)
            and set(marker) == {"kind", "version", "runId", "createdAt"}
        )

    def _cleanup_legacy(self, now: float) -> int:
        removed = 0
        try:
            children = list(self.system_temp_root.iterdir())
        except OSError:
            return 0
        for child in children:
            if child == self.root or not child.is_dir() or _LEGACY_NAME.fullmatch(child.name) is None:
                continue
            if _is_reparse_point(child) or not self._legacy_contents_safe(child):
                continue
            try:
                latest_mtime = max(item.stat().st_mtime for item in [child, *child.rglob("*")])
            except OSError:
                continue
            if now - latest_mtime > self.legacy_stale_seconds and self._remove_tree(child):
                removed += 1
        return removed

    @staticmethod
    def _legacy_contents_safe(directory: Path) -> bool:
        try:
            descendants = list(directory.rglob("*"))
        except OSError:
            return False
        if len(descendants) > 256:
            return False
        for item in descendants:
            if _is_reparse_point(item) or item.is_dir():
                return False
            if not item.is_file() or item.suffix.lower() not in _LEGACY_FILE_SUFFIXES:
                return False
        return True

    def _remove_tree(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        allowed_parent = resolved.parent in {self.root, self.system_temp_root}
        if not allowed_parent or resolved in {self.root, self.system_temp_root} or _is_reparse_point(resolved):
            return False
        for attempt in range(self.cleanup_retries):
            try:
                shutil.rmtree(resolved)
                return True
            except FileNotFoundError:
                return True
            except OSError:
                if attempt + 1 < self.cleanup_retries:
                    time.sleep(self.cleanup_backoff_seconds * (2**attempt))
        return not resolved.exists()

    def _janitor_loop(self) -> None:
        while not self._stop_event.wait(self.janitor_interval_seconds):
            self.cleanup_stale()


@contextmanager
def operation_workspace(
    manager: TempWorkspaceManager | None, *, legacy_prefix: str
) -> Iterator[Path]:
    """Yield a marked workspace when injected, preserving legacy direct use.

    Production coordinators inject one shared manager.  The fallback exists for
    standalone library callers and current focused tests during migration.
    """

    if manager is not None:
        with manager.workspace() as workspace:
            yield workspace.path
        return
    with tempfile.TemporaryDirectory(prefix=legacy_prefix) as folder:
        yield Path(folder)


class CoordinatorRuntime:
    """Convenience owner for the three coordinator-wide runtime facilities."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None = None,
        execution_slots: ExecutionSlots | None = None,
        temp_workspaces: TempWorkspaceManager | None = None,
    ) -> None:
        self.sessions = session_manager or SessionManager()
        self.slots = execution_slots or ExecutionSlots()
        self.temp_workspaces = temp_workspaces or TempWorkspaceManager()

    def close(self) -> None:
        self.temp_workspaces.close()
