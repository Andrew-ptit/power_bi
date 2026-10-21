"""Compatibility import for :mod:`pbip_assistant.powerbi.planning`."""

import importlib as _importlib
import sys as _sys

_sys.modules[__name__] = _importlib.import_module("pbip_assistant.powerbi.planning")
