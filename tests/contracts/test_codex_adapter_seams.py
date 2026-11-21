"""Pin the Codex adapter extraction seams.

The two Codex planners moved out of the authority stores into
`pbip_assistant.adapters.codex`. Callers and tests still import them through the
store modules (`pbip_assistant.pq_typed`, `pbip_assistant.problem_chain`), so the
re-export has to stay a real alias. The adapters must also stay loadable without
the authority stores, or the extraction would only move the cycle around.
"""

from __future__ import annotations

import types
import unittest

import pbip_assistant.adapters.codex.problem_chain as problem_chain_adapter
import pbip_assistant.adapters.codex.typed as typed_adapter
import pbip_assistant.pq_typed as typed_store
import pbip_assistant.problem_chain as history_store


FORBIDDEN_MODULES = {
    "pbip_assistant.powerquery.typed.store",
    "pbip_assistant.powerquery.history.store",
}


class CodexAdapterReexportTests(unittest.TestCase):
    def test_typed_names_are_the_same_objects_in_the_store(self) -> None:
        for name in ("AI_SCHEMA_PATH", "CodexTypedRunner", "_codex_failure_code", "_load_and_preflight_ai_schema"):
            with self.subTest(name=name):
                self.assertIs(getattr(typed_store, name), getattr(typed_adapter, name))

    def test_continuation_names_are_the_same_objects_in_the_store(self) -> None:
        for name in (
            "CONTINUATION_SCHEMA_PATH", "CodexProblemChainPlanner",
            "_continuation_failure_code", "_load_and_preflight_continuation_schema",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(history_store, name), getattr(problem_chain_adapter, name))


class CodexAdapterIsolationTests(unittest.TestCase):
    def test_adapters_do_not_load_the_authority_stores(self) -> None:
        for module in (typed_adapter, problem_chain_adapter):
            for name, value in vars(module).items():
                if isinstance(value, types.ModuleType):
                    with self.subTest(adapter=module.__name__, binding=name):
                        self.assertNotIn(value.__name__, FORBIDDEN_MODULES)


if __name__ == "__main__":
    unittest.main()
