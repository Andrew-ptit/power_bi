"""History HTTP adapters; shared request authorization stays in server.py."""

from __future__ import annotations

from http import HTTPStatus
from pbip_assistant.errors import InputError
from pbip_assistant.coordinator.endpoints import (
    MAX_PLAN_JSON_BYTES, MAX_PROBLEM_CHAIN_JSON_BYTES, MAX_APPLY_JSON_BYTES,
)
from pbip_assistant.pq_typed import build_source_catalog


class HistoryEndpoints:
    def _post_pq_v2_problem_chains_load(self) -> None:
        request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
        document = request.get("document")
        # Loading workbook metadata is a runtime trust boundary.  No
        # preview/approval/apply authority from the previously loaded
        # workbook or head may survive, including when this workbook
        # has no Problem Chain document.
        if isinstance(document, dict) and self.app.pq_typed.can_retain_problem_cache(
            document.get("chainId"), request.get("workbook"),
        ):
            self.app.pq_typed.invalidate_runtime()
        else:
            self.app.pq_typed.close()
        if document is None:
            self.app.problem_chains.close()
            self._json(HTTPStatus.OK, {"document": None, "historyHash": None, "dataVersion": 0})
        else:
            loaded = self.app.problem_chains.load(document)
            loaded["dataVersion"] = self.app.pq_typed.bind_problem_chain(
                loaded["document"]["chainId"], request.get("workbook"),
            )
            self._json(HTTPStatus.OK, loaded)
        return

    def _post_pq_v2_problem_chains_problems(self) -> None:
        request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
        document = request.get("document")
        typed_plan = None
        source_catalog = None
        if document is None or request.get("creationMode") == "newRoot":
            typed_plan = self.app.pq_typed.create_plan(
                request.get("prompt"), request.get("workbook"), request.get("source"),
                allow_clarification_response=True,
            )
            if typed_plan.get("status") == "needsClarification":
                self.app.codex_cooldown.note_success()
                self._json(HTTPStatus.OK, typed_plan)
                return
            # The initial Typed draft only seeds a candidate.  Until
            # Custom XML read-back and commit, it grants no runtime
            # preview/approval authority.
            self.app.pq_typed.invalidate_plan(typed_plan["planId"])
        else:
            _, current_sources, _ = build_source_catalog(request.get("workbook"))
            source_catalog = [
                {key: value for key, value in source.items() if key != "sampleRows"}
                for source in current_sources
            ]
        candidate = self.app.problem_chains.create_problem(
            document, request.get("baseHistoryHash"), request.get("prompt"),
            base_revision_id=request.get("baseRevisionId"), typed_plan=typed_plan,
            source_catalog=source_catalog,
            creation_mode=request.get("creationMode", "continue"),
            edit_revision_id=request.get("editRevisionId"),
        )
        self.app.codex_cooldown.note_success()
        self._json(HTTPStatus.OK, candidate)
        return

    def _post_pq_v2_problem_chains_chains_activate(self) -> None:
        request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.problem_chains.activate_chain(
            request.get("document"), request.get("baseHistoryHash"),
            request.get("chainId"), request.get("revisionId"),
        ))
        return

    def _post_pq_v2_problem_chains_checkout(self) -> None:
        request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.problem_chains.checkout(
            request.get("document"), request.get("baseHistoryHash"), request.get("revisionId"),
        ))
        return

    def _post_pq_v2_problem_chains_problems_delete(self) -> None:
        request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
        self._json(HTTPStatus.OK, self.app.problem_chains.delete_problem(
            request.get("document"), request.get("baseHistoryHash"), request.get("revisionId"),
        ))
        return

    def _post_pq_v2_problem_chains_revisions(self) -> None:
        request = self._read_json(MAX_PROBLEM_CHAIN_JSON_BYTES)
        _, current_sources, _ = build_source_catalog(request.get("workbook"))
        source_catalog = [
            {key: value for key, value in source.items() if key != "sampleRows"}
            for source in current_sources
        ]
        candidate = self.app.problem_chains.create_manual_revision(
            request.get("document"), request.get("baseHistoryHash"),
            request.get("baseRevisionId"), request.get("changes"),
            request.get("changeReason"), source_catalog=source_catalog,
        )
        self._json(HTTPStatus.OK, candidate)
        return

    def _post_pq_v2_problem_chains_mutations_commit(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        committed = self.app.problem_chains.commit(
            request.get("mutationId"), request.get("observedHistoryHash"),
        )
        # A committed chain head supersedes every standalone Typed
        # runtime artifact in this panel session.
        self.app.pq_typed.invalidate_runtime()
        if request.get("workbook") is not None:
            self.app.pq_typed.bind_problem_chain(
                committed["document"]["chainId"], request.get("workbook"),
            )
        committed["dataVersion"] = self.app.pq_typed.problem_data_version(committed["document"]["chainId"])
        self._json(HTTPStatus.OK, committed)
        return

    def _post_pq_v2_problem_chains_cached_results_prepare(self) -> None:
        request = self._read_json(MAX_APPLY_JSON_BYTES)
        active = self.app.problem_chains.active_revision(request.get("revisionId"))
        if active is None or active["historyHash"] != request.get("baseHistoryHash"):
            raise InputError("PQPC_HEAD_MISMATCH", "baseHistoryHash", "Restore requires the current committed HEAD")
        if request.get("sourceDataChanged") is not False:
            raise InputError("PQPC_RESULT_CACHE_STALE", "sourceDataChanged", "Changed-source mode requires a new preview")
        self._json(HTTPStatus.OK, self.app.pq_typed.prepare_cached_problem_result(
            chain_id=active["chainId"], revision_id=request.get("revisionId"),
            review_hash=active["revision"]["reviewHash"], workbook=request.get("workbook"),
            workbook_base64=request.get("workbookBase64"),
            destination_marker=request.get("destinationMarker"),
        ))
        return

    def _post_pq_v2_problem_chains_cached_results_invalidate(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        active = self.app.problem_chains.active_revision(request.get("revisionId"))
        if active is None or active["historyHash"] != request.get("baseHistoryHash"):
            raise InputError("PQPC_HEAD_MISMATCH", "baseHistoryHash", "Source-version change requires the committed HEAD")
        self.app.pq_typed.bind_problem_chain(active["chainId"], request.get("workbook"))
        version = self.app.pq_typed.increment_problem_data_version(active["chainId"])
        self._json(HTTPStatus.OK, {"status": "versionIncremented", "dataVersion": version})
        return

    def _post_pq_v2_problem_chains_previews_cancel(self) -> None:
        request = self._read_json(MAX_PLAN_JSON_BYTES)
        active = self.app.problem_chains.active_revision(request.get("revisionId"))
        if active is None or active["historyHash"] != request.get("baseHistoryHash"):
            raise InputError("PQPC_HEAD_MISMATCH", "baseHistoryHash", "Cancel requires the committed HEAD")
        self.app.pq_typed.cancel_problem_preview(
            active["chainId"], request.get("revisionId"), request.get("previewId"),
        )
        self._json(HTTPStatus.OK, {"status": "cancelled"})
        return

