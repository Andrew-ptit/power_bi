"""Safe copy coordinator and Windows Excel helper adapter for W-21."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import secrets
import subprocess
import tempfile
from typing import Any, Protocol

from pbip_assistant.core.resources import repository_path
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator_runtime import TempWorkspaceManager, operation_workspace
from pbip_assistant.excel_plan import REQUIRED_TABLES, helper_operations, local_source_path
from pbip_assistant.xlsx import profile_workbook


MAX_WORKBOOK_BYTES = 32 * 1024 * 1024
DEFAULT_HELPER_TIMEOUT_SECONDS = 120
DEFAULT_CALC_TIMEOUT_SECONDS = 45
HELPER_SCRIPT = repository_path("tools", "excel_connector", "Invoke-ExcelConnector.ps1")


class _WindowsProcessApi:
    """Query and terminate one retained kernel object, never a re-looked-up PID."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows process handles are unavailable")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateProcess.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def open(self, process_id):
        # PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        handle = self.kernel.OpenProcess(0x0001 | 0x1000 | 0x00100000, False, process_id)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def creation_time(self, handle):
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (created.dwHighDateTime << 32) | created.dwLowDateTime

    def image_path(self, handle):
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not self.kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return image.value

    def terminate(self, handle):
        if not self.kernel.TerminateProcess(handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        return True

    def wait(self, handle, milliseconds):
        return self.kernel.WaitForSingleObject(handle, milliseconds)

    def close(self, handle):
        self.kernel.CloseHandle(handle)


class ExcelRunner(Protocol):
    def apply(self, request: dict[str, Any]) -> dict[str, Any]: ...


class PowerShellExcelRunner:
    """Invoke the fixed PowerShell COM helper with a typed JSON request."""

    def __init__(
        self,
        script: str | Path = HELPER_SCRIPT,
        *,
        timeout_seconds: int = DEFAULT_HELPER_TIMEOUT_SECONDS,
        workspace_manager: TempWorkspaceManager | None = None,
    ) -> None:
        self.script = Path(script).resolve()
        self.timeout_seconds = timeout_seconds
        self.workspace_manager = workspace_manager

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.script.is_file():
            raise InputError("CONNECTOR_MISSING", str(self.script), "Excel connector helper script is missing")
        with operation_workspace(self.workspace_manager, legacy_prefix="pbip-excel-request-") as folder:
            request_path = folder / "request.json"
            state_path = folder / "state.json"
            helper_request = {**request, "statePath": str(state_path)}
            request_path.write_text(
                json.dumps(helper_request, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            command = [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
                "-RequestPath",
                str(request_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except FileNotFoundError as exc:
                raise InputError("CONNECTOR_UNAVAILABLE", "powershell.exe", "Windows PowerShell is not available") from exc
            except subprocess.TimeoutExpired as exc:
                self._terminate_created_excel(state_path)
                trace = self._last_trace(exc.stderr)
                detail = "Excel connector exceeded its execution timeout"
                if trace:
                    detail += f"; last stage: {trace}"
                raise InputError("CALC_TIMEOUT", "excel", detail) from exc
            output = completed.stdout.strip()
            try:
                result = json.loads(output) if output else None
            except json.JSONDecodeError as exc:
                self._terminate_created_excel(state_path)
                raise InputError("CONNECTOR_PROTOCOL", "stdout", "Excel connector returned invalid JSON") from exc
            if not isinstance(result, dict):
                self._terminate_created_excel(state_path)
                raise InputError(
                    "CONNECTOR_PROTOCOL",
                    "stdout",
                    f"Excel connector returned no JSON result (exit code {completed.returncode})",
                )
            if completed.returncode != 0 or not result.get("ok"):
                error = result.get("error") if isinstance(result.get("error"), dict) else {}
                stage = str(error.get("stage") or "")
                detail = str(error.get("detail") or "Excel connector failed")
                if stage:
                    detail += f" (stage: {stage})"
                raise InputError(
                    str(error.get("code") or "EXCEL_CONNECTOR_FAILED"),
                    str(error.get("target") or "excel"),
                    detail,
                )
            return result

    @staticmethod
    def _last_trace(stderr: str | bytes | None) -> str:
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if not stderr:
            return ""
        lines = [line.strip() for line in stderr.splitlines() if line.strip().startswith("[w21]")]
        return lines[-1][5:].strip()[:160] if lines else ""

    @staticmethod
    def _terminate_created_excel(state_path: Path) -> None:
        """Fail closed unless helper ownership and kernel process identity agree.

        The helper records proof only after excluding all pre-existing Excel
        PIDs. Holding the queried process HANDLE through termination avoids PID
        reuse between identity verification and the termination request.
        """
        handle, api = None, None
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            if not isinstance(state, dict) or state.get("excelOwned") is not True:
                return
            process_id = state.get("excelPid")
            creation = state.get("excelCreationFileTime")
            if (type(process_id) is not int or not 0 < process_id < 2**32
                    or not isinstance(creation, str) or not creation.isascii() or not creation.isdecimal()
                    or not 0 < len(creation) <= 20 or not 0 < int(creation) < 2**64):
                return
            api = _WindowsProcessApi()
            handle = api.open(process_id)
            if not handle or api.creation_time(handle) != int(creation):
                return
            image = api.image_path(handle)
            if not isinstance(image, str) or PureWindowsPath(image).name.casefold() != "excel.exe":
                return
            if api.terminate(handle):
                api.wait(handle, 2000)
        except (OSError, ValueError, TypeError):
            return
        finally:
            if handle is not None and api is not None:
                try:
                    api.close(handle)
                except OSError:
                    pass


def decode_workbook_export(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise InputError("WORKBOOK_EXPORT_REQUIRED", "workbookBase64", "Workbook export is missing")
    if len(value) > ((MAX_WORKBOOK_BYTES + 2) // 3) * 4 + 8:
        raise InputError("WORKBOOK_LIMIT", "workbookBase64", "Workbook export exceeds the 32 MiB W-21 limit")
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InputError("WORKBOOK_EXPORT_INVALID", "workbookBase64", "Workbook export is not valid base64") from exc
    if not payload or len(payload) > MAX_WORKBOOK_BYTES:
        raise InputError("WORKBOOK_LIMIT", "workbookBase64", "Workbook export is empty or exceeds 32 MiB")
    if not payload.startswith(b"PK\x03\x04"):
        raise InputError("WORKBOOK_EXPORT_INVALID", "workbookBase64", "Export is not an .xlsx ZIP package")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_export_schema(path: Path) -> dict[str, Any]:
    try:
        profile = profile_workbook(path, include_preview=True, preview_limit=20)
    except (InputError, OSError, ValueError) as exc:
        raise InputError("WORKBOOK_EXPORT_INVALID", path.name, "Exported workbook could not be parsed") from exc
    tables: dict[str, list[str]] = {}
    for sheet in profile.get("sheets", []):
        for table in sheet.get("tables", []):
            tables[table["name"]] = list(table.get("columns", []))
    for table_name, required in REQUIRED_TABLES.items():
        missing = [column for column in required if column not in tables.get(table_name, [])]
        if missing:
            raise InputError(
                "SCHEMA_MISMATCH",
                table_name,
                f"Exported workbook is missing table or columns: {', '.join(missing)}",
            )
    return profile


def _validate_export_matches_approved(profile: dict[str, Any], workbook: dict[str, Any]) -> None:
    """Block apply when the exported workbook differs from the reviewed preview."""

    actual: dict[tuple[str, str], dict[str, Any]] = {}
    for sheet in profile.get("sheets", []):
        preview_rows = sheet.get("preview", {}).get("rows", [])
        for table in sheet.get("tables", []):
            actual[(sheet["name"], table["name"])] = {
                "headers": table.get("columns", []),
                "rows": preview_rows,
            }
    for approved in workbook.get("tables", []):
        key = (approved["sheet"], approved["name"])
        exported = actual.get(key)
        if exported is None:
            raise InputError("SOURCE_CHANGED", approved["name"], "Reviewed table is missing from the workbook export")
        if exported["headers"] != approved["headers"] or exported["rows"] != approved["rows"]:
            raise InputError(
                "SOURCE_CHANGED",
                approved["name"],
                "Workbook data or schema changed after preview; analyze and approve a new revision",
            )


def _default_copy_path(source: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(2)
    return source.with_name(f"{source.stem}_AI_copy_{timestamp}_{suffix}.xlsx")


def _close_number(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-8
    return left == right


def reconcile_runtime(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("rows")
    preview = plan.get("preview") or {}
    expected_rows = preview.get("afterRows")
    columns = preview.get("afterColumns")
    if not isinstance(rows, list) or not isinstance(expected_rows, list) or not isinstance(columns, list):
        return {"matched": False, "reason": "Runtime or simulated result is incomplete"}
    expected = [dict(zip(columns, row, strict=True)) for row in expected_rows]
    if len(rows) != len(expected):
        return {"matched": False, "reason": f"Row count differs: Excel={len(rows)}, expected={len(expected)}"}
    mismatches: list[dict[str, Any]] = []
    for index, (actual, wanted) in enumerate(zip(rows, expected, strict=True), start=1):
        if not isinstance(actual, dict):
            mismatches.append({"row": index, "column": "*", "reason": "Runtime row is invalid"})
            continue
        for column, expected_value in wanted.items():
            if not _close_number(actual.get(column), expected_value):
                mismatches.append({
                    "row": index,
                    "column": column,
                    "expected": expected_value,
                    "actual": actual.get(column),
                })
    return {"matched": not mismatches, "mismatches": mismatches[:20]}


def apply_export_to_copy(
    *,
    workbook: dict[str, Any],
    workbook_bytes: bytes,
    plan: dict[str, Any],
    runner: ExcelRunner,
    copy_path_factory: Callable[[Path], Path] = _default_copy_path,
) -> dict[str, Any]:
    """Create a non-overwriting copy and apply the fixed operations to it."""

    source = local_source_path(workbook).resolve()
    if not source.is_file():
        raise InputError("SOURCE_NOT_FOUND", source.name, "Saved source workbook no longer exists")
    with tempfile.TemporaryDirectory(prefix="pbip-excel-validate-") as validation_folder:
        validation_path = Path(validation_folder) / "export.xlsx"
        validation_path.write_bytes(workbook_bytes)
        export_profile = _validate_export_schema(validation_path)
        _validate_export_matches_approved(export_profile, workbook)
    source_hash_before = _sha256(source)
    copy_path = copy_path_factory(source).resolve()
    if copy_path.parent != source.parent or copy_path.suffix.lower() != ".xlsx" or copy_path == source:
        raise InputError("DESTINATION_UNSAFE", copy_path.name, "Copy must be a new .xlsx beside the source workbook")

    try:
        with copy_path.open("xb") as stream:
            stream.write(workbook_bytes)
    except FileExistsError as exc:
        raise InputError("COPY_EXISTS", copy_path.name, "Copy destination already exists; no file was overwritten") from exc
    except OSError as exc:
        raise InputError("COPY_FAILED", copy_path.name, "Could not create workbook copy beside the source") from exc

    copy_hash_before = _sha256(copy_path)
    helper_request = {
        "version": 1,
        "workbookPath": str(copy_path),
        "operations": helper_operations(),
        "resultTable": "SalesTable",
        "keyColumn": "SaleID",
        "calculationTimeoutSeconds": DEFAULT_CALC_TIMEOUT_SECONDS,
    }
    runtime: dict[str, Any] | None = None
    runner_error: Exception | None = None
    try:
        runtime = runner.apply(helper_request)
    except Exception as exc:  # preserve the connector error after checking source integrity
        runner_error = exc
    source_hash_after = _sha256(source)
    if source_hash_after != source_hash_before:
        raise InputError("SOURCE_CHANGED", source.name, "Source workbook bytes changed during copy apply")
    if runner_error is not None:
        raise runner_error
    assert runtime is not None

    runtime_errors = runtime.get("formulaErrors")
    if runtime_errors:
        raise InputError("FORMULA_RUNTIME_ERROR", copy_path.name, "Excel returned one or more formula errors in the copy")
    reconciliation = reconcile_runtime(runtime, plan)
    status = "excel_runtime_verified" if runtime.get("calculationState") == "done" and reconciliation["matched"] else "runtime_failed"
    return {
        "status": status,
        "copy": {
            "name": copy_path.name,
            "path": str(copy_path),
            "sha256BeforeApply": copy_hash_before,
            "sha256AfterApply": _sha256(copy_path),
            "bytes": copy_path.stat().st_size,
        },
        "source": {"name": source.name, "sha256Unchanged": True},
        "runtime": runtime,
        "reconciliation": reconciliation,
    }
