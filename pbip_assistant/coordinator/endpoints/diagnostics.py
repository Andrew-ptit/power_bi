"""Diagnostics HTTP adapters; shared request authorization stays in server.py."""

from __future__ import annotations

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.endpoints import (
    MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES,
)
import hashlib
import json
from pbip_assistant.pq_typed import build_source_catalog
from pbip_assistant.excel_connector import decode_workbook_export
from pbip_assistant.workbook_fingerprint import workbook_data_fingerprint
from pbip_assistant.coordinator_runtime import operation_workspace
from pbip_assistant.xlsx import profile_workbook


class DiagnosticsEndpoints:
    def _post_pq_v2_step_diagnostics_samples(self) -> None:
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

    def _post_pq_v2_step_diagnostics_runs(self) -> None:
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

    def _post_pq_v2_step_diagnostics_confirms(self) -> None:
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

    def _post_pq_v2_step_diagnostics_cancels(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.pq_typed.cancel_step_diagnostic(request.get("stagingId")))
        return

    def _post_pq_v2_step_diagnostics_cache_inspect(self) -> None:
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

