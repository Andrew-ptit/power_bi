"""The endpoint split must preserve rejection ordering and cleanup semantics."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from pbip_assistant.coordinator.server import (
    CODEX_JOB_PATHS, STATE_PATHS, ExcelAddinRequestHandler,
)
from pbip_assistant.errors import InputError


class CoordinatorDispatchContracts(unittest.TestCase):
    def test_every_baseline_post_path_has_a_callable_handler(self) -> None:
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "route_paths.json"
        expected = set(json.loads(fixture.read_text())["post_paths"])
        self.assertEqual(set(ExcelAddinRequestHandler.POST_ENDPOINTS) | {"/api/session/close"}, expected)
        for path, name in ExcelAddinRequestHandler.POST_ENDPOINTS.items():
            with self.subTest(path=path):
                self.assertTrue(callable(getattr(ExcelAddinRequestHandler, name)))

    def harness(self, *, route="/api/pq/v2/plans", guard=True, token_error=False, cooldown_error=False, handler_error=False):
        events = []
        handler = object.__new__(ExcelAddinRequestHandler)
        handler.path = route
        handler.headers = {"X-Local-Token": "token"}

        @contextmanager
        def slot(name):
            events.append(name + ".enter")
            try:
                yield
            finally:
                events.append(name + ".exit")

        def begin_job(token):
            self.assertEqual(token, "token")
            events.append("token")
            if token_error:
                raise InputError("TOKEN_EXPIRED", "token", "Expired")
            return SimpleNamespace(release=lambda: events.append("job.release"))

        def check_cooldown():
            events.append("cooldown")
            if cooldown_error:
                raise InputError("CODEX_RATE_LIMITED", "codex", "Busy")

        def dispatch():
            events.append("handler")
            if handler_error:
                raise InputError("PLAN_STALE", "plan", "Stale")

        cooldown = SimpleNamespace(check=check_cooldown, remaining_seconds=lambda: 1)
        handler.app = SimpleNamespace(
            runtime=SimpleNamespace(
                sessions=SimpleNamespace(begin_job=begin_job),
                slots=SimpleNamespace(acquire=lambda name: slot(name), state=lambda: slot("state")),
            ), codex_cooldown=cooldown,
        )
        handler._mutation_allowed = lambda: events.append("host.origin") or guard
        handler._input_error = lambda error: events.append(error.code)
        handler.POST_ENDPOINTS = {handler.path: "_test_dispatch"}
        handler._test_dispatch = dispatch
        return handler, events

    def test_success_and_handler_error_release_state_slot_then_job(self) -> None:
        for route in ("/api/pq/v2/plans", "/api/pq/v2/approvals"):
            for failing in (False, True):
                with self.subTest(route=route, handler_error=failing):
                    handler, events = self.harness(route=route, handler_error=failing)
                    handler.do_POST()
                    expected = ["host.origin", "token"]
                    if route in CODEX_JOB_PATHS:
                        expected.extend(["cooldown", "codex.enter"])
                    if route in STATE_PATHS:
                        expected.append("state.enter")
                    expected.append("handler")
                    if failing:
                        expected.append("PLAN_STALE")
                    if route in STATE_PATHS:
                        expected.append("state.exit")
                    if route in CODEX_JOB_PATHS:
                        expected.append("codex.exit")
                    expected.append("job.release")
                    self.assertEqual(events, expected)

    def test_host_token_and_cooldown_rejections_never_enter_execution(self) -> None:
        for options, expected in (
            ({"guard": False}, ["host.origin"]),
            ({"token_error": True}, ["host.origin", "token", "TOKEN_EXPIRED"]),
            ({"cooldown_error": True}, ["host.origin", "token", "cooldown", "CODEX_RATE_LIMITED", "job.release"]),
        ):
            with self.subTest(options=options):
                handler, events = self.harness(**options)
                handler.do_POST()
                self.assertEqual(events, expected)

    def test_oversized_or_truncated_body_never_reaches_json_parser(self) -> None:
        handler = object.__new__(ExcelAddinRequestHandler)
        handler.rfile = BytesIO(b"{}")
        handler.headers = {"Content-Length": "11"}
        with self.assertRaises(InputError) as caught:
            handler._read_json(10)
        self.assertEqual(caught.exception.code, "REQUEST_LIMIT")
        self.assertEqual(handler.rfile.tell(), 0)
        handler.headers = {"Content-Length": "3"}
        with self.assertRaisesRegex(ValueError, "ended early"):
            handler._read_json(10)
