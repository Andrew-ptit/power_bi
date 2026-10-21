"""Compatibility alias for the canonical Power Query typed service module."""

import sys
from .powerquery.typed import store as _implementation

sys.modules[__name__] = _implementation
