"""Compatibility alias for the canonical Power Query history service module."""

import sys
from .powerquery.history import store as _implementation

sys.modules[__name__] = _implementation
