"""Resolve bundled resources independently of the importing module's location."""

from pathlib import Path


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_REPOSITORY_ROOT = _PACKAGE_ROOT.parent


def package_path(*parts: str) -> Path:
    """Return a package resource path; callers supply trusted resource names."""
    return _PACKAGE_ROOT.joinpath(*parts)


def repository_path(*parts: str) -> Path:
    """Return a development/runtime helper location inside this checkout."""
    return _REPOSITORY_ROOT.joinpath(*parts)


def schema_path(name: str) -> Path:
    """Return a JSON schema bundled with the application."""
    return package_path("schemas", name)
