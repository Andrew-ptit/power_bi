"""Dẫn xuất biến thể contract từ fixture đã lưu; không chạy engine hoặc ghi nguồn."""

from __future__ import annotations

import copy
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path

from tests.support.paths import FIXTURES


ROOT = FIXTURES / "assistant"
DRIFT = Decimal("1234560")


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _base(name: str, reason: str) -> dict:
    result = copy.deepcopy(json.loads((ROOT / "tp-fin" / name).read_text(encoding="utf-8")))
    result["variantOf"] = name
    result["variantReason"] = reason
    return result


def _finish(document: dict, hash_key: str) -> str:
    # Các extension được bind vào hash, ngoài hai field tự tham chiếu.
    for key in document:
        if key not in {"schemaVersion", "hashBasis", hash_key} and key not in document["hashBasis"]:
            document["hashBasis"].append(key)
    document[hash_key] = canonical_hash({key: document[key] for key in document["hashBasis"]})
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_variants() -> dict[str, str]:
    """Tạo tám nhánh lỗi/cảnh báo, chỉ đọc bộ fixture tự chứa."""
    variants = {}
    drift = _base("wl5_reconciliation.json", "Tiêm sai lệch tổng kết quả để chứng minh cổng đối soát chặn duyệt.")
    drift["controlTotalResult"] = format(Decimal(drift["controlTotalResult"]) + DRIFT, "f")
    drift["controlTotalPassed"] = False
    drift["passed"] = False
    drift["blockers"] = [{"code": "AF_RECONCILE_FAILED", "severity": "blocker", "message": "Tổng kết quả lệch tổng nguồn; không được duyệt."}]
    for check in drift["checks"]:
        if check["id"] == "control_total":
            check["passed"] = False
            check["detail"] = "Tổng kết quả lệch tổng nguồn sau khử trùng."
    variants["fin_reconcile_control_drift.json"] = _finish(drift, "reconcileHash")

    missing = _base("wl2_understand.json", "Giả lập EUR có phát sinh trong kỳ nhưng thiếu tỷ giá bình quân; không sửa CSV gốc.")
    missing["passed"] = False
    missing["blockers"] = [{"code": "AF_MISSING_DATA", "severity": "blocker", "message": "Kịch bản synthetic: EUR có phát sinh T9 nhưng thiếu average rate; dừng trước thực thi."}]
    variants["fin_rate_missing_blocker.json"] = _finish(missing, "understandHash")

    closing = _base("wl2_understand.json", "Chỉ thiếu tỷ giá cuối kỳ USD tháng trước; báo cáo P&L dùng tỷ giá bình quân.")
    closing["passed"] = True
    closing["blockers"] = []
    closing["warnings"] = [{"code": "AF_MISSING_DATA", "severity": "warning", "message": "Thiếu USD closing T8; không ảnh hưởng P&L dùng average rate."}]
    variants["fin_rate_closing_missing_warning.json"] = _finish(closing, "understandHash")

    spec = _base("wl4_execution_spec.json", "Người dùng đổi quyết định sau freeze; spec cũ mất hiệu lực.")
    spec.update(stale=True, code="AF_SPEC_STALE", invalidatedBy="decisionChanged")
    variants["fin_spec_invalidated.json"] = _finish(spec, "fingerprint")

    record = _base("wl7_decision_record.json", "Nguồn thay đổi sau khi lập record; record phải mang nhãn stale.")
    record.update(stale=True, code="AF_SPEC_STALE")
    record["labels"] = [*record["labels"], "stale"]
    variants["fin_record_stale.json"] = _finish(record, "hash")

    ambiguous = _base("wl1_snapshot.json", "Cùng mẫu synthetic có hai cách đọc delimiter; người dùng phải chọn lại profile.")
    # Mẫu nhỏ dẫn xuất từ CSV synthetic đã lưu, không tạo bảng hoặc file nguồn khác.
    sample = "\n".join((ROOT / "tp-fin" / "source" / "Currency.csv").read_text(encoding="utf-8").splitlines()[:3]) + "\n"
    profiles = {}
    for mode, delimiter in (("auto", ";"), ("manual", ",")):
        parsed = list(csv.reader(io.StringIO(sample), delimiter=delimiter))
        profiles[mode] = {"mode": mode, "encoding": "utf-8", "delimiter": delimiter, "header": True,
                          "fingerprint": canonical_hash({"header": parsed[0], "sample": parsed[1:]})}
    ambiguous.update(status="needs_clarification", synthetic=True, csvProfile=profiles)
    variants["wl1_csv_ambiguous.json"] = _finish(ambiguous, "snapshotHash")

    blocked = _base("wl1_snapshot.json", "Ba loại nguồn không hợp lệ phải bị chặn trước khi tạo tệp tạm.")
    blocked.update(code="AF_INGEST_FAILED", severity="blocker", tempCreated=False,
                   cases=[{"kind": kind, "code": "AF_INGEST_FAILED", "severity": "blocker", "tempCreated": False}
                          for kind in ("exe", "pathTraversal", "oversize")])
    variants["wl1_connector_blocked.json"] = _finish(blocked, "snapshotHash")

    duplicate = _base("wl1_snapshot.json", "Hai bảng cùng tên phải yêu cầu đổi tên; không tự ghi đè.")
    duplicate["tables"][1]["name"] = duplicate["tables"][0]["name"]
    # Fingerprint vẫn theo đúng tên/header/sample của bảng sau thay đổi tên.
    table = duplicate["tables"][1]
    header = [column["name"] for column in table["columns"]]
    sample_rows = [list(row) for row in zip(*(column["sample"] for column in table["columns"]), strict=True)]
    table["fingerprint"] = canonical_hash({"name": table["name"], "header": header, "sample": sample_rows})
    duplicate.update(requiresRename=True, code="AF_INGEST_FAILED", overwritten=False)
    variants["wl1_duplicate_table_name.json"] = _finish(duplicate, "snapshotHash")
    return variants


def generate(root: Path = ROOT / "variants") -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in sorted(build_variants().items()):
        (root / name).write_text(payload, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generate()
    print(json.dumps({"variants": len(build_variants())}, sort_keys=True))
