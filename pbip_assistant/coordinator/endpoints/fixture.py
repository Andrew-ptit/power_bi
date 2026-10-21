"""Fixture HTTP adapters; shared request authorization stays in server.py."""

from __future__ import annotations

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.endpoints import (
    MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES,
)
from pbip_assistant.excel_plan import create_fixture_plan, validate_current_plan
from pbip_assistant.excel_connector import decode_workbook_export, apply_export_to_copy


class FixtureEndpoints:
    def _post_excel_plan(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        self._json(
            HTTPStatus.OK,
            create_fixture_plan(request.get("prompt"), request.get("workbook")),
        )
        return

    def _post_excel_apply(self) -> None:
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

