"""Shared test fixtures for isolating temporary document storage."""

import importlib
import os
from pathlib import Path

import pytest


# app.config creates its default storage directories at import time. During this
# one import only, skip those exact project paths so pytest collection does not
# create or touch them. All unrelated mkdir calls keep their normal behavior.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FORMAL_STORAGE_PATHS = {
    os.path.normcase(os.path.abspath(os.fspath(path)))
    for path in (
        _PROJECT_ROOT / "storage",
        _PROJECT_ROOT / "storage" / "temp_uploads",
        _PROJECT_ROOT / "storage" / "temp_results",
    )
}
_original_makedirs = os.makedirs


def _skip_formal_storage_makedirs(path, *args, **kwargs):
    normalized_path = os.path.normcase(os.path.abspath(os.fspath(path)))
    if normalized_path in _FORMAL_STORAGE_PATHS:
        return None
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _skip_formal_storage_makedirs
try:
    config = importlib.import_module("app.config")
finally:
    os.makedirs = _original_makedirs


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Redirect both PDF and result storage paths to this test's temporary directory."""
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()

    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    return upload_dir, result_dir
