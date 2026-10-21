from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from spikes.problem_chain_custom_xml.package_oracle.oracle import (
    MAX_DOCUMENT_BYTES,
    PROBLEM_CHAIN_NAMESPACE,
    build_problem_chain_xml,
    canonical_json_bytes,
    inspect_problem_chain_parts,
    package_part_delta,
    semantic_workbook_snapshot,
)


HERE = Path(__file__).resolve().parent
HELPER = HERE / "Invoke-CustomXmlPackageSpike.ps1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_document(note: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "chainId": "chain_package_spike",
        "planId": "plan_package_spike",
        "storageVersion": 1,
        "headRevisionId": "rev_0123456789abcdef01234567",
        "samplePersistence": {
            "enabled": False,
            "warningAcceptedAt": None,
            "maxRows": 20,
            "maxColumns": 200,
        },
        "sampleStore": {},
        "revisions": [{
            "revisionId": "rev_0123456789abcdef01234567",
            "parentRevisionId": None,
            "originKind": "problem",
            "createdAt": "2026-10-12T12:00:00+07:00",
            "problemPrompt": "Chuẩn hóa dữ liệu bán hàng ở Hà Nội",
            "changeReason": "Tạo chuỗi kiểm thử Custom XML",
            "name": "Bản thử tiếng Việt",
            "note": note,
            "steps": [],
            "finalOutputStepId": None,
            "reviewHash": "sha256:" + "0" * 64,
        }],
    }


def invoke_com(working: Path, save_as: Path, xml_documents: list[str]) -> dict[str, Any]:
    request = {
        "version": 1,
        "workingCopyPath": str(working),
        "saveAsPath": str(save_as),
        "namespace": PROBLEM_CHAIN_NAMESPACE,
        "xmlDocuments": xml_documents,
    }
    request_path = working.with_suffix(".request.json")
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HELPER), "-RequestPath", str(request_path)],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=120,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"COM spike returned no JSON (exit {completed.returncode})")
    result = json.loads(lines[-1])
    if completed.returncode or not result.get("ok"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def run_case(source: Path, folder: Path, label: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    working = folder / f"{label}_working.xlsx"
    save_as = folder / f"{label}_save_as.xlsx"
    shutil.copyfile(source, working)
    before_snapshot = semantic_workbook_snapshot(working)
    before_size = working.stat().st_size
    xml_documents: list[str] = []
    expected_hashes: list[str] = []
    for document in documents:
        xml, history_hash = build_problem_chain_xml(document)
        xml_documents.append(xml)
        expected_hashes.append(history_hash)
    com = invoke_com(working, save_as, xml_documents)
    working_inspection = inspect_problem_chain_parts(working)
    save_as_inspection = inspect_problem_chain_parts(save_as)
    return {
        "label": label,
        "expectedHistoryHashes": expected_hashes,
        "com": com,
        "workingPartCount": working_inspection["count"],
        "saveAsPartCount": save_as_inspection["count"],
        "workingCanonicalHash": None if working_inspection["count"] != 1 else working_inspection["parts"][0]["historyHash"],
        "saveAsCanonicalHash": None if save_as_inspection["count"] != 1 else save_as_inspection["parts"][0]["historyHash"],
        "semanticWorkingPreserved": semantic_workbook_snapshot(working) == before_snapshot,
        "semanticSaveAsPreserved": semantic_workbook_snapshot(save_as) == before_snapshot,
        "workingSizeBefore": before_size,
        "workingSizeAfter": working.stat().st_size,
        "saveAsSize": save_as.stat().st_size,
        "partDelta": package_part_delta(source, working),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the independent Problem Chain Custom XML package/COM spike.")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--full", action="store_true", help="Also execute duplicate and near-2-MiB COM cases.")
    args = parser.parse_args()
    source = args.fixture.resolve()
    source_hash = sha256_file(source)
    report: dict[str, Any] = {"source": str(source), "sourceSha256Before": source_hash, "cases": []}
    with tempfile.TemporaryDirectory(prefix="pqpc-package-spike-") as temp:
        folder = Path(temp)
        report["cases"].append(run_case(source, folder, "small", [sample_document()]))
        if args.full:
            duplicate_a = sample_document("duplicate-a")
            duplicate_b = sample_document("duplicate-b")
            try:
                duplicate = run_case(source, folder, "duplicate", [duplicate_a, duplicate_b])
            except Exception as exc:
                # The independent package oracle is expected to reject this workbook.
                duplicate = {"label": "duplicate", "oracleRejected": True, "error": str(exc)}
            report["cases"].append(duplicate)

            large = sample_document("")
            target = MAX_DOCUMENT_BYTES - 64 * 1024
            base_size = len(canonical_json_bytes(large))
            large["revisions"][0]["note"] = "Dữ liệu metadata " + "x" * max(0, target - base_size - 32)
            report["cases"].append(run_case(source, folder, "near_limit", [large]))

    report["sourceSha256After"] = sha256_file(source)
    report["sourceUnchanged"] = report["sourceSha256Before"] == report["sourceSha256After"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["sourceUnchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
