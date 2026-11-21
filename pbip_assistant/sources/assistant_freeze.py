"""Closed v2 freeze bindings, without recipe defaults, IO or approval authority."""

from copy import deepcopy
from datetime import datetime
import re

from pbip_assistant.errors import InputError
from .assistant_ingest import canonical_hash
from .assistant_reconcile_v2 import ENGINE, result_digest, _BASIS as _RECONCILE_BASIS


_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_BASIS = ("id", "snapshotHash", "understandHash", "planningHash", "decisionsHash", "decisions",
          "branchId", "planHash", "controlPolicy", "reconcileHash", "previewHash", "resultDigest",
          "steps", "finalOutputStepId", "sourceSchemas", "labels", "unverifiedAssumptions", "workbookIdentity", "target",
          "createdAt", "stale", "variantOf", "variantReason", "engine")


def _invalid(message, code="AF_SPEC_STALE", path="spec"):
    return InputError(code, path, message)


def timestamp(value):
    try:
        if not isinstance(value, str) or len(value) > 64 or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError()
    except ValueError:
        raise _invalid("Cần timestamp ISO có timezone tường minh.", "INVALID_REQUEST", "timestamp") from None


def workbook_identity(identity):
    if (not isinstance(identity, dict) or set(identity) != {"name", "documentHash"}
            or not isinstance(identity["name"], str) or not 0 < len(identity["name"]) <= 255
            or any(character in identity["name"] for character in ("/", "\\", ":", "\0"))
            or not isinstance(identity["documentHash"], str) or not _HASH.fullmatch(identity["documentHash"])):
        raise _invalid("Định danh workbook không hợp lệ.", "INVALID_REQUEST", "workbookIdentity")
    return deepcopy(identity)


def assert_freezable(branch, acknowledge_missing_control=False):
    reconciliation = branch["reconciliation"]
    if (set(reconciliation) != {"schemaVersion", "hashBasis", "reconcileHash", *_RECONCILE_BASIS}
            or reconciliation.get("schemaVersion") != "1.0" or reconciliation.get("hashBasis") != list(_RECONCILE_BASIS)
            or reconciliation.get("reconcileHash") != canonical_hash({key: reconciliation[key] for key in _RECONCILE_BASIS})
            or reconciliation.get("planHash") != branch["planHash"]
            or reconciliation.get("previewHash") != branch["preview"]["previewHash"]
            or reconciliation.get("resultDigest") != branch["preview"]["resultDigest"]
            or reconciliation.get("snapshotHash") != branch["preview"]["snapshotHash"]
            or reconciliation.get("controlTotal") != branch["controlTotal"]
            or reconciliation.get("maxFanOut") != branch["maxFanOut"] or reconciliation.get("blockers")):
        raise _invalid("Đối soát không còn toàn vẹn hoặc còn hard blocker.", "AF_RECONCILE_FAILED")
    if reconciliation.get("hardChecksPassed") is not True or reconciliation.get("selectable") is not True:
        raise _invalid("Nhánh có lỗi hình dạng, tổng kiểm soát hoặc fan-out; cần sửa kế hoạch.", "AF_RECONCILE_FAILED")
    if reconciliation.get("controlTotalApplicable") is True:
        if reconciliation.get("passed") is not True:
            raise _invalid("Tổng kiểm soát chưa đạt.", "AF_RECONCILE_FAILED")
    elif acknowledge_missing_control is not True:
        raise _invalid("Xác nhận rõ việc nhánh này chưa có đối soát tổng kiểm soát.", "AF_MISSING_DATA")


def spec_fingerprint_v2(spec):
    if (not isinstance(spec, dict) or set(spec) != {"schemaVersion", "fingerprint", "hashBasis", *_BASIS}
            or spec.get("schemaVersion") != "2.0" or spec.get("hashBasis") != list(_BASIS)
            or spec.get("stale") is not False or spec.get("variantOf") is not None or spec.get("variantReason") is not None
            or spec.get("branchId") not in ("A", "B") or not isinstance(spec.get("id"), str)
            or re.fullmatch(r"spec_[a-f0-9]{24}", spec["id"]) is None):
        raise _invalid("Spec v2 sai hợp đồng.")
    for key in ("snapshotHash", "understandHash", "planningHash", "decisionsHash", "planHash", "reconcileHash", "previewHash", "resultDigest"):
        if not isinstance(spec[key], str) or not _HASH.fullmatch(spec[key]):
            raise _invalid("Spec v2 thiếu binding hash.")
    timestamp(spec["createdAt"])
    workbook_identity(spec["workbookIdentity"])
    if (spec["target"] != {"sheet": "Assistant_" + spec["branchId"] + "_" + spec["id"][5:13]}
            or not isinstance(spec["steps"], list) or not spec["steps"]
            or spec["finalOutputStepId"] not in {step["stepId"] for step in spec["steps"]}
            or any(set(source) != {"sourceId", "schemaHash", "columns"} for source in spec["sourceSchemas"])
            or any(set(column) != {"columnId", "name", "inferredType"} for source in spec["sourceSchemas"] for column in source["columns"])):
        raise _invalid("Spec v2 chứa target hoặc schema chưa được phép.")
    if spec["decisionsHash"] != canonical_hash(spec["decisions"]):
        raise _invalid("Quyết định không còn khớp Spec.")
    if spec["planHash"] != canonical_hash({"steps": spec["steps"], "finalOutputStepId": spec["finalOutputStepId"],
            "sourceSchemas": [{"sourceId": source["sourceId"], "schemaHash": source["schemaHash"]} for source in spec["sourceSchemas"]]}):
        raise _invalid("Kế hoạch và final output không còn khớp planHash.")
    return canonical_hash({key: spec[key] for key in _BASIS})


