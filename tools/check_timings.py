"""Report where the check gates spend their time.

Usage:
    py tools/check_timings.py fast [--top 25] [--by module|area]

Read-only: it uses the same discovery and selection rules as run_checks.py, so a
slow test is still a test that runs. Output is a report, not a new gate.
"""
from __future__ import annotations

import argparse
import io
import time
import unittest
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tools.run_checks as run_checks  # noqa: E402


class TimingResult(unittest.TextTestResult):
    """Records wall-clock time per test id without altering outcomes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.timings: list[tuple[str, float]] = []
        self._started_at = 0.0

    def startTest(self, test):  # noqa: N802 - unittest API
        self._started_at = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):  # noqa: N802 - unittest API
        self.timings.append((test.id(), time.perf_counter() - self._started_at))
        super().stopTest(test)


def bucket_of(test_id: str, by: str) -> str:
    if by == "module":
        return test_id.rsplit(".", 2)[0]
    parts = test_id.split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else test_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=("fast", "runtime", "all"))
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--by", choices=("module", "area"), default="module")
    args = parser.parse_args()

    discovered = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    if unittest.defaultTestLoader.errors:
        for error in unittest.defaultTestLoader.errors:
            print(error, file=sys.stderr)
        return 1
    chosen = [case for case in run_checks.cases(discovered) if run_checks.selected(case, args.gate)]
    if not chosen:
        parser.error("The selected gate discovered no cases")

    started = time.perf_counter()
    result = TimingResult(io.StringIO(), True, 0)
    unittest.TestSuite(chosen).run(result)
    total = time.perf_counter() - started

    print(f"gate={args.gate} tests={result.testsRun} failures={len(result.failures)} "
          f"errors={len(result.errors)} total={total:.1f}s")
    print(f"\n== slowest {args.top} tests ==")
    for test_id, seconds in sorted(result.timings, key=lambda item: -item[1])[: args.top]:
        print(f"{seconds:7.2f}s  {test_id}")

    buckets: dict[str, list[float]] = defaultdict(list)
    for test_id, seconds in result.timings:
        buckets[bucket_of(test_id, args.by)].append(seconds)

    print(f"\n== slowest {args.top} {args.by}s ==")
    for key, values in sorted(buckets.items(), key=lambda kv: -sum(kv[1]))[: args.top]:
        print(f"{sum(values):7.2f}s  n={len(values):3}  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
