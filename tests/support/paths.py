"""Stable repository and synthetic fixture locations for every test layer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"