def validate_frozen_spec(spec, preview):
    if spec_fingerprint_v2(spec) != spec.get("fingerprint"):
        raise _invalid("Fingerprint Spec đã thay đổi.")
    if (preview.get("previewHash") != spec["previewHash"] or preview.get("snapshotHash") != spec["snapshotHash"]
            or preview.get("planHash") != spec["planHash"] or preview.get("resultDigest") != spec["resultDigest"]
            or preview.get("previewHash") != canonical_hash({key: value for key, value in preview.items() if key != "previewHash"})):
        raise _invalid("Preview không còn khớp Spec.")


def build_frozen_spec(snapshot, understand, branch, *, planning_hash, created_at,
                      workbook, acknowledge_missing_control=False, assumptions=()):
    timestamp(created_at)
    identity = workbook_identity(workbook)
    if snapshot["snapshot"].get("mode") != "compute":
        raise _invalid("Đọc toàn bộ nguồn trước khi chốt nhánh.", "AF_SAMPLE_ONLY")
    assert_freezable(branch, acknowledge_missing_control)
    preview, reconciliation = branch["preview"], branch["reconciliation"]
    if preview["snapshotHash"] != snapshot["snapshotHash"] or result_digest(branch["result"]) != preview["resultDigest"]:
        raise _invalid("Kết quả không còn khớp snapshot.")
    labels = set()
    if assumptions:
        labels.add("assumed")
    if not reconciliation["controlTotalApplicable"] or assumptions:
        labels.add("unverified")
    decisions = {"schemaVersion": "2.0", "snapshotHash": snapshot["snapshotHash"],
        "understandHash": understand["understandHash"], "branchId": branch["id"],
        "decisions": [{"subProblemId": "SP-1", "optionId": "branch-" + branch["id"],
                       "branchId": branch["id"], "source": "user"}],
        "acknowledgeMissingControl": acknowledge_missing_control is True}
    spec = {"schemaVersion": "2.0", "id": "", "snapshotHash": snapshot["snapshotHash"],
        "understandHash": understand["understandHash"], "planningHash": planning_hash,
        "decisionsHash": canonical_hash(decisions), "decisions": decisions, "branchId": branch["id"],
        "planHash": branch["planHash"], "controlPolicy": {"controlTotal": deepcopy(branch["controlTotal"]), "maxFanOut": branch["maxFanOut"]},
        "reconcileHash": reconciliation["reconcileHash"], "previewHash": preview["previewHash"],
        "resultDigest": preview["resultDigest"], "steps": deepcopy(branch["plan"]["steps"]),
        "finalOutputStepId": branch["plan"]["finalOutputStepId"],
        "sourceSchemas": [{"sourceId": source["sourceId"], "schemaHash": source["schemaHash"],
                           "columns": [{key: column[key] for key in ("columnId", "name", "inferredType")} for column in source["columns"]]}
                          for source in branch["plan"]["sources"]],
        "labels": sorted(labels), "unverifiedAssumptions": deepcopy(list(assumptions)),
        "workbookIdentity": identity, "target": {}, "createdAt": created_at, "stale": False,
        "variantOf": None, "variantReason": None, "engine": deepcopy(ENGINE),
        "fingerprint": "", "hashBasis": list(_BASIS)}
    spec["id"] = "spec_" + canonical_hash({key: value for key, value in spec.items() if key not in ("id", "target", "fingerprint")})[7:31]
    spec["target"] = {"sheet": "Assistant_" + branch["id"] + "_" + spec["id"][5:13]}
    spec["fingerprint"] = spec_fingerprint_v2(spec)
    validate_frozen_spec(spec, preview)
    return spec


def result_marker(spec):
    return "LOCAL_DATA_COPILOT|" + spec["target"]["sheet"] + "|" + spec["fingerprint"] + "|" + spec["resultDigest"]
