"""Typed Power Query planning, validation, compilation, revision and approval.

The model-facing draft is deliberately not executable. The pure validation and
compiler modules produce M; this module owns session authority and runner calls.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
import secrets
from threading import Lock
from typing import Any, Protocol

from pbip_assistant.core.limits import MAX_PROMPT_CHARS
from pbip_assistant.core.workbook_snapshot import snapshot_workbook as _snapshot
from pbip_assistant.errors import InputError
from pbip_assistant.pq_code_m import PQPreviewStore
from pbip_assistant.workbook_fingerprint import workbook_data_fingerprint
from pbip_assistant.excel_connector import decode_workbook_export
from pbip_assistant.powerquery.typed.diagnostics_service import StepDiagnosticService

# The Codex draft adapter moved to pbip_assistant.adapters.codex.typed. These
# names stay importable from this module for existing callers; a test that
# replaces them must patch the adapter module, which is where the runner
# resolves them.
from pbip_assistant.adapters.codex.typed import (
    AI_SCHEMA_PATH,
    MAX_RESPONSE_CHARS,
    CodexTypedRunner,
    _codex_failure_code,
    _load_and_preflight_ai_schema,
    find_codex_executable,
)

# Compatibility imports retain the established public and private module API.
from pbip_assistant.powerquery.typed.model import (
    SCHEMA_VERSION,
    MAX_STEPS,
    MAX_SOURCES,
    MAX_INPUTS,
    MAX_ACTIVE_PREVIEWS,
    MAX_PROBLEM_RESULT_CACHE_BYTES,
    MAX_STEP_DIAGNOSTIC_CACHE_ENTRIES,
    MAX_STEP_DIAGNOSTIC_CACHE_BYTES,
    MAX_STEP_DIAGNOSTIC_STAGING_BYTES,
    MAX_COMPILED_M_CHARS,
    TYPED_COMPILER_POLICY_VERSION,
    TYPED_SCHEMA_POLICY_VERSION,
    DESTINATION_MARKER,
    VARIABLE,
    CLIENT_REF,
    M_RESERVED,
    OPERATION_ARITY,
    TYPE_NAMES,
    AGGREGATIONS,
    JOIN_KINDS,
    FUNCTIONS,
    COMPARE_OPERATORS,
    PARAMETER_KEYS,
    EXPRESSION_KEYS,
    _canonical,
    _compatible_types,
    _content_id,
    _digest,
    _infer_type,
    _issue,
    _list_of_strings,
    _now,
    _public_sources,
    _random_id,
    _replace_refs,
    _strict_keys,
)
from pbip_assistant.powerquery.typed.validation import (
    _bind_single_draft_source,
    _column,
    _column_list,
    _new_column,
    _normalize_aggregations,
    _normalize_expression,
    _normalize_operation,
    _normalize_steps,
    _validate_draft_shape,
    build_source_catalog,
)
from pbip_assistant.powerquery.typed.compiler import (
    _compile_expression,
    _m_text,
    _m_type,
    _source_preserving_output_names,
    compile_m,
    compile_m_to_step,
    dependency_closure_steps,
    diagnostic_step_cache_keys,
)




class TypedDraftRunner(Protocol):
    def propose(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class TypedPlanStore:
    """Session-only authoritative store for Typed Steps v2."""

    def __init__(self, runner: TypedDraftRunner, previews: PQPreviewStore) -> None:
        self.runner = runner
        self.previews = previews
        self._lock = Lock()
        self._revisions: dict[str, dict[str, Any]] = {}
        self._latest_by_plan: dict[str, str] = {}
        self._preview_records: dict[str, dict[str, Any]] = {}
        self._approvals: dict[str, dict[str, Any]] = {}
        self._patches: dict[str, dict[str, Any]] = {}
        self._applies: dict[str, dict[str, Any]] = {}
        self._problem_result_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._problem_binding: tuple[str, tuple[str, str]] | None = None
        self._problem_data_versions: dict[str, int] = {}
        self._step_diagnostic_staging: dict[str, Any] | None = None
        self._step_diagnostic_cache: dict[str, dict[str, Any]] = {}
        self._diagnostics = StepDiagnosticService(self)

    def close(self) -> None:
        with self._lock:
            self._revisions.clear(); self._latest_by_plan.clear(); self._preview_records.clear()
            self._approvals.clear(); self._patches.clear(); self._applies.clear()
            self._problem_result_cache.clear()
            self._problem_binding = None
            self._problem_data_versions.clear()
            self._step_diagnostic_staging = None
            self._step_diagnostic_cache.clear()

    def invalidate_runtime(self) -> None:
        """A HEAD mutation revokes approval authority, not bounded result bytes."""
        with self._lock:
            self._revisions.clear(); self._latest_by_plan.clear(); self._preview_records.clear()
            self._approvals.clear(); self._patches.clear(); self._applies.clear()

    def can_retain_problem_cache(self, chain_id: Any, workbook: Any) -> bool:
        with self._lock:
            return self._problem_binding == (chain_id, self._workbook_key(workbook))

    def bind_problem_chain(self, chain_id: str, workbook: Any) -> int:
        with self._lock:
            binding = (chain_id, self._workbook_key(workbook))
            if self._problem_binding is not None and self._problem_binding != binding:
                self._problem_result_cache.clear()
                self._problem_data_versions.clear()
                self._step_diagnostic_staging = None
                self._step_diagnostic_cache.clear()
            self._problem_binding = binding
            return self._problem_data_versions.setdefault(chain_id, 0)

    def problem_data_version(self, chain_id: str) -> int:
        with self._lock:
            return self._problem_data_versions.get(chain_id, 0)

    def increment_problem_data_version(self, chain_id: str) -> int:
        with self._lock:
            value = self._problem_data_versions.get(chain_id, 0) + 1
            self._problem_data_versions[chain_id] = value
            # Keep confirmed cache entries for comparison, but revoke any
            # unconfirmed staging result from the preceding source version.
            for preview in self._preview_records.values():
                if preview.get("problemChainId") == chain_id and preview["status"] == "active":
                    preview["status"] = "evicted"
                    preview.pop("resultWorkbookBase64", None)
            for approval in self._approvals.values():
                if approval["status"] == "approved":
                    preview = self._preview_records.get(approval["previewId"])
                    if preview is not None and preview.get("problemChainId") == chain_id:
                        approval["status"] = "invalidated"
            if (
                self._step_diagnostic_staging is not None
                and self._step_diagnostic_staging.get("problemChainId") == chain_id
                and self._step_diagnostic_staging.get("status") in {"running", "ready"}
            ):
                self._step_diagnostic_staging["status"] = "stale"
                self._step_diagnostic_staging.pop("resultWorkbookBase64", None)
            return value

    def discard_problem_cache(self, chain_id: str) -> None:
        with self._lock:
            self._problem_result_cache = {
                key: value for key, value in self._problem_result_cache.items()
                if value["chainId"] != chain_id
            }

    @staticmethod
    def _workbook_key(workbook: Any) -> tuple[str, str]:
        if not isinstance(workbook, dict):
            return ("", "")
        return (str(workbook.get("name") or ""), str(workbook.get("url") or ""))

    def _store_revision(
        self, *, plan_id: str, snapshot_id: str, sources: list[dict[str, Any]], prompt_hash: str,
        summary: str, questions: list[str], assumptions: list[str], warnings: list[str],
        steps: list[dict[str, Any]], final_step_id: str | None, blockers: list[dict[str, str]],
        parent_revision_id: str | None, change_reason: str, change_set: list[dict[str, Any]],
    ) -> dict[str, Any]:
        review_value = {
            "planId": plan_id, "snapshotId": snapshot_id, "promptHash": prompt_hash,
            "sources": _public_sources(sources), "summary": summary, "questions": questions,
            "assumptions": assumptions, "warnings": warnings, "hardBlockers": blockers,
            "steps": steps, "finalOutputStepId": final_step_id,
        }
        review_hash = "sha256:" + _digest(review_value)
        revision_id = _content_id("rev", review_value)
        plan_status = "needsClarification" if questions else "blocked" if blockers else "reviewReady"
        compiled = None
        compiled_hash = None
        gates = []
        for number in range(1, 10):
            issues = [{key: value for key, value in issue.items() if key != "gate"} for issue in blockers if issue["gate"] == f"V{number}"]
            gates.append({"gate": f"V{number}", "status": "blocked" if issues else "passed", "issues": issues})
        public = {
            "schemaVersion": SCHEMA_VERSION, "planId": plan_id, "snapshotId": snapshot_id,
            "revision": {
                "revisionId": revision_id, "parentRevisionId": parent_revision_id,
                "createdAt": _now(), "changeReason": change_reason, "reviewHash": review_hash,
            },
            "planStatus": plan_status, "summary": summary, "questions": questions,
            "assumptions": assumptions, "warnings": warnings,
            "hardBlockers": [{key: value for key, value in item.items() if key != "gate"} for item in blockers],
            "sources": _public_sources(sources), "steps": steps, "finalOutputStepId": final_step_id,
            "changeSet": change_set,
            "validation": {"overall": "blocked" if blockers else "passed", "gates": gates, "compiledMHash": None},
            "preview": None, "approval": {"status": "notRequested"},
        }
        if plan_status == "reviewReady":
            try:
                compiled = compile_m(public, enforce_source_order=True)
                compiled_hash = "sha256:" + hashlib.sha256(compiled.encode("utf-8")).hexdigest()
                public["validation"]["compiledMHash"] = compiled_hash
            except InputError as exc:
                blocker = _issue("V9", exc.code, exc.path, "compiler", exc.detail, "Simplify or correct the typed pipeline")
                public["hardBlockers"].append({key: value for key, value in blocker.items() if key != "gate"})
                public["planStatus"] = "blocked"
                public["validation"]["overall"] = "blocked"
                public["validation"]["gates"][8] = {"gate": "V9", "status": "blocked", "issues": [public["hardBlockers"][-1]]}
        record = {
            "public": public, "compiledM": compiled, "compiledMHash": compiled_hash,
            "promptHash": prompt_hash, "sourcesInternal": deepcopy(sources),
        }
        with self._lock:
            self._invalidate_plan_locked(plan_id)
            self._revisions[revision_id] = record
            self._latest_by_plan[plan_id] = revision_id
        return deepcopy(public)

    def _invalidate_plan_locked(self, plan_id: str) -> None:
        for preview in self._preview_records.values():
            if preview["planId"] == plan_id and preview["status"] == "active": preview["status"] = "invalidated"
        for approval in self._approvals.values():
            if approval["planId"] == plan_id and approval["status"] == "approved": approval["status"] = "invalidated"

    def invalidate_plan(self, plan_id: Any) -> None:
        """Invalidate session-only runtime authority after a committed head change."""

        if not isinstance(plan_id, str) or not plan_id:
            return
        with self._lock:
            self._invalidate_plan_locked(plan_id)
            self._latest_by_plan.pop(plan_id, None)

    def create_plan(
        self, prompt: Any, workbook: Any, selection: Any = None, *,
        allow_clarification_response: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise InputError("PROMPT_REQUIRED", "prompt", "Enter a request before creating a typed plan")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise InputError("PROMPT_LIMIT", "prompt", "Request exceeds 4000 characters")
        snapshot, sources, snapshot_id = build_source_catalog(workbook)
        primary_source_id = None
        if isinstance(selection, dict):
            for source in sources:
                if source["sheetName"] != selection.get("sheet"): continue
                if selection.get("kind") == "table" and source.get("objectName") == selection.get("name"): primary_source_id = source["sourceId"]
                if selection.get("kind") == "sheet" and source["kind"] == "usedRange": primary_source_id = source["sourceId"]
        planner_payload = {
            "schemaVersion": SCHEMA_VERSION, "userRequest": prompt,
            "workbookName": snapshot["name"], "activeSheet": snapshot["activeSheet"],
            "primarySourceId": primary_source_id, "sourceCatalog": sources,
            "operationCatalog": list(OPERATION_ARITY),
        }
        response = self.runner.propose(planner_payload)
        draft = _validate_draft_shape(response)
        if allow_clarification_response and draft["questions"]:
            questions = list(dict.fromkeys(value.strip() for value in draft["questions"] if value.strip()))
            if not questions:
                raise InputError("CODEX_RESPONSE_INVALID", "questions", "Clarification questions cannot be empty")
            return {
                "status": "needsClarification",
                "questions": questions,
                "assumptions": list(dict.fromkeys(value.strip() for value in draft["assumptions"] if value.strip())),
                "warnings": list(dict.fromkeys(value.strip() for value in draft["warnings"] if value.strip())),
            }
        source_was_bound = _bind_single_draft_source(draft, sources, primary_source_id)
        steps, final_step, blockers, generated_warnings = _normalize_steps(draft["steps"], draft["finalOutputRef"], sources, draft=True)
        if allow_clarification_response and any(item["code"] == "PQV2_COLUMN_NOT_FOUND" for item in blockers) and all(
            item["code"] in {"PQV2_COLUMN_NOT_FOUND", "PQV2_FINAL_OUTPUT_NOT_TABLE"} for item in blockers
        ):
            return {
                "status": "needsClarification",
                "questions": ["Một cột được yêu cầu chưa có hoặc tên cột chưa rõ tại bước xử lý. Bạn muốn dùng cột nào đang có, hay tạo cột mới theo quy tắc nào?"],
                "assumptions": [], "warnings": [],
            }
        retryable_plan_codes = {
            "PQV2_FINAL_OUTPUT_NOT_TABLE",
            "PQV2_NESTED_TABLE_NOT_EXPANDED",
        }
        blocker_codes = {item.get("code") for item in blockers}
        if blocker_codes and blocker_codes <= retryable_plan_codes:
            repaired_payload = deepcopy(planner_payload)
            repaired_payload["validationFeedback"] = {
                "codes": sorted(blocker_codes),
                "instruction": (
                    "Return a complete corrected plan with one non-empty flat-table finalOutputRef. "
                    "For Merge, add Expand downstream and make the expanded step final."
                ),
            }
            response = self.runner.propose(repaired_payload)
            draft = _validate_draft_shape(response)
            if allow_clarification_response and draft["questions"]:
                questions = list(dict.fromkeys(value.strip() for value in draft["questions"] if value.strip()))
                if not questions:
                    raise InputError("CODEX_RESPONSE_INVALID", "questions", "Clarification questions cannot be empty")
                return {
                    "status": "needsClarification", "questions": questions,
                    "assumptions": list(dict.fromkeys(value.strip() for value in draft["assumptions"] if value.strip())),
                    "warnings": list(dict.fromkeys(value.strip() for value in draft["warnings"] if value.strip())),
                }
            source_was_bound = _bind_single_draft_source(draft, sources, primary_source_id)
            steps, final_step, blockers, generated_warnings = _normalize_steps(
                draft["steps"], draft["finalOutputRef"], sources, draft=True,
            )
        plan_id = _random_id("plan")
        return self._store_revision(
            plan_id=plan_id, snapshot_id=snapshot_id, sources=sources,
            prompt_hash="sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            summary=draft["summary"], questions=_list_of_strings(draft["questions"], "questions"),
            assumptions=_list_of_strings(draft["assumptions"], "assumptions"),
            warnings=[*_list_of_strings(draft["warnings"], "warnings"), *generated_warnings,
                      *(["Planner source reference was bound to the explicitly selected workbook source."] if source_was_bound else []),
                      *(["Only a bounded workbook sample was sent to Codex; unseen rows may contain other patterns."] if any(source["sampleOnly"] for source in sources) else [])],
            steps=steps, final_step_id=final_step, blockers=blockers,
            parent_revision_id=None, change_reason="Created typed plan", change_set=[],
        )

    def _record(self, revision_id: Any) -> dict[str, Any]:
        if not isinstance(revision_id, str) or revision_id not in self._revisions:
            raise InputError("PQV2_REVISION_NOT_FOUND", "revisionId", "Typed revision is missing from this panel session")
        return self._revisions[revision_id]

    def activate_problem_revision(
        self, plan_id: Any, revision: Any, workbook: Any,
    ) -> dict[str, Any]:
        """Register a committed Problem Chain head for the existing preview flow.

        Problem Chain revision IDs are random persistence identities rather than
        TypedPlanStore content IDs.  This bridge deliberately accepts only the
        already validated semantic fields and rebuilds the source catalog from
        the current workbook.  The caller owns the Problem Chain document/hash
        validation and source-schema fingerprint comparison.
        """

        if not isinstance(plan_id, str) or not plan_id:
            raise InputError("PQPC_DOCUMENT_INVALID", "planId", "Problem Chain plan ID is invalid")
        if not isinstance(revision, dict):
            raise InputError("PQPC_DOCUMENT_INVALID", "revision", "Problem Chain revision is invalid")
        revision_id = revision.get("revisionId")
        if not isinstance(revision_id, str) or not revision_id:
            raise InputError("PQPC_DOCUMENT_INVALID", "revision.revisionId", "Problem Chain revision ID is invalid")

        _, current_sources, current_snapshot_id = build_source_catalog(workbook)
        persisted_sources = revision.get("sources")
        if not isinstance(persisted_sources, list) or not persisted_sources:
            raise InputError("PQPC_SOURCE_SCHEMA_CHANGED", "revision.sources", "Problem Chain sources are missing")
        matched_sources: list[dict[str, Any]] = []
        current_schema_sources: list[dict[str, Any]] = []
        for persisted in persisted_sources:
            if not isinstance(persisted, dict):
                raise InputError("PQPC_DOCUMENT_INVALID", "revision.sources", "Problem Chain source is invalid")
            if persisted.get("kind") == "excelTable":
                matches = [
                    source for source in current_sources
                    if source.get("kind") == "excelTable"
                    and source.get("objectName") == persisted.get("objectName")
                ]
            else:
                matches = [
                    source for source in current_sources
                    if source.get("kind") == "usedRange"
                    and source.get("sheetName") == persisted.get("sheetName")
                    and source.get("headerRow") == persisted.get("headerRow")
                ]
            if len(matches) != 1:
                raise InputError(
                    "PQPC_SOURCE_SCHEMA_CHANGED", "workbook",
                    "A source used by the Problem Chain no longer exists in the workbook",
                )
            current = matches[0]
            current_schema_sources.append(_public_sources([current])[0])
            # Runtime location/sample comes from the current workbook, while
            # semantic IDs remain those reviewed and persisted in the chain.
            runtime_source = deepcopy(current)
            runtime_source["sourceId"] = persisted["sourceId"]
            runtime_source["columns"] = deepcopy(persisted["columns"])
            matched_sources.append(runtime_source)
        # Imported lazily to avoid a module cycle: Problem Chain uses the
        # deterministic Typed compiler while this bridge uses its persistence
        # fingerprint policy.
        from pbip_assistant.powerquery.history.document import source_schema_fingerprint
        if source_schema_fingerprint(current_schema_sources) != revision.get("sourceSchemaFingerprint"):
            raise InputError(
                "PQPC_SOURCE_SCHEMA_CHANGED", "workbook",
                "Workbook source columns or inferred types changed after this revision",
            )

        steps = deepcopy(revision.get("steps"))
        final_step_id = revision.get("finalOutputStepId")
        compiled_probe = {
            "sources": deepcopy(persisted_sources),
            "steps": steps,
            "finalOutputStepId": final_step_id,
        }
        semantic_compiled = compile_m(compiled_probe)
        semantic_compiled_hash = "sha256:" + hashlib.sha256(semantic_compiled.encode("utf-8")).hexdigest()
        historical = revision.get("validationAtCreation")
        if not isinstance(historical, dict) or historical.get("compiledMHash") != semantic_compiled_hash:
            raise InputError(
                "PQPC_HASH_MISMATCH", "revision.validationAtCreation.compiledMHash",
                "Compiled Problem Chain semantics differ from the persisted revision",
            )
        compiled = compile_m(compiled_probe, enforce_source_order=True)
        compiled_hash = "sha256:" + hashlib.sha256(compiled.encode("utf-8")).hexdigest()
        questions = deepcopy(revision.get("questions", []))
        plan_status = "needsClarification" if questions else "reviewReady"
        public = {
            "schemaVersion": SCHEMA_VERSION,
            "planId": plan_id,
            "snapshotId": current_snapshot_id,
            "revision": {
                "revisionId": revision_id,
                "parentRevisionId": revision.get("parentRevisionId"),
                "createdAt": revision.get("createdAt"),
                "changeReason": revision.get("changeReason"),
                "reviewHash": revision.get("reviewHash"),
            },
            "planStatus": plan_status,
            "summary": revision.get("summary", ""),
            "questions": questions,
            "assumptions": deepcopy(revision.get("assumptions", [])),
            "warnings": deepcopy(revision.get("warnings", [])),
            "hardBlockers": [],
            "sources": deepcopy(persisted_sources),
            "steps": steps,
            "finalOutputStepId": final_step_id,
            "changeSet": deepcopy(revision.get("changeSet", [])),
            "validation": {
                "overall": "passed",
                "gates": [],
                "compiledMHash": compiled_hash,
            },
            "preview": None,
            "approval": {"status": "notRequested"},
        }
        record = {
            "public": public,
            "compiledM": compiled,
            "compiledMHash": compiled_hash,
            "promptHash": "sha256:" + hashlib.sha256(
                str(revision.get("problemPrompt", "")).encode("utf-8")
            ).hexdigest(),
            "sourcesInternal": deepcopy(matched_sources),
        }
        with self._lock:
            self._invalidate_plan_locked(plan_id)
            self._revisions[revision_id] = record
            self._latest_by_plan[plan_id] = revision_id
        return deepcopy(public)

    def create_revision(self, request: dict[str, Any]) -> dict[str, Any]:
        base = self._record(request.get("baseRevisionId"))
        base_public = base["public"]
        plan_id = base_public["planId"]
        if self._latest_by_plan.get(plan_id) != base_public["revision"]["revisionId"]:
            raise InputError("PQV2_REVISION_STALE", "baseRevisionId", "Create edits from the latest revision")
        steps = deepcopy(base_public["steps"])
        final_step = base_public["finalOutputStepId"]
        change_set: list[dict[str, Any]] = []
        patch_id = request.get("patchId")
        changes = request.get("changes", [])
        if patch_id is not None:
            patch = self._patches.get(patch_id)
            if patch is None or patch["baseRevisionId"] != base_public["revision"]["revisionId"] or patch["snapshotId"] != base_public["snapshotId"]:
                raise InputError("PQV2_PATCH_STALE", "patchId", "Repair patch is missing or stale")
            changes = deepcopy(patch["changes"])
        if not isinstance(changes, list) or not 1 <= len(changes) <= 50:
            raise InputError("PQV2_JSON_INVALID", "changes", "Revision requires 1-50 changes")
        for index, change in enumerate(changes):
            if not isinstance(change, dict) or change.get("type") not in {"insertStep", "updateStep", "deleteStep", "moveStep", "setFinalOutput"}:
                raise InputError("PQV2_JSON_INVALID", f"changes[{index}]", "Unsupported revision change")
            kind, step_id = change["type"], change.get("stepId")
            position = next((i for i, step in enumerate(steps) if step["stepId"] == step_id), None)
            if kind == "insertStep":
                draft = change.get("stepDraft")
                if not isinstance(draft, dict): raise InputError("PQV2_JSON_INVALID", f"changes[{index}].stepDraft", "Insert requires a step draft")
                new_step = deepcopy(draft)
                # A prevalidated server-side repair patch may reserve the new ID
                # so its companion reconnect changes can reference it.  Client
                # requests never get to choose this private field.
                new_step["stepId"] = change.get("_serverStepId", _random_id("stp")) if patch_id is not None else _random_id("stp")
                if "operationType" in new_step:
                    new_step["operation"] = {"type": new_step.pop("operationType"), "parameters": new_step.pop("parameters", {})}
                new_step.setdefault("inputs", [])
                after = change.get("afterStepId")
                insert_at = 0 if after is None else next((i + 1 for i, item in enumerate(steps) if item["stepId"] == after), None)
                if insert_at is None: raise InputError("PQV2_DEPENDENCY_INVALID", f"changes[{index}].afterStepId", "Insertion anchor does not exist")
                steps.insert(insert_at, new_step)
                change = {**change, "stepId": new_step["stepId"]}
            elif position is None:
                raise InputError("PQV2_DEPENDENCY_INVALID", f"changes[{index}].stepId", "Target step does not exist")
            elif kind == "updateStep":
                draft = change.get("stepDraft")
                if not isinstance(draft, dict): raise InputError("PQV2_JSON_INVALID", f"changes[{index}].stepDraft", "Update requires a step draft")
                updated = deepcopy(steps[position])
                for field in ("variableName", "actionDescription", "inputs"):
                    if field in draft: updated[field] = deepcopy(draft[field])
                if "operationType" in draft or "parameters" in draft:
                    updated["operation"] = {"type": draft.get("operationType", updated["operation"]["type"]), "parameters": deepcopy(draft.get("parameters", updated["operation"]["parameters"]))}
                if "operation" in draft: updated["operation"] = deepcopy(draft["operation"])
                steps[position] = updated
            elif kind == "deleteStep":
                steps.pop(position)
                if final_step == step_id: final_step = None
            elif kind == "moveStep":
                new_position = change.get("position")
                if not isinstance(new_position, int) or not 1 <= new_position <= len(steps):
                    raise InputError("PQV2_JSON_INVALID", f"changes[{index}].position", "Move position is invalid")
                item = steps.pop(position); steps.insert(new_position - 1, item)
            elif kind == "setFinalOutput":
                final_step = step_id
            change_set.append({key: deepcopy(value) for key, value in change.items() if key not in {"stepDraft", "_serverStepId"}})
        for index, step in enumerate(steps): step["position"] = index + 1
        normalized, normalized_final, blockers, generated_warnings = _normalize_steps(steps, final_step, base["sourcesInternal"], draft=False)
        return self._store_revision(
            plan_id=plan_id, snapshot_id=base_public["snapshotId"], sources=base["sourcesInternal"],
            prompt_hash=base["promptHash"], summary=base_public["summary"], questions=base_public["questions"],
            assumptions=base_public["assumptions"], warnings=[*base_public["warnings"], *generated_warnings],
            steps=normalized, final_step_id=normalized_final, blockers=blockers,
            parent_revision_id=base_public["revision"]["revisionId"],
            change_reason=str(request.get("changeReason") or "Edited typed steps")[:500], change_set=change_set,
        )

    def _step_diagnostic_authority(
        self, revision_id: Any, selected_step_id: Any, problem_chain_id: Any,
        workbook: Any, run_version: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], tuple[str, str]]:
        """Shared diagnostic guards; inputs are derived only once these pass."""
        record = self._record(revision_id)
        public = record["public"]
        if (
            self._latest_by_plan.get(public["planId"]) != revision_id
            or public["planStatus"] != "reviewReady"
        ):
            raise InputError("TSD_HEAD_MISMATCH", "revisionId", "Step diagnostic requires the committed review-ready HEAD")
        if not isinstance(selected_step_id, str):
            raise InputError("TSD_STEP_NOT_FOUND", "selectedStepId", "Select a step from the current revision")
        if not isinstance(problem_chain_id, str) or not problem_chain_id:
            raise InputError("TSD_HEAD_MISMATCH", "problemChainId", "Step diagnostic requires an active Problem Chain")
        workbook_key = self._workbook_key(workbook)
        if self._problem_binding != (problem_chain_id, workbook_key):
            raise InputError("TSD_SOURCE_STALE", "workbook", "Workbook or Problem Chain binding changed")
        if not isinstance(run_version, int) or run_version != self.problem_data_version(problem_chain_id):
            raise InputError("TSD_SOURCE_STALE", "runVersion", "Source data version changed")
        return record, public, workbook_key

    def _step_diagnostic_begin(self, running: dict[str, Any]) -> None:
        with self._lock:
            if self._step_diagnostic_staging is not None:
                old = self._step_diagnostic_staging
                if old.get("status") == "running":
                    raise InputError("COORDINATOR_BUSY", "stepDiagnostic", "A step diagnostic is already running")
                old["status"] = "stale"
                old.pop("resultWorkbookBase64", None)
            self._step_diagnostic_staging = running

    def _step_diagnostic_commit(
        self, running: dict[str, Any], ready: dict[str, Any],
        problem_chain_id: str, run_version: int,
    ) -> None:
        with self._lock:
            if self._step_diagnostic_staging is not running or running.get("status") != "running":
                raise InputError("TSD_STAGING_STALE", "stagingId", "Step diagnostic was replaced while Excel was running")
            if self._problem_data_versions.get(problem_chain_id, 0) != run_version:
                running["status"] = "stale"
                raise InputError("TSD_SOURCE_STALE", "runVersion", "Source changed while step diagnostic was running")
            self._step_diagnostic_staging = ready

    def _step_diagnostic_abort(self, running: dict[str, Any]) -> None:
        with self._lock:
            if self._step_diagnostic_staging is running and running.get("status") == "running":
                running["status"] = "failed"

    def _step_diagnostic_promote(
        self, staging_id: Any, *, revision_id: Any, selected_step_id: Any,
        problem_chain_id: Any, run_version: Any, context: dict[str, Any],
    ) -> dict[str, Any]:
        """Promote a ready staging into the cache; every guard stays under the lock."""
        with self._lock:
            staging = self._step_diagnostic_staging
            if (
                staging is None or staging.get("stagingId") != staging_id
                or staging.get("status") != "ready"
                or staging.get("revisionId") != revision_id
                or staging.get("selectedStepId") != selected_step_id
                or staging.get("problemChainId") != problem_chain_id
            ):
                raise InputError("TSD_STAGING_STALE", "stagingId", "Step diagnostic staging is no longer confirmable")
            workbook_key = context["workbookKey"]
            if (
                staging.get("runVersion") != run_version
                or self._problem_data_versions.get(problem_chain_id, 0) != run_version
                or self._problem_binding != (problem_chain_id, workbook_key)
                or staging.get("reviewHash") != context["public"]["revision"]["reviewHash"]
                or staging.get("workbookKey") != workbook_key
                or staging.get("sourceFingerprint") != context["sourceFingerprint"]
                or staging.get("stepCacheKey") != context["stepCacheKey"]
            ):
                staging["status"] = "stale"
                staging.pop("resultWorkbookBase64", None)
                raise InputError("TSD_SOURCE_STALE", "stagingId", "Revision, source or selected-step inputs changed before confirmation")
            encoded_size = len(staging["resultWorkbookBase64"].encode("ascii"))
            if encoded_size > MAX_STEP_DIAGNOSTIC_CACHE_BYTES:
                raise InputError("TSD_STAGING_LIMIT", "result", "Confirmed step result exceeds the 32 MiB cache budget")
            cache_id = _random_id("cache")
            entry = deepcopy(staging)
            entry.update({"cacheId": cache_id, "status": "confirmed", "cachedAt": _now(), "encodedBytes": encoded_size})
            for old_cache_id, old_entry in list(self._step_diagnostic_cache.items()):
                if (
                    old_entry.get("problemChainId") == problem_chain_id
                    and old_entry.get("selectedStepId") == selected_step_id
                ):
                    self._step_diagnostic_cache.pop(old_cache_id)
            while self._step_diagnostic_cache and (
                len(self._step_diagnostic_cache) >= MAX_STEP_DIAGNOSTIC_CACHE_ENTRIES
                or sum(item["encodedBytes"] for item in self._step_diagnostic_cache.values()) + encoded_size
                    > MAX_STEP_DIAGNOSTIC_CACHE_BYTES
            ):
                self._step_diagnostic_cache.pop(next(iter(self._step_diagnostic_cache)))
            self._step_diagnostic_cache[cache_id] = entry
            staging["status"] = "confirmed"
            staging.pop("resultWorkbookBase64", None)
        return {
            "cacheId": cache_id, "status": "confirmed", "cachedAt": entry["cachedAt"],
            "stepCacheKey": entry["stepCacheKey"],
        }

    def _step_diagnostic_release(self, staging_id: Any) -> dict[str, Any]:
        with self._lock:
            staging = self._step_diagnostic_staging
            if staging is None or staging.get("stagingId") != staging_id:
                raise InputError("TSD_STAGING_STALE", "stagingId", "Step diagnostic staging was not found")
            if staging.get("status") == "cancelled":
                return {"stagingId": staging_id, "status": "cancelled"}
            if staging.get("status") not in {"running", "ready"}:
                raise InputError("TSD_STAGING_STALE", "stagingId", "Step diagnostic staging is no longer active")
            staging["status"] = "cancelled"
            staging.pop("resultWorkbookBase64", None)
        return {"stagingId": staging_id, "status": "cancelled"}

    def _step_diagnostic_lookup(
        self, problem_chain_id: Any, run_version: Any, selected_step_id: Any,
        context: dict[str, Any],
    ) -> tuple[str, str | None, dict[str, Any] | None]:
        """Return (kind, reason, entry); the caller projects the public payload."""
        workbook_key = context["workbookKey"]
        with self._lock:
            if (
                self._problem_data_versions.get(problem_chain_id, 0) != run_version
                or self._problem_binding != (problem_chain_id, workbook_key)
            ):
                return "stale", "sourceOrWorkbookChanged", None
            candidates = [
                entry for entry in self._step_diagnostic_cache.values()
                if entry.get("problemChainId") == problem_chain_id
                and entry.get("selectedStepId") == selected_step_id
            ]
            hit = next((
                entry for entry in reversed(candidates)
                if entry.get("stepCacheKey") == context["stepCacheKey"]
                and entry.get("sourceFingerprint") == context["sourceFingerprint"]
                and entry.get("workbookKey") == workbook_key
                and entry.get("runVersion") == run_version
            ), None)
            if hit is not None:
                return "hit", None, hit
            if candidates:
                return "stale", "sourceOrDependencyChanged", None
        return "miss", None, None

    def run_step_diagnostic(
        self, revision_id: Any, selected_step_id: Any, workbook: Any,
        workbook_base64: Any, *, problem_chain_id: Any, run_version: Any,
    ) -> dict[str, Any]:
        return self._diagnostics.run(
            revision_id, selected_step_id, workbook, workbook_base64,
            problem_chain_id=problem_chain_id, run_version=run_version,
        )

    def confirm_step_diagnostic(
        self, staging_id: Any, revision_id: Any, selected_step_id: Any,
        workbook: Any, workbook_base64: Any, *, problem_chain_id: Any,
        run_version: Any,
    ) -> dict[str, Any]:
        return self._diagnostics.confirm(
            staging_id, revision_id, selected_step_id, workbook, workbook_base64,
            problem_chain_id=problem_chain_id, run_version=run_version,
        )

    def cancel_step_diagnostic(self, staging_id: Any) -> dict[str, Any]:
        return self._diagnostics.cancel(staging_id)

    def inspect_step_cache(
        self, revision_id: Any, selected_step_id: Any, workbook: Any,
        workbook_base64: Any, *, problem_chain_id: Any, run_version: Any,
    ) -> dict[str, Any]:
        return self._diagnostics.inspect(
            revision_id, selected_step_id, workbook, workbook_base64,
            problem_chain_id=problem_chain_id, run_version=run_version,
        )

    def preview(
        self, revision_id: Any, workbook: Any, workbook_base64: Any,
        *, problem_chain_id: str | None = None, run_version: int | None = None,
    ) -> dict[str, Any]:
        record = self._record(revision_id)
        public = record["public"]
        if public["planStatus"] == "needsClarification":
            raise InputError(
                "PQV2_CLARIFICATION_REQUIRED", "questions",
                "This revision has unanswered questions; clarify the requirement in a new problem before Preview",
            )
        if self._latest_by_plan.get(public["planId"]) != revision_id or public["planStatus"] != "reviewReady" or not record["compiledM"]:
            raise InputError("PQV2_PREVIEW_STALE", "revisionId", "Preview requires the latest review-ready revision")
        _, current_sources, current_snapshot = build_source_catalog(workbook)
        if current_snapshot != public["snapshotId"]:
            raise InputError("PQV2_SOURCE_CHANGED", "workbook", "Workbook source metadata/sample changed; create a new plan")
        used_source_ids = [step["operation"]["parameters"]["sourceId"] for step in public["steps"] if step["operation"]["type"].startswith("source.")]
        runtime_sources = [source for source in record["sourcesInternal"] if source["sourceId"] in used_source_ids]
        if not runtime_sources:
            raise InputError("PQV2_SOURCE_NOT_FOUND", "steps", "Plan has no workbook source")
        source_sheet_names = frozenset(source["sheetName"] for source in runtime_sources)
        runtime = self.previews.preview_compiled(
            workbook=workbook, sources=runtime_sources, m_code=record["compiledM"], workbook_base64=workbook_base64,
            typed_result_source_sheets=source_sheet_names,
        )
        preview_id = _random_id("prv")
        response = {
            "previewId": preview_id, "revisionId": revision_id, "snapshotId": public["snapshotId"],
            "compiledMHash": record["compiledMHash"], "status": "excelRuntimePreview",
            "sourceRows": runtime["sourceRows"], "resultRows": runtime["resultRows"],
            "resultColumns": runtime["resultColumns"], "resultSheetName": "PQ_Typed_Result",
            "beforeColumns": runtime["beforeColumns"], "beforeRows": runtime["beforeRows"],
            "afterColumns": runtime["afterColumns"], "afterRows": runtime["afterRows"],
            "previewLimited": runtime["previewLimited"],
            "runtimeEvidence": {"excelVersion": runtime.get("excelVersion"), "refreshSucceeded": True},
        }
        if problem_chain_id is not None:
            response["runVersion"] = run_version
        preview_record = {
            **deepcopy(response), "planId": public["planId"], "status": "active",
            "problemChainId": problem_chain_id,
            "workbookKey": self._workbook_key(workbook),
            "resultWorkbookBase64": runtime["resultWorkbookBase64"],
            "resultWorkbookSheetName": runtime["resultWorkbookSheetName"],
            "sourceFingerprint": runtime["sourceFingerprint"],
            "sourceSheetNames": source_sheet_names,
        }
        with self._lock:
            if problem_chain_id is not None and self._problem_data_versions.get(problem_chain_id, 0) != run_version:
                raise InputError("PQPC_RESULT_CACHE_STALE", "runVersion", "Source version changed while Preview was running")
            active = [key for key, value in self._preview_records.items() if value["status"] == "active"]
            if len(active) >= MAX_ACTIVE_PREVIEWS: self._preview_records[active[0]]["status"] = "evicted"
            self._preview_records[preview_id] = preview_record
        return response

    def cache_problem_preview(self, chain_id: str, preview_id: str, workbook: Any) -> bool:
        """Keep at most five full, validated values packages in this panel session.

        No preview or approval identifier is retained in this cache. A restore
        is a separate, explicit write attempt against the committed HEAD.
        """
        with self._lock:
            preview = self._preview_records.get(preview_id)
            if preview is None or preview["status"] != "consumed":
                return False
            if preview.get("problemChainId") != chain_id or preview.get("runVersion") != self._problem_data_versions.get(chain_id, 0):
                return False
            revision = self._revisions.get(preview["revisionId"])
            if revision is None:
                return False
            encoded = preview["resultWorkbookBase64"]
            if len(encoded) > MAX_PROBLEM_RESULT_CACHE_BYTES:
                return False
            key = (chain_id, preview["revisionId"])
            self._problem_result_cache.pop(key, None)
            while self._problem_result_cache and (
                len(self._problem_result_cache) >= MAX_ACTIVE_PREVIEWS
                or sum(len(item["resultWorkbookBase64"]) for item in self._problem_result_cache.values())
                + len(encoded) > MAX_PROBLEM_RESULT_CACHE_BYTES
            ):
                self._problem_result_cache.pop(next(iter(self._problem_result_cache)))
            self._problem_result_cache[key] = {
                "chainId": chain_id, "workbookKey": preview["workbookKey"],
                "revisionId": preview["revisionId"],
                "dataVersion": preview["runVersion"],
                "reviewHash": revision["public"]["revision"]["reviewHash"],
                "sourceFingerprint": preview["sourceFingerprint"],
                "sourceSheetNames": preview["sourceSheetNames"],
                "resultWorkbookBase64": encoded,
                "resultWorkbookSheetName": preview["resultWorkbookSheetName"],
                "resultRows": preview["resultRows"], "resultColumns": preview["resultColumns"],
            }
            return True

    def prepare_cached_problem_result(
        self, *, chain_id: str, revision_id: str, review_hash: str,
        workbook: Any, workbook_base64: Any, destination_marker: Any,
    ) -> dict[str, Any]:
        """Approve an explicit restore click after independently checking input data."""
        if destination_marker != DESTINATION_MARKER:
            raise InputError("PQV2_APPROVAL_MISMATCH", "destinationMarker", "Typed result marker is invalid")
        key = (chain_id, revision_id)
        with self._lock:
            cached = self._problem_result_cache.get(key)
        if cached is None:
            raise InputError("PQPC_RESULT_CACHE_MISS", "revisionId", "Full result cache is unavailable; preview this revision again")
        if cached["reviewHash"] != review_hash or cached["workbookKey"] != self._workbook_key(workbook):
            raise InputError("PQPC_RESULT_CACHE_STALE", "revisionId", "Revision or workbook identity changed; preview again")
        if cached["dataVersion"] != self.problem_data_version(chain_id):
            raise InputError("PQPC_RESULT_CACHE_STALE", "dataVersion", "Result belongs to an older source version; preview again")
        payload = decode_workbook_export(workbook_base64)
        current = workbook_data_fingerprint(
            payload, typed_result_source_sheets=cached["sourceSheetNames"],
        )
        if current != cached["sourceFingerprint"]:
            raise InputError("PQPC_RESULT_CACHE_STALE", "workbookBase64", "Source data changed since this result was previewed")
        apply_id = _random_id("apply")
        attempt = {
            "applyId": apply_id, "approvalId": None, "status": "prepared",
            "marker": destination_marker, "expectedRows": cached["resultRows"],
            "expectedColumns": cached["resultColumns"], "resultSheetName": "PQ_Typed_Result",
        }
        with self._lock:
            if (self._problem_result_cache.get(key) is not cached
                    or cached["dataVersion"] != self._problem_data_versions.get(chain_id, 0)):
                raise InputError("PQPC_RESULT_CACHE_STALE", "revisionId", "Cached result changed during preparation")
            self._applies[apply_id] = attempt
        return {
            "applyId": apply_id, "resultWorkbookBase64": cached["resultWorkbookBase64"],
            "resultWorkbookSheetName": cached["resultWorkbookSheetName"],
            "resultSheetName": attempt["resultSheetName"], "expectedRows": attempt["expectedRows"],
            "expectedColumns": attempt["expectedColumns"], "destinationMarker": destination_marker,
        }

    def approve(self, revision_id: Any, preview_id: Any, destination_marker: Any) -> dict[str, Any]:
        record = self._record(revision_id)
        public = record["public"]
        preview = self._preview_records.get(preview_id) if isinstance(preview_id, str) else None
        if destination_marker != DESTINATION_MARKER:
            raise InputError("PQV2_APPROVAL_MISMATCH", "destinationMarker", "Typed result marker is invalid")
        if preview is None or preview["status"] != "active" or preview["revisionId"] != revision_id or self._latest_by_plan.get(public["planId"]) != revision_id:
            raise InputError("PQV2_PREVIEW_STALE", "previewId", "Approval requires the current successful preview")
        if preview.get("problemChainId") is not None and preview.get("runVersion") != self.problem_data_version(preview["problemChainId"]):
            raise InputError("PQPC_RESULT_CACHE_STALE", "runVersion", "Source version changed after Preview")
        approval_id = _random_id("apr")
        approval = {
            "approvalId": approval_id, "planId": public["planId"], "revisionId": revision_id,
            "snapshotId": public["snapshotId"], "previewId": preview_id,
            "reviewHash": public["revision"]["reviewHash"], "destinationMarker": destination_marker,
            "status": "approved", "approvedAt": _now(),
        }
        with self._lock: self._approvals[approval_id] = approval
        return {key: value for key, value in approval.items() if key != "planId"}

    def prepare_apply(self, approval_id: Any, workbook_base64: Any, destination: Any) -> dict[str, Any]:
        approval = self._approvals.get(approval_id) if isinstance(approval_id, str) else None
        if approval is None:
            raise InputError("PQV2_APPROVAL_REQUIRED", "approvalId", "A server-issued approval is required")
        if approval["status"] == "used":
            raise InputError("PQV2_APPROVAL_USED", "approvalId", "Approval has already been consumed")
        if approval["status"] != "approved":
            raise InputError("PQV2_APPROVAL_MISMATCH", "approvalId", "Approval is no longer valid")
        if not isinstance(destination, dict) or destination.get("marker") != approval["destinationMarker"]:
            raise InputError("PQV2_APPROVAL_MISMATCH", "destination", "Destination differs from the approved marker")
        preview = self._preview_records.get(approval["previewId"])
        record = self._record(approval["revisionId"])
        if preview is None or preview["status"] != "active" or self._latest_by_plan.get(approval["planId"]) != approval["revisionId"] or record["public"]["revision"]["reviewHash"] != approval["reviewHash"]:
            approval["status"] = "invalidated"
            raise InputError("PQV2_APPROVAL_MISMATCH", "approvalId", "Revision or preview changed after approval")
        if preview.get("problemChainId") is not None and preview.get("runVersion") != self.problem_data_version(preview["problemChainId"]):
            approval["status"] = "invalidated"
            raise InputError("PQPC_RESULT_CACHE_STALE", "runVersion", "Source version changed after Preview")
        payload = decode_workbook_export(workbook_base64)
        if workbook_data_fingerprint(payload, typed_result_source_sheets=preview["sourceSheetNames"]) != preview["sourceFingerprint"]:
            approval["status"] = "invalidated"
            raise InputError("PQV2_SOURCE_CHANGED", "workbookBase64", "Workbook changed after preview")
        approval["status"] = "used"
        preview["status"] = "consumed"
        apply_id = _random_id("apply")
        attempt = {
            "applyId": apply_id, "approvalId": approval_id, "status": "prepared",
            "previewId": approval["previewId"], "problemChainId": preview.get("problemChainId"),
            "marker": approval["destinationMarker"], "expectedRows": preview["resultRows"],
            "expectedColumns": preview["resultColumns"], "resultSheetName": "PQ_Typed_Result",
        }
        self._applies[apply_id] = attempt
        return {
            "applyId": apply_id, "resultWorkbookBase64": preview["resultWorkbookBase64"],
            "resultWorkbookSheetName": preview["resultWorkbookSheetName"],
            "resultSheetName": attempt["resultSheetName"], "expectedRows": attempt["expectedRows"],
            "expectedColumns": attempt["expectedColumns"], "destinationMarker": attempt["marker"],
        }

    def complete_apply(self, apply_id: Any, readback: Any) -> dict[str, Any]:
        attempt = self._applies.get(apply_id) if isinstance(apply_id, str) else None
        if attempt is None or attempt["status"] != "prepared":
            raise InputError("PQV2_APPLY_READBACK_FAILED", "applyId", "Apply attempt is missing or already completed")
        valid = (
            isinstance(readback, dict) and readback.get("marker") == attempt["marker"]
            and readback.get("rowCount") == attempt["expectedRows"]
            and readback.get("columnCount") == attempt["expectedColumns"]
            and isinstance(readback.get("sheetName"), str) and bool(readback["sheetName"])
        )
        attempt["status"] = "applied" if valid else "applyFailed"
        attempt["completedAt"] = _now()
        if not valid:
            raise InputError("PQV2_APPLY_READBACK_FAILED", "readback", "Worksheet read-back does not match the approved result")
        cached = False
        if attempt.get("problemChainId") is not None:
            cached = self.cache_problem_preview(attempt["problemChainId"], attempt["previewId"], None)
        return {"applyId": apply_id, "status": "applied", "readback": deepcopy(readback), "resultCached": cached}

    def cancel_problem_preview(self, chain_id: str, revision_id: str, preview_id: str) -> None:
        with self._lock:
            preview = self._preview_records.get(preview_id)
            if preview is None or preview.get("problemChainId") != chain_id or preview.get("revisionId") != revision_id or preview["status"] != "active":
                raise InputError("PQV2_PREVIEW_STALE", "previewId", "Staging Preview is no longer active")
            preview["status"] = "cancelled"
            preview.pop("resultWorkbookBase64", None)

    def repair(self, revision_id: Any, snapshot_id: Any, error: Any) -> dict[str, Any]:
        record = self._record(revision_id)
        public = record["public"]
        if snapshot_id != public["snapshotId"] or not isinstance(error, dict):
            raise InputError("PQV2_PATCH_STALE", "snapshotId", "Repair input is stale or invalid")
        failed_step_id = error.get("failedStepId")
        existing_ids = {step["stepId"] for step in public["steps"]}
        affected = []
        frontier = {failed_step_id} if failed_step_id in existing_ids else {
            step["stepId"] for step in public["steps"]
            if any(item["ref"] == failed_step_id for item in step["inputs"])
        }
        while frontier:
            current = frontier.pop()
            if current in affected: continue
            affected.append(current)
            frontier.update(step["stepId"] for step in public["steps"] if any(item["ref"] == current for item in step["inputs"]))
        options = []
        parent_id = public["revision"]["parentRevisionId"]
        if parent_id and parent_id in self._revisions:
            parent_steps = self._revisions[parent_id]["public"]["steps"]
            deleted = [step for step in parent_steps if step["stepId"] not in existing_ids]
            if deleted:
                restored = deleted[-1]
                previous = parent_steps[parent_steps.index(restored) - 1]["stepId"] if parent_steps.index(restored) else None
                restored_id = _random_id("stp")
                replacements = {restored["stepId"]: restored_id}
                input_column_ids: set[str] = set()
                for input_ref in restored["inputs"]:
                    producer = next((item for item in parent_steps if item["stepId"] == input_ref["ref"]), None)
                    if producer:
                        input_column_ids.update(item["columnId"] for item in producer["outputContract"]["columns"])
                for column in restored["outputContract"]["columns"]:
                    if column["columnId"] not in input_column_ids:
                        replacements[column["columnId"]] = _new_column(
                            restored_id, column["name"], column["inferredType"], column["ordinal"],
                            nullable=column.get("nullable", True), nested_schema=column.get("nestedSchema"),
                        )["columnId"]
                reconnect = []
                for step in public["steps"]:
                    updated_inputs = _replace_refs(step["inputs"], replacements)
                    updated_operation = _replace_refs(step["operation"], replacements)
                    if updated_inputs != step["inputs"] or updated_operation != step["operation"]:
                        reconnect.append({
                            "type": "updateStep", "stepId": step["stepId"],
                            "stepDraft": {"inputs": updated_inputs, "operation": updated_operation},
                        })
                options.append({
                    "rank": 1, "label": f"Restore {restored['variableName']}",
                    "rationale": "Restore the deleted producer instead of removing dependent business logic.",
                    "semanticImpact": f"Restores the previous operation {restored['operation']['type']}.",
                    "risks": ["Review the restored business expression before preview."],
                    "changes": [{
                        "type": "insertStep", "afterStepId": previous, "_serverStepId": restored_id,
                        "stepDraft": {key: deepcopy(value) for key, value in restored.items() if key not in {"stepId", "position", "outputContract"}},
                    }, *reconnect],
                })
        surviving = [step["stepId"] for step in public["steps"] if step["stepId"] not in affected]
        if affected and surviving:
            options.append({
                "rank": len(options) + 1, "label": "Remove broken downstream steps",
                "rationale": "Make the graph structurally executable by removing the failed branch.",
                "semanticImpact": "Removes transformations and can materially change the business result.",
                "risks": ["The original filtering/calculation intent may be lost."],
                "changes": [
                    *[{"type": "deleteStep", "stepId": step_id} for step_id in reversed(affected)],
                    {"type": "setFinalOutput", "stepId": surviving[-1]},
                ],
            })
        if not options:
            return {
                "status": "needsClarification",
                "questions": ["Which existing column or business rule should replace the missing reference?"],
                "diagnosis": {"rootCause": str(error.get("message") or error.get("code") or "Unknown runtime error"), "affectedStepIds": affected, "evidence": [], "confidence": "low"},
                "recommendedPatchId": None, "patchOptions": [],
            }
        public_options = []
        for option in options[:3]:
            patch_id = _random_id("patch")
            patch = {**option, "patchId": patch_id, "baseRevisionId": revision_id, "snapshotId": snapshot_id}
            self._patches[patch_id] = patch
            public_options.append({
                "patchId": patch_id, "rank": option["rank"], "label": option["label"],
                "rationale": option["rationale"], "semanticImpact": option["semanticImpact"],
                "risks": option["risks"],
                "changes": [{key: deepcopy(value) for key, value in change.items() if key not in {"stepDraft", "_serverStepId"}} for change in option["changes"]],
                "preconditions": {"baseRevisionId": revision_id, "snapshotId": snapshot_id},
            })
        return {
            "status": "repairProposed",
            "diagnosis": {
                "rootCause": str(error.get("message") or "A producer/reference required by the failed step is missing."),
                "affectedStepIds": affected, "evidence": ["Repair was derived from the stored immutable revision graph."],
                "confidence": "high" if parent_id else "medium",
            },
            "recommendedPatchId": public_options[0]["patchId"], "patchOptions": public_options,
        }
