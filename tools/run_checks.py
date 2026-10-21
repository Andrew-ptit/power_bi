"""Run deterministic checks or explicitly selected external-runtime gates.

Usage: py tools/run_checks.py fast|runtime|codex|all
External Excel cases remain serial. Live Codex is a separate opt-in gate.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def cases(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def selected(case: unittest.TestCase, gate: str) -> bool:
    identity = case.id()
    is_codex = identity.startswith("tests.runtime.test_codex_problem_chain.")
    is_runtime = identity.startswith("tests.runtime.")
    if gate == "fast":
        return not is_runtime
    if gate == "runtime":
        return is_runtime and not is_codex
    if gate == "codex":
        return is_codex
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=("fast", "runtime", "codex", "all"))
    parser.add_argument("--list", action="store_true", help="List case ids without executing any test")
    args = parser.parse_args()
    if args.gate == "codex" and not args.list and os.environ.get("PQPC_LIVE_CODEX") != "1":
        parser.error("Live Codex requires explicit PQPC_LIVE_CODEX=1; no request was sent")
    discovered = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    if unittest.defaultTestLoader.errors:
        for error in unittest.defaultTestLoader.errors:
            print(error, file=sys.stderr)
        return 1
    all_cases = list(cases(discovered))
    # A missing module can still produce a green unittest run. Migration IDs
    # make retained regression coverage an explicit gate, independent of count.
    migration = json.loads((ROOT / "tests" / "case_migration.json").read_text(encoding="utf-8"))
    required_ids = {case["new"] for case in migration["cases"] + migration.get("promoted_cases", [])}
    discovered_ids = {case.id() for case in all_cases}
    missing = required_ids - discovered_ids
    if missing:
        print("Missing retained test cases:\n" + "\n".join(sorted(missing)), file=sys.stderr)
        return 1
    chosen = [case for case in all_cases if selected(case, args.gate)]
    if not chosen:
        parser.error("The selected gate discovered no cases")
    if args.list:
        print("\n".join(case.id() for case in chosen))
        print(f"gate={args.gate} cases={len(chosen)}")
        return 0
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(chosen))
    print(
        f"gate={args.gate} run={result.testsRun} failed={len(result.failures)} "
        f"errors={len(result.errors)} skipped={len(result.skipped)} elapsed={time.perf_counter()-started:.3f}s"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
