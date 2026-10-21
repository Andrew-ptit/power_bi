from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from tests.support.oracle import (
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
