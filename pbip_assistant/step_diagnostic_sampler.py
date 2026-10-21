"""Compatibility alias for :mod:`pbip_assistant.powerquery.diagnostics.sampler`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pbip_assistant.powerquery.diagnostics.sampler")

_sys.modules[__name__] = _implementation
