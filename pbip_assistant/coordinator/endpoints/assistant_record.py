"""Build the safe Record; only the add-in may persist workbook metadata."""

from http import HTTPStatus
from pbip_assistant.errors import InputError
from . import MAX_ASSISTANT_JSON_BYTES


class AssistantRecordEndpoints:
    def _post_assistant_record(self):
        try:
            body = self._read_json(MAX_ASSISTANT_JSON_BYTES)
            if body:
                raise InputError("INVALID_REQUEST", "request", "Record chỉ nhận body rỗng từ trạng thái đã áp dụng.")
            self._json(HTTPStatus.OK, self.app.assistant.record())
        except (InputError, ValueError) as exc:
            self._assistant_error(exc)
