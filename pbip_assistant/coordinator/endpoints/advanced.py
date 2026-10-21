"""Advanced HTTP adapters; shared request authorization stays in server.py."""

from __future__ import annotations

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.endpoints import (
    MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES,
)
from pbip_assistant.excel_connector import decode_workbook_export
from pbip_assistant.pq_code_m import advanced_preview_ignored_sheets
from pbip_assistant.workbook_fingerprint import workbook_data_fingerprint


class AdvancedEndpoints:
    def _post_pq_run_sheet(self) -> None:
        request = self._read_json(MAX_APPLY_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.pq_previews.preview(
            workbook=request.get("workbook"), selection=request.get("source"),
            m_code=request.get("mCode"), risk_accepted=request.get("riskAccepted"),
            risk_policy_id=request.get("riskPolicyId"),
            workbook_base64=request.get("workbookBase64"), values_for_open_workbook=True,
            ignored_sheet_names=request.get("ignoredSheetNames"),
        ))
        return

    def _post_pq_check_source(self) -> None:
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

    def _post_pq_preview(self) -> None:
        self._error(HTTPStatus.GONE, "PQ_COPY_FLOW_REMOVED", "Reload the task pane; use run-sheet, review PQ_Result, then apply explicitly to the source")
        return

