"""Assistant HTTP composition and engine error mapping, without state authority."""

from http import HTTPStatus

from pbip_assistant.errors import InputError
from .assistant_source import AssistantSourceEndpoints
from .assistant_plan import AssistantPlanEndpoints
from .assistant_exec import AssistantExecEndpoints
from .assistant_freeze import AssistantFreezeEndpoints
from .assistant_record import AssistantRecordEndpoints


class AssistantEndpoints(AssistantSourceEndpoints, AssistantPlanEndpoints,
                         AssistantExecEndpoints, AssistantFreezeEndpoints, AssistantRecordEndpoints):
    _ASSISTANT_STATUS = {
        **{code: HTTPStatus.CONFLICT for code in (
            "AF_SPEC_STALE", "AF_MISSING_DATA", "AF_FANOUT_RISK", "AF_POLICY_UNSUPPORTED",
            "AF_RECONCILE_FAILED", "AF_SOURCE_LOST", "AF_STAGE_INVALID", "AF_APPROVAL_MISSING",
            "AF_UNDERSTAND_INVALID", "AF_SAMPLE_ONLY", "PQPC_HISTORY_CONFLICT")},
        "AF_WRITE_PARTIAL": HTTPStatus.INTERNAL_SERVER_ERROR,
        "AF_INGEST_FAILED": HTTPStatus.UNPROCESSABLE_ENTITY,
        "ASSISTANT_ROOT_INVALID": HTTPStatus.BAD_REQUEST,
        "ASSISTANT_WORKBOOK_REQUIRED": HTTPStatus.BAD_REQUEST,
        "INVALID_REQUEST": HTTPStatus.BAD_REQUEST,
        "REQUEST_LIMIT": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "CODEX_AUTH_REQUIRED": HTTPStatus.SERVICE_UNAVAILABLE,
        "CODEX_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
        "CODEX_RATE_LIMITED": HTTPStatus.TOO_MANY_REQUESTS,
        "CODEX_TIMEOUT": HTTPStatus.GATEWAY_TIMEOUT,
        "CODEX_FAILED": HTTPStatus.BAD_GATEWAY,
        "CODEX_SCHEMA_INVALID": HTTPStatus.INTERNAL_SERVER_ERROR,
    }

    def _assistant_error(self, exc: BaseException, *, consumed=None) -> None:
        code = exc.code if isinstance(exc, InputError) else "AF_ADAPTER_INVALID"
        detail = exc.detail if isinstance(exc, InputError) else "Nội dung yêu cầu không đúng hợp đồng."
        path = exc.path if isinstance(exc, InputError) else ""
        # Only an error captured under the store's apply lock proves whether
        # this attempt consumed authority. Missing evidence stays unknown.
        extra = {"approvalConsumed": consumed} if type(consumed) is bool else None
        if code == "AF_WRITE_PARTIAL":
            extra = {**(extra or {}), "written": False if consumed is False else None,
                     "retryable": consumed is False}
        self._error(self._ASSISTANT_STATUS.get(code, HTTPStatus.UNPROCESSABLE_ENTITY),
                    code, detail, path=path, extra=extra)
