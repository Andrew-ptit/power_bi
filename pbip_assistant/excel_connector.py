"""Compatibility alias for :mod:`pbip_assistant.excel.connector`."""

import importlib as _importlib
import sys as _sys

_implementation = _importlib.import_module("pbip_assistant.excel.connector")

_sys.modules[__name__] = _implementation
