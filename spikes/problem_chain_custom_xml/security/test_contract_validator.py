from __future__ import annotations

import base64
from copy import deepcopy
import json
import unittest

from spikes.problem_chain_custom_xml.security.contract_validator import (
    ContractError, MAX_CANONICAL_JSON_BYTES, canonical_json, compute_history_hash,
    compute_review_hash, decode_xml, encode_xml, select_problem_chain_part,
    source_schema_fingerprint, validate_document,
)


def source() -> dict:
    return {
        "sourceId": "src_ignored", "kind": "excelTable", "sheetName": "Sales",
        "objectName": "tblSales", "sampleOnly": True, "totalRows": 3,
        "columns": [
            {"columnId": "col_ignored", "ordinal": 0, "name": "OrderID", "inferredType": "text", "nullable": False},
            {"columnId": "col_ignored2", "ordinal": 1, "name": "Qty", "inferredType": "integer", "nullable": True},
        ],
    }


def revision(number: int = 1, parent: str | None = None) -> dict:
    result = {
        "revisionId": f"rev_{number:024x}", "parentRevisionId": parent,
        "originKind": "problem", "createdAt": "2026-10-12T10:00:00+07:00",
        "problemPrompt": "Chuẩn hóa dữ liệu bán hàng", "changeReason": "Initial problem",
        "name": None, "note": None, "annotationUpdatedAt": None,
        "sourceSchemaFingerprint": source_schema_fingerprint([source()]), "snapshotId": "snap_fixture",
        "summary": "Chuẩn hóa bảng", "questions": [], "assumptions": [], "warnings": [],
        "sources": [source()],
        "steps": [{"stepId": "stp_source", "operation": {"type": "source.workbookTable"}}],
        "finalOutputStepId": "stp_source", "changeSet": [], "validationAtCreation": {},
        "runtimeSummary": None, "reviewHash": "",
    }
    result["reviewHash"] = compute_review_hash(result)
    return result


def document(revisions: list[dict] | None = None) -> dict:
    values = revisions or [revision()]
    return {
        "schemaVersion": "1.0", "chainId": "chain_fixture", "planId": "plan_fixture",
        "storageVersion": 1, "headRevisionId": values[-1]["revisionId"],
        "samplePersistence": {"enabled": False, "warningAcceptedAt": None, "maxRows": 20, "maxColumns": 200},
        "sampleStore": {}, "revisions": values,
    }


