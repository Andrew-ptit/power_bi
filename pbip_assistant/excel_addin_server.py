"""Compatibility alias for :mod:`pbip_assistant.coordinator.server`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pbip_assistant.coordinator.server")

if __name__ == "__main__":
    raise SystemExit(_implementation.main())

_sys.modules[__name__] = _implementation
