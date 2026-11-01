"""Isolated tests for atomic analysis report persistence."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config
from app.services import report_service


@pytest.fixture
def report_storage(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", results)
    return results


def _report(document_id="a" * 32, body='{"status":"test"}'):
    return SimpleNamespace(
        document_id=document_id,
        model_dump_json=lambda indent: body,
    )


def test_save_report_atomically_writes_in_results_directory(report_storage):
    report = _report()

    saved_path = report_service.save_report(report)

    assert saved_path == report_storage / f"{report.document_id}.report.json"
    assert saved_path.read_text(encoding="utf-8") == '{"status":"test"}'
    assert not (report_storage / f"{report.document_id}.report.json.tmp").exists()


def test_failed_replace_preserves_previous_report_and_removes_partial_file(
    report_storage, monkeypatch
):
    report = _report()
    target = report_storage / f"{report.document_id}.report.json"
    temporary = report_storage / f"{report.document_id}.report.json.tmp"
    target.write_text("previous-success", encoding="utf-8")

    def fail_replace(*_args, **_kwargs):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(report_service.os, "replace", fail_replace)
    with pytest.raises(report_service.ReportPersistenceError):
        report_service.save_report(report)

    assert target.read_text(encoding="utf-8") == "previous-success"
    assert not temporary.exists()


def test_report_path_rejects_unsafe_document_id(report_storage):
    with pytest.raises(ValueError, match="識別碼"):
        report_service.report_path("../outside")
