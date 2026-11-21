"""Thin Assistant branch planning HTTP adapter; authority stays in the store."""

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.adapters.codex.assistant_plan import CodexAssistantPlanRunner
from . import MAX_ASSISTANT_JSON_BYTES


class AssistantPlanEndpoints:
    def _post_assistant_plan_draft(self):
        try:
            body = self._read_json(MAX_ASSISTANT_JSON_BYTES)
            if set(body) - {"prompt", "answers", "acknowledged"}:
                raise InputError("AF_PLAN_INVALID", "request", "Unsupported plan request fields")
            runner = self.app.assistant_plan_runner
            if runner is None:
                runner = CodexAssistantPlanRunner(workspace_manager=self.app.runtime.temp_workspaces)
            result = self.app.assistant.plan_draft(body.get("prompt"), body.get("answers", []),
                                                  body.get("acknowledged"), runner)
            self._json(HTTPStatus.OK, result)
        except InputError as exc:
            if exc.code.startswith("CODEX_"):
                raise  # central HTTP handler owns Codex cooldown and slot policy
            self._assistant_error(exc)
        except ValueError as exc:
            self._assistant_error(exc)
