"""Index baseline functions, their new locations and static navigation evidence.

This inventory accompanies human review notes; AST equivalence is not runtime
verification, and name-matched callers/test references are only candidates.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "baseline/pre-1.2.0-byte-exact"


def functions(tree: ast.AST, prefix: str = ""):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}.{node.name}" if prefix else node.name
            if not isinstance(node, ast.ClassDef):
                yield name, node
            yield from functions(node, name)


def call_names(node: ast.AST) -> set[str]:
    return {
        item.func.id if isinstance(item.func, ast.Name) else item.func.attr
        for item in ast.walk(node)
        if isinstance(item, ast.Call) and isinstance(item.func, (ast.Name, ast.Attribute))
    }


def body(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def main() -> None:
    current = defaultdict(list)
    callers = defaultdict(set)
    test_references = defaultdict(set)
    for path in sorted((ROOT / "pbip_assistant").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for name, node in functions(tree):
            location = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}#{name}"
            current[name].append((location, node))
            for called in call_names(node):
                callers[called].add(location)
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for name, node in functions(tree):
            if node.name.startswith("test_"):
                for called in call_names(node):
                    test_references[called].add(f"{path.relative_to(ROOT).as_posix()}#{name}")
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", BASELINE, "pbip_assistant"],
        cwd=ROOT, text=True,
    ).splitlines()
    rows = []
    for path in paths:
        if not path.endswith(".py"):
            continue
        source = subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT)
        for name, node in functions(ast.parse(source.decode("utf-8-sig"))):
            candidates = current["snapshot_workbook" if name == "_snapshot" else name]
            same = [location for location, item in candidates if body(item) == body(node)]
            destinations = same or [location for location, _ in candidates]
            calls = call_names(node)
            rows.append({
                "baseline": f"{path}:{node.lineno}#{name}",
                "destination_candidates": destinations,
                "decision": "retain_body_relocate" if same else "reviewed_extraction_or_dispatch_change",
                "same_ast": bool(same),
                "baseline_lines": node.end_lineno - node.lineno + 1,
                "called_names": sorted(calls),
                "possible_callers_by_name": sorted(callers[node.name]),
                "possible_test_references_by_name": sorted(test_references[node.name]),
                "side_effect_review_hints": sorted(calls & {
                    "run", "read_bytes", "write_bytes", "open", "read_text", "write_text",
                    "unlink", "replace", "acquire", "release", "clear", "append", "pop",
                    "mkdir", "cleanup", "commit", "preview", "apply", "create_problem",
                }),
            })
    output = ROOT / "docs" / "evidence" / "function-review-inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "baseline": BASELINE,
        "function_count": len(rows),
        "limitations": "Static name matches are navigation hints, not a resolved call graph, test coverage proof or full behavioral equivalence.",
        "human_review": "REFACTOR_REVIEW.md",
        "functions": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Indexed {len(rows)} baseline functions; {sum(row['same_ast'] for row in rows)} exact AST matches")


if __name__ == "__main__":
    main()
