"""Loopback HTTPS coordinator for the W-21 Excel task pane spike."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import struct
from threading import RLock
import time
from typing import Any
from urllib.parse import urlsplit
import zlib

from pbip_assistant.coordinator.endpoints import MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES
from pbip_assistant.coordinator.endpoints.analysis import AnalysisEndpoints
from pbip_assistant.coordinator.endpoints.advanced import AdvancedEndpoints
from pbip_assistant.coordinator.endpoints.typed import TypedEndpoints
from pbip_assistant.coordinator.endpoints.history import HistoryEndpoints
from pbip_assistant.coordinator.endpoints.diagnostics import DiagnosticsEndpoints
from pbip_assistant.coordinator.endpoints.fixture import FixtureEndpoints
from pbip_assistant.coordinator.endpoints.assistant import AssistantEndpoints
from pbip_assistant.coordinator.endpoints.preparation import PreparationEndpoints
from pbip_assistant.sources.preparation.store import PreparationStore
from pbip_assistant.sources.preparation.evidence import PhysicalBudget
from pbip_assistant.excel.folder_picker import pick_folder
from pbip_assistant.sources.assistant_session import AssistantSessionStore, _STAGES as ASSISTANT_STAGES
from pbip_assistant.core import http_io
from pbip_assistant.core.resources import repository_path, package_path
from pbip_assistant.errors import InputError
from pbip_assistant.codex_excel import AnalysisRunner, CodexExecRunner, analyze_workbook, codex_available
from pbip_assistant.codex_pq import CodexMRunner, MProposalRunner, propose_m
from pbip_assistant.excel_connector import (
    MAX_WORKBOOK_BYTES,
    ExcelRunner,
    PowerShellExcelRunner,
    apply_export_to_copy,
    decode_workbook_export,
)
from pbip_assistant.excel_plan import MAX_PREVIEW_ROWS, MAX_PROMPT_CHARS, create_fixture_plan, validate_current_plan
from pbip_assistant.pq_code_m import PQPreviewStore, advanced_m_policy, advanced_preview_ignored_sheets
from pbip_assistant.pq_typed import (
    CodexTypedRunner, DESTINATION_MARKER, TypedDraftRunner, TypedPlanStore,
    build_source_catalog,
)
from pbip_assistant.problem_chain import CodexProblemChainPlanner, ContinuationPlanner, ProblemChainStore
from pbip_assistant.workbook_fingerprint import workbook_data_fingerprint
from pbip_assistant.coordinator_runtime import CoordinatorBusy, CoordinatorRuntime, ExecutionSlots, SessionManager, TempWorkspaceManager
from pbip_assistant.coordinator_runtime import operation_workspace
from pbip_assistant.step_diagnostic_sampler import SourceProfileCache
from pbip_assistant.xlsx import profile_workbook


DEFAULT_ADDIN_PORTS = tuple(range(3079, 3071, -1))
DEFAULT_CATALOG_MANIFEST = Path(r"C:\AddinManifests\manifest.xml")
_LOCALHOST_URL = re.compile(r"https://localhost:\d+(?P<path>/[^\"<\s]*)?")
_CHANNEL = re.compile(r"^[0-9a-f]{24}$")


def _runtime_manifest_text(template: str, port: int, channel: str) -> str:
    """Render one Excel manifest for a bound coordinator instance."""
    if port not in range(1, 65536):
        raise ValueError("Coordinator port must be between 1 and 65535")
    if _CHANNEL.fullmatch(channel) is None:
        raise ValueError("Runtime channel must be a 96-bit lowercase hex value")
    matches = list(_LOCALHOST_URL.finditer(template))
    if not matches:
        raise ValueError("Manifest contains no localhost coordinator URLs")

    def replace(match: re.Match[str]) -> str:
        path = match.group("path") or ""
        path = re.sub(r"\?channel=[0-9a-f]+$", "", path)
        suffix = f"?channel={channel}" if path else ""
        return f"https://localhost:{port}{path}{suffix}"

    rendered = _LOCALHOST_URL.sub(replace, template)
    # Parse before touching either source-of-truth copy.
    from xml.etree import ElementTree
    ElementTree.fromstring(rendered)
    return rendered


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def sync_runtime_manifest(
    source_manifest: Path, catalog_manifest: Path, port: int, channel: str,
) -> str:
    """Atomically keep repository/catalog manifests byte-identical."""
    if not source_manifest.is_file():
        raise FileNotFoundError(f"Manifest not found: {source_manifest}")
    if not catalog_manifest.parent.is_dir():
        raise FileNotFoundError(f"Add-in catalog directory not found: {catalog_manifest.parent}")
    source_before = source_manifest.read_bytes()
    catalog_existed = catalog_manifest.is_file()
    catalog_before = catalog_manifest.read_bytes() if catalog_existed else None
    rendered = _runtime_manifest_text(source_before.decode("utf-8-sig"), port, channel)
    payload = rendered.encode("utf-8")
    try:
        _atomic_write(catalog_manifest, payload)
        _atomic_write(source_manifest, payload)
        if source_manifest.read_bytes() != catalog_manifest.read_bytes():
            raise OSError("Repository and catalog manifests differ after synchronization")
    except Exception:
        # Best-effort rollback prevents a half-updated catalog from pointing at
        # a coordinator that was never started.
        try:
            _atomic_write(source_manifest, source_before)
            if catalog_existed and catalog_before is not None:
                _atomic_write(catalog_manifest, catalog_before)
            elif not catalog_existed:
                catalog_manifest.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def create_server_from_port_pool(
    host: str, ports: tuple[int, ...], **kwargs: Any,
) -> LocalThreadingHTTPServer:
    """Bind the first available port in caller order; never queue or reuse."""
    last_error: OSError | None = None
    for port in ports:
        try:
            return create_server(host, port, **kwargs)
        except OSError as exc:
            if getattr(exc, "winerror", None) != 10048 and getattr(exc, "errno", None) not in {48, 98, 10048}:
                raise
            last_error = exc
    detail = ", ".join(str(port) for port in ports)
    raise OSError(f"No coordinator port is available in the configured pool: {detail}") from last_error


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
STATIC_ROOT = package_path("excel_addin")
ASSISTANT_PATHS = frozenset("/api/assistant/" + suffix for suffix in (
    "session", "ingest", "understand", "plan-draft", "branches", "freeze",
    "approvals", "apply", "record", "state", "reset",
))
CODEX_JOB_PATHS = frozenset({
    "/api/excel/analyze", "/api/pq/propose", "/api/pq/v2/plans",
    "/api/pq/v2/problem-chains/problems",
    "/api/assistant/plan-draft",
})
EXCEL_JOB_PATHS = frozenset({
    "/api/pq/v2/previews", "/api/pq/run-sheet", "/api/pq/check-source", "/api/excel/apply",
    "/api/pq/v2/problem-chains/cached-results/prepare",
    "/api/pq/v2/step-diagnostics/runs",
})
PREPARATION_PATHS = frozenset("/api/preparation/" + action for action in (
    "preservation-begin", "preservation-chunk", "preservation-finish",
"attach", "detach", "state", "browse", "inventory", "source-snapshot", "source-set", "scan", "answer", "preview", "review-import", "pick-folder",
    "direct-begin", "direct-write-ready", "direct-complete", "packages", "approve", "begin", "image-begin", "image-chunk", "image-finish", "write-ready", "complete", "undo", "redo", "restore-complete",
))
EXCEL_JOB_PATHS = EXCEL_JOB_PATHS | frozenset("/api/preparation/" + action for action in (
    "direct-begin", "direct-write-ready", "direct-complete", "approve", "begin", "image-begin", "image-chunk", "image-finish", "write-ready", "complete", "undo", "redo", "restore-complete",
))
STATE_PATHS = ASSISTANT_PATHS | PREPARATION_PATHS | frozenset({
    "/api/pq/v2/revisions", "/api/pq/v2/repairs", "/api/pq/v2/approvals",
    "/api/pq/v2/applies/prepare", "/api/pq/v2/applies/complete", "/api/excel/plan",
    "/api/pq/v2/problem-chains/load", "/api/pq/v2/problem-chains/checkout",
    "/api/pq/v2/problem-chains/chains/activate",
    "/api/pq/v2/problem-chains/revisions",
    "/api/pq/v2/problem-chains/problems/delete",
    "/api/pq/v2/problem-chains/mutations/commit",
    "/api/pq/v2/problem-chains/cached-results/invalidate",
    "/api/pq/v2/problem-chains/data-version/increment",
    "/api/pq/v2/problem-chains/previews/cancel",
    "/api/pq/v2/step-diagnostics/confirms",
    "/api/pq/v2/step-diagnostics/cancels",
    "/api/pq/v2/step-diagnostics/cache/inspect",
})


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _icon_png(size: int) -> bytes:
    """Return an icon PNG accepted by Office manifests, using static asset if available."""

    icon_file = STATIC_ROOT / f"icon-{size}.png"
    if icon_file.is_file():
        return icon_file.read_bytes()
    width = height = size
    pixel = bytes((13, 107, 80, 255))
    scanlines = b"".join(b"\x00" + pixel * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + _png_chunk(b"IEND", b"")
    )


ICON_PNGS = {size: _icon_png(size) for size in (16, 32, 64, 80)}


class CodexCooldown:
    """Bound repeat CLI calls after an upstream 429; never replay a request."""

    def __init__(self, *, clock: Any = time.monotonic) -> None:
        self._clock = clock
        self._lock = RLock()
        self._until = 0.0
        self._last_failure = 0.0
        self._failures = 0

    def remaining_seconds(self) -> int:
        with self._lock:
            return max(0, math.ceil(self._until - self._clock()))

    def check(self) -> None:
        remaining = self.remaining_seconds()
        if remaining:
            raise InputError(
                "CODEX_RATE_LIMITED", "codex",
                f"Codex returned 429. Wait at least {remaining} seconds before trying again; "
                "the coordinator did not resend your request.",
            )

    def note_rate_limit(self) -> int:
        with self._lock:
            now = self._clock()
            if now - self._last_failure > 1800:
                self._failures = 0
            self._failures += 1
            self._last_failure = now
            self._until = max(self._until, now + min(60 * 2 ** min(self._failures - 1, 4), 900))
            return max(1, math.ceil(self._until - now))

    def note_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._until = 0.0


class ExcelAddinApp:
    def __init__(
        self, runner: ExcelRunner | None = None, codex_runner: AnalysisRunner | None = None,
        pq_runner: ExcelRunner | None = None, pq_codex_runner: MProposalRunner | None = None,
        pq_typed_runner: TypedDraftRunner | None = None,
        problem_chain_planner: ContinuationPlanner | None = None,
        session_clock: Any = time.time,
        idle_timeout_seconds: int = 1800,
        absolute_timeout_seconds: int = 28800,
        temp_workspaces: TempWorkspaceManager | None = None,
        assistant_plan_runner: Any = None,
        preparation_write_enabled: bool = True,
    ) -> None:
        self._session_state_lock = RLock()
        self._state_session_id: str | None = None
        self.codex_cooldown = CodexCooldown()
        workspace_manager = temp_workspaces or TempWorkspaceManager()
        self.runner = runner or PowerShellExcelRunner(workspace_manager=workspace_manager)
        self.codex_runner = codex_runner or CodexExecRunner(workspace_manager=workspace_manager)
        self.pq_codex_runner = pq_codex_runner or CodexMRunner(workspace_manager=workspace_manager)
        pq_script = repository_path("tools", "excel_connector", "Invoke-PQCodeM.ps1")
        self.pq_previews = PQPreviewStore(
            pq_runner or PowerShellExcelRunner(
                pq_script, timeout_seconds=180, workspace_manager=workspace_manager,
            ),
            workspace_manager=workspace_manager,
        )
        self.pq_typed = TypedPlanStore(
            pq_typed_runner or CodexTypedRunner(workspace_manager=workspace_manager), self.pq_previews,
        )
        self.problem_chains = ProblemChainStore(
            problem_chain_planner or CodexProblemChainPlanner(workspace_manager=workspace_manager),
        )
        self.step_source_profiles = SourceProfileCache(max_entries=20)
        self.assistant = AssistantSessionStore()
        self.physical_budget = PhysicalBudget()
        self.preparation = PreparationStore(clock=session_clock, start_janitor=True, workspace_manager=workspace_manager, native_write_enabled=preparation_write_enabled, backup_enabled=False)
        self.preparation._physical_budget = self.physical_budget
        if self.preparation._journal is not None:
            self.preparation._journal._physical_budget = self.physical_budget
        self.preparation_evidence = None
        self.preparation._evidence = self.preparation_evidence
        self.folder_picker = pick_folder
        self.assistant_plan_runner = assistant_plan_runner
        sessions = SessionManager(
            idle_timeout_seconds=idle_timeout_seconds,
            absolute_timeout_seconds=absolute_timeout_seconds,
            clock=session_clock,
            on_invalidate=self._session_invalidated,
        )
        self.runtime = CoordinatorRuntime(
            session_manager=sessions, execution_slots=ExecutionSlots(), temp_workspaces=workspace_manager,
        )

    def bootstrap(self) -> dict[str, Any]:
        issued = self.runtime.sessions.bootstrap()
        with self._session_state_lock:
            if issued.session.session_id != self._state_session_id:
                self._clear_session_state()
                self._state_session_id = issued.session.session_id
        return issued.public_dict()

    def _session_invalidated(self, session_id: str, _reason: str) -> None:
        self.preparation.transport_closed(session_id, _reason)
        if self.preparation_evidence is not None:
            self.preparation_evidence.transport_closed(session_id, _reason)
        with self._session_state_lock:
            if self._state_session_id == session_id:
                self._clear_session_state()
                self._state_session_id = None

    def _clear_session_state(self) -> None:
        self.assistant.reset()
        self.pq_typed.close()
        self.problem_chains.close()
        self.pq_previews.reset()
        self.step_source_profiles.clear()

    def close(self) -> None:
        if self.preparation_evidence is not None:
            self.preparation_evidence.close()
        self.preparation.close()
        self.assistant.close()
        self.pq_typed.close()
        self.problem_chains.close()
        self.pq_previews.close()
        self.runtime.close()


class ExcelAddinRequestHandler(
    AnalysisEndpoints, AdvancedEndpoints, TypedEndpoints, HistoryEndpoints, DiagnosticsEndpoints, FixtureEndpoints, AssistantEndpoints, PreparationEndpoints,
    BaseHTTPRequestHandler,
):
    protocol_version = "HTTP/1.1"
    server_version = "PBIPExcelAddin/0.1"

    def __init__(self, *args: Any, app: ExcelAddinApp, **kwargs: Any) -> None:
        self.app = app
        super().__init__(*args, **kwargs)

    def parse_request(self) -> bool:
        if hasattr(self, "raw_requestline") and self.raw_requestline.startswith(b"{}"):
            self.raw_requestline = self.raw_requestline[2:]
        return super().parse_request()

    def log_message(self, format: str, *args: Any) -> None:
        # Never log prompt, workbook bytes, names, paths, or raw cell values.
        method = self.command if isinstance(self.command, str) else "INVALID"
        request_path = urlsplit(self.path).path if isinstance(self.path, str) else "-"
        print(f"[excel-addin] {method} {request_path}")

    def do_GET(self) -> None:
        if not self._request_host_allowed():
            return
        path = urlsplit(self.path).path
        if path == "/api/bootstrap":
            try:
                session = self.app.bootstrap()
            except CoordinatorBusy as exc:
                self._error(
                    HTTPStatus.TOO_MANY_REQUESTS, exc.code, exc.detail, path=exc.path,
                    headers={"Retry-After": str(exc.retry_after_seconds)},
                )
                return
            self._json(HTTPStatus.OK, {
                **session,
                "scope": "W-21 connector spike",
                "limits": {
                    "promptChars": MAX_PROMPT_CHARS,
                    "previewRows": MAX_PREVIEW_ROWS,
                    "workbookBytes": MAX_WORKBOOK_BYTES,
                },
                "capabilities": {
                    "officeJsRead": True,
                    "preparationReadV1": True,
                    "preparationBackups": self.app.preparation._backup_enabled,
                    "preparationFolderPicker": True,
                    "preparationV1": self.app.preparation._native_write_enabled,
                    "preparationNativeQualification": "user_pending",
                    "localXlsx": True,
                    "sourceWrite": False,
                    "copyApply": True,
                    "excelCalculate": True,
                    "generalAiPlanner": False,
                    "codexAnalysis": codex_available() or not isinstance(self.app.codex_runner, CodexExecRunner),
                    "pqCodeM": True,
                    "advancedMPolicy": advanced_m_policy(),
                    "pqOpenWorkbookWrite": True,
                    "pqTypedStepsV2": True,
                    "pqTypedStepDiagnostics": True,
                    "pqTypedDestinationMarker": DESTINATION_MARKER,
                    "pqProblemChainV1": True,
                    "pqProblemChainNamespace": "urn:local-data-copilot:pq-problem-chain:v1",
                    "mcpServer": False,
                    "assistantFlowV2": True,
                    "assistantFlowStages": list(ASSISTANT_STAGES),
                },
            })
            return
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok", "scope": "w21_excel_taskpane"})
            return
        if path in {f"/assets/icon-{size}.png" for size in ICON_PNGS}:
            size = int(path.removeprefix("/assets/icon-").removesuffix(".png"))
            self._bytes(HTTPStatus.OK, ICON_PNGS[size], "image/png")
            return
        static_files = {
            "/": ("taskpane.html", "text/html; charset=utf-8"),
            "/taskpane.html": ("taskpane.html", "text/html; charset=utf-8"),
            "/commands.html": ("commands.html", "text/html; charset=utf-8"),
            "/model_dialog.html": ("model_dialog.html", "text/html; charset=utf-8"),
            "/assets/taskpane.css": ("taskpane.css", "text/css; charset=utf-8"),
            "/assets/taskpane.js": ("taskpane.js", "text/javascript; charset=utf-8"),
"/assets/taskpane_core.js": ("taskpane_core.js", "text/javascript; charset=utf-8"),
            "/assets/taskpane_flow.js": ("taskpane_flow.js", "text/javascript; charset=utf-8"),
            "/assets/taskpane_workspace.js": ("taskpane_workspace.js", "text/javascript; charset=utf-8"),
            "/assets/taskpane_problem_chain.js": ("taskpane_problem_chain.js", "text/javascript; charset=utf-8"),
            "/assets/taskpane_typed_pq.js": ("taskpane_typed_pq.js", "text/javascript; charset=utf-8"),
            "/assets/preparation_runtime.js": ("preparation_runtime.js", "text/javascript; charset=utf-8"),
            "/assets/preparation_bridge.js": ("preparation_bridge.js", "text/javascript; charset=utf-8"),
            "/assets/preparation_session.js": ("preparation_session.js", "text/javascript; charset=utf-8"),
            "/assets/preparation_controller.js": ("preparation_controller.js", "text/javascript; charset=utf-8"),
            "/assets/assistant_entry.js": ("assistant_entry.js", "text/javascript; charset=utf-8"),
"/assets/assistant_model_diagram.js": ("assistant_model_diagram.js", "text/javascript; charset=utf-8"),
"/assets/assistant_understand.js": ("assistant_understand.js", "text/javascript; charset=utf-8"),
"/assets/model_dialog.html": ("model_dialog.html", "text/html; charset=utf-8"),
"/assets/model_dialog.js": ("model_dialog.js", "text/javascript; charset=utf-8"),
"/assets/assistant_browser.js": ("assistant_browser.js", "text/javascript; charset=utf-8"),
            "/assets/assistant_custom_xml.js": ("assistant_custom_xml.js", "text/javascript; charset=utf-8"),
        }
        target = static_files.get(path)
        if target is None:
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Page not found")
            return
        file_path = STATIC_ROOT / target[0]
        if not file_path.is_file():
            if path == "/assets/assistant_custom_xml.js":
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Assistant helper is not available")
                return
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "ASSET_MISSING", "Excel task pane asset is missing")
            return
        self._bytes(HTTPStatus.OK, file_path.read_bytes(), target[1])

    # Host/origin -> session -> execution slot -> state lock stays centralized.
    # Body limits and operation-specific guards belong to individual handlers.
    POST_ENDPOINTS = {
        **{path: "_post_preparation" for path in PREPARATION_PATHS},
        '/api/assistant/session': '_post_assistant_session',
        '/api/assistant/ingest': '_post_assistant_ingest',
        '/api/assistant/understand': '_post_assistant_understand',
        '/api/assistant/plan-draft': '_post_assistant_plan_draft',
        '/api/assistant/branches': '_post_assistant_branches',
        '/api/assistant/freeze': '_post_assistant_freeze',
        '/api/assistant/approvals': '_post_assistant_approvals',
        '/api/assistant/apply': '_post_assistant_apply',
        '/api/assistant/record': '_post_assistant_record',
        '/api/assistant/state': '_post_assistant_state',
        '/api/assistant/reset': '_post_assistant_reset',
        '/api/excel/analyze': '_post_excel_analyze',
        '/api/pq/propose': '_post_pq_propose',
        '/api/pq/v2/plans': '_post_pq_v2_plans',
        '/api/pq/v2/problem-chains/load': '_post_pq_v2_problem_chains_load',
        '/api/pq/v2/problem-chains/problems': '_post_pq_v2_problem_chains_problems',
        '/api/pq/v2/problem-chains/chains/activate': '_post_pq_v2_problem_chains_chains_activate',
        '/api/pq/v2/problem-chains/checkout': '_post_pq_v2_problem_chains_checkout',
        '/api/pq/v2/problem-chains/problems/delete': '_post_pq_v2_problem_chains_problems_delete',
        '/api/pq/v2/problem-chains/revisions': '_post_pq_v2_problem_chains_revisions',
        '/api/pq/v2/problem-chains/mutations/commit': '_post_pq_v2_problem_chains_mutations_commit',
        '/api/pq/v2/revisions': '_post_pq_v2_revisions',
        '/api/pq/v2/repairs': '_post_pq_v2_repairs',
        '/api/pq/v2/previews': '_post_pq_v2_previews',
        '/api/pq/v2/problem-chains/cached-results/prepare': '_post_pq_v2_problem_chains_cached_results_prepare',
        '/api/pq/v2/problem-chains/cached-results/invalidate': '_post_pq_v2_problem_chains_cached_results_invalidate',
        '/api/pq/v2/problem-chains/data-version/increment': '_post_pq_v2_problem_chains_cached_results_invalidate',
        '/api/pq/v2/problem-chains/previews/cancel': '_post_pq_v2_problem_chains_previews_cancel',
        '/api/pq/v2/step-diagnostics/samples': '_post_pq_v2_step_diagnostics_samples',
        '/api/pq/v2/step-diagnostics/runs': '_post_pq_v2_step_diagnostics_runs',
        '/api/pq/v2/step-diagnostics/confirms': '_post_pq_v2_step_diagnostics_confirms',
        '/api/pq/v2/step-diagnostics/cancels': '_post_pq_v2_step_diagnostics_cancels',
        '/api/pq/v2/step-diagnostics/cache/inspect': '_post_pq_v2_step_diagnostics_cache_inspect',
        '/api/pq/v2/approvals': '_post_pq_v2_approvals',
        '/api/pq/v2/applies/prepare': '_post_pq_v2_applies_prepare',
        '/api/pq/v2/applies/complete': '_post_pq_v2_applies_complete',
        '/api/pq/run-sheet': '_post_pq_run_sheet',
        '/api/pq/check-source': '_post_pq_check_source',
        '/api/pq/preview': '_post_pq_preview',
        '/api/pq/save': '_post_pq_preview',
        '/api/excel/plan': '_post_excel_plan',
        '/api/excel/apply': '_post_excel_apply',
    }

    def do_POST(self) -> None:
        if not self._mutation_allowed():
            return
        path = urlsplit(self.path).path
        token = self.headers.get("X-Local-Token", "")
        if path == "/api/session/close":
            try:
                if self.headers.get("Content-Length"):
                    self._read_body(MAX_PLAN_JSON_BYTES)
                self.close_connection = True
                self.app.runtime.sessions.close(token)
                self._json(HTTPStatus.OK, {"status": "closed"})
            except InputError as exc:
                self._input_error(exc)
            return
        job = None
        execution_context = nullcontext()
        state_context = nullcontext()
        execution_entered = False
        state_entered = False
        try:
            job = self.app.runtime.sessions.begin_job(token)
            if path in CODEX_JOB_PATHS:
                self.app.codex_cooldown.check()
                execution_context = self.app.runtime.slots.acquire("codex")
            elif path in EXCEL_JOB_PATHS:
                execution_context = self.app.runtime.slots.acquire("excel")
            if path in STATE_PATHS:
                state_context = self.app.runtime.slots.state()
            execution_context.__enter__()
            execution_entered = True
            state_context.__enter__()
            state_entered = True
            handler_name = self.POST_ENDPOINTS.get(path)
            if handler_name is None:
                self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")
                return
            getattr(self, handler_name)()
        except CoordinatorBusy as exc:
            self._error(
                HTTPStatus.TOO_MANY_REQUESTS, exc.code, exc.detail, path=exc.path,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        except InputError as exc:
            if path in CODEX_JOB_PATHS and exc.code == "CODEX_RATE_LIMITED":
                if self.app.codex_cooldown.remaining_seconds() == 0:
                    self.app.codex_cooldown.note_rate_limit()
            self._input_error(exc)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", str(exc))
        except OSError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "IO_ERROR", "Local workbook operation failed")
        finally:
            if state_entered:
                state_context.__exit__(None, None, None)
            if execution_entered:
                execution_context.__exit__(None, None, None)
            if job is not None:
                job.release()


    def _request_host_allowed(self) -> bool:
        if not http_io.host_header_is_loopback(self.headers.get("Host", "")):
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "HOST_BLOCKED", "Only loopback hosts are accepted")
            return False
        return True

    def _mutation_allowed(self) -> bool:
        if not self._request_host_allowed():
            return False
        origin = self.headers.get("Origin")
        if origin:
            if not http_io.origin_is_loopback(origin, schemes=frozenset({"http", "https"})):
                self._error(HTTPStatus.FORBIDDEN, "ORIGIN_BLOCKED", "Cross-origin request blocked")
                return False
        return True

    def _input_error(self, exc: InputError) -> None:
        statuses = {
            "TOKEN_EXPIRED": HTTPStatus.UNAUTHORIZED,
            "TOKEN_REQUIRED": HTTPStatus.FORBIDDEN,
            "CODEX_SCHEMA_INVALID": HTTPStatus.INTERNAL_SERVER_ERROR,
            "CODEX_AUTH_REQUIRED": HTTPStatus.SERVICE_UNAVAILABLE,
            "CODEX_RATE_LIMITED": HTTPStatus.TOO_MANY_REQUESTS,
            "CODEX_TIMEOUT": HTTPStatus.GATEWAY_TIMEOUT,
            "CODEX_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
            "CODEX_FAILED": HTTPStatus.BAD_GATEWAY,
            "TEMP_STORAGE_UNAVAILABLE": HTTPStatus.INSUFFICIENT_STORAGE,
            "TSD_RESULT_LIMIT": HTTPStatus.UNPROCESSABLE_ENTITY,
            "TSD_STAGING_LIMIT": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            "TSD_METRICS_UNAVAILABLE": HTTPStatus.UNPROCESSABLE_ENTITY,
            "TSD_EXCEL_FAILED": HTTPStatus.BAD_GATEWAY,
        }
        conflicts = {
            "PLAN_STALE", "PREVIEW_STALE", "COPY_EXISTS", "SOURCE_CHANGED",
            "PQ_RISK_POLICY_STALE", "PQV2_SOURCE_CHANGED", "PQV2_PREVIEW_STALE",
            "PQV2_CLARIFICATION_REQUIRED",
            "PQV2_REVISION_STALE", "PQV2_PATCH_STALE", "PQV2_APPROVAL_MISMATCH",
            "PQV2_APPROVAL_USED",
            "PQPC_HISTORY_CONFLICT", "PQPC_HEAD_MISMATCH", "PQPC_BRANCHING_NOT_AVAILABLE",
            "PQPC_BRANCH_INTENT_REQUIRED", "PQPC_EDIT_BASE_MISMATCH",
            "PQPC_EDIT_ROOT_UNSUPPORTED", "PQPC_EDIT_TARGET_INVALID",
            "PQPC_DELETE_ROOT_UNSUPPORTED",
            "PQPC_NO_PIPELINE_CHANGE", "PQPC_CLARIFICATION_REQUIRED",
            "PQPC_SOURCE_SCHEMA_CHANGED", "PQPC_MUTATION_NOT_COMMITTED",
            "TSD_HEAD_MISMATCH", "TSD_SOURCE_STALE", "TSD_STAGING_STALE",
        }
        status = statuses.get(exc.code, HTTPStatus.CONFLICT if exc.code in conflicts else HTTPStatus.BAD_REQUEST)
        headers = (
            {"Retry-After": str(self.app.codex_cooldown.remaining_seconds())}
            if exc.code == "CODEX_RATE_LIMITED" and self.app.codex_cooldown.remaining_seconds()
            else None
        )
        self._error(status, exc.code, exc.detail, path=exc.path, headers=headers)

    def _read_body(self, maximum: int) -> bytes:
        return http_io.read_body(self.headers, self.rfile, maximum)

    def _read_json(self, maximum: int) -> dict[str, Any]:
        return http_io.read_json(self.headers, self.rfile, maximum)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://appsforoffice.microsoft.com "
            "https://officeapis.public.onecdn.static.microsoft; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _bytes(
        self, status: HTTPStatus, payload: bytes, content_type: str,
        *, headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self._security_headers()
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # A task pane unload sends /api/session/close with keepalive and may
            # tear down its socket before the small acknowledgement is written.
            # The close mutation has already completed, so this is an expected
            # client disconnect rather than a coordinator failure.
            self.close_connection = True

    def _json(
        self, status: HTTPStatus, value: dict[str, Any],
        *, headers: dict[str, str] | None = None,
    ) -> None:
        self._bytes(
            status,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
            headers=headers,
        )

    def _error(
        self, status: HTTPStatus, code: str, detail: str, *, path: str = "",
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.close_connection = True
        payload = {"code": code, "detail": detail, "path": path}
        if extra:
            payload.update(extra)
        self._json(status, {"error": payload}, headers=headers)


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR allows two live coordinators on the same port, causing
    # requests to reach an old Python process while new static assets are served.
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def server_close(self) -> None:
        try:
            if hasattr(self, "app"):
                self.app.close()
        finally:
            super().server_close()


def create_server(
    host: str = "127.0.0.1",
    port: int = 3000,
    *,
    runner: ExcelRunner | None = None,
    codex_runner: AnalysisRunner | None = None,
    pq_runner: ExcelRunner | None = None,
    pq_codex_runner: MProposalRunner | None = None,
    pq_typed_runner: TypedDraftRunner | None = None,
    problem_chain_planner: ContinuationPlanner | None = None,
    ssl_context: ssl.SSLContext | None = None,
    session_clock: Any = time.time,
    idle_timeout_seconds: int = 1800,
    absolute_timeout_seconds: int = 28800,
    temp_workspaces: TempWorkspaceManager | None = None,
    assistant_plan_runner: Any = None,
    preparation_write_enabled: bool = True,
) -> LocalThreadingHTTPServer:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("The Excel add-in server may bind only to a loopback address")
    app = ExcelAddinApp(
        runner, codex_runner, pq_runner, pq_codex_runner, pq_typed_runner, problem_chain_planner,
        session_clock=session_clock,
        idle_timeout_seconds=idle_timeout_seconds,
        absolute_timeout_seconds=absolute_timeout_seconds,
        temp_workspaces=temp_workspaces,
        assistant_plan_runner=assistant_plan_runner,
        preparation_write_enabled=preparation_write_enabled,
    )

    def handler(*args: Any, **kwargs: Any) -> ExcelAddinRequestHandler:
        return ExcelAddinRequestHandler(*args, app=app, **kwargs)

    try:
        server = LocalThreadingHTTPServer((host, port), handler)
    except OSError:
        app.close()
        raise
    server.app = app  # type: ignore[attr-defined]
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    return server


def _tls_context(certfile: Path, keyfile: Path) -> ssl.SSLContext:
    if not certfile.is_file() or not keyfile.is_file():
        raise FileNotFoundError("Local HTTPS certificate/key not found; run tools/excel_addin/setup-dev.ps1")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile, keyfile)
    return context


def main() -> int:
    repository_root = repository_path()
    addin_root = repository_root / "tools" / "excel_addin"
    default_cert_dir = addin_root / ".certs"
    parser = argparse.ArgumentParser(description="W-21 local Excel task pane coordinator")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "::1"])
    parser.add_argument(
        "--port", type=int, default=None,
        help="Explicit port override; default chooses the first free port from 3079 down to 3072",
    )
    parser.add_argument("--certfile", type=Path, default=default_cert_dir / "localhost.pem")
    parser.add_argument("--keyfile", type=Path, default=default_cert_dir / "localhost.key")
    parser.add_argument("--manifest", type=Path, default=addin_root / "manifest.xml")
    parser.add_argument("--catalog-manifest", type=Path, default=DEFAULT_CATALOG_MANIFEST)
    parser.add_argument("--http-dev", action="store_true", help="HTTP only for unit/debug; Excel sideload requires HTTPS")
    args = parser.parse_args()
    if args.port is not None and args.port not in DEFAULT_ADDIN_PORTS:
        parser.error("--port must be one of 3079, 3078, 3077, 3076, 3075, 3074, 3073 or 3072")
    context = None if args.http_dev else _tls_context(args.certfile, args.keyfile)
    ports = (args.port,) if args.port is not None else DEFAULT_ADDIN_PORTS
    server = create_server_from_port_pool(args.host, ports, ssl_context=context)
    address, port = server.server_address[:2]
    channel = secrets.token_hex(12)
    try:
        manifest_hash = sync_runtime_manifest(
            args.manifest.resolve(), args.catalog_manifest.resolve(), port, channel,
        )
    except Exception:
        server.server_close()
        raise
    scheme = "http" if context is None else "https"
    display_host = f"[{address}]" if ":" in address else "localhost"
    print(f"Excel task pane: {scheme}://{display_host}:{port}/taskpane.html?channel={channel}")
    print(f"Runtime port: {port} (pool 3079 -> 3072); channel: {channel}")
    print(f"Manifest synchronized: {manifest_hash}")
    print("Close and reopen the Excel task pane after every coordinator restart so Excel reads the new manifest URL.")
    print("Local-only coordinator. Advanced M source apply requires explicit confirmation and never auto-saves. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Excel task pane server.")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
