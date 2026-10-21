"""Read-only TMDL catalog through Microsoft's local TmdlSerializer helper."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import InputError


_ROOT = Path(__file__).resolve().parents[1]
_BRIDGE_RELEASE = _ROOT / "tools" / "tmdl_bridge" / "bin" / "Release" / "net8.0" / "TmdlBridge.dll"
_BRIDGE_DEBUG = _ROOT / "tools" / "tmdl_bridge" / "bin" / "Debug" / "net8.0" / "TmdlBridge.dll"


def _regular_tmdl_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in [*directories, *filenames]:
            path = Path(current) / name
            if path.is_symlink():
                raise InputError("UNSAFE_TMDL_PATH", str(path), "Symlinks are not allowed in a TMDL source")
        files.extend(Path(current) / name for name in filenames)
    return sorted(files)


def _folder_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _regular_tmdl_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _bridge_command(bridge_path: str | Path | None) -> list[str]:
    candidates = [Path(bridge_path).resolve()] if bridge_path else [_BRIDGE_RELEASE, _BRIDGE_DEBUG]
    bridge = next((candidate for candidate in candidates if candidate.is_file()), None)
    if bridge is None:
        raise InputError(
            "TMDL_BRIDGE_UNAVAILABLE",
            str(candidates[0]),
            "Build the pinned local bridge with the command documented in tools/tmdl_bridge/README.md",
        )
    if bridge.suffix.lower() == ".dll":
        dotnet = shutil.which("dotnet")
        if not dotnet:
            raise InputError("TMDL_BRIDGE_UNAVAILABLE", str(bridge), "dotnet runtime is not available")
        return [dotnet, str(bridge)]
    return [str(bridge)]


def catalog_tmdl(
    definition_folder: str | Path,
    *,
    bridge_path: str | Path | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Parse a complete TMDL definition folder without writing to it."""
    try:
        root = Path(definition_folder).resolve(strict=True)
    except OSError as exception:
        raise InputError("INVALID_TMDL", str(definition_folder), "TMDL definition folder does not exist") from exception
    if not root.is_dir():
        raise InputError("INVALID_TMDL", str(root), "Expected a TMDL definition folder")
    if not (root / "database.tmdl").is_file() or not (root / "model.tmdl").is_file():
        raise InputError("INVALID_TMDL", str(root), "Expected database.tmdl and model.tmdl")

    before = _folder_hash(root)
    command = [*_bridge_command(bridge_path), "catalog", str(root)]
    environment = os.environ.copy()
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    environment["DOTNET_NOLOGO"] = "1"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exception:
        raise InputError("TMDL_BRIDGE_FAILED", str(root), "Local TMDL helper could not complete") from exception

    after = _folder_hash(root)
    if after != before:
        raise InputError("TMDL_SOURCE_CHANGED", str(root), "TMDL source changed during read-only parsing")
    if result.returncode == 10:
        raise InputError("INVALID_TMDL", str(root), "Official TMDL parser rejected the model")
    if result.returncode != 0:
        raise InputError("TMDL_BRIDGE_FAILED", str(root), f"Local TMDL helper exited with code {result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exception:
        raise InputError("TMDL_BRIDGE_FAILED", str(root), "Local TMDL helper returned invalid JSON") from exception
    if payload.get("sourceHash") != before:
        raise InputError("TMDL_BRIDGE_FAILED", str(root), "Local and Python source hashes disagree")
    return {
        **payload,
        "root": str(root),
        "parseValidation": "passed",
        "access": "read_only",
        "patchEligible": False,
    }
