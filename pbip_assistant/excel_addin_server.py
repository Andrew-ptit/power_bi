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

from .errors import InputError
from .codex_excel import AnalysisRunner, CodexExecRunner, analyze_workbook, codex_available
from .codex_pq import CodexMRunner, MProposalRunner, propose_m
from .excel_connector import (
    MAX_WORKBOOK_BYTES,
    ExcelRunner,
    PowerShellExcelRunner,
    apply_export_to_copy,
    decode_workbook_export,
)
from .excel_plan import MAX_PREVIEW_ROWS, MAX_PROMPT_CHARS, create_fixture_plan, validate_current_plan
from .pq_code_m import PQPreviewStore, advanced_m_policy, advanced_preview_ignored_sheets
from .pq_typed import (
    CodexTypedRunner, DESTINATION_MARKER, TypedDraftRunner, TypedPlanStore,
    build_source_catalog,
)
from .problem_chain import CodexProblemChainPlanner, ContinuationPlanner, ProblemChainStore
from .workbook_fingerprint import workbook_data_fingerprint
from .coordinator_runtime import CoordinatorBusy, CoordinatorRuntime, ExecutionSlots, SessionManager, TempWorkspaceManager
from .coordinator_runtime import operation_workspace
from .step_diagnostic_sampler import SourceProfileCache
from .xlsx import profile_workbook


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
MAX_PLAN_JSON_BYTES = 512 * 1024
MAX_PROBLEM_CHAIN_JSON_BYTES = 4 * 1024 * 1024
MAX_APPLY_JSON_BYTES = 48 * 1024 * 1024
STATIC_ROOT = Path(__file__).with_name("excel_addin")
CODEX_JOB_PATHS = frozenset({
    "/api/excel/analyze", "/api/pq/propose", "/api/pq/v2/plans",
    "/api/pq/v2/problem-chains/problems",
})
EXCEL_JOB_PATHS = frozenset({
    "/api/pq/v2/previews", "/api/pq/run-sheet", "/api/pq/check-source", "/api/excel/apply",
    "/api/pq/v2/problem-chains/cached-results/prepare",
    "/api/pq/v2/step-diagnostics/runs",
})
STATE_PATHS = frozenset({
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
    ) -> None:
        self._session_state_lock = RLock()
        self._state_session_id: str | None = None
        self.codex_cooldown = CodexCooldown()
        workspace_manager = temp_workspaces or TempWorkspaceManager()
        self.runner = runner or PowerShellExcelRunner(workspace_manager=workspace_manager)
        self.codex_runner = codex_runner or CodexExecRunner(workspace_manager=workspace_manager)
        self.pq_codex_runner = pq_codex_runner or CodexMRunner(workspace_manager=workspace_manager)
        pq_script = Path(__file__).resolve().parents[1] / "tools" / "excel_connector" / "Invoke-PQCodeM.ps1"
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
        with self._session_state_lock:
            if self._state_session_id == session_id:
                self._clear_session_state()
                self._state_session_id = None

    def _clear_session_state(self) -> None:
        self.pq_typed.close()
        self.problem_chains.close()
        self.pq_previews.reset()
        self.step_source_profiles.clear()

    def close(self) -> None:
        self.pq_typed.close()
        self.problem_chains.close()
        self.pq_previews.close()
        self.runtime.close()


class ExcelAddinRequestHandler(BaseHTTPRequestHandler):
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
            "/assets/taskpane.css": ("taskpane.css", "text/css; charset=utf-8"),
            "/assets/taskpane.js": ("taskpane.js", "text/javascript; charset=utf-8"),
        }
        target = static_files.get(path)
        if target is None:
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Page not found")
            return
        file_path = STATIC_ROOT / target[0]
        if not file_path.is_file():
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "ASSET_MISSING", "Excel task pane asset is missing")
            return
        self._bytes(HTTPStatus.OK, file_path.read_bytes(), target[1])

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
            if path == "/api/excel/analyze":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                result = analyze_workbook(
                    request.get("prompt"), request.get("workbook"), self.app.codex_runner,
                    request.get("formulaListSeparator", ";"),
                )
                self.app.codex_cooldown.note_success()
                self._json(HTTPStatus.OK, result)
                return
            if path == "/api/pq/propose":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                result = propose_m(
                    request.get("prompt"), request.get("workbook"), request.get("source"),
                    self.app.pq_codex_runner,
                )
                self.app.codex_cooldown.note_success()
                self._json(HTTPStatus.OK, result)
                return
            if path == "/api/pq/v2/plans":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                if self.app.problem_chains.has_active_chain():
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "planId",
                        "Typed plans must continue through the active Problem Chain",
                    )
                plan = self.app.pq_typed.create_plan(
                    request.get("prompt"), request.get("workbook"), request.get("source"),
                )
                if self.app.problem_chains.has_active_chain():
                    self.app.pq_typed.invalidate_plan(plan["planId"])
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "planId",
                        "The Problem Chain became active while this Typed plan was being created",
                    )
                self.app.codex_cooldown.note_success()
                self._json(HTTPStatus.OK, plan)
                return
            if path == "/api/pq/v2/problem-chains/load":
                request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
                document = request.get("document")
                # Loading workbook metadata is a runtime trust boundary.  No
                # preview/approval/apply authority from the previously loaded
                # workbook or head may survive, including when this workbook
                # has no Problem Chain document.
                if isinstance(document, dict) and self.app.pq_typed.can_retain_problem_cache(
                    document.get("chainId"), request.get("workbook"),
                ):
                    self.app.pq_typed.invalidate_runtime()
                else:
                    self.app.pq_typed.close()
                if document is None:
                    self.app.problem_chains.close()
                    self._json(HTTPStatus.OK, {"document": None, "historyHash": None, "dataVersion": 0})
                else:
                    loaded = self.app.problem_chains.load(document)
                    loaded["dataVersion"] = self.app.pq_typed.bind_problem_chain(
                        loaded["document"]["chainId"], request.get("workbook"),
                    )
                    self._json(HTTPStatus.OK, loaded)
                return
            if path == "/api/pq/v2/problem-chains/problems":
                request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
                document = request.get("document")
                typed_plan = None
                source_catalog = None
                if document is None or request.get("creationMode") == "newRoot":
                    typed_plan = self.app.pq_typed.create_plan(
                        request.get("prompt"), request.get("workbook"), request.get("source"),
                        allow_clarification_response=True,
                    )
                    if typed_plan.get("status") == "needsClarification":
                        self.app.codex_cooldown.note_success()
                        self._json(HTTPStatus.OK, typed_plan)
                        return
                    # The initial Typed draft only seeds a candidate.  Until
                    # Custom XML read-back and commit, it grants no runtime
                    # preview/approval authority.
                    self.app.pq_typed.invalidate_plan(typed_plan["planId"])
                else:
                    _, current_sources, _ = build_source_catalog(request.get("workbook"))
                    source_catalog = [
                        {key: value for key, value in source.items() if key != "sampleRows"}
                        for source in current_sources
                    ]
                candidate = self.app.problem_chains.create_problem(
                    document, request.get("baseHistoryHash"), request.get("prompt"),
                    base_revision_id=request.get("baseRevisionId"), typed_plan=typed_plan,
                    source_catalog=source_catalog,
                    creation_mode=request.get("creationMode", "continue"),
                    edit_revision_id=request.get("editRevisionId"),
                )
                self.app.codex_cooldown.note_success()
                self._json(HTTPStatus.OK, candidate)
                return
            if path == "/api/pq/v2/problem-chains/chains/activate":
                request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.problem_chains.activate_chain(
                    request.get("document"), request.get("baseHistoryHash"),
                    request.get("chainId"), request.get("revisionId"),
                ))
                return
            if path == "/api/pq/v2/problem-chains/checkout":
                request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.problem_chains.checkout(
                    request.get("document"), request.get("baseHistoryHash"), request.get("revisionId"),
                ))
                return
            if path == "/api/pq/v2/problem-chains/problems/delete":
                request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.problem_chains.delete_problem(
                    request.get("document"), request.get("baseHistoryHash"), request.get("revisionId"),
                ))
                return
            if path == "/api/pq/v2/problem-chains/revisions":
                request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
                _, current_sources, _ = build_source_catalog(request.get("workbook"))
                source_catalog = [
                    {key: value for key, value in source.items() if key != "sampleRows"}
                    for source in current_sources
                ]
                candidate = self.app.problem_chains.create_manual_revision(
                    request.get("document"), request.get("baseHistoryHash"),
                    request.get("baseRevisionId"), request.get("changes"),
                    request.get("changeReason"), source_catalog=source_catalog,
                )
                self._json(HTTPStatus.OK, candidate)
                return
            if path == "/api/pq/v2/problem-chains/mutations/commit":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                committed = self.app.problem_chains.commit(
                    request.get("mutationId"), request.get("observedHistoryHash"),
                )
                # A committed chain head supersedes every standalone Typed
                # runtime artifact in this panel session.
                self.app.pq_typed.invalidate_runtime()
                if request.get("workbook") is not None:
                    self.app.pq_typed.bind_problem_chain(
                        committed["document"]["chainId"], request.get("workbook"),
                    )
                committed["dataVersion"] = self.app.pq_typed.problem_data_version(committed["document"]["chainId"])
                self._json(HTTPStatus.OK, committed)
                return
            if path == "/api/pq/v2/revisions":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                if self.app.problem_chains.has_active_chain():
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "baseRevisionId",
                        "Step edits in an active Problem Chain require a committed history mutation",
                    )
                self._json(HTTPStatus.OK, self.app.pq_typed.create_revision(request))
                return
            if path == "/api/pq/v2/repairs":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                if self.app.problem_chains.has_active_chain():
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "baseRevisionId",
                        "Repair patches in an active Problem Chain require a committed history mutation",
                    )
                self._json(HTTPStatus.OK, self.app.pq_typed.repair(
                    request.get("baseRevisionId"), request.get("snapshotId"), request.get("error"),
                ))
                return
            if path == "/api/pq/v2/previews":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None and self.app.problem_chains.has_active_chain():
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "revisionId",
                        "Only the committed Problem Chain head can be previewed",
                    )
                if active is not None:
                    parent = active.get("parentRevision")
                    if (
                        parent is not None
                        and active["revision"]["steps"] == parent["steps"]
                        and active["revision"]["finalOutputStepId"] == parent["finalOutputStepId"]
                    ):
                        raise InputError(
                            "PQPC_NO_PIPELINE_CHANGE", "revisionId",
                            "Revision này không thay đổi bước xử lý so với revision cha; hãy tạo yêu cầu cụ thể hơn",
                        )
                    historical = active["revision"].get("validationAtCreation", {})
                    if historical.get("overall") != "passed":
                        issues = historical.get("issues")
                        first = issues[0] if isinstance(issues, list) and issues else {}
                        raise InputError(
                            first.get("code", "PQV2_DEPENDENCY_INVALID"),
                            first.get("path", "revision.validationAtCreation"),
                            first.get("reason", "The committed head is blocked and cannot be previewed"),
                        )
                    self.app.pq_typed.activate_problem_revision(
                        active["planId"], active["revision"], request.get("workbook"),
                    )
                run_version = self.app.pq_typed.bind_problem_chain(
                    active["chainId"], request.get("workbook"),
                ) if active is not None else None
                preview = self.app.pq_typed.preview(
                    request.get("revisionId"), request.get("workbook"), request.get("workbookBase64"),
                    problem_chain_id=active["chainId"] if active is not None else None,
                    run_version=run_version,
                )
                self._json(HTTPStatus.OK, preview)
                return
            if path == "/api/pq/v2/problem-chains/cached-results/prepare":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None or active["historyHash"] != request.get("baseHistoryHash"):
                    raise InputError("PQPC_HEAD_MISMATCH", "baseHistoryHash", "Restore requires the current committed HEAD")
                if request.get("sourceDataChanged") is not False:
                    raise InputError("PQPC_RESULT_CACHE_STALE", "sourceDataChanged", "Changed-source mode requires a new preview")
                self._json(HTTPStatus.OK, self.app.pq_typed.prepare_cached_problem_result(
                    chain_id=active["chainId"], revision_id=request.get("revisionId"),
                    review_hash=active["revision"]["reviewHash"], workbook=request.get("workbook"),
                    workbook_base64=request.get("workbookBase64"),
                    destination_marker=request.get("destinationMarker"),
                ))
                return
            if path in {"/api/pq/v2/problem-chains/cached-results/invalidate", "/api/pq/v2/problem-chains/data-version/increment"}:
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None or active["historyHash"] != request.get("baseHistoryHash"):
                    raise InputError("PQPC_HEAD_MISMATCH", "baseHistoryHash", "Source-version change requires the committed HEAD")
                self.app.pq_typed.bind_problem_chain(active["chainId"], request.get("workbook"))
                version = self.app.pq_typed.increment_problem_data_version(active["chainId"])
                self._json(HTTPStatus.OK, {"status": "versionIncremented", "dataVersion": version})
                return
            if path == "/api/pq/v2/problem-chains/previews/cancel":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None or active["historyHash"] != request.get("baseHistoryHash"):
                    raise InputError("PQPC_HEAD_MISMATCH", "baseHistoryHash", "Cancel requires the committed HEAD")
                self.app.pq_typed.cancel_problem_preview(
                    active["chainId"], request.get("revisionId"), request.get("previewId"),
                )
                self._json(HTTPStatus.OK, {"status": "cancelled"})
                return
            if path == "/api/pq/v2/step-diagnostics/samples":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                workbook = request.get("workbook")
                _, sources, _ = build_source_catalog(workbook)
                requested_source = request.get("source") if isinstance(request.get("source"), dict) else {}
                source_id = request.get("sourceId")
                source = next((item for item in sources if item["sourceId"] == source_id), None)
                if source is None and requested_source:
                    source = next((item for item in sources if (
                        item["sheetName"] == requested_source.get("sheet")
                        and (
                            item["kind"] == "excelTable" and requested_source.get("kind") == "table"
                            and item.get("objectName") == requested_source.get("name")
                            or item["kind"] == "usedRange" and requested_source.get("kind") == "sheet"
                        )
                    )), None)
                if source is None:
                    raise InputError("PQV2_SOURCE_NOT_FOUND", "sourceId", "Diagnostic sample source was not found")
                payload = decode_workbook_export(request.get("workbookBase64"))
                source_fingerprint = workbook_data_fingerprint(payload)
                identity = (
                    str(workbook.get("url", "")) if isinstance(workbook, dict) else "",
                    str(workbook.get("name", "")) if isinstance(workbook, dict) else "",
                )
                chain_id = request.get("chainId")
                data_version = self.app.pq_typed.problem_data_version(chain_id) if isinstance(chain_id, str) else 0
                selected_ids = request.get("selectedColumnIds")
                selected = {
                    item for item in selected_ids if isinstance(item, str)
                } if isinstance(selected_ids, list) else set()
                selected_indices = tuple(
                    column["ordinal"] for column in source["columns"] if column["columnId"] in selected
                )
                workbook_identity = "\u0000".join(identity)
                profile_id = "prof_" + hashlib.sha256(json.dumps(
                    [workbook_identity, source["sourceId"], source_fingerprint, data_version],
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()[:24]
                cached = self.app.step_source_profiles.get_cached(
                    workbook_identity=workbook_identity, source_id=source["sourceId"],
                    source_data_fingerprint=source_fingerprint, data_version=data_version,
                    selected_column_indices=selected_indices,
                )
                if cached is not None:
                    self._json(HTTPStatus.OK, {
                        **cached, "sourceId": source["sourceId"],
                        "columnTypes": [item.get("inferredType", "any") for item in source["columns"]],
                        "profileId": profile_id, "sourceFingerprint": source_fingerprint,
                        "sourceDataFingerprint": source_fingerprint, "cacheHit": True,
                    })
                    return
                with operation_workspace(self.app.runtime.temp_workspaces, legacy_prefix="ldc_step_sample_") as folder:
                    source_path = folder / "source.xlsx"
                    source_path.write_bytes(payload)
                    profile = profile_workbook(
                        source_path, sheet_names=[source["sheetName"]],
                        table_name=source.get("objectName") if source["kind"] == "excelTable" else None,
                        include_preview=True, preview_limit=None,
                    )
                sheet = profile["sheets"][0]
                preview = sheet.get("preview", {})
                sampled, cache_hit = self.app.step_source_profiles.get_or_build(
                    workbook_identity=workbook_identity, source_id=source["sourceId"],
                    source_data_fingerprint=source_fingerprint, data_version=data_version,
                    rows=preview.get("rows", []), column_names=preview.get("columns", []),
                    column_types=[item.get("inferredType", "any") for item in source["columns"]],
                    selected_column_indices=selected_indices,
                )
                self._json(HTTPStatus.OK, {
                    **sampled, "sourceId": source["sourceId"],
                    "columnTypes": [item.get("inferredType", "any") for item in source["columns"]],
                    "profileId": profile_id, "sourceFingerprint": source_fingerprint,
                    "sourceDataFingerprint": source_fingerprint, "cacheHit": cache_hit,
                })
                return
            if path == "/api/pq/v2/step-diagnostics/runs":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None or active["historyHash"] != request.get("baseHistoryHash"):
                    raise InputError("TSD_HEAD_MISMATCH", "baseHistoryHash", "Step diagnostic requires the committed HEAD")
                self.app.pq_typed.activate_problem_revision(
                    active["planId"], active["revision"], request.get("workbook"),
                )
                run_version = self.app.pq_typed.bind_problem_chain(
                    active["chainId"], request.get("workbook"),
                )
                self._json(HTTPStatus.OK, self.app.pq_typed.run_step_diagnostic(
                    request.get("revisionId"), request.get("selectedStepId"),
                    request.get("workbook"), request.get("workbookBase64"),
                    problem_chain_id=active["chainId"], run_version=run_version,
                ))
                return
            if path == "/api/pq/v2/step-diagnostics/confirms":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None or active["historyHash"] != request.get("baseHistoryHash"):
                    raise InputError("TSD_HEAD_MISMATCH", "baseHistoryHash", "Step diagnostic confirmation requires the committed HEAD")
                run_version = self.app.pq_typed.bind_problem_chain(
                    active["chainId"], request.get("workbook"),
                )
                self._json(HTTPStatus.OK, self.app.pq_typed.confirm_step_diagnostic(
                    request.get("stagingId"), request.get("revisionId"), request.get("selectedStepId"),
                    request.get("workbook"), request.get("workbookBase64"),
                    problem_chain_id=active["chainId"], run_version=run_version,
                ))
                return
            if path == "/api/pq/v2/step-diagnostics/cancels":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.pq_typed.cancel_step_diagnostic(request.get("stagingId")))
                return
            if path == "/api/pq/v2/step-diagnostics/cache/inspect":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None or active["historyHash"] != request.get("baseHistoryHash"):
                    raise InputError("TSD_HEAD_MISMATCH", "baseHistoryHash", "Step cache inspection requires the committed HEAD")
                run_version = self.app.pq_typed.bind_problem_chain(
                    active["chainId"], request.get("workbook"),
                )
                self._json(HTTPStatus.OK, self.app.pq_typed.inspect_step_cache(
                    request.get("revisionId"), request.get("selectedStepId"),
                    request.get("workbook"), request.get("workbookBase64"),
                    problem_chain_id=active["chainId"], run_version=run_version,
                ))
                return
            if path == "/api/pq/v2/approvals":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                active = self.app.problem_chains.active_revision(request.get("revisionId"))
                if active is None and self.app.problem_chains.has_active_chain():
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "revisionId",
                        "Only the committed Problem Chain head can be approved",
                    )
                self._json(HTTPStatus.OK, self.app.pq_typed.approve(
                    request.get("revisionId"), request.get("previewId"), request.get("destinationMarker"),
                ))
                return
            if path == "/api/pq/v2/applies/prepare":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.pq_typed.prepare_apply(
                    request.get("approvalId"), request.get("workbookBase64"), request.get("destination"),
                ))
                return
            if path == "/api/pq/v2/applies/complete":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.pq_typed.complete_apply(
                    request.get("applyId"), request.get("readback"),
                ))
                return
            if path == "/api/pq/run-sheet":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                self._json(HTTPStatus.OK, self.app.pq_previews.preview(
                    workbook=request.get("workbook"), selection=request.get("source"),
                    m_code=request.get("mCode"), risk_accepted=request.get("riskAccepted"),
                    risk_policy_id=request.get("riskPolicyId"),
                    workbook_base64=request.get("workbookBase64"), values_for_open_workbook=True,
                    ignored_sheet_names=request.get("ignoredSheetNames"),
                ))
                return
            if path == "/api/pq/check-source":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                expected = request.get("sourceFingerprint")
                if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
                    raise InputError("WORKBOOK_FINGERPRINT_INVALID", "sourceFingerprint", "Run Power Query again before checking the source")
                ignored_sheets = advanced_preview_ignored_sheets(request.get("ignoredSheetNames"))
                current = workbook_data_fingerprint(
                    decode_workbook_export(request.get("workbookBase64")),
                    ignored_sheet_names=ignored_sheets,
                    include_styles=False,
                )
                self._json(HTTPStatus.OK, {"unchanged": current == expected})
                return
            if path in {"/api/pq/preview", "/api/pq/save"}:
                self._error(HTTPStatus.GONE, "PQ_COPY_FLOW_REMOVED", "Reload the task pane; use run-sheet, review PQ_Result, then apply explicitly to the source")
                return
            if path == "/api/excel/plan":
                request = self._read_json(MAX_PLAN_JSON_BYTES)
                self._json(
                    HTTPStatus.OK,
                    create_fixture_plan(request.get("prompt"), request.get("workbook")),
                )
                return
            if path == "/api/excel/apply":
                request = self._read_json(MAX_APPLY_JSON_BYTES)
                plan, workbook = validate_current_plan(
                    prompt=request.get("prompt"),
                    workbook=request.get("workbook"),
                    snapshot_id=request.get("snapshotId"),
                    plan_revision_id=request.get("planRevisionId"),
                    operation_ids=request.get("operationIds"),
                )
                workbook_bytes = decode_workbook_export(request.get("workbookBase64"))
                result = apply_export_to_copy(
                    workbook=workbook,
                    workbook_bytes=workbook_bytes,
                    plan=plan,
                    runner=self.app.runner,
                )
                self._json(HTTPStatus.OK, result)
                return
            self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint not found")
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
        host_header = self.headers.get("Host", "")
        try:
            hostname = urlsplit(f"//{host_header}").hostname
        except ValueError:
            hostname = None
        if hostname not in LOOPBACK_HOSTS:
            self._error(HTTPStatus.MISDIRECTED_REQUEST, "HOST_BLOCKED", "Only loopback hosts are accepted")
            return False
        return True

    def _mutation_allowed(self) -> bool:
        if not self._request_host_allowed():
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                parsed = None
            if parsed is None or parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
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
        value = self.headers.get("Content-Length")
        if value is None:
            raise ValueError("Content-Length is required")
        length = int(value)
        if length < 0 or length > maximum:
            raise InputError("REQUEST_LIMIT", "", f"Request exceeds {maximum} bytes")
        payload = self.rfile.read(length)
        if len(payload) != length:
            raise ValueError("Request body ended early")
        return payload

    def _read_json(self, maximum: int) -> dict[str, Any]:
        value = json.loads(self._read_body(maximum).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

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
    ) -> None:
        self.close_connection = True
        self._json(status, {"error": {"code": code, "detail": detail, "path": path}}, headers=headers)


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
) -> LocalThreadingHTTPServer:
    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("The Excel add-in server may bind only to a loopback address")
    app = ExcelAddinApp(
        runner, codex_runner, pq_runner, pq_codex_runner, pq_typed_runner, problem_chain_planner,
        session_clock=session_clock,
        idle_timeout_seconds=idle_timeout_seconds,
        absolute_timeout_seconds=absolute_timeout_seconds,
        temp_workspaces=temp_workspaces,
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
    repository_root = Path(__file__).resolve().parents[1]
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
