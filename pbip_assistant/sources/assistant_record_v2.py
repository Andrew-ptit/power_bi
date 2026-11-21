"""Immutable, recipe-free Decision Records and bounded workbook metadata.

Source rows are inspected only to compute diagnostics. They are never projected
into a Record. Metadata freshness is separate from the historical Record hash.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import re

from pbip_assistant.errors import InputError
from pbip_assistant.powerquery.typed.model import OPERATION_ARITY, PARAMETER_KEYS
from .assistant_ingest import canonical_hash
from .assistant_profile import snapshot_hash
from .assistant_record import _BASIS, _safe
from .assistant_freeze import spec_fingerprint_v2, assert_freezable
from .assistant_reconcile_v2 import ENGINE, _BASIS as RECONCILE_BASIS, _graph, _source


_HASH = re.compile(r"sha256:[a-f0-9]{64}")
_LABELS = {"assumed", "unverified", "out_of_scope", "stale"}
_DELTA = {"rowsIn", "rowsOut", "nullsBefore", "nullsAfter", "duplicatesBefore", "duplicatesAfter", "changedColumns"}
_ADDITIONS = {"specFingerprint", "finalOutputStepId", "sourceSchemas"}


def _invalid(detail, code="AF_RECORD_INVALID"):
    return InputError(code, "record", detail)


def utc_timestamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        stamp = stamp.astimezone(timezone.utc)
        return stamp.isoformat(timespec="milliseconds" if stamp.microsecond else "seconds").replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError):
        raise _invalid("Record cần thời điểm ISO có timezone.") from None


def _privacy(value):
    # Extend the unchanged v1 privacy boundary for Typed catalog sample keys.
    def visit(item):
        if isinstance(item, dict):
            if any(str(key).casefold() in {"samplerows", "sampleordinals", "planningsamples", "sources", "relativeorigin", "objectname"} for key in item):
                raise _invalid("Record không nhận nguồn, mẫu hoặc đường dẫn nguồn.")
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    _safe(value)


def _duplicates(rows):
    return sum(count - 1 for count in Counter(canonical_hash(row) for row in rows).values())


def _nulls(columns, rows):
    return {column: sum(row[index] is None or isinstance(row[index], str) and not row[index].strip() for row in rows)
            for index, column in enumerate(columns)}


def compute_v2_delta(plan, source_tables, result):
    """Count unique final ancestors, actual blanks and full-row duplicates."""
    by_id, ancestry = _graph(plan)
    catalogs = {source["sourceId"]: source for source in plan["sources"]}
    used = {}
    for reference in sorted(ancestry(plan["finalOutputStepId"])):
        identifier = by_id[reference]["operation"]["parameters"]["sourceId"]
        used[identifier] = _source(catalogs[identifier], source_tables)
    before = {}
    for identifier, raw in sorted(used.items()):
        columns = catalogs[identifier]["columns"]
        names = [identifier + "." + column["columnId"] for column in columns]
        before.update(_nulls(names, raw["rows"]))
    final = by_id[plan["finalOutputStepId"]]["outputContract"]["columns"]
    expected = [{"name": column["name"], "type": column["inferredType"]} for column in final]
    if result.get("columns") != expected or any(len(row) != len(final) for row in result["rows"]):
        raise _invalid("Delta không khớp schema kết quả.")
    changes = []
    reached = set()
    def walk(identifier):
        if identifier in reached:
            return
        reached.add(identifier)
        for reference in by_id[identifier]["inputs"]:
            walk(reference["ref"])
    walk(plan["finalOutputStepId"])
    for step in plan["steps"]:
        if step["stepId"] not in reached or step["operation"]["type"].startswith("source."):
            continue
        previous = {column["columnId"]: column for ref in step["inputs"] for column in by_id[ref["ref"]]["outputContract"]["columns"]}
        current = {column["columnId"]: column for column in step["outputContract"]["columns"]}
        changed = sorted(identifier for identifier in set(previous) | set(current)
                         if previous.get(identifier) != current.get(identifier))
        if changed:
            changes.append(step["stepId"] + ":" + step["operation"]["type"] + "→" + ",".join(changed))
    return {"rowsIn": sum(len(raw["rows"]) for raw in used.values()), "rowsOut": len(result["rows"]),
            "nullsBefore": before, "nullsAfter": _nulls([column["columnId"] for column in final], result["rows"]),
            "duplicatesBefore": sum(_duplicates(raw["rows"]) for raw in used.values()),
            "duplicatesAfter": _duplicates(result["rows"]), "changedColumns": changes}


def _shape(record):
    if (not isinstance(record, dict) or set(record) != {"schemaVersion", "hashBasis", "hash", *_BASIS}
            or record.get("schemaVersion") != "2.0" or record.get("hashBasis") != list(_BASIS)
            or not isinstance(record.get("id"), str) or not re.fullmatch(r"rec_[a-f0-9]{24}", record["id"])
            or record.get("stale") is not False or record.get("variantOf") is not None or record.get("variantReason") is not None):
        raise _invalid("Record v2 sai shape hoặc hash basis.")
    if utc_timestamp(record["createdAt"]) != record["createdAt"]:
        raise _invalid("Record cần thời điểm UTC canonical.")
    if set(record["snapshot"]) != {"snapshotHash", "sourceFingerprint"} or set(record["brief"]) != {"briefHash", "prompt"}:
        raise _invalid("Record thiếu tham chiếu nguồn hoặc kế hoạch.")
    for value in [*record["snapshot"].values(), record["brief"]["briefHash"]]:
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            raise _invalid("Record thiếu binding hash.")
    if not isinstance(record["brief"]["prompt"], str) or not record["brief"]["prompt"].strip():
        raise _invalid("Record thiếu đề bài đã duyệt.")
    if not isinstance(record["labels"], list) or len(record["labels"]) != len(set(record["labels"])) or set(record["labels"]) - _LABELS:
        raise _invalid("Record có nhãn không hợp lệ.")
    decisions = record["decisions"]
    if (not isinstance(decisions, dict) or set(decisions) != {"schemaVersion", "snapshotHash", "understandHash", "branchId", "decisions", "acknowledgeMissingControl"}
            or decisions["schemaVersion"] != "2.0" or decisions["branchId"] not in ("A", "B")
            or type(decisions["acknowledgeMissingControl"]) is not bool or decisions["snapshotHash"] != record["snapshot"]["snapshotHash"]
            or not isinstance(decisions["understandHash"], str) or not _HASH.fullmatch(decisions["understandHash"])
            or decisions["decisions"] != [{"subProblemId": "SP-1", "optionId": "branch-" + decisions["branchId"], "branchId": decisions["branchId"], "source": "user"}]):
        raise _invalid("Record thiếu quyết định nhánh tường minh.")
    assumptions = record["assumptions"]
    if (not isinstance(assumptions, list) or len(assumptions) > 20 or any(not isinstance(item, dict)
            or set(item) != {"statement", "risk"} or not isinstance(item["statement"], str) or not item["statement"].strip()
            or item["risk"] not in ("low", "medium", "high") for item in assumptions)
            or assumptions and not {"assumed", "unverified"}.issubset(record["labels"])):
        raise _invalid("Record assumption ledger sai hợp đồng.")
    if not isinstance(record["reconciliations"], list) or len(record["reconciliations"]) != 1:
        raise _invalid("Record cần đúng một đối soát.")
    reconciliation = record["reconciliations"][0]
    if (not isinstance(reconciliation, dict) or set(reconciliation) != {"schemaVersion", "reconcileHash", *RECONCILE_BASIS, *_ADDITIONS}
            or reconciliation["schemaVersion"] != "1.0"
            or reconciliation["reconcileHash"] != canonical_hash({key: reconciliation[key] for key in RECONCILE_BASIS})):
        raise _invalid("Đối soát gốc không khớp hash basis.")
    if reconciliation["snapshotHash"] != record["snapshot"]["snapshotHash"] or reconciliation["sourceFingerprint"] != record["snapshot"]["sourceFingerprint"]:
        raise _invalid("Record không bind đúng đối soát nguồn.")
    if not isinstance(reconciliation["specFingerprint"], str) or not _HASH.fullmatch(reconciliation["specFingerprint"]):
        raise _invalid("Record thiếu Spec fingerprint.")
    if (reconciliation["engine"] != ENGINE or reconciliation["hardChecksPassed"] is not True
            or reconciliation["selectable"] is not True or reconciliation["blockers"]
            or (reconciliation["controlTotalApplicable"] is True and reconciliation["passed"] is not True)
            or (reconciliation["controlTotalApplicable"] is False and (decisions["acknowledgeMissingControl"] is not True or "unverified" not in record["labels"]))):
        raise _invalid("Record không được nâng mức xác minh hoặc bỏ hard blocker.")
    sources = reconciliation["sourceSchemas"]
    if (not isinstance(sources, list) or not 1 <= len(sources) <= 20
            or any(not isinstance(source, dict) or set(source) != {"sourceId", "schemaHash", "columns"} for source in sources)
            or len({source["sourceId"] for source in sources}) != len(sources)):
        raise _invalid("Record chỉ nhận source schema projection.")
    if any(set(column) != {"columnId", "name", "inferredType"} for source in sources for column in source["columns"]):
        raise _invalid("Record chứa schema ngoài projection.")
    steps = record["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise _invalid("Record cần kế hoạch trong giới hạn.")
    fields = {"stepId", "position", "variableName", "actionDescription", "operation", "inputs", "outputContract"}
    seen = set()
    for step in steps:
        if (not isinstance(step, dict) or set(step) != fields or set(step["operation"]) != {"type", "parameters"}
                or step["stepId"] in seen or any(set(ref) != {"kind", "ref"} or ref["kind"] != "step" or ref["ref"] not in seen for ref in step["inputs"])):
            raise _invalid("Record chứa graph không hợp lệ.")
        operation = step["operation"]["type"]
        if (operation not in OPERATION_ARITY or not isinstance(step["operation"]["parameters"], dict)
                or set(step["operation"]["parameters"]) - PARAMETER_KEYS[operation]
                or not OPERATION_ARITY[operation][0] <= len(step["inputs"]) <= OPERATION_ARITY[operation][1]
                or set(step["outputContract"]) != {"kind", "schemaHash", "columns"}
                or step["outputContract"]["kind"] != "table"):
            raise _invalid("Record chứa operation ngoài catalog hoặc output contract sai.")
        seen.add(step["stepId"])
    if reconciliation["finalOutputStepId"] not in seen or reconciliation["planHash"] != canonical_hash({"steps": steps,
            "finalOutputStepId": reconciliation["finalOutputStepId"], "sourceSchemas": [{"sourceId": source["sourceId"], "schemaHash": source["schemaHash"]} for source in sources]}):
        raise _invalid("Record không giữ đúng thuật toán đã chốt.")
    delta = record["delta"]
    if not isinstance(delta, dict) or set(delta) != _DELTA:
        raise _invalid("Record delta sai shape.")
    for key, maximum in (("rowsIn", 2000000), ("rowsOut", 100000), ("duplicatesBefore", 2000000), ("duplicatesAfter", 100000)):
        if type(delta[key]) is not int or not 0 <= delta[key] <= maximum:
            raise _invalid("Record delta vượt giới hạn số đếm.")
    if delta["rowsIn"] != reconciliation["rowsIn"] or delta["rowsOut"] != reconciliation["rowsOut"]:
        raise _invalid("Record delta không khớp số đếm đối soát.")
    for key, maximum in (("nullsBefore", delta["rowsIn"]), ("nullsAfter", delta["rowsOut"])):
        if not isinstance(delta[key], dict) or any(not isinstance(name, str) or type(value) is not int or not 0 <= value <= maximum for name, value in delta[key].items()):
            raise _invalid("Record null profile sai số đếm.")
    if not isinstance(delta["changedColumns"], list) or any(not isinstance(change, str) or "→" not in change for change in delta["changedColumns"]):
        raise _invalid("Record thiếu lineage cột.")
    _privacy(record)


def record_hash_v2(record):
    try:
        _shape(record)
    except (KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise _invalid("Record không đúng JSON metadata đóng.") from exc
    return canonical_hash({key: record[key] for key in _BASIS})


def build_v2_record(snapshot, plan, branch, spec, reconciliation, delta, created_at, source_evidence=None):
    """Build a historical audit artifact; caller owns consumed Apply authority."""
    if snapshot_hash(snapshot) != snapshot.get("snapshotHash") or spec_fingerprint_v2(spec) != spec.get("fingerprint"):
        raise _invalid("Snapshot hoặc Spec không còn khớp.", "AF_SPEC_STALE")
    assert_freezable(branch, spec["decisions"]["acknowledgeMissingControl"])
    if (reconciliation != branch["reconciliation"] or spec["reconcileHash"] != reconciliation["reconcileHash"]
            or spec["snapshotHash"] != snapshot["snapshotHash"] or spec["planHash"] != branch["planHash"]
            or plan["steps"] != spec["steps"] or plan["finalOutputStepId"] != spec["finalOutputStepId"]):
        raise _invalid("Record không bind đúng nhánh đã áp dụng.", "AF_SPEC_STALE")
    projected = {key: deepcopy(reconciliation[key]) for key in ("schemaVersion", "reconcileHash", *RECONCILE_BASIS)}
    projected.update(specFingerprint=spec["fingerprint"], finalOutputStepId=spec["finalOutputStepId"], sourceSchemas=deepcopy(spec["sourceSchemas"]))
    prompt = source_evidence.get("prompt") if isinstance(source_evidence, dict) else None
    record = {"schemaVersion": "2.0", "id": "rec_" + canonical_hash({"snapshot": snapshot["snapshotHash"], "spec": spec["fingerprint"]})[7:31],
        "createdAt": utc_timestamp(created_at), "snapshot": {"snapshotHash": snapshot["snapshotHash"], "sourceFingerprint": reconciliation["sourceFingerprint"]},
        "brief": {"briefHash": spec["planningHash"], "prompt": prompt}, "decisions": deepcopy(spec["decisions"]),
        "assumptions": deepcopy(spec["unverifiedAssumptions"]), "steps": deepcopy(spec["steps"]),
        "reconciliations": [projected], "delta": deepcopy(delta), "labels": deepcopy(spec["labels"]),
        "stale": False, "variantOf": None, "variantReason": None, "hashBasis": list(_BASIS), "hash": ""}
    record["hash"] = record_hash_v2(record)
    return record


def record_node(record, branch):
    if record_hash_v2(record) != record.get("hash") or branch not in ("A", "B") or branch != record["decisions"]["branchId"]:
        raise _invalid("Không tạo metadata từ Record lỗi.")
    node = {"schemaVersion": "1.0", "id": record["id"], "recordHash": record["hash"],
        "snapshot": record["snapshot"]["snapshotHash"], "spec": record["reconciliations"][0]["specFingerprint"],
        "branch": branch, "createdAt": record["createdAt"], "labels": deepcopy(record["labels"])}
    node["hash"] = canonical_hash(node)
    return node


def detect_stale_v2(record, *, current_snapshot_hash=None, source_unavailable=False):
    if record_hash_v2(record) != record.get("hash"):
        raise _invalid("Record đã thay đổi.")
    stale = None if current_snapshot_hash is None else current_snapshot_hash != record["snapshot"]["snapshotHash"]
    return {"stale": stale, "reason": "sourceUnavailable" if source_unavailable else "sourceChanged" if stale else None,
        "freshness": "unknown" if stale is None else "stale" if stale else "matches", "verifiedAtApply": True, "currentCheckedAt": None}
