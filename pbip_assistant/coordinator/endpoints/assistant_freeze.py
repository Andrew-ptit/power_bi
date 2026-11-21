"""Wave E owns Assistant freeze, approval and result handoff endpoints."""

from pbip_assistant.errors import InputError
from http import HTTPStatus
from . import MAX_ASSISTANT_JSON_BYTES, MAX_ASSISTANT_INGEST_JSON_BYTES


class AssistantFreezeEndpoints:
    def _post_assistant_freeze(self):
        try:
            body = self._read_json(MAX_ASSISTANT_JSON_BYTES)
            if set(body) != {"branchId", "createdAt", "workbookIdentity", "acknowledgeMissingControl", "expectedPlanningHash", "expectedPreviewHash", "expectedResultDigest"} or type(body["acknowledgeMissingControl"]) is not bool:
                raise InputError("INVALID_REQUEST", "request", "Cần nhánh, thời điểm chốt, định danh workbook và acknowledgement.")
            self._json(HTTPStatus.OK, self.app.assistant.freeze(body["branchId"], body["createdAt"], body["workbookIdentity"], body["acknowledgeMissingControl"],
                expected_planning_hash=body["expectedPlanningHash"], expected_preview_hash=body["expectedPreviewHash"], expected_result_digest=body["expectedResultDigest"]))
        except (InputError, ValueError) as exc:
            self._assistant_error(exc)

    def _post_assistant_approvals(self):
        try:
            body = self._read_json(MAX_ASSISTANT_INGEST_JSON_BYTES)
            if set(body) != {"approvedAt", "acknowledged", "workbookIdentity", "workbookSources", "expectedSpecFingerprint", "expectedPreviewHash", "expectedResultDigest"} or type(body["acknowledged"]) is not bool:
                raise InputError("INVALID_REQUEST", "request", "Cần xác nhận duyệt và nguồn workbook vừa đọc lại.")
            self._json(HTTPStatus.OK, self.app.assistant.approve(body["approvedAt"], body["acknowledged"], body["workbookIdentity"], body["workbookSources"],
                expected_spec_fingerprint=body["expectedSpecFingerprint"], expected_preview_hash=body["expectedPreviewHash"], expected_result_digest=body["expectedResultDigest"]))
        except (InputError, ValueError) as exc:
            self._assistant_error(exc)

    def _post_assistant_apply(self):
        try:
            body = self._read_json(MAX_ASSISTANT_INGEST_JSON_BYTES)
            if set(body) == {"receipt", "appliedAt"}:
                result = self.app.assistant.complete_apply(body["receipt"], body["appliedAt"])
            elif set(body) == {"workbookBase64", "appliedAt", "workbookIdentity", "workbookSources", "expectedSpecFingerprint", "expectedPreviewHash", "expectedResultDigest"}:
                result = self.app.assistant.apply(body["workbookBase64"], body["appliedAt"], body["workbookIdentity"], body["workbookSources"],
                    expected_spec_fingerprint=body["expectedSpecFingerprint"], expected_preview_hash=body["expectedPreviewHash"], expected_result_digest=body["expectedResultDigest"])
            else:
                raise InputError("INVALID_REQUEST", "request", "Cần package workbook và nguồn mới, hoặc receipt đọc lại.")
            self._json(HTTPStatus.OK, result)
        except (InputError, ValueError) as exc:
            self._assistant_error(exc, consumed=getattr(exc, "assistant_approval_consumed", None))
