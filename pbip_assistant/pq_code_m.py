"""Compatibility alias for :mod:`pbip_assistant.powerquery.advanced.runtime`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pbip_assistant.powerquery.advanced.runtime")

_sys.modules[__name__] = _implementation
