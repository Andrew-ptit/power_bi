"""Problem Chain v1 domain model for Typed Steps.

This module owns no Office.js or HTTP behavior.  Mutations are prepared as
immutable candidates, persisted by the task pane, and become committed only
after a matching Custom XML read-back hash is supplied.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
import re
import secrets
from threading import Lock
from typing import Any, Protocol

from pbip_assistant.errors import InputError
from pbip_assistant.core.limits import MAX_PROMPT_CHARS
from pbip_assistant.powerquery.typed.validation import _normalize_steps
from pbip_assistant.powerquery.typed.compiler import compile_m

# The Codex continuation adapter moved to
# pbip_assistant.adapters.codex.problem_chain. These names stay importable from
# this module for existing callers; a test that replaces them must patch the
# adapter module, which is where the planner resolves them.
from pbip_assistant.adapters.codex.problem_chain import (
    CONTINUATION_SCHEMA_PATH,
    MAX_RESPONSE_CHARS,
    CodexProblemChainPlanner,
    _continuation_failure_code,
    _load_and_preflight_continuation_schema,
    find_codex_executable,
)
from .mutations import (
    _clarification_response,
    _collect_column_ids,
    _continuation_plan,
    _descendant_impact_report,
    _manual_edit_plan,
    _now,
    _random_id,
    _revision_from_plan,
    _validate_continuation_proposal_shape,
)
from pbip_assistant.powerquery.history.document import (
    SCHEMA_VERSION,
    TYPE_INFERENCE_POLICY,
    MAX_REVISIONS,
    MAX_CANONICAL_JSON_BYTES,
    MAX_PENDING_MUTATIONS,
    _REVISION_ID,
    _CHAIN_ID,
    _PLAN_ID,
    _HASH,
    _FORBIDDEN_KEYS,
    _FORBIDDEN_KEYS_CASEFOLD,
    _CHAIN_DOCUMENT_KEYS,
    _DOCUMENT_KEYS,
    _REVISION_KEYS,
    _SOURCE_COMMON_KEYS,
    _SOURCE_TABLE_KEYS,
    _SOURCE_RANGE_KEYS,
    _COLUMN_KEYS,
    _analyze_semantic_plan,
    _bare_chain,
    _hash,
    _normalized_schema_source,
    _persisted_sources,
    _reject_non_finite,
    _scan_forbidden,
    _validate_chain_fields,
    _validate_persisted_source,
    _validate_revision,
    _validate_semantic_plan,
    canonical_json,
    compute_history_hash,
    compute_review_hash,
    source_schema_fingerprint,
    validate_document,
)




class ContinuationPlanner(Protocol):
    def propose(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ProblemChainStore:
    """In-memory coordinator state for CAS-bound Problem Chain mutations."""

    def __init__(self, planner: ContinuationPlanner | None = None) -> None:
        self.planner = planner
        self._lock = Lock()
        self._generation = 0
        self._active_chain_id: str | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._committed: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        with self._lock:
            self._generation += 1
            self._active_chain_id = None
            self._pending.clear()
            self._committed.clear()

    def load(self, document: Any) -> dict[str, Any]:
        validated = validate_document(document)
        with self._lock:
            # Workbook Custom XML is the persistence source of truth.  Loading
            # a workbook replaces, rather than accumulates, session history so
            # a revision from a previously opened workbook cannot be activated.
            self._generation += 1
            self._active_chain_id = validated["chainId"]
            self._pending.clear()
            self._committed.clear()
            self._committed[validated["chainId"]] = deepcopy(validated)
        return {"document": validated, "historyHash": compute_history_hash(validated)}

    def active_revision(self, revision_id: Any) -> dict[str, Any] | None:
        """Look up a committed head for the head-bound preview/approval bridge."""
        if not isinstance(revision_id, str):
            return None
        with self._lock:
            for document in self._committed.values():
                revision = next(
                    (item for item in document["revisions"] if item["revisionId"] == revision_id),
                    None,
                )
                if revision is None:
                    continue
                if document["headRevisionId"] != revision_id:
                    raise InputError(
                        "PQPC_HEAD_MISMATCH", "revisionId",
                        "Preview, approval and apply require the committed head revision",
                    )
                return {
                    "chainId": document["chainId"], "planId": document["planId"],
                    "revision": deepcopy(revision), "historyHash": compute_history_hash(document),
                    "parentRevision": deepcopy(next((
                        item for item in document["revisions"]
                        if item["revisionId"] == revision["parentRevisionId"]
                    ), None)),
                }
        return None

    def has_active_chain(self) -> bool:
        with self._lock:
            return self._active_chain_id is not None

    @staticmethod
    def _assert_cas(document: dict[str, Any], base_history_hash: Any) -> str:
        actual = compute_history_hash(document)
        if base_history_hash != actual:
            raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "History changed; reload before retrying")
        return actual

    def _candidate(
        self, document: dict[str, Any], base_hash: str | None,
        revision: dict[str, Any], expected_generation: int, *,
        creation_mode: str | None = None,
        impact_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_document(document)
        history_hash = compute_history_hash(document)
        mutation_id = _random_id("mut")
        envelope = {
            "mutationId": mutation_id, "baseHistoryHash": base_hash,
            "document": deepcopy(document), "historyHash": history_hash,
            "revision": deepcopy(revision),
        }
        if creation_mode is not None:
            envelope["creationMode"] = creation_mode
        if impact_report is not None:
            envelope["impactReport"] = deepcopy(impact_report)
        with self._lock:
            if self._generation != expected_generation:
                raise InputError(
                    "PQPC_HISTORY_CONFLICT", "baseHistoryHash",
                    "The loaded workbook history changed while the mutation was being prepared",
                )
            while len(self._pending) >= MAX_PENDING_MUTATIONS:
                self._pending.pop(next(iter(self._pending)))
            self._pending[mutation_id] = {
                "envelope": deepcopy(envelope),
                "generation": expected_generation,
            }
        return envelope

    @staticmethod
    def _preflight_append_size(document: dict[str, Any], base_revision: dict[str, Any], prompt: str) -> None:
        """Reject guaranteed overflow before invoking an untrusted/expensive planner.

        The lower-bound revision reuses the current semantic payload.  The exact
        candidate is checked again after planning because a planner can add steps.
        """
        lower_revision = deepcopy(base_revision)
        lower_revision.update({
            "revisionId": "rev_" + "0" * 24,
            "parentRevisionId": base_revision["revisionId"],
            "createdAt": "2000-01-01T00:00:00+00:00",
            "problemPrompt": prompt,
            "changeReason": "Continued problem chain",
        })
        lower_revision["reviewHash"] = compute_review_hash(lower_revision)
        lower_document = deepcopy(document)
        lower_document["storageVersion"] += 1
        lower_document["revisions"].append(lower_revision)
        lower_document["headRevisionId"] = lower_revision["revisionId"]
        if len(canonical_json(lower_document)) > MAX_CANONICAL_JSON_BYTES:
            raise InputError("PQPC_HISTORY_LIMIT", "$", "Another revision cannot fit within the 2 MiB history limit")

    @staticmethod
    def _continuation_sources(
        base_revision: dict[str, Any], source_catalog: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Validate the current catalog and preserve reviewed IDs for existing sources."""
        if source_catalog is None:
            return deepcopy(base_revision["sources"])
        if not isinstance(source_catalog, list) or not source_catalog:
            raise InputError("PQPC_SOURCE_SCHEMA_CHANGED", "sourceCatalog", "Current workbook sources are missing")
        if len(source_catalog) > 20:
            raise InputError("PQV2_SOURCE_LIMIT", "sourceCatalog", "Typed continuations support at most 20 sources")
        current = deepcopy(source_catalog)
        for index, source in enumerate(current):
            _validate_persisted_source(source, f"sourceCatalog[{index}]")

        def identity(source: dict[str, Any]) -> tuple[Any, ...]:
            if source["kind"] == "excelTable":
                return ("excelTable", source["objectName"])
            return ("usedRange", source["sheetName"], source["headerRow"])

        current_by_identity: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for source in current:
            current_by_identity.setdefault(identity(source), []).append(source)
        if len({source["sourceId"] for source in current}) != len(current):
            raise InputError("PQPC_DOCUMENT_INVALID", "sourceCatalog", "Source IDs must be unique")
        if any(len(matches) != 1 for matches in current_by_identity.values()):
            raise InputError("PQPC_DOCUMENT_INVALID", "sourceCatalog", "Source identities must be unique")
        matched_current: list[dict[str, Any]] = []
        base_identities: set[tuple[Any, ...]] = set()
        for persisted in base_revision["sources"]:
            key = identity(persisted)
            base_identities.add(key)
            matches = current_by_identity.get(key, [])
            if len(matches) != 1:
                raise InputError(
                    "PQPC_SOURCE_SCHEMA_CHANGED", "sourceCatalog",
                    "A source used by the current head is missing or ambiguous",
                )
            matched_current.append(matches[0])
        if source_schema_fingerprint(matched_current) != base_revision["sourceSchemaFingerprint"]:
            raise InputError(
                "PQPC_SOURCE_SCHEMA_CHANGED", "sourceCatalog",
                "A source used by the current head changed columns or inferred types",
            )

        # Keep reviewed sourceId/columnId lineage for the existing pipeline.
        # New sources use IDs allocated by the current workbook catalog.
        combined = deepcopy(base_revision["sources"])
        known_source_ids = {source["sourceId"] for source in combined}
        for source in current:
            if identity(source) in base_identities:
                continue
            if source["sourceId"] in known_source_ids:
                raise InputError("PQPC_DOCUMENT_INVALID", "sourceCatalog", "Source IDs must be unique")
            combined.append(source)
            known_source_ids.add(source["sourceId"])
        return combined

    @staticmethod
    def _new_chain_document(revision: dict[str, Any], archived_chains: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the document for a chain whose root revision is already known.

        Both creation paths (fresh chain and new root reusing an existing chain)
        need exactly this shape; keeping it in one place stops the two copies
        from drifting in field order or default values.
        """
        return {
            "schemaVersion": SCHEMA_VERSION, "chainId": _random_id("chain"),
            "planId": _random_id("plan"), "storageVersion": 1,
            "headRevisionId": revision["revisionId"],
            "samplePersistence": {"enabled": False, "warningAcceptedAt": None, "maxRows": 20, "maxColumns": 200},
            "sampleStore": {}, "revisions": [revision], "archivedChains": archived_chains,
        }


    def _check_request(
        self, prompt: Any, creation_mode: Any, base_revision_id: Any, edit_revision_id: Any,
    ) -> None:
        """Reject a malformed request before any history is read."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise InputError("PROMPT_REQUIRED", "prompt", "Enter a problem before creating a revision")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise InputError("PROMPT_LIMIT", "prompt", "Problem exceeds 4000 characters")
        if not isinstance(creation_mode, str) or creation_mode not in {"continue", "branch", "editProblem", "newRoot"}:
            raise InputError("PQPC_DOCUMENT_INVALID", "creationMode", "Unknown problem creation mode")
        if base_revision_id is not None and not isinstance(base_revision_id, str):
            raise InputError("PQPC_DOCUMENT_INVALID", "baseRevisionId", "Base revision ID must be text or null")
        if edit_revision_id is not None and not isinstance(edit_revision_id, str):
            raise InputError("PQPC_DOCUMENT_INVALID", "editRevisionId", "Edit revision ID must be text or null")

    def _create_root_problem(
        self, *, typed_plan: dict[str, Any] | None, prompt: str, base_history_hash: str | None,
        base_revision_id: str | None, creation_mode: str, edit_revision_id: str | None,
        expected_generation: int, expected_active_chain_id: str | None,
    ) -> dict[str, Any]:
        """First revision of a workbook with no history yet."""
        if creation_mode != "continue" or edit_revision_id is not None:
            raise InputError("PQPC_DOCUMENT_INVALID", "creationMode", "A root problem must use continue mode")
        if base_history_hash is not None or base_revision_id is not None or typed_plan is None:
            raise InputError("PQPC_DOCUMENT_INVALID", "document", "A root problem requires only a typed plan")
        if expected_active_chain_id is not None:
            raise InputError("PQPC_HISTORY_CONFLICT", "document", "A workbook history is already loaded")
        if isinstance(typed_plan, dict) and typed_plan.get("questions"):
            return _clarification_response(
                typed_plan["questions"], typed_plan.get("assumptions", []), typed_plan.get("warnings", []),
            )
        revision = _revision_from_plan(typed_plan, prompt=prompt, parent_revision_id=None, change_reason="Created problem chain")
        candidate = self._new_chain_document(revision, [])
        return self._candidate(
            candidate, None, revision, expected_generation, creation_mode="continue",
        )

    def _check_active_chain(
        self, current: dict[str, Any], base_hash: str, expected_generation: int, expected_active_chain_id: str | None,
    ) -> None:
        """Recheck the loaded history and the committed chain under the lock."""
        with self._lock:
            if self._generation != expected_generation:
                raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "The loaded workbook history changed")
            if expected_active_chain_id is not None:
                committed = self._committed.get(current["chainId"])
                if expected_active_chain_id != current["chainId"] or committed is None:
                    raise InputError("PQPC_HISTORY_CONFLICT", "chainId", "A different workbook chain is active")
                if compute_history_hash(committed) != base_hash:
                    raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "A newer history is already committed")

    def _check_mode_preconditions(
        self, current: dict[str, Any], by_id: dict[str, Any], base_id: str,
        creation_mode: str, edit_revision_id: str | None,
    ) -> None:
        """Reject a continuation, branch or edit that would break the tree shape."""
        if creation_mode == "continue":
            if edit_revision_id is not None:
                raise InputError("PQPC_DOCUMENT_INVALID", "editRevisionId", "Continue mode cannot edit an old problem")
            if base_id != current["headRevisionId"]:
                raise InputError("PQPC_HEAD_MISMATCH", "baseRevisionId", "Continuation must use the current head")
            if any(item["parentRevisionId"] == base_id for item in current["revisions"]):
                raise InputError(
                    "PQPC_BRANCH_INTENT_REQUIRED", "creationMode",
                    "The selected revision already has a child; explicitly create a branch",
                )
        elif creation_mode == "branch":
            if edit_revision_id is not None:
                raise InputError("PQPC_DOCUMENT_INVALID", "editRevisionId", "Branch mode cannot edit a problem")
        else:
            edited = by_id.get(edit_revision_id or "")
            if edited is None:
                raise InputError("PQPC_REVISION_NOT_FOUND", "editRevisionId", "Problem revision to edit does not exist")
            if edited["originKind"] != "problem":
                raise InputError(
                    "PQPC_EDIT_TARGET_INVALID", "editRevisionId",
                    "Only a revision created from a user problem can use editProblem",
                )
            parent_id = edited["parentRevisionId"]
            if parent_id is None:
                raise InputError(
                    "PQPC_EDIT_ROOT_UNSUPPORTED", "editRevisionId",
                    "The root problem cannot be edited because a chain has exactly one root",
                )
            if base_id != parent_id:
                raise InputError(
                    "PQPC_EDIT_BASE_MISMATCH", "baseRevisionId",
                    "An edited problem must create a sibling from its original parent",
                )

    def create_problem(
        self, document: dict[str, Any] | None, base_history_hash: str | None,
        prompt: Any, *, base_revision_id: str | None = None,
        creation_mode: str = "continue", edit_revision_id: str | None = None,
        typed_plan: dict[str, Any] | None = None,
        source_catalog: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            expected_generation = self._generation
            expected_active_chain_id = self._active_chain_id
        self._check_request(prompt, creation_mode, base_revision_id, edit_revision_id)
        if document is None:
            return self._create_root_problem(
                typed_plan=typed_plan, prompt=prompt, base_history_hash=base_history_hash,
                base_revision_id=base_revision_id, creation_mode=creation_mode,
                edit_revision_id=edit_revision_id, expected_generation=expected_generation,
                expected_active_chain_id=expected_active_chain_id,
            )

        current = validate_document(document)
        base_hash = self._assert_cas(current, base_history_hash)
        self._check_active_chain(current, base_hash, expected_generation, expected_active_chain_id)
        if creation_mode == "newRoot":
            if base_revision_id is not None or edit_revision_id is not None or typed_plan is None:
                raise InputError(
                    "PQPC_DOCUMENT_INVALID", "creationMode",
                    "A new root requires a fresh typed plan and no base revision",
                )
            total_revisions = len(current["revisions"]) + sum(
                len(chain["revisions"]) for chain in current.get("archivedChains", [])
            )
            if total_revisions >= MAX_REVISIONS:
                raise InputError("PQPC_HISTORY_LIMIT", "revisions", "Total revision count has reached 50")
            if isinstance(typed_plan, dict) and typed_plan.get("questions"):
                return _clarification_response(
                    typed_plan["questions"], typed_plan.get("assumptions", []), typed_plan.get("warnings", []),
                )
            revision = _revision_from_plan(
                typed_plan, prompt=prompt, parent_revision_id=None,
                change_reason="Created independent problem chain",
            )
            candidate = self._new_chain_document(
                revision, deepcopy(current.get("archivedChains", [])) + [_bare_chain(current)],
            )
            return self._candidate(
                candidate, base_hash, revision, expected_generation, creation_mode="newRoot",
            )
        by_id = {item["revisionId"]: item for item in current["revisions"]}
        base_id = base_revision_id or current["headRevisionId"]
        if base_id not in by_id:
            raise InputError("PQPC_REVISION_NOT_FOUND", "baseRevisionId", "Base revision does not exist")
        self._check_mode_preconditions(current, by_id, base_id, creation_mode, edit_revision_id)
        if len(current["revisions"]) >= MAX_REVISIONS:
            raise InputError("PQPC_HISTORY_LIMIT", "revisions", "Revision count has reached 50")
        self._preflight_append_size(current, by_id[base_id], prompt)
        continuation_sources = self._continuation_sources(by_id[base_id], source_catalog)
        planner_payload: dict[str, Any] | None = None
        if typed_plan is None:
            if self.planner is None:
                raise InputError("PQPC_PLANNER_REQUIRED", "planner", "A continuation planner is required")
            planner_payload = {
                "schemaVersion": SCHEMA_VERSION, "userRequest": prompt,
                "baseRevision": deepcopy(by_id[base_id]),
                "sourceCatalog": deepcopy(continuation_sources),
            }
            proposal = self.planner.propose(planner_payload)
            _validate_continuation_proposal_shape(proposal)
            if proposal["questions"]:
                return _clarification_response(
                    proposal["questions"], proposal["assumptions"], proposal["warnings"],
                )
            try:
                typed_plan = _continuation_plan(
                    by_id[base_id], proposal, source_catalog=continuation_sources,
                )
            except InputError as exc:
                if exc.code == "PQV2_COLUMN_NOT_FOUND":
                    return _clarification_response(
                        ["Một cột được yêu cầu chưa có hoặc tên cột chưa rõ tại bước xử lý. Bạn muốn dùng cột nào đang có, hay tạo cột mới theo quy tắc nào?"],
                        [], [],
                    )
                raise
        else:
            raise InputError(
                "PQPC_DOCUMENT_INVALID", "typedPlan",
                "Continuation accepts only an explicit planner change proposal, not pipeline replacement",
            )
        try:
            revision = _revision_from_plan(
                typed_plan, prompt=prompt, parent_revision_id=base_id,
                change_reason=str(typed_plan.get("changeReason") or "Continued problem chain"),
            )
        except InputError as exc:
            if exc.code == "PQV2_COLUMN_NOT_FOUND":
                return _clarification_response(
                    ["Một cột được yêu cầu chưa có hoặc tên cột chưa rõ tại bước xử lý. Bạn muốn dùng cột nào đang có, hay tạo cột mới theo quy tắc nào?"],
                    [], [],
                )
            retryable_plan_codes = {
                "PQV2_FINAL_OUTPUT_NOT_TABLE",
                "PQV2_NESTED_TABLE_NOT_EXPANDED",
            }
            if (
                exc.code not in retryable_plan_codes
                or planner_payload is None
                or self.planner is None
            ):
                raise
            repaired_payload = deepcopy(planner_payload)
            repaired_payload["validationFeedback"] = {
                "code": exc.code,
                "path": exc.path,
                "instruction": (
                    "Return a complete corrected delta. Preserve the current final step unless a valid "
                    "replacement exists. For Merge, insert Expand downstream and make the expanded flat "
                    "table the final output. Include setFinalOutput as the last change."
                ),
            }
            repaired_proposal = self.planner.propose(repaired_payload)
            _validate_continuation_proposal_shape(repaired_proposal)
            if repaired_proposal["questions"]:
                return _clarification_response(
                    repaired_proposal["questions"], repaired_proposal["assumptions"], repaired_proposal["warnings"],
                )
            try:
                typed_plan = _continuation_plan(
                    by_id[base_id], repaired_proposal, source_catalog=continuation_sources,
                )
                revision = _revision_from_plan(
                    typed_plan, prompt=prompt, parent_revision_id=base_id,
                    change_reason=str(typed_plan.get("changeReason") or "Continued problem chain"),
                )
            except InputError as repaired_exc:
                if repaired_exc.code == "PQV2_COLUMN_NOT_FOUND":
                    return _clarification_response(
                        ["Một cột được yêu cầu chưa có hoặc tên cột chưa rõ tại bước xử lý. Bạn muốn dùng cột nào đang có, hay tạo cột mới theo quy tắc nào?"],
                        [], [],
                    )
                raise
        if (
            revision["steps"] == by_id[base_id]["steps"]
            and revision["finalOutputStepId"] == by_id[base_id]["finalOutputStepId"]
        ):
            questions = revision.get("questions") or []
            if questions:
                raise InputError(
                    "PQPC_CLARIFICATION_REQUIRED", "planner.questions",
                    f"Planner chưa thay đổi bước xử lý. Cần làm rõ: {questions[0]}",
                )
            raise InputError(
                "PQPC_NO_PIPELINE_CHANGE", "planner.changes",
                "Planner không thay đổi bước xử lý hoặc đầu ra; HEAD hiện tại được giữ nguyên",
            )
        candidate = deepcopy(current)
        candidate["storageVersion"] += 1
        candidate["revisions"].append(revision)
        candidate["headRevisionId"] = revision["revisionId"]
        impact_report = None
        if creation_mode == "editProblem":
            impact_report = _descendant_impact_report(current, edit_revision_id)
        return self._candidate(
            candidate, base_hash, revision, expected_generation,
            creation_mode=creation_mode, impact_report=impact_report,
        )

    def checkout(
        self, document: dict[str, Any], base_history_hash: Any, revision_id: Any,
    ) -> dict[str, Any]:
        with self._lock:
            expected_generation = self._generation
        current = validate_document(document)
        base_hash = self._assert_cas(current, base_history_hash)
        by_id = {item["revisionId"]: item for item in current["revisions"]}
        if not isinstance(revision_id, str) or revision_id not in by_id:
            raise InputError("PQPC_REVISION_NOT_FOUND", "revisionId", "Revision does not exist")
        candidate = deepcopy(current)
        candidate["storageVersion"] += 1
        candidate["headRevisionId"] = revision_id
        return self._candidate(candidate, base_hash, by_id[revision_id], expected_generation)

    def activate_chain(
        self, document: dict[str, Any], base_history_hash: Any,
        chain_id: Any, revision_id: Any | None = None,
    ) -> dict[str, Any]:
        """Switch the working chain while preserving every independent tree."""
        with self._lock:
            expected_generation = self._generation
        current = validate_document(document)
        base_hash = self._assert_cas(current, base_history_hash)
        if not isinstance(chain_id, str):
            raise InputError("PQPC_DOCUMENT_INVALID", "chainId", "Target chain ID is required")
        if chain_id == current["chainId"]:
            target_revision = revision_id or current["headRevisionId"]
            return self.checkout(current, base_hash, target_revision)
        archives = current.get("archivedChains", [])
        target_index = next((i for i, item in enumerate(archives) if item["chainId"] == chain_id), None)
        if target_index is None:
            raise InputError("PQPC_REVISION_NOT_FOUND", "chainId", "Problem chain does not exist")
        target = deepcopy(archives[target_index])
        target_by_id = {item["revisionId"]: item for item in target["revisions"]}
        selected_revision_id = revision_id or target["headRevisionId"]
        if selected_revision_id not in target_by_id:
            raise InputError("PQPC_REVISION_NOT_FOUND", "revisionId", "Revision does not exist in the target chain")
        target["headRevisionId"] = selected_revision_id
        target["storageVersion"] += 1
        remaining = [deepcopy(item) for i, item in enumerate(archives) if i != target_index]
        target["archivedChains"] = remaining + [_bare_chain(current)]
        return self._candidate(
            target, base_hash, target_by_id[selected_revision_id], expected_generation,
            creation_mode="activateChain",
        )

    def delete_problem(
        self, document: dict[str, Any], base_history_hash: Any, revision_id: Any,
    ) -> dict[str, Any]:
        """Prepare deletion of one problem and all of its descendants.

        The root is intentionally protected because a valid chain must have
        exactly one root.  This mutation never invokes the planner and never
        rewrites surviving revisions.
        """
        with self._lock:
            expected_generation = self._generation
            expected_active_chain_id = self._active_chain_id
        current = validate_document(document)
        base_hash = self._assert_cas(current, base_history_hash)
        with self._lock:
            committed = self._committed.get(current["chainId"])
            if (
                self._generation != expected_generation
                or expected_active_chain_id != current["chainId"]
                or committed is None
                or compute_history_hash(committed) != base_hash
            ):
                raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "Delete requires the current committed workbook history")
        by_id = {item["revisionId"]: item for item in current["revisions"]}
        if not isinstance(revision_id, str) or revision_id not in by_id:
            raise InputError("PQPC_REVISION_NOT_FOUND", "revisionId", "Problem revision does not exist")
        target = by_id[revision_id]
        if target["parentRevisionId"] is None:
            archives = current.get("archivedChains", [])
            if not archives:
                raise InputError(
                    "PQPC_DELETE_ROOT_UNSUPPORTED", "revisionId",
                    "The last root must be removed by clearing the complete history",
                )
            promoted = deepcopy(archives[-1])
            promoted["archivedChains"] = deepcopy(archives[:-1])
            new_head = next(
                item for item in promoted["revisions"]
                if item["revisionId"] == promoted["headRevisionId"]
            )
            deleted_ids = sorted(item["revisionId"] for item in current["revisions"])
            envelope = self._candidate(promoted, base_hash, new_head, expected_generation)
            envelope["deletedRevisionIds"] = deleted_ids
            with self._lock:
                self._pending[envelope["mutationId"]]["envelope"]["deletedRevisionIds"] = deleted_ids
            return envelope
        children: dict[str, list[str]] = {}
        for item in current["revisions"]:
            parent_id = item["parentRevisionId"]
            if parent_id is not None:
                children.setdefault(parent_id, []).append(item["revisionId"])
        deleted_ids: set[str] = set()
        pending = [revision_id]
        while pending:
            current_id = pending.pop()
            if current_id in deleted_ids:
                continue
            deleted_ids.add(current_id)
            pending.extend(children.get(current_id, ()))
        candidate = deepcopy(current)
        candidate["storageVersion"] += 1
        candidate["revisions"] = [
            item for item in candidate["revisions"] if item["revisionId"] not in deleted_ids
        ]
        if candidate["headRevisionId"] in deleted_ids:
            candidate["headRevisionId"] = target["parentRevisionId"]
        new_head = next(
            item for item in candidate["revisions"]
            if item["revisionId"] == candidate["headRevisionId"]
        )
        envelope = self._candidate(candidate, base_hash, new_head, expected_generation)
        envelope["deletedRevisionIds"] = sorted(deleted_ids)
        # Persist response metadata in the pending envelope as well; commit
        # authority still comes solely from the candidate history hash.
        with self._lock:
            self._pending[envelope["mutationId"]]["envelope"]["deletedRevisionIds"] = sorted(deleted_ids)
        return envelope

    def create_manual_revision(
        self, document: dict[str, Any], base_history_hash: Any, base_revision_id: Any,
        changes: Any, change_reason: Any, *, source_catalog: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Prepare, but do not activate, a manual Typed edit revision."""
        with self._lock:
            expected_generation = self._generation
            expected_active_chain_id = self._active_chain_id
        current = validate_document(document)
        base_hash = self._assert_cas(current, base_history_hash)
        with self._lock:
            committed = self._committed.get(current["chainId"])
            if (
                self._generation != expected_generation
                or expected_active_chain_id != current["chainId"]
                or committed is None
                or compute_history_hash(committed) != base_hash
            ):
                raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "Manual edits require the current committed workbook history")
        by_id = {item["revisionId"]: item for item in current["revisions"]}
        if base_revision_id != current["headRevisionId"]:
            raise InputError("PQPC_HEAD_MISMATCH", "baseRevisionId", "Manual edits require the committed head revision")
        base = by_id.get(base_revision_id)
        if base is None:
            raise InputError("PQPC_REVISION_NOT_FOUND", "baseRevisionId", "Base revision does not exist")
        if any(item["parentRevisionId"] == base_revision_id for item in current["revisions"]):
            raise InputError("PQPC_BRANCHING_NOT_AVAILABLE", "baseRevisionId", "Branch creation is unsupported")
        if len(current["revisions"]) >= MAX_REVISIONS:
            raise InputError("PQPC_HISTORY_LIMIT", "revisions", "Revision count has reached 50")
        self._preflight_append_size(current, base, base["problemPrompt"])
        current_sources = self._continuation_sources(base, source_catalog)
        edited_plan = _manual_edit_plan(
            base, changes, change_reason, source_catalog=current_sources,
        )
        revision = _revision_from_plan(
            edited_plan, prompt=base["problemPrompt"], parent_revision_id=base_revision_id,
            origin_kind="manualEdit", change_reason=change_reason, allow_blocked=True,
        )
        candidate = deepcopy(current)
        candidate["storageVersion"] += 1
        candidate["revisions"].append(revision)
        candidate["headRevisionId"] = revision["revisionId"]
        return self._candidate(candidate, base_hash, revision, expected_generation)

    def commit(self, mutation_id: Any, observed_history_hash: Any) -> dict[str, Any]:
        with self._lock:
            pending_record = self._pending.get(mutation_id) if isinstance(mutation_id, str) else None
            if pending_record is None:
                raise InputError("PQPC_MUTATION_NOT_COMMITTED", "mutationId", "Mutation is missing or already committed")
            if pending_record["generation"] != self._generation:
                raise InputError("PQPC_HISTORY_CONFLICT", "mutationId", "The loaded workbook history changed")
            pending = pending_record["envelope"]
            if observed_history_hash != pending["historyHash"]:
                raise InputError("PQPC_HISTORY_CONFLICT", "observedHistoryHash", "Custom XML read-back differs from candidate")
            document = validate_document(pending["document"])
            previous_active_id = self._active_chain_id
            committed = self._committed.get(previous_active_id) if previous_active_id is not None else None
            if pending["baseHistoryHash"] is None:
                if committed is not None or self._active_chain_id is not None:
                    raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "A history already exists")
            elif committed is None or pending["baseHistoryHash"] != compute_history_hash(committed):
                raise InputError("PQPC_HISTORY_CONFLICT", "baseHistoryHash", "A newer history is already committed")
            self._committed.clear()
            self._committed[document["chainId"]] = deepcopy(document)
            self._active_chain_id = document["chainId"]
            self._generation += 1
            for other_id, other in self._pending.items():
                if other_id != mutation_id:
                    other["envelope"] = None
            del self._pending[mutation_id]
        return {"document": document, "historyHash": compute_history_hash(document)}

