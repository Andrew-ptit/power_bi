"""One subprocess policy shared by the read-only structured Codex runners.

Callers retain prompt construction, preflight, response validation and public
error mapping. Injecting their process runner preserves local test seams.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess
from typing import Any


def run_structured_process(
    executable: str, schema: Path, instruction: str, *, cwd: Path,
    timeout_seconds: int, process_runner: Callable[..., Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    runner = process_runner if process_runner is not None else subprocess.run
    return runner(
        [
            executable, "exec", "--sandbox", "read-only", "--ephemeral",
            "--ignore-user-config", "--skip-git-repo-check",
            "--output-schema", str(schema), "-",
        ],
        input=instruction, text=True, encoding="utf-8", errors="replace",
        capture_output=True, cwd=str(cwd), timeout=timeout_seconds, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
