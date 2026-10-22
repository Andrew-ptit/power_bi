"""Developer-only live Excel gate support; never imported by production.

Only the planner is deterministic. Workbook export, Power Query, Custom XML,
preview, approval and write/read-back use the real product paths and Excel.
The driver must verify the disposable workbook's Gate_Run_Id before acting.
"""

from __future__ import annotations

import base64
import binascii
from http import HTTPStatus
import html
import json
import math
import os
from pathlib import Path
import re
import secrets
from threading import Lock
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pbip_assistant.coordinator.server import (
    ExcelAddinApp, ExcelAddinRequestHandler, LocalThreadingHTTPServer,
)
from pbip_assistant.problem_chain import compute_history_hash
from pbip_assistant.errors import InputError
from tests.support.pq_typed import FakeTypedPlanner


MAX_GATE_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_GATE_ARTIFACT_JSON_BYTES = 4 * ((MAX_GATE_ARTIFACT_BYTES + 2) // 3) + 4096


class GateClock:
    def __init__(self) -> None:
        self._lock = Lock()
        self._offset = 0.0
        self._epoch = time.time()
        self._monotonic = time.monotonic()

    def __call__(self) -> float:
        with self._lock:
            return self._epoch + time.monotonic() - self._monotonic + self._offset

    def expire_idle(self) -> None:
        with self._lock:
            self._offset += 1801


class GateContinuationPlanner:
    def propose(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = payload["baseRevision"]
        final = base["finalOutputStepId"]
        names = {step["variableName"] for step in base["steps"]}
        index = 1
        while f"GateFiltered{index}" in names:
            index += 1
        return {
            "summary": "Deterministic live gate: Gross Revenue > 2000.",
            "questions": [], "assumptions": [], "warnings": [],
            "changeReason": "Deterministic live gate continuation",
            "changes": [
                {"type": "insertStep", "afterStepId": final, "stepDraft": {
                    "clientRef": "gate_filter", "variableName": f"GateFiltered{index}",
                    "actionDescription": "Keep Gross Revenue above 2000.",
                    "operationType": "table.filterRows", "inputs": [final],
                    "parameters": {"predicate": {
                        "kind": "compare", "operator": "gt",
                        "left": {"kind": "columnRef", "columnName": "Gross Revenue"},
                        "right": {"kind": "literal", "valueType": "number", "value": 2000},
                    }, "onEvaluationError": "block"},
                }},
                {"type": "setFinalOutput", "stepId": "gate_filter"},
            ],
        }


class CountingRunner:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.calls = 0
        self._lock = Lock()

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.calls += 1
        return self.delegate.apply(request)


_TEXT_FIELDS = frozenset({
    "event", "stage", "status", "code", "action", "method", "path", "planner",
    "runId", "revisionId", "parentRevisionId", "headRevisionId", "historyHash",
    "reviewHash", "sourceFingerprint", "sourceFingerprintBefore",
    "sourceFingerprintAfter", "sourceDataFingerprint", "compiledMHash", "assertion",
})
_NUMBER_FIELDS = frozenset({
    "elapsedMs", "statusCode", "recordedAt", "revisionCount", "resultRows",
    "resultColumns", "stepsCount", "pendingMutationsCount", "cachedResultsCount",
    "previewsCount", "approvalsCount", "appliesCount", "stagingCount",
    "runtimeCalls", "runtimeCallsBefore", "runtimeCallsAfter",
    "injectedCompletionFailuresCount",
})
_BOOLEAN_FIELDS = frozenset({"errorVisible", "busy", "sourceWriteStarted", "completionFaultArmed"})
_LIST_FIELDS = frozenset({"revisions", "sourceFingerprints"})
_OBJECT_FIELDS = frozenset({"state"})


def redact(value: Any, key: str = "") -> Any:
    """Accept a closed metadata schema; generic data/rows/values are discarded."""
    if isinstance(value, dict):
        result = {}
        for name, item in list(value.items())[:80]:
            if name in _TEXT_FIELDS and (item is None or isinstance(item, str)):
                result[name] = item[:160] if isinstance(item, str) else None
            elif name in _NUMBER_FIELDS and (item is None or (
                isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
            )):
                result[name] = item
            elif name in _BOOLEAN_FIELDS and isinstance(item, bool):
                result[name] = item
            elif name in _LIST_FIELDS and isinstance(item, list):
                result[name] = [redact(record) for record in item[:50] if isinstance(record, dict)]
            elif name in _OBJECT_FIELDS and isinstance(item, dict):
                result[name] = redact(item)
        return result
    return None


class GateEvidence:
    def __init__(self, output: Path, run_id: str) -> None:
        self.output, self.run_id = output, run_id
        self._lock = Lock()

    def write(self, event: dict[str, Any]) -> None:
        record = {**redact(event), "recordedAt": time.time(), "runId": self.run_id,
                  "planner": "deterministic"}
        with self._lock:
            with (self.output / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def state_snapshot(app: ExcelAddinApp) -> dict[str, Any]:
    chain_store, typed = app.problem_chains, app.pq_typed
    with chain_store._lock:
        chain = chain_store._committed.get(chain_store._active_chain_id or "")
        result = {
            "headRevisionId": chain.get("headRevisionId") if chain else None,
            "historyHash": compute_history_hash(chain) if chain else None,
            "revisions": [{"revisionId": rev["revisionId"],
                           "parentRevisionId": rev["parentRevisionId"],
                           "reviewHash": rev["reviewHash"], "stepsCount": len(rev["steps"])}
                          for rev in chain["revisions"]] if chain else [],
            "pendingMutationsCount": len(chain_store._pending),
        }
    with typed._lock:
        result.update({
            "cachedResultsCount": len(typed._problem_result_cache),
            "previewsCount": len(typed._preview_records),
            "approvalsCount": len(typed._approvals), "appliesCount": len(typed._applies),
            "stagingCount": int(typed._step_diagnostic_staging is not None),
            "sourceFingerprints": [{"revisionId": item.get("revisionId"),
                                    "sourceFingerprint": item.get("sourceFingerprint", item.get("previewInputFingerprint"))}
                                   for item in list(typed._problem_result_cache.values())[:5]],
        })
    result["runtimeCalls"] = app.pq_previews.runner.calls
    if hasattr(app, "_gate_completion_fault"):
        with app._gate_completion_fault_lock:
            result["completionFaultArmed"] = app._gate_completion_fault["armed"]
            result["injectedCompletionFailuresCount"] = app._gate_completion_fault["count"]
    return result


def create_gate_server(
    output: Path, config: dict[str, Any], *, port: int,
    ssl_context: Any = None, app: ExcelAddinApp | None = None,
) -> LocalThreadingHTTPServer:
    clock = GateClock()
    app = app or ExcelAddinApp(
        pq_typed_runner=FakeTypedPlanner(), problem_chain_planner=GateContinuationPlanner(),
        session_clock=clock, idle_timeout_seconds=1800, absolute_timeout_seconds=28800,
    )
    app.pq_previews.runner = CountingRunner(app.pq_previews.runner)
    evidence = GateEvidence(output, config["runId"])
    app._gate_completion_fault_lock = Lock()
    app._gate_completion_fault = {"armed": False, "count": 0}
    complete_apply = app.pq_typed.complete_apply

    def complete_with_injected_fault(apply_id: Any, readback: Any) -> dict[str, Any]:
        # Developer-only failure occurs after Office.js write/read-back but
        # before the real store can promote staging. HTTP guards still run.
        with app._gate_completion_fault_lock:
            fail = app._gate_completion_fault["armed"]
            if fail:
                app._gate_completion_fault["armed"] = False
                app._gate_completion_fault["count"] += 1
        if fail:
            evidence.write({"event": "faultInjection", "stage": "typed-completion",
                "status": "injected", "code": "GATE_COMPLETION_UNAVAILABLE"})
            raise InputError("GATE_COMPLETION_UNAVAILABLE", "readback",
                "Injected test coordinator completion failure after real Office.js write/read-back")
        return complete_apply(apply_id, readback)

    app.pq_typed.complete_apply = complete_with_injected_fault
    config["baseUrl"] = f"{'https' if ssl_context else 'http'}://localhost:{port}"

    class GateHandler(ExcelAddinRequestHandler):
        def log_message(self, _format: str, *args: Any) -> None:
            pass

        def _gate_authorized(self, *, mutation: bool) -> bool:
            if not self._request_host_allowed():
                return False
            query = parse_qs(urlsplit(self.path).query)
            if not secrets.compare_digest(query.get("gateKey", [""])[0], config["gateKey"]):
                self._error(HTTPStatus.FORBIDDEN, "GATE_AUTH_REQUIRED", "Test gate authentication required")
                return False
            if mutation and self.headers.get("Origin") != config["baseUrl"]:
                self._error(HTTPStatus.FORBIDDEN, "GATE_ORIGIN_BLOCKED", "Test control requires the exact same origin")
                return False
            return True

        def _bytes(self, status: HTTPStatus, payload: bytes, content_type: str, *, headers: Any = None) -> None:
            self._gate_status = int(status)
            path = urlsplit(self.path).path
            if path in {"/", "/taskpane.html"} and status == HTTPStatus.OK and "text/html" in content_type:
                tag = '<script src="/__gate/driver.js?gateKey=' + html.escape(config["gateKey"], quote=True) + '" defer></script>'
                payload = payload.replace(b'<script src="/assets/taskpane.js" defer></script>',
                    ('<script src="/assets/taskpane.js" defer></script>\n  ' + tag).encode("utf-8"))
            elif content_type.startswith("application/json"):
                try:
                    response = json.loads(payload)
                    self._gate_metadata = redact({key: response[key] for key in (
                        "revisionId", "headRevisionId", "historyHash", "sourceFingerprint",
                        "sourceDataFingerprint", "status") if key in response})
                    if isinstance(response.get("error"), dict):
                        self._gate_metadata["code"] = response["error"].get("code")
                except (ValueError, TypeError):
                    pass
            super()._bytes(status, payload, content_type, headers=headers)

        def _serve_get(self) -> None:
            if urlsplit(self.path).path == "/__gate/driver.js":
                if not self._gate_authorized(mutation=False):
                    return
                driver = Path(config["driverPath"])
                if not driver.is_file():
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, "GATE_DRIVER_MISSING", "Test driver is not ready")
                    return
                public = {key: val for key, val in config.items() if key not in {"driverPath", "manifestPath", "outputPath"}}
                payload = ("window.__LIVE_EXCEL_GATE__=" + json.dumps(public) + ";\n").encode("utf-8") + driver.read_bytes()
                self._bytes(HTTPStatus.OK, payload, "text/javascript; charset=utf-8")
                return
            super().do_GET()

        def _serve_post(self) -> None:
            path = urlsplit(self.path).path
            if not path.startswith("/__gate/"):
                super().do_POST()
                return
            if not self._gate_authorized(mutation=True):
                return
            try:
                request = self._read_json(
                    MAX_GATE_ARTIFACT_JSON_BYTES if path == "/__gate/artifact" else 64 * 1024,
                )
                if path == "/__gate/artifact":
                    name = request.get("name")
                    if set(request) != {"name", "workbookBase64"} or not isinstance(name, str) or name not in {"before-result", "after-result"}:
                        self._error(HTTPStatus.BAD_REQUEST, "GATE_ARTIFACT_INVALID", "Unknown test artifact")
                        return
                    encoded = request.get("workbookBase64")
                    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_GATE_ARTIFACT_BYTES + 2) // 3):
                        self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "GATE_ARTIFACT_LIMIT", "Test artifact exceeds the export limit")
                        return
                    try:
                        payload = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error):
                        self._error(HTTPStatus.BAD_REQUEST, "GATE_ARTIFACT_INVALID", "Test artifact must be strict base64")
                        return
                    if len(payload) > MAX_GATE_ARTIFACT_BYTES:
                        self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "GATE_ARTIFACT_LIMIT", "Test artifact exceeds the export limit")
                        return
                    if not payload.startswith(b"PK\x03\x04"):
                        self._error(HTTPStatus.BAD_REQUEST, "GATE_ARTIFACT_INVALID", "Test artifact must be a ZIP workbook export")
                        return
                    target = output / (name + ".xlsx")
                    temporary = output / (".artifact-" + secrets.token_hex(12) + ".tmp")
                    try:
                        temporary.write_bytes(payload)
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                    self._json(HTTPStatus.OK, {"status": "ok"})
                    return
                if path == "/__gate/events":
                    evidence.write({"event": "driver", **redact(request)})
                elif path == "/__gate/control" and request.get("action") in {"snapshot", "expireSession", "failNextCompletion"}:
                    if request["action"] == "expireSession":
                        clock.expire_idle()
                    elif request["action"] == "failNextCompletion":
                        with app._gate_completion_fault_lock:
                            app._gate_completion_fault["armed"] = True
                    evidence.write({"event": "control", "action": request["action"]})
                else:
                    self._error(HTTPStatus.BAD_REQUEST, "GATE_ACTION_INVALID", "Unknown test control action")
                    return
                self._json(HTTPStatus.OK, {"status": "ok", "runId": config["runId"],
                                         "planner": "deterministic", "state": state_snapshot(app)})
            except InputError as exc:
                status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if exc.code == "REQUEST_LIMIT" else HTTPStatus.BAD_REQUEST
                self._error(status, "GATE_REQUEST_INVALID", "Test request exceeds its bounds")
            except (ValueError, UnicodeError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, "GATE_REQUEST_INVALID", type(exc).__name__)
            except OSError:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "GATE_STORAGE_ERROR", "Test artifact could not be stored")

        def _recorded(self, operation: Any) -> None:
            start = time.perf_counter()
            self._gate_status, self._gate_metadata = None, {}
            try:
                operation()
            finally:
                evidence.write({"event": "http", "method": self.command,
                    "path": urlsplit(self.path).path, "statusCode": self._gate_status,
                    "elapsedMs": round((time.perf_counter() - start) * 1000, 3),
                    **self._gate_metadata, "state": state_snapshot(app)})

        def do_GET(self) -> None:
            self._recorded(self._serve_get)

        def do_POST(self) -> None:
            self._recorded(self._serve_post)

    def handler(*args: Any, **kwargs: Any) -> GateHandler:
        return GateHandler(*args, app=app, **kwargs)

    try:
        server = LocalThreadingHTTPServer(("127.0.0.1", port), handler)
    except BaseException:
        app.close()
        raise
    server.app = app
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    config["baseUrl"] = f"{'https' if ssl_context else 'http'}://localhost:{server.server_port}"
    return server
