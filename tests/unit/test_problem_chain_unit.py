from __future__ import annotations
from copy import deepcopy
import json
import re
import subprocess
import time
import unittest
from unittest import mock
from pbip_assistant.errors import InputError
from pbip_assistant.problem_chain import (
    MAX_CANONICAL_JSON_BYTES,
    MAX_PENDING_MUTATIONS,
    CodexProblemChainPlanner,
    ProblemChainStore,
    _load_and_preflight_continuation_schema,
    canonical_json,
    compute_history_hash,
    compute_review_hash,
    source_schema_fingerprint,
    validate_document,
)

from tests.support.problem_chain import (typed_plan, FakeContinuationPlanner, LiteralCollisionPlanner, AppendSecondSourcePlanner, MissingSourceContinuationPlanner, MissingFinalThenValidPlanner)

class ProblemChainDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = FakeContinuationPlanner()
        self.store = ProblemChainStore(self.planner)
        self.addCleanup(self.store.close)

    def root(self) -> dict:
        return self.store.create_problem(None, None, "Vấn đề 1", typed_plan=typed_plan())

    def test_independent_roots_keep_separate_chain_ids_and_heads(self) -> None:
        first = self.root()
        first_committed = self.store.commit(first["mutationId"], first["historyHash"])
        first_chain_id = first_committed["document"]["chainId"]
        first_head = first_committed["document"]["headRevisionId"]

        second = self.store.create_problem(
            first_committed["document"], first_committed["historyHash"], "Vấn đề gốc 2",
            creation_mode="newRoot", typed_plan=typed_plan(summary="Đọc bảng Products."),
        )
        self.assertNotEqual(second["document"]["chainId"], first_chain_id)
        self.assertEqual(len(second["document"]["archivedChains"]), 1)
        self.assertEqual(second["document"]["archivedChains"][0]["chainId"], first_chain_id)
        self.assertEqual(second["document"]["archivedChains"][0]["headRevisionId"], first_head)
        second_committed = self.store.commit(second["mutationId"], second["historyHash"])

        activated = self.store.activate_chain(
            second_committed["document"], second_committed["historyHash"], first_chain_id, first_head,
        )
        self.assertEqual(activated["document"]["chainId"], first_chain_id)
        self.assertEqual(activated["document"]["headRevisionId"], first_head)
        self.assertEqual(len(activated["document"]["archivedChains"]), 1)

    def test_root_candidate_commit_and_load_are_hash_bound(self) -> None:
        full_public = typed_plan()
        full_public["approval"] = {"status": "notRequested"}
        full_public["preview"] = None
        full_public["sources"][0]["sampleRows"] = [["secret", 12]]
        candidate = self.store.create_problem(None, None, "Vấn đề 1", typed_plan=full_public)
        self.assertRegex(candidate["revision"]["revisionId"], r"^rev_[0-9a-f]{24}$")
        self.assertRegex(candidate["document"]["chainId"], r"^chain_[0-9a-f]{24}$")
        self.assertEqual(candidate["historyHash"], compute_history_hash(candidate["document"]))
        self.assertNotIn("historyHash", candidate["document"])
        self.assertEqual(candidate["document"]["sampleStore"], {})
        self.assertNotIn("sampleRows", str(candidate["document"]))
        committed = self.store.commit(candidate["mutationId"], candidate["historyHash"])
        self.assertEqual(committed, self.store.load(committed["document"]))
        with self.assertRaises(InputError) as replay:
            self.store.commit(candidate["mutationId"], candidate["historyHash"])
        self.assertEqual(replay.exception.code, "PQPC_MUTATION_NOT_COMMITTED")

    def test_root_preserves_typed_blocker_instead_of_masking_as_persistence_error(self) -> None:
        blocked = typed_plan()
        blocked["steps"][0]["operation"]["parameters"]["sourceId"] = "src_missing"
        blocked["planStatus"] = "blocked"
        blocked["hardBlockers"] = [{
            "code": "PQV2_SOURCE_NOT_FOUND",
            "path": "steps[0].operation.parameters.sourceId",
            "target": "stp_source",
            "reason": "Source does not exist or has the wrong kind",
            "remedy": "Select an existing workbook source",
        }]
        with self.assertRaises(InputError) as caught:
            self.store.create_problem(None, None, "Blocked root", typed_plan=blocked)
        self.assertEqual(caught.exception.code, "PQV2_SOURCE_NOT_FOUND")
        self.assertEqual(caught.exception.path, "steps[0].operation.parameters.sourceId")
        self.assertEqual(caught.exception.detail, "Source does not exist or has the wrong kind")

    def test_continuation_missing_source_reports_exact_step_and_preserves_head(self) -> None:
        store = ProblemChainStore(MissingSourceContinuationPlanner())
        self.addCleanup(store.close)
        root_candidate = store.create_problem(None, None, "Root", typed_plan=typed_plan())
        committed = store.commit(root_candidate["mutationId"], root_candidate["historyHash"])
        root_id = committed["document"]["headRevisionId"]
        before = store.active_revision(root_id)
        with self.assertRaises(InputError) as caught:
            store.create_problem(
                committed["document"], committed["historyHash"], "Use missing source",
                base_revision_id=root_id,
                source_catalog=deepcopy(committed["document"]["revisions"][0]["sources"]),
            )
        self.assertEqual(caught.exception.code, "PQV2_SOURCE_NOT_FOUND")
        self.assertEqual(caught.exception.path, "steps[1].operation.parameters.sourceId")
        self.assertEqual(store.active_revision(root_id), before)
        self.assertEqual(store.load(committed["document"])["historyHash"], committed["historyHash"])

    def test_abandoned_pending_mutations_are_memory_bounded(self) -> None:
        candidates = [self.root() for _ in range(MAX_PENDING_MUTATIONS + 1)]
        with self.assertRaises(InputError) as evicted:
            self.store.commit(candidates[0]["mutationId"], candidates[0]["historyHash"])
        self.assertEqual(evicted.exception.code, "PQPC_MUTATION_NOT_COMMITTED")
        committed = self.store.commit(candidates[-1]["mutationId"], candidates[-1]["historyHash"])
        self.assertEqual(committed["document"]["headRevisionId"], candidates[-1]["revision"]["revisionId"])

    def test_continuation_preserves_parent_and_old_revision_deep_equal(self) -> None:
        root = self.root()
        old_revision = deepcopy(root["revision"])
        next_candidate = self.store.create_problem(
            root["document"], root["historyHash"], "Vấn đề 2",
            base_revision_id=root["revision"]["revisionId"],
        )
        self.assertEqual(root["document"]["revisions"][0], old_revision)
        self.assertEqual(next_candidate["document"]["revisions"][0], old_revision)
        self.assertEqual(next_candidate["revision"]["parentRevisionId"], old_revision["revisionId"])
        self.assertNotEqual(next_candidate["revision"]["revisionId"], old_revision["revisionId"])
        self.assertEqual(next_candidate["document"]["headRevisionId"], next_candidate["revision"]["revisionId"])
        self.assertEqual(len(self.planner.calls), 1)
        self.assertEqual(self.planner.calls[0]["baseRevision"], old_revision)
        self.assertEqual(next_candidate["revision"]["steps"][0]["stepId"], "stp_source")
        self.assertRegex(next_candidate["revision"]["steps"][1]["stepId"], r"^stp_[0-9a-f]{24}$")

    def test_checkout_is_candidate_and_does_not_delete_descendant(self) -> None:
        root = self.root()
        second = self.store.create_problem(root["document"], root["historyHash"], "Vấn đề 2")
        checked = self.store.checkout(second["document"], second["historyHash"], root["revision"]["revisionId"])
        self.assertEqual(checked["document"]["headRevisionId"], root["revision"]["revisionId"])
        self.assertEqual(checked["document"]["revisions"], second["document"]["revisions"])
        self.assertEqual(checked["document"]["storageVersion"], second["document"]["storageVersion"] + 1)
        with self.assertRaises(InputError) as branch:
            self.store.create_problem(checked["document"], checked["historyHash"], "Nhánh chưa hỗ trợ")
        self.assertEqual(branch.exception.code, "PQPC_BRANCH_INTENT_REQUIRED")

    def test_cas_readback_and_head_fail_closed(self) -> None:
        root = self.root()
        with self.assertRaises(InputError) as stale:
            self.store.create_problem(root["document"], "sha256:" + "0" * 64, "Vấn đề 2")
        self.assertEqual(stale.exception.code, "PQPC_HISTORY_CONFLICT")
        with self.assertRaises(InputError) as readback:
            self.store.commit(root["mutationId"], "sha256:" + "f" * 64)
        self.assertEqual(readback.exception.code, "PQPC_HISTORY_CONFLICT")
        # Failed read-back does not consume the candidate.
        self.store.commit(root["mutationId"], root["historyHash"])
        with self.assertRaises(InputError) as missing:
            self.store.checkout(root["document"], root["historyHash"], "rev_" + "0" * 24)
        self.assertEqual(missing.exception.code, "PQPC_REVISION_NOT_FOUND")

    def test_second_concurrent_candidate_cannot_commit_over_newer_history(self) -> None:
        root = self.root()
        self.store.commit(root["mutationId"], root["historyHash"])
        first = self.store.create_problem(root["document"], root["historyHash"], "Vấn đề A")
        second = self.store.create_problem(root["document"], root["historyHash"], "Vấn đề B")
        self.store.commit(first["mutationId"], first["historyHash"])
        with self.assertRaises(InputError) as conflict:
            self.store.commit(second["mutationId"], second["historyHash"])
        self.assertEqual(conflict.exception.code, "PQPC_HISTORY_CONFLICT")

    def test_manual_edit_is_immutable_candidate_and_has_no_authority_before_commit(self) -> None:
        root = self.root()
        committed = self.store.commit(root["mutationId"], root["historyHash"])
        old_revision = deepcopy(committed["document"]["revisions"][0])
        candidate = self.store.create_manual_revision(
            committed["document"], committed["historyHash"], old_revision["revisionId"],
            [{
                "type": "updateStep", "stepId": "stp_source",
                "stepDraft": {"actionDescription": "Đọc bảng Sales đã chỉnh."},
            }],
            "Edited source description", source_catalog=typed_plan()["sources"],
        )
        self.assertEqual(candidate["document"]["revisions"][0], old_revision)
        self.assertEqual(candidate["revision"]["originKind"], "manualEdit")
        self.assertEqual(candidate["revision"]["parentRevisionId"], old_revision["revisionId"])
        self.assertRegex(candidate["revision"]["revisionId"], r"^rev_[0-9a-f]{24}$")
        self.assertEqual(candidate["revision"]["steps"][0]["stepId"], "stp_source")
        self.assertIsNone(self.store.active_revision(candidate["revision"]["revisionId"]))
        self.assertEqual(
            self.store.active_revision(old_revision["revisionId"])["revision"]["revisionId"],
            old_revision["revisionId"],
        )
        committed_edit = self.store.commit(candidate["mutationId"], candidate["historyHash"])
        self.assertEqual(committed_edit["document"]["headRevisionId"], candidate["revision"]["revisionId"])

    def test_manual_reorder_can_persist_blocked_revision_without_changing_parent(self) -> None:
        root = self.root()
        committed_root = self.store.commit(root["mutationId"], root["historyHash"])
        continued = self.store.create_problem(
            committed_root["document"], committed_root["historyHash"], "Vấn đề 2",
        )
        committed = self.store.commit(continued["mutationId"], continued["historyHash"])
        old_revisions = deepcopy(committed["document"]["revisions"])
        selected = committed["document"]["revisions"][-1]["steps"][-1]
        candidate = self.store.create_manual_revision(
            committed["document"], committed["historyHash"], committed["document"]["headRevisionId"],
            [{"type": "moveStep", "stepId": selected["stepId"], "position": 1}],
            "Moved selected before source", source_catalog=typed_plan()["sources"],
        )
        self.assertEqual(candidate["document"]["revisions"][:-1], old_revisions)
        self.assertEqual(candidate["revision"]["validationAtCreation"]["overall"], "blocked")
        self.assertIsNone(candidate["revision"]["validationAtCreation"]["compiledMHash"])
        self.assertIn(
            "PQV2_DEPENDENCY_INVALID",
            {issue["code"] for issue in candidate["revision"]["validationAtCreation"]["issues"]},
        )

    def test_review_hash_excludes_annotations_runtime_and_identity(self) -> None:
        revision = self.root()["revision"]
        original = revision["reviewHash"]
        changed = deepcopy(revision)
        changed.update({
            "revisionId": "rev_" + "a" * 24, "parentRevisionId": "rev_" + "b" * 24,
            "createdAt": "2099-01-01T00:00:00+00:00", "name": "Tên", "note": "Ghi chú",
            "annotationUpdatedAt": "2099-01-01T00:00:00+00:00",
            "runtimeSummary": {"historical": True},
            "validationAtCreation": {"overall": "historical"},
        })
        self.assertEqual(original, compute_review_hash(changed))
        changed["summary"] = "Semantic change"
        self.assertNotEqual(original, compute_review_hash(changed))

    def test_table_schema_hash_ignores_sheet_and_runtime_metadata(self) -> None:
        sources = typed_plan()["sources"]
        original = source_schema_fingerprint(sources)
        moved = deepcopy(sources)
        moved[0]["sheetName"] = "OtherSheet"
        moved[0]["totalRows"] = 999
        moved[0]["sourceId"] = "src_new"
        moved[0]["columns"][0]["columnId"] = "col_new"
        self.assertEqual(original, source_schema_fingerprint(moved))
        moved[0]["columns"][0]["name"] = "Renamed"
        self.assertNotEqual(original, source_schema_fingerprint(moved))

    def test_graph_hash_policy_and_limits_are_rejected(self) -> None:
        root = self.root()
        bad = deepcopy(root["document"])
        bad["revisions"][0]["steps"][0]["operation"]["parameters"]["rawM"] = "Web.Contents(\"x\")"
        with self.assertRaises(InputError) as raw:
            validate_document(bad)
        self.assertEqual(raw.exception.code, "PQV2_POLICY_VIOLATION")

        bad = deepcopy(root["document"])
        bad["revisions"][0]["reviewHash"] = "sha256:" + "0" * 64
        with self.assertRaises(InputError) as hashed:
            validate_document(bad)
        self.assertEqual(hashed.exception.code, "PQPC_HASH_MISMATCH")

        over = deepcopy(root["document"])
        over["revisions"] = [deepcopy(over["revisions"][0]) for _ in range(51)]
        for index, revision in enumerate(over["revisions"]):
            revision["revisionId"] = f"rev_{index:024x}"
            revision["parentRevisionId"] = None if index == 0 else over["revisions"][index - 1]["revisionId"]
        with self.assertRaises(InputError) as count:
            validate_document(over)
        self.assertEqual(count.exception.code, "PQPC_HISTORY_LIMIT")

        huge = deepcopy(root["document"])
        huge["revisions"][0]["changeSet"] = [{"padding": "x" * MAX_CANONICAL_JSON_BYTES}]
        with self.assertRaises(InputError) as size:
            validate_document(huge)
        self.assertEqual(size.exception.code, "PQPC_HISTORY_LIMIT")

    def test_phase2_document_accepts_branch_but_rejects_external_metadata(self) -> None:
        root = self.root()["document"]
        branched = deepcopy(root)
        first = branched["revisions"][0]
        for suffix in ("a", "b"):
            child = deepcopy(first)
            child["revisionId"] = "rev_" + suffix * 24
            child["parentRevisionId"] = first["revisionId"]
            child["problemPrompt"] = f"Child {suffix}"
            child["reviewHash"] = compute_review_hash(child)
            branched["revisions"].append(child)
        branched["headRevisionId"] = branched["revisions"][-1]["revisionId"]
        self.assertEqual(validate_document(branched), branched)

        polluted = deepcopy(root)
        polluted["revisions"][0]["validationAtCreation"]["localPath"] = r"C:\\secret.xlsx"
        with self.assertRaises(InputError) as secret:
            validate_document(polluted)
        self.assertEqual(secret.exception.code, "PQPC_DOCUMENT_INVALID")

    def test_near_size_limit_blocks_before_planner_call(self) -> None:
        root = self.root()
        near = deepcopy(root["document"])
        near["revisions"][0]["changeSet"] = [{"padding": ""}]
        padding = MAX_CANONICAL_JSON_BYTES - 100 - len(canonical_json(near))
        near["revisions"][0]["changeSet"][0]["padding"] = "x" * padding
        self.assertEqual(len(canonical_json(near)), MAX_CANONICAL_JSON_BYTES - 100)
        validate_document(near)
        calls_before = len(self.planner.calls)
        with self.assertRaises(InputError) as limited:
            self.store.create_problem(near, compute_history_hash(near), "Vấn đề tiếp")
        self.assertEqual(limited.exception.code, "PQPC_HISTORY_LIMIT")
        self.assertEqual(len(self.planner.calls), calls_before)

    def test_random_revision_ids_for_identical_content(self) -> None:
        first = self.root()["revision"]
        second = self.store.create_problem(None, None, "Vấn đề 1", typed_plan=typed_plan())["revision"]
        self.assertNotEqual(first["revisionId"], second["revisionId"])
        self.assertEqual(first["reviewHash"], second["reviewHash"])

    def test_client_ref_resolution_never_rewrites_literal_or_description(self) -> None:
        store = ProblemChainStore(LiteralCollisionPlanner())
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Root", typed_plan=typed_plan())
        continued = store.create_problem(root["document"], root["historyHash"], "Filter")
        inserted = continued["revision"]["steps"][1]
        self.assertRegex(inserted["stepId"], r"^stp_[0-9a-f]{24}$")
        self.assertEqual(inserted["actionDescription"], "selected")
        self.assertEqual(inserted["operation"]["parameters"]["predicate"]["right"]["value"], "selected")
        self.assertEqual(continued["revision"]["finalOutputStepId"], inserted["stepId"])

    def test_change_variants_reject_unknown_or_missing_fields(self) -> None:
        root = self.root()
        invalid = FakeContinuationPlanner().propose({})
        invalid["changes"][0]["unexpected"] = "must fail closed"
        planner = mock.Mock()
        planner.propose.return_value = invalid
        store = ProblemChainStore(planner)
        self.addCleanup(store.close)
        with self.assertRaises(InputError) as caught:
            store.create_problem(root["document"], root["historyHash"], "Continue")
        self.assertEqual(caught.exception.code, "PQPC_DOCUMENT_INVALID")

    def test_committed_head_lookup_is_authority_free_and_head_bound(self) -> None:
        root = self.root()
        self.assertIsNone(self.store.active_revision(root["revision"]["revisionId"]))
        self.store.commit(root["mutationId"], root["historyHash"])
        active = self.store.active_revision(root["revision"]["revisionId"])
        self.assertEqual(active["revision"], root["revision"])
        self.assertNotIn("approval", active)
        second = self.store.create_problem(root["document"], root["historyHash"], "Continue")
        self.store.commit(second["mutationId"], second["historyHash"])
        with self.assertRaises(InputError) as caught:
            self.store.active_revision(root["revision"]["revisionId"])
        self.assertEqual(caught.exception.code, "PQPC_HEAD_MISMATCH")

    def test_continuation_schema_preflight_and_runner_contract(self) -> None:
        schema = _load_and_preflight_continuation_schema()
        self.assertEqual(len(schema["properties"]["changes"]["items"]["anyOf"]), 5)
        response = FakeContinuationPlanner().propose({})
        completed = subprocess.CompletedProcess(["codex"], 0, json.dumps(response), "")
        with mock.patch("pbip_assistant.adapters.codex.problem_chain.find_codex_executable", return_value="codex"), mock.patch(
            "pbip_assistant.adapters.codex.problem_chain.subprocess.run", return_value=completed,
        ) as invoked:
            actual = CodexProblemChainPlanner(timeout_seconds=3).propose({"baseRevision": {}})
        self.assertEqual(actual, response)
        command = invoked.call_args.args[0]
        self.assertIn("--output-schema", command)
        self.assertNotIn("secret stderr", str(actual))
        instruction = invoked.call_args.kwargs["input"]
        self.assertIn("table.mergeTables creates a nested table column", instruction)
        self.assertIn("table.expandTableColumn", instruction)

    def test_question_only_continuation_is_valid_schema_output_without_a_delta(self) -> None:
        schema = _load_and_preflight_continuation_schema()
        self.assertEqual(schema["properties"]["changes"]["minItems"], 0)
        response = {
            "summary": "Need one business rule", "questions": ["Which column should be used?"],
            "assumptions": [], "warnings": [], "changeReason": "Await clarification", "changes": [],
        }
        completed = subprocess.CompletedProcess(["codex"], 0, json.dumps(response), "")
        with mock.patch("pbip_assistant.adapters.codex.problem_chain.find_codex_executable", return_value="codex"), mock.patch(
            "pbip_assistant.adapters.codex.problem_chain.subprocess.run", return_value=completed,
        ):
            actual = CodexProblemChainPlanner(timeout_seconds=3).propose({"baseRevision": {}})
        self.assertEqual(actual, response)

    def test_invalid_final_delta_gets_one_bounded_structural_repair(self) -> None:
        planner = MissingFinalThenValidPlanner()
        store = ProblemChainStore(planner)
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Root", typed_plan=typed_plan())
        continued = store.create_problem(
            root["document"], root["historyHash"], "Continue safely",
            source_catalog=typed_plan()["sources"],
        )
        self.assertEqual(len(planner.calls), 2)
        feedback = planner.calls[1]["validationFeedback"]
        self.assertEqual(feedback["code"], "PQV2_FINAL_OUTPUT_NOT_TABLE")
        self.assertEqual(continued["revision"]["validationAtCreation"]["overall"], "passed")
        final_id = continued["revision"]["finalOutputStepId"]
        self.assertIn(final_id, {step["stepId"] for step in continued["revision"]["steps"]})

    def test_continuation_runner_sanitizes_schema_auth_rate_and_timeout(self) -> None:
        cases = {
            "invalid_json_schema: cell secret": "CODEX_SCHEMA_INVALID",
            "not logged in: cell secret": "CODEX_AUTH_REQUIRED",
            "rate limit: cell secret": "CODEX_RATE_LIMITED",
            "other failure: cell secret": "CODEX_FAILED",
        }
        for stderr, expected in cases.items():
            with self.subTest(expected=expected), mock.patch(
                "pbip_assistant.adapters.codex.problem_chain.find_codex_executable", return_value="codex",
            ), mock.patch(
                "pbip_assistant.adapters.codex.problem_chain.subprocess.run",
                return_value=subprocess.CompletedProcess(["codex"], 1, "", stderr),
            ):
                with self.assertRaises(InputError) as caught:
                    CodexProblemChainPlanner().propose({})
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("cell secret", str(caught.exception))
        with mock.patch(
            "pbip_assistant.adapters.codex.problem_chain.find_codex_executable", return_value="codex",
        ), mock.patch(
            "pbip_assistant.adapters.codex.problem_chain.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1),
        ):
            with self.assertRaises(InputError) as caught:
                CodexProblemChainPlanner(timeout_seconds=1).propose({})
            self.assertEqual(caught.exception.code, "CODEX_TIMEOUT")

    def test_continuation_can_add_and_append_a_new_workbook_source(self) -> None:
        planner = AppendSecondSourcePlanner()
        store = ProblemChainStore(planner)
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Root", typed_plan=typed_plan())
        catalog = deepcopy(root["revision"]["sources"])
        archive = deepcopy(catalog[0])
        archive.update({
            "sourceId": "src_archive", "sheetName": "Archive",
            "objectName": "tblSalesArchive",
        })
        archive["columns"][0]["columnId"] = "col_archive_order"
        archive["columns"][1]["columnId"] = "col_archive_qty"
        catalog.append(archive)
        continued = store.create_problem(
            root["document"], root["historyHash"], "Append archive",
            source_catalog=catalog,
        )
        self.assertEqual(len(planner.calls), 1)
        self.assertEqual([source["sourceId"] for source in planner.calls[0]["sourceCatalog"]], ["src_sales", "src_archive"])
        self.assertEqual([source["sourceId"] for source in continued["revision"]["sources"]], ["src_sales", "src_archive"])
        self.assertEqual(
            [step["operation"]["type"] for step in continued["revision"]["steps"]],
            ["source.workbookTable", "source.workbookTable", "table.appendTables"],
        )
        self.assertEqual(len(continued["revision"]["steps"][2]["inputs"]), 2)

    def test_source_schema_drift_blocks_before_continuation_planner(self) -> None:
        planner = AppendSecondSourcePlanner()
        store = ProblemChainStore(planner)
        self.addCleanup(store.close)
        root = store.create_problem(None, None, "Root", typed_plan=typed_plan())
        changed = deepcopy(root["revision"]["sources"])
        changed[0]["columns"][1]["inferredType"] = "number"
        with self.assertRaises(InputError) as caught:
            store.create_problem(
                root["document"], root["historyHash"], "Continue",
                source_catalog=changed,
            )
        self.assertEqual(caught.exception.code, "PQPC_SOURCE_SCHEMA_CHANGED")
        self.assertEqual(planner.calls, [])


if __name__ == "__main__":
    unittest.main()
