"""Thin, local-only branch execution HTTP adapter."""

from http import HTTPStatus
from pbip_assistant.errors import InputError
from . import MAX_ASSISTANT_JSON_BYTES


class AssistantExecEndpoints:
    def _post_assistant_branches(self):
        try:
            body = self._read_json(MAX_ASSISTANT_JSON_BYTES)
            if set(body) - {"expectedPlanningHash"} or ("expectedPlanningHash" in body and not isinstance(body["expectedPlanningHash"], str)):
                raise InputError("INVALID_REQUEST", "request", "Expected only an optional planning hash")
            self._json(HTTPStatus.OK, self.app.assistant.run_branches(body.get("expectedPlanningHash")))
        except (InputError, ValueError) as exc:
            self._assistant_error(exc)
