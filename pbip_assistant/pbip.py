"""Read-only PBIP inventory; no TMDL/PBIR patching in this slice."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import InputError


def _regular_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in [*directories, *filenames]:
            path = Path(current) / name
            if path.is_symlink():
                raise InputError("UNSAFE_PBIP_PATH", str(path), "Symlinks are not allowed in a PBIP source")
        files.extend(Path(current) / name for name in filenames)
    return sorted(files)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_pbip(root: str | Path) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise InputError("INVALID_PBIP", str(root), "Expected a PBIP project directory")
    files = _regular_files(root)
    projects = [path for path in files if path.parent == root and path.suffix.lower() == ".pbip"]
    if len(projects) != 1:
        raise InputError("INVALID_PBIP", str(root), "Expected exactly one .pbip file at project root")
    reports = []
    models = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        if directory.name.endswith(".Report"):
            definition = directory / "definition"
            modern = definition.is_dir() and any(path.suffix == ".json" for path in definition.rglob("*.json"))
            legacy = (directory / "report.json").is_file()
            if not modern and not legacy:
                raise InputError("INVALID_PBIP", str(directory), "Report has neither PBIR definition nor legacy report.json")
            reports.append({
                "name": directory.name,
                "format": "PBIR" if modern else "PBIR-legacy",
                "definition_json_count": sum(1 for path in definition.rglob("*.json")) if modern else 0,
                "external_edit_candidate": modern,
                "patch_eligible": False,
                "schema_validation": "not_run",
            })
        elif directory.name.endswith(".SemanticModel"):
            definition = directory / "definition"
            tmdl_files = sorted(definition.rglob("*.tmdl")) if definition.is_dir() else []
            models.append({
                "name": directory.name,
                "format": "TMDL" if tmdl_files else "unknown_or_legacy",
                "tmdl_file_count": len(tmdl_files),
                "parse_validation": "not_run",
            })
    if not reports or not models:
        raise InputError("INVALID_PBIP", str(root), "Expected at least one .Report and .SemanticModel folder")
    return {
        "root": str(root),
        "project_file": projects[0].name,
        "reports": reports,
        "semantic_models": models,
        "file_count": len(files),
        "patch_readiness": "inventory_only",
    }


def create_snapshot(pbip_root: str | Path, source_paths: list[str | Path]) -> dict[str, Any]:
    """Hash all selected Excel/CSV sources without modifying them."""
    root = Path(pbip_root).resolve(strict=True)
    inventory_pbip(root)
    project_hashes = {path.relative_to(root).as_posix(): _sha256(path) for path in _regular_files(root)}
    source_hashes = {}
    for supplied in source_paths:
        path = Path(supplied).resolve(strict=True)
        if not path.is_file():
            raise InputError("INVALID_SOURCE", str(path), "Expected a regular source file")
        source_hashes[str(path)] = _sha256(path)
    payload = {"pbip_root": str(root), "project_files": project_hashes, "source_files": source_hashes}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "id": fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }


def snapshot_matches(snapshot: dict[str, Any]) -> bool:
    try:
        # ``excel_files`` keeps snapshots from the first slice readable.
        sources = snapshot.get("source_files", snapshot.get("excel_files"))
        if not isinstance(sources, dict):
            return False
        current = create_snapshot(snapshot["pbip_root"], list(sources))
    except (InputError, OSError, KeyError):
        return False
    if "source_files" in snapshot:
        return current["id"] == snapshot["id"]
    legacy_payload = {
        "pbip_root": snapshot["pbip_root"],
        "project_files": current["project_files"],
        "excel_files": current["source_files"],
    }
    legacy_id = hashlib.sha256(json.dumps(legacy_payload, sort_keys=True).encode("utf-8")).hexdigest()
    return legacy_id == snapshot["id"]
