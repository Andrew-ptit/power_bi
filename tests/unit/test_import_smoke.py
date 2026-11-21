"""Import every package module so a stale import path cannot hide inside the gate.

Nothing else in the suite loads a module that no other test imports, so a broken
import there stays invisible until a human runs it by hand. That is exactly how
`examples/make_sample.py` kept importing `tests.fixtures` after the generators
moved to `tests/support`: the file raised ImportError on cold start while the
whole gate stayed green. This test closes that gap by importing the modules
itself and naming any that fail.
"""

from __future__ import annotations

import importlib
import pkgutil
import unittest


PACKAGE_ROOTS = (
    "pbip_assistant",
    "tests.support",
    "examples",
)

# Modules whose presence is load-bearing for the gate. A deliberate move updates
# this list; an accidental one fails here instead of going unnoticed.
ANCHOR_MODULES = (
    "pbip_assistant.coordinator",
    "pbip_assistant.powerquery.history.store",
    "pbip_assistant.powerquery.typed.store",
    "examples.make_sample",
    "tests.support.pbip_fixtures",
    "tests.support.source_fixtures",
)


def discover_modules(root: str) -> tuple[list[str], list[str]]:
    """List a package's modules without importing each one twice.

    `walk_packages` swallows a failure while importing a subpackage, so the
    error has to be captured through `onerror` instead of being trusted to
    surface on its own.
    """
    package = importlib.import_module(root)
    modules: list[str] = []
    walk_errors: list[str] = []

    def record_error(name: str) -> None:
        walk_errors.append(f"{name}: subpackage import failed")

    for info in pkgutil.walk_packages(package.__path__, root + ".", onerror=record_error):
        modules.append(info.name)
    return modules, walk_errors


class ImportSmokeTests(unittest.TestCase):
    def test_every_package_module_imports_cleanly(self) -> None:
        problems: list[str] = []
        discovered: list[str] = []
        for root in PACKAGE_ROOTS:
            modules, walk_errors = discover_modules(root)
            self.assertTrue(modules, f"{root} contributed no modules to the import smoke")
            problems.extend(walk_errors)
            discovered.extend(modules)
        present = set(discovered)
        missing_anchors = [name for name in ANCHOR_MODULES if name not in present]
        self.assertEqual(missing_anchors, [], f"anchor modules were not discovered: {missing_anchors}")
        for name in discovered:
            try:
                importlib.import_module(name)
            except Exception as exc:  # report every bad module, not just the first
                problems.append(f"{name}: {type(exc).__name__}: {exc}")
        self.assertEqual(problems, [], "package modules must import cleanly:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
