"""Thin WL1/WL2 Assistant HTTP adapters; state belongs to the locked store."""

from http import HTTPStatus

from pbip_assistant.errors import InputError
from . import MAX_ASSISTANT_JSON_BYTES, MAX_ASSISTANT_INGEST_JSON_BYTES


class AssistantSourceEndpoints:
    def _assistant_source_call(self, action, *, maximum=MAX_ASSISTANT_JSON_BYTES):
        try:
            request = self._read_json(maximum)
            result = action(request)
            self._json(HTTPStatus.OK, result)
        except (InputError, ValueError) as exc:
            self._assistant_error(exc)

    def _post_assistant_session(self):
        def bind(body):
            if body.get("sourceMode") == "workbook":
                if set(body) != {"sourceMode"}:
                    raise InputError("INVALID_REQUEST", "session", "Workbook-only session accepts no folder or file parameters")
                return self.app.assistant.bind_workbook()
            if "sourceMode" in body:
                raise InputError("INVALID_REQUEST", "sourceMode", "Unsupported source mode")
            return self.app.assistant.bind_root(body.get("root"))
        self._assistant_source_call(bind)

    def _post_assistant_ingest(self):
        def ingest(body):
            if "expectedPlanningHash" in body and not isinstance(body["expectedPlanningHash"], str):
                raise InputError("INVALID_REQUEST", "expectedPlanningHash", "Expected planning binding must be text")
            return self.app.assistant.ingest(body.get("requests"), body.get("expectedPlanningHash"))
        self._assistant_source_call(ingest,
                                    maximum=MAX_ASSISTANT_INGEST_JSON_BYTES)

    def _post_assistant_understand(self):
        self._assistant_source_call(lambda body: self.app.assistant.understand())

    def _post_assistant_state(self):
        self._assistant_source_call(lambda body: self.app.assistant.state())

    def _post_assistant_reset(self):
        self._assistant_source_call(lambda body: self.app.assistant.reset())
