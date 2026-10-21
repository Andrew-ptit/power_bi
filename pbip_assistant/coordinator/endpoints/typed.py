"""Typed HTTP adapters; shared request authorization stays in server.py."""

from __future__ import annotations

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.endpoints import (
    MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES,
)


class TypedEndpoints:
    def _post_pq_v2_plans(self) -> None:
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

    def _post_pq_v2_revisions(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        if self.app.problem_chains.has_active_chain():
            raise InputError(
                "PQPC_HEAD_MISMATCH", "baseRevisionId",
                "Step edits in an active Problem Chain require a committed history mutation",
            )
        self._json(HTTPStatus.OK, self.app.pq_typed.create_revision(request))
        return

    def _post_pq_v2_repairs(self) -> None:
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

    def _post_pq_v2_previews(self) -> None:
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

    def _post_pq_v2_approvals(self) -> None:
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

    def _post_pq_v2_applies_prepare(self) -> None:
        request = self._read_json(MAX_APPLY_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.pq_typed.prepare_apply(
            request.get("approvalId"), request.get("workbookBase64"), request.get("destination"),
        ))
        return

    def _post_pq_v2_applies_complete(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.pq_typed.complete_apply(
            request.get("applyId"), request.get("readback"),
        ))
        return

