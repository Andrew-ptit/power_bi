"""Kiểm soát chất lượng bàn giao Codex cho feature 003.

Vì working tree đã có sẵn nhiều thay đổi cũ, công cụ so với **baseline chụp lúc bàn giao**
chứ không so với HEAD.

    py tools/review_003.py --snapshot            # chụp baseline trước khi giao việc
    py tools/review_003.py --task T304           # rà thay đổi của task so với baseline
    py tools/review_003.py --task T304 --base HEAD   # nếu muốn so với git
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "specs" / "003-source-import-redesign" / "tasks.md"
BASELINE = ROOT / "specs" / "003-source-import-redesign" / ".baseline.json"
SKIP_DIRS = {".git", "runs", "node_modules", "__pycache__", ".artifacts", ".venv", "bin", "obj"}
SKIP_MARKERS = ("unittest.skip(", "pytest.mark.skip", "it.skip", "test.skip(", "describe.skip")
WEAK_MARKERS = ("assert True", "assertEqual(1, 1)", "expect(true).toBe(true)")
TODO_MARKERS = ("TODO", "FIXME", "XXX")


def configure_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    return result.stdout


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def walk() -> dict[str, str]:
    files: dict[str, str] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.suffix in {".xlsx", ".bin", ".zip", ".png", ".jpg"}:
            continue
        if rel.as_posix() == BASELINE.relative_to(ROOT).as_posix():
            continue
        files[rel.as_posix()] = digest(path)
    return files


def snapshot() -> int:
    files = walk()
    BASELINE.write_text(json.dumps(files, ensure_ascii=False, indent=0, sort_keys=True),
                        encoding="utf-8", newline="\n")
    print(f"Đã chụp baseline: {len(files)} file → {BASELINE.relative_to(ROOT)}")
    return 0


def parse_task(text: str, task_id: str) -> dict:
    start = re.search(rf"^## {task_id}\b.*$", text, re.M)
    if not start:
        raise SystemExit(f"Không thấy task {task_id} trong tasks.md")
    tail = text[start.start():]
    end = re.search(r"^## T3\d{2}\b", tail[4:], re.M)
    body = tail[: end.start() + 4] if end else tail
    files_block = re.search(r"\*\*Files\*\*\s*\n(.*?)(?=\n\*\*|\Z)", body, re.S)
    paths: list[str] = []
    if files_block:
        for line in files_block.group(1).splitlines():
            for token in re.findall(r"`([^`]+)`", line):
                token = token.strip()
                if "/" in token and not token.startswith("--"):
                    paths.append(token.replace("\\", "/"))
    verify = re.search(r"\*\*Kiểm chứng\*\*\s*\n```[a-zA-Z]*\n(.*?)```", body, re.S)
    commands = [line.strip() for line in (verify.group(1).splitlines() if verify else []) if line.strip()]
    return {"id": task_id, "files": sorted(set(paths)), "verify": commands}


def changed_since_baseline() -> list[str]:
    if not BASELINE.is_file():
        raise SystemExit("Chưa có baseline. Chạy: py tools/review_003.py --snapshot")
    old = json.loads(BASELINE.read_text(encoding="utf-8"))
    new = walk()
    changed = [path for path, value in new.items() if old.get(path) != value]
    deleted = [path for path in old if path not in new]
    return sorted(changed + deleted)


def changed_since_git(base: str) -> list[str]:
    return sorted({line.split("\t")[-1] for line in git("diff", "--name-status", base).splitlines()
                   if line.strip()})


def read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def scan(path: str) -> list[str]:
    text = read(path)
    if not text:
        return []
    problems = [f"{path}: dùng skip/disable test ({marker})" for marker in SKIP_MARKERS if marker in text]
    problems += [f"{path}: assert vô nghĩa ({marker})" for marker in WEAK_MARKERS if marker in text]
    problems += [f"{path}: còn '{marker}'" for marker in TODO_MARKERS if marker in text]
    if re.search(r"except\s*(Exception)?\s*:\s*\n\s*pass\b", text):
        problems.append(f"{path}: except rỗng nuốt lỗi")
    is_test = path.startswith("tests/") and path.endswith(".py") and not path.startswith("tests/support/")
    if is_test:
        tests = len(re.findall(r"def test_", text))
        asserts = len(re.findall(r"self\.assert", text))
        if tests == 0:
            problems.append(f"{path}: không có test nào")
        elif asserts < tests:
            problems.append(f"{path}: {tests} test nhưng chỉ {asserts} assert (có test không kiểm gì)")
    return problems


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Rà chất lượng bàn giao feature 003")
    parser.add_argument("--task", help="ID task, ví dụ T304")
    parser.add_argument("--snapshot", action="store_true", help="Chụp baseline trước khi giao việc")
    parser.add_argument("--base", help="So với base git (ví dụ HEAD) thay vì baseline")
    args = parser.parse_args(argv)

    if args.snapshot:
        return snapshot()
    if not args.task:
        parser.error("cần --task hoặc --snapshot")

    task = parse_task(TASKS.read_text(encoding="utf-8"), args.task)
    allowed = set(task["files"])
    changed = changed_since_git(args.base) if args.base else changed_since_baseline()
    touched = set(changed)
    relevant = sorted(touched & allowed)
    outside = sorted(path for path in touched if path not in allowed)

    problems = [f"ngoài allowlist: {path}" for path in outside]
    for path in relevant:
        problems.extend(scan(path))
    missing = sorted(path for path in allowed if path not in touched)

    print(f"Task {task['id']}: allowlist {len(allowed)} file; đã đổi {len(relevant)} file")
    for path in relevant:
        print(f"  ✓ {path}")
    for path in missing:
        print(f"  – chưa có thay đổi: {path}")

    if problems:
        print("\nVấn đề:")
        for problem in problems:
            print(f"  ✗ {problem}")
        print("\nKết luận: CHƯA ĐẠT.")
        return 1

    print("\nKết luận: đạt phần tĩnh. Vẫn phải chạy đúng lệnh kiểm chứng (bạn tự chạy, đừng tin báo cáo):")
    for command in task["verify"] or ["(task này không có lệnh kiểm chứng)"]:
        print(f"  $ {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
