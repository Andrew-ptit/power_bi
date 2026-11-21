"""Step-diagnostic use cases: context derivation, runtime call and projection.

`TypedPlanStore` keeps the lock, the single staging slot, the diagnostic cache
and every guard that decides whether a staging may be promoted. This service
sequences those authority calls: it derives the cache context, runs the isolated
preview, rejects an oversized staging and assembles the public payload. It never
mutates store state itself and never takes the store lock, so the staging/cache
transitions stay atomic in one owner.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import TYPE_CHECKING, Any

from pbip_assistant.errors import InputError
from pbip_assistant.excel_connector import decode_workbook_export
from pbip_assistant.powerquery.typed.compiler import compile_m_to_step, diagnostic_step_cache_keys
from pbip_assistant.powerquery.typed.model import MAX_STEP_DIAGNOSTIC_STAGING_BYTES, _random_id
from pbip_assistant.workbook_fingerprint import workbook_data_fingerprint

if TYPE_CHECKING:  # the store owns the state; this module only drives it
    from pbip_assistant.powerquery.typed.store import TypedPlanStore


HIDDEN_DIAGNOSTIC_FIELDS = frozenset({
    "resultWorkbookBase64", "resultWorkbookSheetName", "sourceSheetNames",
    "sourceFingerprint", "workbookKey", "problemChainId", "reviewHash",
})


def public_step_diagnostic(value: dict[str, Any]) -> dict[str, Any]:
    """Drop the payload and the binding identity from a staging or cache entry."""
    return deepcopy({key: item for key, item in value.items() if key not in HIDDEN_DIAGNOSTIC_FIELDS})


class StepDiagnosticService:
    """Sequence one step-diagnostic use case at a time against store authority."""

    def __init__(self, store: TypedPlanStore) -> None:
        self._store = store

    def run(
        self, revision_id: Any, selected_step_id: Any, workbook: Any,
        workbook_base64: Any, *, problem_chain_id: Any, run_version: Any,
    ) -> dict[str, Any]:
        context = self._context(
            revision_id, selected_step_id, workbook, workbook_base64,
            problem_chain_id, run_version,
        )
        running = {
            "stagingId": _random_id("stage"), "revisionId": revision_id,
            "selectedStepId": selected_step_id, "runVersion": run_version,
            "stepCacheKey": context["stepCacheKey"], "paramsHash": context["paramsHash"],
            "inputVersion": context["inputVersion"], "status": "running",
            "problemChainId": problem_chain_id,
        }
        self._store._step_diagnostic_begin(running)
        try:
            runtime = self._store.previews.preview_diagnostic(
                workbook=workbook, sources=context["runtimeSources"],
                m_code=context["compiledM"], workbook_base64=workbook_base64,
                typed_result_source_sheets=context["sourceSheetNames"],
            )
            encoded = runtime["resultWorkbookBase64"]
            if len(encoded.encode("ascii")) > MAX_STEP_DIAGNOSTIC_STAGING_BYTES:
                raise InputError("TSD_STAGING_LIMIT", "result", "Step diagnostic staging exceeds 48 MiB")
            ready = {
                **running, "status": "ready", "reviewHash": context["public"]["revision"]["reviewHash"],
                "workbookKey": context["workbookKey"],
                "sourceFingerprint": context["sourceFingerprint"],
                "sourceSheetNames": context["sourceSheetNames"],
                "compiledMHash": context["compiledMHash"],
                "inputRows": runtime["inputRows"], "outputRows": runtime["outputRows"],
                "outputColumns": runtime["outputColumns"],
                "blankCells": runtime["blankCells"], "errorCells": runtime["errorCells"],
                "errorSamples": runtime["errorSamples"], "metricStatus": runtime["metricStatus"],
                "columns": runtime["columns"], "rows": runtime["rows"],
                "previewLimited": runtime["previewLimited"], "elapsedMs": runtime["elapsedMs"],
                "excelVersion": runtime.get("excelVersion"),
                "resultWorkbookBase64": encoded,
                "resultWorkbookSheetName": runtime["resultWorkbookSheetName"],
            }
            self._store._step_diagnostic_commit(running, ready, problem_chain_id, run_version)
            return public_step_diagnostic(ready)
        except Exception:
            self._store._step_diagnostic_abort(running)
            raise

    def confirm(
        self, staging_id: Any, revision_id: Any, selected_step_id: Any,
        workbook: Any, workbook_base64: Any, *, problem_chain_id: Any,
        run_version: Any,
    ) -> dict[str, Any]:
        context = self._context(
            revision_id, selected_step_id, workbook, workbook_base64,
            problem_chain_id, run_version,
        )
        return self._store._step_diagnostic_promote(
            staging_id, revision_id=revision_id, selected_step_id=selected_step_id,
            problem_chain_id=problem_chain_id, run_version=run_version, context=context,
        )

    def cancel(self, staging_id: Any) -> dict[str, Any]:
        return self._store._step_diagnostic_release(staging_id)

    def inspect(
        self, revision_id: Any, selected_step_id: Any, workbook: Any,
        workbook_base64: Any, *, problem_chain_id: Any, run_version: Any,
    ) -> dict[str, Any]:
        context = self._context(
            revision_id, selected_step_id, workbook, workbook_base64,
            problem_chain_id, run_version,
        )
        kind, reason, entry = self._store._step_diagnostic_lookup(
            problem_chain_id, run_version, selected_step_id, context,
        )
        if kind == "hit":
            public = public_step_diagnostic(entry)
            public["status"] = "hit"
            return public
        if kind == "stale":
            return {"status": "stale", "reason": reason}
        return {"status": "miss"}

    def _context(
        self, revision_id: Any, selected_step_id: Any, workbook: Any,
        workbook_base64: Any, problem_chain_id: Any, run_version: Any,
    ) -> dict[str, Any]:
        """Derive the cache context after the store's HEAD/binding guards pass."""
        record, public, workbook_key = self._store._step_diagnostic_authority(
            revision_id, selected_step_id, problem_chain_id, workbook, run_version,
        )
        compiled, closure = compile_m_to_step(public, selected_step_id)
        selected = closure[-1]
        output_columns = selected.get("outputContract", {}).get("columns")
        if not isinstance(output_columns, list) or not output_columns:
            raise InputError("TSD_GRAPH_INVALID", "selectedStepId", "Selected step does not have a table output contract")
        if len(output_columns) > 75:
            raise InputError("TSD_RESULT_LIMIT", "selectedStepId", "Selected step output exceeds 75 columns")
        used_source_ids = {
            step["operation"]["parameters"]["sourceId"]
            for step in closure if step["operation"]["type"].startswith("source.")
        }
        runtime_sources = [
            source for source in record["sourcesInternal"]
            if source["sourceId"] in used_source_ids
        ]
        if not runtime_sources:
            raise InputError("TSD_GRAPH_INVALID", "selectedStepId", "Selected step has no workbook source dependency")
        source_sheet_names = frozenset(source["sheetName"] for source in runtime_sources)
        source_fingerprint = workbook_data_fingerprint(
            decode_workbook_export(workbook_base64),
            typed_result_source_sheets=source_sheet_names,
        )
        key_parts = diagnostic_step_cache_keys(public, source_fingerprint, selected_step_id)[selected_step_id]
        return {
            "record": record, "public": public, "compiledM": compiled,
            "compiledMHash": "sha256:" + hashlib.sha256(compiled.encode("utf-8")).hexdigest(),
            "runtimeSources": runtime_sources, "sourceSheetNames": source_sheet_names,
            "sourceFingerprint": source_fingerprint, "workbookKey": workbook_key, **key_parts,
        }
