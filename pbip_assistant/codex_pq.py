"""Compatibility alias for :mod:`pbip_assistant.adapters.codex.powerquery`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pbip_assistant.adapters.codex.powerquery")

_sys.modules[__name__] = _implementation
