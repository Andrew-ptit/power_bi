"""Run M on an exported temporary workbook; return static values for the open sheet."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import time
from threading import Lock
from typing import Any
from urllib.parse import urlsplit
import zipfile
from xml.etree import ElementTree as ET

from pbip_assistant.codex_pq import selected_source
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator_runtime import TempWorkspaceManager
from pbip_assistant.excel_connector import ExcelRunner, MAX_WORKBOOK_BYTES, decode_workbook_export
from pbip_assistant.excel_plan import local_source_path
from pbip_assistant.workbook_fingerprint import workbook_data_fingerprint


MAX_M_CHARS = 16_000
MAX_RESULT_ROWS = 100_000
MAX_RESULT_COLUMNS = 200
MAX_RESULT_CELLS = 2_000_000
MAX_DIAGNOSTIC_ROWS = 100_000
MAX_DIAGNOSTIC_COLUMNS = 75
MAX_DIAGNOSTIC_CELLS = 1_000_000
MAIN_XML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
STATIC_SHEET = "PQ_Result_Values"
ADVANCED_M_POLICY_ID = "advanced-m-trusted-v1"


def advanced_m_policy() -> dict[str, Any]:
    """Return the server-owned release policy for arbitrary Advanced M."""

    return {
        "policyId": ADVANCED_M_POLICY_ID,
        "mode": "trusted",
        "enabled": True,
        "riskAcknowledgementRequired": True,
        "acknowledgementScope": "workbookPanelSession",
        "externalConnectors": "allowed",
        "previewIsolation": "temporaryWorkbookNotSandbox",
        "applyToSource": "explicitConfirmation",
        "backupPolicy": "none",
        "autoSave": False,
    }


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unlink_temporary(path: Path) -> None:
    """Best-effort cleanup without masking the connector's original error.

    Excel COM can keep a temporary workbook handle briefly after a timeout even
    after its dedicated process has been terminated.
    """

    for attempt in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 19:
                return
            time.sleep(0.1)


def advanced_preview_ignored_sheets(value: Any) -> frozenset[str]:
    if value in (None, []):
        return frozenset()
    if not isinstance(value, list) or len(value) != 1:
        raise InputError("PQ_PREVIEW_SHEET_INVALID", "ignoredSheetNames", "Expected at most one managed preview sheet")
    name = value[0]
    if not isinstance(name, str) or not re.fullmatch(r"PQ_Result(?:_\d+)?", name):
        raise InputError("PQ_PREVIEW_SHEET_INVALID", "ignoredSheetNames[0]", "Preview sheet name is not managed by the add-in")
    return frozenset({name})


def _m_code(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_M_CHARS:
        raise InputError("PQ_CODE_INVALID", "mCode", "M code must be 1–16000 characters")
    return value


def _export(value: Any) -> bytes:
    payload = decode_workbook_export(value)
    with tempfile.TemporaryFile() as stream:
        stream.write(payload)
        stream.seek(0)
        if not zipfile.is_zipfile(stream):
            raise InputError("WORKBOOK_EXPORT_INVALID", "workbookBase64", "Excel export is not a valid ZIP workbook")
        stream.seek(0)
        try:
            with zipfile.ZipFile(stream) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise InputError("WORKBOOK_EXPORT_INVALID", "workbookBase64", "Excel export lacks workbook files")
        except zipfile.BadZipFile as exc:
            raise InputError("WORKBOOK_EXPORT_INVALID", "workbookBase64", "Excel export is a damaged ZIP workbook") from exc
    return payload


def _source_descriptor(snapshot_source: dict[str, Any]) -> dict[str, Any]:
    if "table" in snapshot_source:
        return {"kind": "table", "sheet": snapshot_source["sheet"], "name": snapshot_source["table"]}
    return {"kind": "sheet", "sheet": snapshot_source["sheet"], "headerRow": snapshot_source["headerRow"]}


def _static_values_payload(
    path: Path, result_rows: int, result_columns: int, *,
    max_rows: int = MAX_RESULT_ROWS,
    max_columns: int = MAX_RESULT_COLUMNS,
    max_cells: int = MAX_RESULT_CELLS,
    limit_code: str = "PQ_RESULT_LIMIT",
) -> bytes:
    if (
        result_rows < 0 or result_rows > max_rows
        or result_columns < 1 or result_columns > max_columns
        or (result_rows + 1) * result_columns > max_cells
    ):
        raise InputError(
            limit_code, "result",
            f"Result exceeds {max_rows} rows, {max_columns} columns or {max_cells} cells",
        )
    if not path.is_file() or path.stat().st_size > MAX_WORKBOOK_BYTES:
        raise InputError("PQ_RESULT_LIMIT", "result", "Static result workbook is missing or exceeds 32 MiB")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = {item.filename for item in members}
            if len(names) != len(members) or sum(item.file_size for item in members) > 256 * 1024 * 1024:
                raise InputError("PQ_RESULT_INVALID", "result", "Static result workbook package is invalid or too large")
            if any(
                name.startswith(("xl/externalLinks/", "xl/queries/"))
                or name in {"xl/connections.xml", "xl/vbaProject.bin"}
                for name in names
            ):
                raise InputError("PQ_RESULT_INVALID", "result", "Static result contains external links, queries or macros")
            sheets = [name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
            if len(sheets) != 1 or "xl/workbook.xml" not in names:
                raise InputError("PQ_RESULT_INVALID", "result", "Static result must contain exactly one worksheet")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheet_nodes = workbook.findall(f"{{{MAIN_XML}}}sheets/{{{MAIN_XML}}}sheet")
            if len(sheet_nodes) != 1 or sheet_nodes[0].get("name") != STATIC_SHEET:
                raise InputError("PQ_RESULT_INVALID", "result", "Static result worksheet name does not match")
            row_count = 0
            header_cells = 0
            with archive.open(sheets[0]) as stream:
                for event, element in ET.iterparse(stream, events=("start", "end")):
                    if event == "start" and element.tag == f"{{{MAIN_XML}}}row":
                        row_count += 1
                    elif event == "end":
                        if element.tag == f"{{{MAIN_XML}}}f":
                            raise InputError("PQ_RESULT_INVALID", "result", "Static result unexpectedly contains a formula")
                        if element.tag == f"{{{MAIN_XML}}}c" and row_count == 1:
                            header_cells += 1
                        element.clear()
            if row_count != result_rows + 1 or header_cells != result_columns:
                raise InputError("PQ_RESULT_INVALID", "result", "Static result dimensions differ from Excel read-back")
    except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise InputError("PQ_RESULT_INVALID", "result", "Excel returned an unreadable static result workbook") from exc
    return path.read_bytes()


def _diagnostic_metrics(path: Path, result_rows: int, result_columns: int) -> dict[str, Any]:
    """Measure values-only output without loading the worksheet XML into memory."""

    blank_cells = result_rows * result_columns
    error_cells = 0
    error_samples: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            sheet = next(
                name for name in archive.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            )
            with archive.open(sheet) as stream:
                for event, element in ET.iterparse(stream, events=("end",)):
                    if element.tag != f"{{{MAIN_XML}}}c":
                        if element.tag == f"{{{MAIN_XML}}}row":
                            element.clear()
                        continue
                    reference = element.get("r", "")
                    match = re.fullmatch(r"([A-Z]+)(\d+)", reference)
                    if match is None or int(match.group(2)) <= 1:
                        element.clear()
                        continue
                    column_number = 0
                    for character in match.group(1):
                        column_number = column_number * 26 + ord(character) - 64
                    if column_number > result_columns:
                        element.clear()
                        continue
                    cell_type = element.get("t")
                    value_node = element.find(f"{{{MAIN_XML}}}v")
                    inline_node = element.find(f"{{{MAIN_XML}}}is/{{{MAIN_XML}}}t")
                    value = (
                        inline_node.text if inline_node is not None
                        else value_node.text if value_node is not None
                        else None
                    )
                    if value not in (None, ""):
                        blank_cells -= 1
                    if cell_type == "e":
                        error_cells += 1
                        if len(error_samples) < 5:
                            error_samples.append({
                                "rowOrdinal": int(match.group(2)) - 1,
                                "columnOrdinal": column_number,
                                "error": str(value or "Excel error")[:200],
                            })
                    element.clear()
    except (OSError, StopIteration, zipfile.BadZipFile, ET.ParseError):
        return {
            "metricStatus": "unavailable", "blankCells": None,
            "errorCells": None, "errorSamples": [],
        }
    return {
        "metricStatus": "available", "blankCells": max(blank_cells, 0),
        "errorCells": error_cells, "errorSamples": error_samples,
    }


def _destination(workbook: dict[str, Any]) -> tuple[Path, Path | None]:
    name = workbook.get("name")
    if not isinstance(name, str) or not name.lower().endswith(".xlsx") or Path(name).name != name:
        raise InputError("PQ_WORKBOOK_INVALID", "workbook.name", "Only an open .xlsx workbook is supported")
    url = workbook.get("url")
    if not isinstance(url, str) or not url:
        raise InputError("WORKBOOK_UNSAVED", "workbook.url", "Save the workbook before running Power Query")
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        if not parsed.netloc:
            raise InputError("INVALID_WORKBOOK", "workbook.url", "Remote workbook URL is invalid")
        source = None
    else:
        source = local_source_path(workbook).resolve()
    if source is not None and not source.is_file():
        raise InputError("SOURCE_NOT_FOUND", name, "Saved local source workbook is missing")
    directory = source.parent if source is not None else Path.home() / "Documents" / "LocalDataCopilot"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = directory / f"{Path(name).stem}_PQ_clean_{timestamp}_{secrets.token_hex(3)}.xlsx"
    return target, source


def _open_workbook_name(workbook: Any) -> str:
    """The sheet-write route uses the Office export, never a disk/cloud source path."""
    name = workbook.get("name") if isinstance(workbook, dict) else None
    if not isinstance(name, str) or not name.lower().endswith(".xlsx") or Path(name).name != name:
        raise InputError("PQ_WORKBOOK_INVALID", "workbook.name", "Only an open .xlsx workbook is supported")
    return name


class PQPreviewStore:
    def __init__(self, runner: ExcelRunner, *, workspace_manager: TempWorkspaceManager | None = None) -> None:
        self.runner = runner
        self._workspace_context = workspace_manager.workspace() if workspace_manager is not None else None
        if self._workspace_context is not None:
            self._workspace = self._workspace_context.__enter__()
            self._temp = None
            self._temp_path = self._workspace.path
        else:
            self._workspace = None
            self._temp = tempfile.TemporaryDirectory(prefix="pq-code-m-", ignore_cleanup_errors=True)
            self._temp_path = Path(self._temp.name)
        self._lock = Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        self.reset()
        if self._workspace_context is not None:
            context, self._workspace_context = self._workspace_context, None
            context.__exit__(None, None, None)
        elif self._temp is not None:
            self._temp.cleanup()

    def reset(self) -> None:
        """Discard session-bound previews without destroying the reusable store."""

        with self._lock:
            sessions, self._sessions = self._sessions, {}
        for session in sessions.values():
            path = session.get("path")
            if isinstance(path, Path):
                _unlink_temporary(path)

    def preview_compiled(
        self, *, workbook: Any, sources: Any, m_code: Any, workbook_base64: Any,
        typed_result_source_sheets: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Run compiler-owned M for Typed Steps without exposing a write payload.

        Unlike arbitrary M, this path needs no external-source risk acknowledgement:
        the typed compiler is the only producer and the helper receives only
        workbook-local source descriptors.  The returned values workbook is held by
        the typed coordinator until the user approves the exact preview.
        """

        code = _m_code(m_code)
        if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
            raise InputError("PQV2_SOURCE_NOT_FOUND", "sources", "Typed preview requires 1-20 workbook sources")
        snapshot_sources = []
        helper_sources = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                raise InputError("PQV2_SOURCE_NOT_FOUND", f"sources[{index}]", "Source descriptor is invalid")
            if source.get("kind") == "excelTable":
                selection = {"kind": "table", "sheet": source.get("sheetName"), "name": source.get("objectName")}
            elif source.get("kind") == "usedRange":
                selection = {"kind": "sheet", "sheet": source.get("sheetName")}
            else:
                raise InputError("PQV2_SOURCE_NOT_FOUND", f"sources[{index}].kind", "Typed source kind is invalid")
            _, matched = selected_source(workbook, selection)
            snapshot_sources.append(matched)
            descriptor = _source_descriptor(matched)
            if selection["kind"] == "sheet":
                alias = source.get("runtimeAlias")
                if not isinstance(alias, str) or not re.fullmatch(r"PQ_Input_[a-f0-9]{8}", alias):
                    raise InputError("PQV2_SOURCE_NOT_FOUND", f"sources[{index}].runtimeAlias", "Used-range runtime alias is invalid")
                descriptor["alias"] = alias
            helper_sources.append(descriptor)

        payload = _export(workbook_base64)
        source_fingerprint = workbook_data_fingerprint(
            payload, typed_result_source_sheets=typed_result_source_sheets,
        )
        preview_id = secrets.token_urlsafe(18)
        stage_path = self._temp_path / f"typed_{preview_id}.xlsx"
        static_path = self._temp_path / f"typed_{preview_id}_values.xlsx"
        with stage_path.open("xb") as stream:
            stream.write(payload)
        try:
            runtime = self.runner.apply({
                "version": 1, "workbookPath": str(stage_path),
                "source": helper_sources[0], "sources": helper_sources,
                "mCode": code, "resultWorkbookPath": str(static_path),
            })
            if not isinstance(runtime, dict) or not runtime.get("ok"):
                raise InputError("PQV2_PREVIEW_FAILED", "excel", "Excel did not return a successful typed preview")
            if not isinstance(runtime.get("resultRows"), int) or not isinstance(runtime.get("sourceRows"), int):
                raise InputError("PQ_CONNECTOR_PROTOCOL", "excel", "Excel returned invalid row counts")
            if not isinstance(runtime.get("columns"), list) or not isinstance(runtime.get("rows"), list):
                raise InputError("PQ_CONNECTOR_PROTOCOL", "excel", "Excel returned invalid preview rows")
            result_columns = runtime.get("resultColumns", len(runtime["columns"]))
            static_bytes = _static_values_payload(static_path, runtime["resultRows"], result_columns)
            primary = snapshot_sources[0]
            return {
                "status": "ready_for_typed_approval",
                "sourceRows": runtime["sourceRows"], "resultRows": runtime["resultRows"],
                "resultColumns": result_columns,
                "beforeColumns": primary["headers"], "beforeRows": primary["rows"],
                "afterColumns": runtime["columns"], "afterRows": runtime["rows"],
                "excelVersion": runtime.get("excelVersion"),
                "previewLimited": runtime["resultRows"] > len(runtime["rows"]) or result_columns > len(runtime["columns"]),
                "sourceFingerprint": source_fingerprint,
                "resultWorkbookSheetName": STATIC_SHEET,
                "resultWorkbookBase64": base64.b64encode(static_bytes).decode("ascii"),
            }
        finally:
            _unlink_temporary(stage_path)
            _unlink_temporary(static_path)

    def preview_diagnostic(
        self, *, workbook: Any, sources: Any, m_code: Any, workbook_base64: Any,
        typed_result_source_sheets: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Run a compiler-owned selected-step prefix without creating write authority."""

        code = _m_code(m_code)
        if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
            raise InputError("PQV2_SOURCE_NOT_FOUND", "sources", "Step diagnostic requires 1-20 workbook sources")
        snapshot_sources = []
        helper_sources = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                raise InputError("PQV2_SOURCE_NOT_FOUND", f"sources[{index}]", "Source descriptor is invalid")
            if source.get("kind") == "excelTable":
                selection = {"kind": "table", "sheet": source.get("sheetName"), "name": source.get("objectName")}
            elif source.get("kind") == "usedRange":
                selection = {"kind": "sheet", "sheet": source.get("sheetName")}
            else:
                raise InputError("PQV2_SOURCE_NOT_FOUND", f"sources[{index}].kind", "Typed source kind is invalid")
            _, matched = selected_source(workbook, selection)
            snapshot_sources.append(matched)
            descriptor = _source_descriptor(matched)
            if selection["kind"] == "sheet":
                alias = source.get("runtimeAlias")
                if not isinstance(alias, str) or not re.fullmatch(r"PQ_Input_[a-f0-9]{8}", alias):
                    raise InputError("PQV2_SOURCE_NOT_FOUND", f"sources[{index}].runtimeAlias", "Used-range runtime alias is invalid")
                descriptor["alias"] = alias
            helper_sources.append(descriptor)

        payload = _export(workbook_base64)
        source_fingerprint = workbook_data_fingerprint(
            payload, typed_result_source_sheets=typed_result_source_sheets,
        )
        diagnostic_id = secrets.token_urlsafe(18)
        stage_path = self._temp_path / f"typed_diag_{diagnostic_id}.xlsx"
        static_path = self._temp_path / f"typed_diag_{diagnostic_id}_values.xlsx"
        with stage_path.open("xb") as stream:
            stream.write(payload)
        started = time.monotonic()
        try:
            runtime = self.runner.apply({
                "version": 1, "workbookPath": str(stage_path),
                "source": helper_sources[0], "sources": helper_sources,
                "mCode": code, "resultWorkbookPath": str(static_path),
            })
            if not isinstance(runtime, dict) or not runtime.get("ok"):
                raise InputError("TSD_EXCEL_FAILED", "excel", "Excel did not return a successful step diagnostic")
            if not isinstance(runtime.get("resultRows"), int) or not isinstance(runtime.get("sourceRows"), int):
                raise InputError("PQ_CONNECTOR_PROTOCOL", "excel", "Excel returned invalid row counts")
            if not isinstance(runtime.get("columns"), list) or not isinstance(runtime.get("rows"), list):
                raise InputError("PQ_CONNECTOR_PROTOCOL", "excel", "Excel returned invalid diagnostic rows")
            result_columns = runtime.get("resultColumns", len(runtime["columns"]))
            static_bytes = _static_values_payload(
                static_path, runtime["resultRows"], result_columns,
                max_rows=MAX_DIAGNOSTIC_ROWS,
                max_columns=MAX_DIAGNOSTIC_COLUMNS,
                max_cells=MAX_DIAGNOSTIC_CELLS,
                limit_code="TSD_RESULT_LIMIT",
            )
            metrics = _diagnostic_metrics(static_path, runtime["resultRows"], result_columns)
            encoded = base64.b64encode(static_bytes).decode("ascii")
            return {
                "inputRows": runtime["sourceRows"],
                "outputRows": runtime["resultRows"],
                "outputColumns": result_columns,
                "columns": runtime["columns"], "rows": runtime["rows"],
                "previewLimited": runtime["resultRows"] > len(runtime["rows"]) or result_columns > len(runtime["columns"]),
                "excelVersion": runtime.get("excelVersion"),
                "elapsedMs": max(0, round((time.monotonic() - started) * 1000)),
                "sourceFingerprint": source_fingerprint,
                "resultWorkbookSheetName": STATIC_SHEET,
                "resultWorkbookBase64": encoded,
                **metrics,
            }
        finally:
            _unlink_temporary(stage_path)
            _unlink_temporary(static_path)

    def preview(
        self, *, workbook: Any, selection: Any, m_code: Any,
        risk_accepted: Any, risk_policy_id: Any, workbook_base64: Any,
        values_for_open_workbook: bool = False,
        ignored_sheet_names: Any = None,
    ) -> dict[str, Any]:
        if risk_accepted is not True:
            raise InputError("PQ_RISK_ACK_REQUIRED", "riskAccepted", "Acknowledge external file/web and credential risks before running M")
        if risk_policy_id != ADVANCED_M_POLICY_ID:
            raise InputError(
                "PQ_RISK_POLICY_STALE", "riskPolicyId",
                "Reload the task pane and acknowledge the current Advanced M policy",
            )
        code = _m_code(m_code)
        snapshot, source = selected_source(workbook, selection)
        if values_for_open_workbook:
            _open_workbook_name(workbook)
            output_path, source_path = None, None
        else:
            output_path, source_path = _destination(workbook)
        payload = _export(workbook_base64)
        ignored_sheets = advanced_preview_ignored_sheets(ignored_sheet_names) if values_for_open_workbook else frozenset()
        source_fingerprint = workbook_data_fingerprint(
            payload, ignored_sheet_names=ignored_sheets, include_styles=False,
        ) if values_for_open_workbook else None
        preview_id = secrets.token_urlsafe(18)
        stage_path = self._temp_path / f"{preview_id}.xlsx"
        static_path = self._temp_path / f"{preview_id}_values.xlsx" if values_for_open_workbook else None
        source_hash_before = _digest(source_path.read_bytes()) if source_path is not None else None
        with stage_path.open("xb") as stream:
            stream.write(payload)
        try:
            runner_request = {
                "version": 1, "workbookPath": str(stage_path),
                "source": _source_descriptor(source), "mCode": code,
            }
            if static_path is not None:
                runner_request["resultWorkbookPath"] = str(static_path)
            runtime = self.runner.apply(runner_request)
            if not isinstance(runtime, dict) or not runtime.get("ok"):
                raise InputError("PQ_REFRESH_FAILED", "excel", "Excel did not return a successful Power Query preview")
            if not isinstance(runtime.get("resultRows"), int) or not isinstance(runtime.get("sourceRows"), int):
                raise InputError("PQ_CONNECTOR_PROTOCOL", "excel", "Excel returned invalid row counts")
            if not isinstance(runtime.get("columns"), list) or not isinstance(runtime.get("rows"), list):
                raise InputError("PQ_CONNECTOR_PROTOCOL", "excel", "Excel returned invalid preview rows")
            source_hash_after = _digest(source_path.read_bytes()) if source_path is not None else None
            if source_hash_before != source_hash_after:
                raise InputError("SOURCE_CHANGED", workbook["name"], "Source workbook changed during Power Query preview")
        except Exception:
            _unlink_temporary(stage_path)
            if static_path is not None:
                _unlink_temporary(static_path)
            raise

        result = {
            "status": "excel_preview", "previewId": preview_id,
            "sourceRows": runtime["sourceRows"], "resultRows": runtime["resultRows"],
            "resultColumns": runtime.get("resultColumns", len(runtime["columns"])),
            "beforeColumns": source["headers"], "beforeRows": source["rows"],
            "afterColumns": runtime["columns"], "afterRows": runtime["rows"],
            "excelVersion": runtime.get("excelVersion"),
            "sourceUnchanged": source_hash_before == source_hash_after if source_path is not None else None,
            "previewLimited": runtime["resultRows"] > len(runtime["rows"]) or runtime.get("resultColumns", 0) > len(runtime["columns"]),
        }
        if static_path is not None:
            try:
                static_bytes = _static_values_payload(static_path, runtime["resultRows"], result["resultColumns"])
                result["status"] = "ready_for_open_workbook"
                result["sourceFingerprint"] = source_fingerprint
                result["resultWorkbookSheetName"] = STATIC_SHEET
                result["resultWorkbookBase64"] = base64.b64encode(static_bytes).decode("ascii")
            finally:
                _unlink_temporary(stage_path)
                _unlink_temporary(static_path)
            return result

        session = {
            "path": stage_path, "destination": output_path, "exportHash": _digest(payload),
            "codeHash": _digest(code.encode("utf-8")),
            "sourceSelection": selection, "saved": False,
            "sourceHash": source_hash_before, "sourcePath": source_path,
        }
        with self._lock:
            if len(self._sessions) >= 5:
                oldest_id = next(iter(self._sessions))
                oldest = self._sessions.pop(oldest_id)
                _unlink_temporary(oldest["path"])
            self._sessions[preview_id] = session
        return {**result, "destination": str(output_path), "queryName": runtime.get("queryName"), "resultSheet": runtime.get("resultSheet")}

    def save(
        self, *, preview_id: Any, m_code: Any, selection: Any,
        workbook_base64: Any,
    ) -> dict[str, Any]:
        if not isinstance(preview_id, str):
            raise InputError("PREVIEW_REQUIRED", "previewId", "Run a Power Query preview first")
        code = _m_code(m_code)
        payload = _export(workbook_base64)
        with self._lock:
            session = self._sessions.get(preview_id)
            if session is None or session["saved"]:
                raise InputError("PREVIEW_STALE", "previewId", "Preview is missing or already saved; run again")
            if (
                session["codeHash"] != _digest(code.encode("utf-8"))
                or session["sourceSelection"] != selection
                or session["exportHash"] != _digest(payload)
            ):
                raise InputError("PREVIEW_STALE", "previewId", "Workbook, source or M code changed; preview again")
            source_path = session["sourcePath"]
            if source_path is not None and _digest(source_path.read_bytes()) != session["sourceHash"]:
                raise InputError("PREVIEW_STALE", "workbook", "Saved source workbook changed; preview again")
            target: Path = session["destination"]
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as stream, session["path"].open("rb") as source_stream:
                    shutil.copyfileobj(source_stream, stream, 1024 * 1024)
            except FileExistsError as exc:
                raise InputError("COPY_EXISTS", target.name, "The result file already exists; nothing was overwritten") from exc
            except OSError as exc:
                _unlink_temporary(target)
                raise InputError("COPY_FAILED", target.name, "Could not save the Power Query result copy") from exc
            session["saved"] = True
            _unlink_temporary(session["path"])
        return {"status": "saved_copy", "path": str(target), "sha256": _digest(target.read_bytes())}
