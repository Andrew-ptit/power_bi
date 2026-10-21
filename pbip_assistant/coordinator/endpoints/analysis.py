"""Analysis HTTP adapters; shared request authorization stays in server.py."""

from __future__ import annotations

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.endpoints import (
    MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES,
)
from pbip_assistant.codex_excel import analyze_workbook
from pbip_assistant.codex_pq import propose_m


class AnalysisEndpoints:
    def _post_excel_analyze(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        result = analyze_workbook(
            request.get("prompt"), request.get("workbook"), self.app.codex_runner,
            request.get("formulaListSeparator", ";"),
        )
        self.app.codex_cooldown.note_success()
        self._json(HTTPStatus.OK, result)
        return

    def _post_pq_propose(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        result = propose_m(
            request.get("prompt"), request.get("workbook"), request.get("source"),
            self.app.pq_codex_runner,
        )
        self.app.codex_cooldown.note_success()
        self._json(HTTPStatus.OK, result)
        return

