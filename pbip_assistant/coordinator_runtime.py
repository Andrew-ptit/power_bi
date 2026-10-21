"""Compatibility alias for :mod:`pbip_assistant.coordinator.runtime`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pbip_assistant.coordinator.runtime")

_sys.modules[__name__] = _implementation
