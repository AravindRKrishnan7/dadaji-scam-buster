"""Shared test setup."""
import pytest

from backend import config


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test saves case files to its own throwaway database, never data/cases.db."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "cases.db"))