class ProblemChainContractTests(unittest.TestCase):
    def assert_code(self, code: str, action) -> ContractError:
        with self.assertRaises(ContractError) as caught:
            action()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_unicode_round_trip_and_canonical_hash(self) -> None:
        value = document()
        value["revisions"][0]["problemPrompt"] = "Chuẩn hóa Hà Nội — Đà Nẵng"
        value["revisions"][0]["reviewHash"] = compute_review_hash(value["revisions"][0])
        xml = encode_xml(value)
        self.assertEqual(value, decode_xml(xml))
        self.assertEqual(compute_history_hash(value), compute_history_hash(decode_xml(xml)))

    def test_annotation_and_runtime_are_outside_review_hash(self) -> None:
        value = revision()
        original = value["reviewHash"]
        value["name"] = "Bản được duyệt nội bộ"
        value["note"] = "Không phải business rule"
        value["annotationUpdatedAt"] = "2026-10-12T11:00:00+07:00"
        value["runtimeSummary"] = {
            "previewedAt": "2026-10-12T11:01:00+07:00", "excelVersion": "16.0",
            "refreshSucceeded": True, "sourceRows": 10, "resultRows": 8, "resultColumns": 2,
            "outputColumnNames": ["OrderID", "Qty"], "compiledMHash": "sha256:" + "a" * 64,
        }
        self.assertEqual(original, compute_review_hash(value))
        self.assertNotEqual(compute_history_hash(document()), compute_history_hash(document([value])))

    def test_semantic_change_requires_new_review_hash(self) -> None:
        value = revision()
        value["problemPrompt"] = "Một quy tắc nghiệp vụ khác"
        self.assert_code("PQPC_HASH_MISMATCH", lambda: validate_document(document([value])))

    def test_schema_fingerprint_ignores_sheet_locator_ids_values_and_counts_for_table(self) -> None:
        left = source()
        right = deepcopy(left)
        right.update({"sheetName": "Moved", "sourceId": "src_other", "sampleRows": [["secret", 99]], "totalRows": 999})
        right["columns"][0]["columnId"] = "col_other"
        self.assertEqual(source_schema_fingerprint([left]), source_schema_fingerprint([right]))

    def test_schema_fingerprint_changes_for_name_order_or_type(self) -> None:
        baseline = source_schema_fingerprint([source()])
        for mutate in (
            lambda item: item["columns"][0].update(name="Different"),
            lambda item: item["columns"][1].update(inferredType="number"),
            lambda item: item.update(objectName="tblOther"),
        ):
            changed = deepcopy(source())
            mutate(changed)
            self.assertNotEqual(baseline, source_schema_fingerprint([changed]))
        reordered = deepcopy(source())
        reordered["columns"].reverse()
        reordered["columns"][0]["ordinal"] = 0
        reordered["columns"][1]["ordinal"] = 1
        self.assertNotEqual(baseline, source_schema_fingerprint([reordered]))

    def test_zero_one_and_duplicate_namespace_parts_fail_closed(self) -> None:
        xml = encode_xml(document())
        self.assertIsNone(select_problem_chain_part([]))
        self.assertEqual(document(), select_problem_chain_part([xml]))
        self.assert_code("PQPC_DUPLICATE_XML_PART", lambda: select_problem_chain_part([xml, xml]))

    def test_dtd_and_entity_are_rejected_before_xml_parse(self) -> None:
        malicious = '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><x>&leak;</x>'
        error = self.assert_code("PQPC_DOCUMENT_INVALID", lambda: decode_xml(malicious))
        self.assertIn("DTD", error.detail)

    def test_noncanonical_json_and_history_hash_tamper_are_rejected(self) -> None:
        value = document()
        pretty = json.dumps(value, ensure_ascii=False).encode("utf-8")
        payload = base64.b64encode(pretty).decode("ascii")
        xml = (
            '<ldc:problemChain xmlns:ldc="urn:local-data-copilot:pq-problem-chain:v1" '
            f'schemaVersion="1.0" historyHash="{compute_history_hash(value)}">'
            f'<ldc:payload encoding="base64">{payload}</ldc:payload></ldc:problemChain>'
        )
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: decode_xml(xml))
        valid = encode_xml(value).replace(compute_history_hash(value), "sha256:" + "0" * 64)
        self.assert_code("PQPC_HASH_MISMATCH", lambda: decode_xml(valid))

    def test_payload_over_two_mib_is_rejected_before_json_parse(self) -> None:
        raw = b"x" * (MAX_CANONICAL_JSON_BYTES + 1)
        payload = base64.b64encode(raw).decode("ascii")
        xml = (
            '<ldc:problemChain xmlns:ldc="urn:local-data-copilot:pq-problem-chain:v1" '
            f'schemaVersion="1.0" historyHash="sha256:{"0" * 64}">'
            f'<ldc:payload encoding="base64">{payload}</ldc:payload></ldc:problemChain>'
        )
        self.assert_code("PQPC_HISTORY_LIMIT", lambda: decode_xml(xml))

    def test_fifty_one_revisions_are_rejected(self) -> None:
        values = []
        parent = None
        for number in range(1, 52):
            item = revision(number, parent)
            values.append(item)
            parent = item["revisionId"]
        self.assert_code("PQPC_HISTORY_LIMIT", lambda: validate_document(document(values)))

    def test_samples_are_empty_by_default_and_require_ack_when_enabled(self) -> None:
        value = document()
        value["sampleStore"] = {"sha256:x": {"rows": [["CELL_SENTINEL"]]}}
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(value))
        value["samplePersistence"]["enabled"] = True
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(value))
        value["samplePersistence"]["warningAcceptedAt"] = "2026-10-12T12:00:00+07:00"
        entry = {"rows": [["CELL_SENTINEL", 1, True, None, 1.5]]}
        value["sampleStore"] = {"sha256:" + __import__("hashlib").sha256(canonical_json(entry)).hexdigest(): entry}
        validate_document(value)

    def test_sample_store_rejects_unknown_shape_hash_mismatch_and_non_scalar_cells(self) -> None:
        value = document()
        value["samplePersistence"].update(
            enabled=True, warningAcceptedAt="2026-10-12T12:00:00+07:00",
        )
        for entry in (
            {"rows": [["ok"]], "sourceId": "src_hidden"},
            {"rows": [[{"nested": "not a scalar"}]]},
            {"rows": [[float("inf")]]},
        ):
            with self.subTest(entry=entry):
                candidate = deepcopy(value)
                candidate["sampleStore"] = {"sha256:" + "a" * 64: entry}
                self.assert_code("PQPC_DOCUMENT_INVALID", lambda candidate=candidate: validate_document(candidate))
        mismatch = deepcopy(value)
        mismatch["sampleStore"] = {"sha256:" + "a" * 64: {"rows": [["different"]]}}
        self.assert_code("PQPC_HASH_MISMATCH", lambda: validate_document(mismatch))

    def test_persisted_source_rejects_samples_and_unknown_source_or_column_fields(self) -> None:
        for mutate in (
            lambda item: item.update(sampleRows=[["secret"]]),
            lambda item: item.update(arbitraryMetadata="secret"),
            lambda item: item["columns"][0].update(cellValues=["secret"]),
        ):
            value = document()
            mutate(value["revisions"][0]["sources"][0])
            value["revisions"][0]["reviewHash"] = compute_review_hash(value["revisions"][0])
            self.assert_code("PQPC_DOCUMENT_INVALID", lambda value=value: validate_document(value))

    def test_derived_or_runtime_authority_fields_cannot_be_persisted(self) -> None:
        for forbidden in ("branchTip", "previewId", "approvalId", "sessionToken", "workbookBase64"):
            value = document()
            value["revisions"][0]["validationAtCreation"][forbidden] = "forbidden"
            self.assert_code("PQPC_DOCUMENT_INVALID", lambda value=value: validate_document(value))

    def test_tree_requires_one_root_existing_parent_no_cycle_and_valid_head(self) -> None:
        second = revision(2, "rev_" + f"{1:024x}")
        valid = document([revision(), second])
        validate_document(valid)

        missing = deepcopy(valid)
        missing["revisions"][1]["parentRevisionId"] = "rev_" + f"{99:024x}"
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(missing))

        two_roots = document([revision(), revision(2)])
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(two_roots))

        bad_head = deepcopy(valid)
        bad_head["headRevisionId"] = "rev_" + f"{99:024x}"
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(bad_head))

        cycle = deepcopy(valid)
        cycle["revisions"][0]["parentRevisionId"] = cycle["revisions"][1]["revisionId"]
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(cycle))

    def test_unknown_fields_and_non_finite_numbers_are_rejected(self) -> None:
        unknown = document()
        unknown["latestRevisionId"] = unknown["headRevisionId"]
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(unknown))
        non_finite = document()
        non_finite["revisions"][0]["validationAtCreation"]["score"] = float("nan")
        self.assert_code("PQPC_DOCUMENT_INVALID", lambda: validate_document(non_finite))


if __name__ == "__main__":
    unittest.main()

