"""B10 tests for coordinating active analysis documents with TTL cleanup."""

import os
import subprocess
import sys
import threading
import textwrap
import time
from pathlib import Path

import pytest

from app import config
from app.models.schemas import AnalysisRequest, DocumentExtractionData
from app.services.analysis_service import (
    AnalysisDocumentUnavailableError,
    analysis_service,
)
from app.services.pdf_service import PDFService


@pytest.fixture
def b10_storage(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    monkeypatch.setattr(analysis_service, "_work_lock", threading.Lock())
    monkeypatch.setattr(analysis_service, "_active_state_lock", threading.Lock())
    monkeypatch.setattr(analysis_service, "_active_document_ids", set())
    monkeypatch.setattr(analysis_service, "executor", None)
    return upload_dir, result_dir


def _document(document_id: str) -> DocumentExtractionData:
    text = "Synthetic source text for B10 cleanup tests."
    return DocumentExtractionData(
        document_id=document_id,
        original_filename="b10-test.pdf",
        total_pages=1,
        total_characters=len(text),
        pages=[{"physical_page": 1, "text": text, "char_count": len(text)}],
        created_at="2026-10-31T00:00:00+00:00",
    )


def _request(document_id: str) -> AnalysisRequest:
    return AnalysisRequest(document_id=document_id, analysis_mode="general")


def _artifacts(b10_storage, document_id: str) -> list[Path]:
    upload_dir, result_dir = b10_storage
    paths = [
        upload_dir / f"{document_id}.pdf",
        result_dir / f"{document_id}.json",
        result_dir / f"{document_id}.json.tmp",
        result_dir / f"{document_id}.metadata.json",
        result_dir / f"{document_id}.metadata.json.tmp",
    ]
    for path in paths:
        path.write_text("temporary test artifact", encoding="utf-8")
    return paths


def _expire(paths: list[Path]) -> None:
    past = time.time() - 7200
    for path in paths:
        os.utime(path, (past, past))


def _document_is_present_and_fresh(paths: list[Path]) -> bool:
    try:
        now = time.time()
        return all(
            path.is_file() and now - path.stat().st_mtime <= 3600
            for path in paths[:2]
        )
    except OSError:
        return False


def test_b10_1_expired_artifacts_are_kept_during_analysis(b10_storage, monkeypatch):
    document_id = "a" * 32
    paths = _artifacts(b10_storage, document_id)

    def executor(_request, _document):
        assert analysis_service.is_document_active(document_id)
        _expire(paths)
        assert PDFService.cleanup_expired_files(ttl_seconds=3600) == 0
        assert all(path.exists() for path in paths)
        return "finished"

    monkeypatch.setattr(analysis_service, "executor", executor)
    assert analysis_service.run(
        _request(document_id),
        _document(document_id),
        preflight=lambda: _document_is_present_and_fresh(paths),
    ) == "finished"
    assert not analysis_service.is_document_active(document_id)
    assert not analysis_service._work_lock.locked()


def test_b10_2_expired_artifacts_are_removed_after_analysis(b10_storage, monkeypatch):
    document_id = "b" * 32
    paths = _artifacts(b10_storage, document_id)
    monkeypatch.setattr(analysis_service, "executor", lambda *_: None)

    analysis_service.run(
        _request(document_id),
        _document(document_id),
        preflight=lambda: _document_is_present_and_fresh(paths),
    )

    _expire(paths)
    assert PDFService.cleanup_expired_files(ttl_seconds=3600) == len(paths)
    assert all(not path.exists() for path in paths)


def test_b10_3_executor_exception_releases_locks_and_document_protection(
    b10_storage, monkeypatch
):
    document_id = "c" * 32
    paths = _artifacts(b10_storage, document_id)

    def failing_executor(_request, _document):
        assert analysis_service.is_document_active(document_id)
        _expire(paths)
        assert PDFService.cleanup_expired_files(ttl_seconds=3600) == 0
        raise RuntimeError("synthetic B10 executor failure")

    monkeypatch.setattr(analysis_service, "executor", failing_executor)
    with pytest.raises(RuntimeError, match="synthetic B10 executor failure"):
        analysis_service.run(
            _request(document_id),
            _document(document_id),
            preflight=lambda: _document_is_present_and_fresh(paths),
        )

    assert not analysis_service.is_document_active(document_id)
    assert not analysis_service._work_lock.locked()
    assert PDFService.cleanup_expired_files(ttl_seconds=3600) == len(paths)
    assert all(not path.exists() for path in paths)


def test_b10_4_unexpired_artifacts_are_not_removed(b10_storage):
    paths = _artifacts(b10_storage, "d" * 32)

    assert PDFService.cleanup_expired_files(ttl_seconds=3600) == 0
    assert all(path.exists() for path in paths)


def test_b10_5_cleanup_removes_expired_other_document_during_analysis(
    b10_storage, monkeypatch
):
    active_id = "e" * 32
    idle_id = "f" * 32
    active_paths = _artifacts(b10_storage, active_id)
    idle_paths = _artifacts(b10_storage, idle_id)
    _expire(idle_paths)

    def executor(_request, _document):
        _expire(active_paths)
        deleted = PDFService.cleanup_expired_files(ttl_seconds=3600)
        assert deleted == len(idle_paths)
        assert all(path.exists() for path in active_paths)
        assert all(not path.exists() for path in idle_paths)

    monkeypatch.setattr(analysis_service, "executor", executor)
    analysis_service.run(
        _request(active_id),
        _document(active_id),
        preflight=lambda: _document_is_present_and_fresh(active_paths),
    )


def test_b10_6_unlink_failure_does_not_block_cleanup_or_later_analysis(
    b10_storage, monkeypatch
):
    expired_id = "1" * 32
    failed_path, *other_paths = _artifacts(b10_storage, expired_id)
    _expire([failed_path, *other_paths])
    original_unlink = Path.unlink

    def fail_one_unlink(path, *args, **kwargs):
        if path == failed_path:
            raise OSError("synthetic unlink failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_unlink)
    assert PDFService.cleanup_expired_files(ttl_seconds=3600) == len(other_paths)
    assert failed_path.exists()
    assert all(not path.exists() for path in other_paths)

    checked, operation_result = analysis_service.run_if_document_inactive(
        expired_id, lambda: "state lock released"
    )
    assert checked is True
    assert operation_result == "state lock released"

    next_id = "2" * 32
    next_paths = _artifacts(b10_storage, next_id)
    monkeypatch.setattr(analysis_service, "executor", lambda *_: "next analysis")
    assert analysis_service.run(
        _request(next_id), _document(next_id), preflight=lambda: _document_is_present_and_fresh(next_paths)
    ) == "next analysis"
    assert not analysis_service._work_lock.locked()


def test_b10_7_cleanup_winning_before_registration_rejects_analysis(
    b10_storage, monkeypatch
):
    document_id = "3" * 32
    paths = _artifacts(b10_storage, document_id)
    _expire(paths)
    calls = []
    monkeypatch.setattr(analysis_service, "executor", lambda *_: calls.append("called"))

    assert PDFService.cleanup_expired_files(ttl_seconds=3600) == len(paths)
    with pytest.raises(AnalysisDocumentUnavailableError):
        analysis_service.run(
            _request(document_id),
            _document(document_id),
            preflight=lambda: _document_is_present_and_fresh(paths),
        )

    assert calls == []
    assert not analysis_service.is_document_active(document_id)
    assert not analysis_service._work_lock.locked()


def test_b10_8_cleanup_skips_document_after_active_registration(
    b10_storage, monkeypatch
):
    document_id = "4" * 32
    paths = _artifacts(b10_storage, document_id)

    def executor(_request, _document):
        assert analysis_service.is_document_active(document_id)
        _expire(paths)
        assert PDFService.cleanup_expired_files(ttl_seconds=3600) == 0
        assert all(path.exists() for path in paths)

    monkeypatch.setattr(analysis_service, "executor", executor)
    analysis_service.run(
        _request(document_id),
        _document(document_id),
        preflight=lambda: _document_is_present_and_fresh(paths),
    )
    assert not analysis_service.is_document_active(document_id)


def test_b10_9_cleanup_and_registration_race_is_serialized(b10_storage):
    document_id = "5" * 32
    paths = _artifacts(b10_storage, document_id)
    _expire(paths)
    child_script = textwrap.dedent(
        '''
        import importlib
        import os
        import sys
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path

        document_id, upload_path, result_path = sys.argv[1:]
        upload_dir = Path(upload_path)
        result_dir = Path(result_path)
        project_root = os.path.abspath(os.getcwd())
        formal_storage_paths = {
            os.path.normcase(os.path.abspath(os.path.join(project_root, "storage"))),
            os.path.normcase(os.path.abspath(os.path.join(project_root, "storage", "temp_uploads"))),
            os.path.normcase(os.path.abspath(os.path.join(project_root, "storage", "temp_results"))),
        }
        original_makedirs = os.makedirs

        def prevent_formal_storage_creation(path, *args, **kwargs):
            candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
            if candidate in formal_storage_paths:
                return None
            return original_makedirs(path, *args, **kwargs)

        os.makedirs = prevent_formal_storage_creation
        try:
            config = importlib.import_module("app.config")
        finally:
            os.makedirs = original_makedirs
        config.TEMP_UPLOADS_DIR = upload_dir
        config.TEMP_RESULTS_DIR = result_dir

        from app.models.schemas import AnalysisRequest, DocumentExtractionData
        from app.services.analysis_service import (
            AnalysisDocumentUnavailableError,
            analysis_service,
        )
        from app.services.pdf_service import PDFService

        pdf_path = upload_dir / f"{document_id}.pdf"
        unlink_entered = threading.Event()
        allow_unlink = threading.Event()
        registration_attempted = threading.Event()
        original_unlink = Path.unlink

        def pause_before_unlink(path, *args, **kwargs):
            if path == pdf_path:
                unlink_entered.set()
                if not allow_unlink.wait(timeout=5):
                    raise TimeoutError("cleanup unlink gate timed out")
            return original_unlink(path, *args, **kwargs)

        Path.unlink = pause_before_unlink
        analysis_service._work_lock = threading.Lock()
        analysis_service._active_state_lock = threading.Lock()
        analysis_service._active_document_ids = set()
        analysis_service.executor = lambda *_: (_ for _ in ()).throw(
            AssertionError("executor must not run after cleanup removed the document")
        )
        text = "Synthetic source text for B10 cleanup tests."
        document = DocumentExtractionData(
            document_id=document_id,
            original_filename="b10-test.pdf",
            total_pages=1,
            total_characters=len(text),
            pages=[{"physical_page": 1, "text": text, "char_count": len(text)}],
            created_at="2026-10-31T00:00:00+00:00",
        )
        request = AnalysisRequest(document_id=document_id, analysis_mode="general")

        def preflight():
            try:
                current_pdf = PDFService.get_document_pdf_path(document_id)
                current_json = result_dir / f"{document_id}.json"
                now = time.time()
                return bool(current_pdf and current_pdf.is_file() and current_json.is_file()
                    and now - current_pdf.stat().st_mtime <= 3600
                    and now - current_json.stat().st_mtime <= 3600)
            except OSError:
                return False

        pool = ThreadPoolExecutor(max_workers=2)
        cleanup_future = None
        analysis_future = None
        try:
            cleanup_future = pool.submit(PDFService.cleanup_expired_files, 3600)
            if not unlink_entered.wait(timeout=3):
                raise TimeoutError("cleanup did not reach guarded unlink")

            def start_analysis():
                registration_attempted.set()
                try:
                    analysis_service.run(request, document, preflight=preflight)
                except AnalysisDocumentUnavailableError:
                    return "rejected"
                raise AssertionError("analysis should be rejected after cleanup")

            analysis_future = pool.submit(start_analysis)
            if not registration_attempted.wait(timeout=3):
                raise TimeoutError("analysis registration was not attempted")
            allow_unlink.set()
            assert cleanup_future.result(timeout=3) == 5
            assert analysis_future.result(timeout=3) == "rejected"
            assert not analysis_service._work_lock.locked()
        finally:
            allow_unlink.set()
            pool.shutdown(wait=True, cancel_futures=True)
            Path.unlink = original_unlink
        print("cleanup-first race rejected analysis before executor")
        '''
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            child_script,
            document_id,
            str(b10_storage[0]),
            str(b10_storage[1]),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, (
        f"B10 cleanup race subprocess failed:\nstdout={completed.stdout}\nstderr={completed.stderr}"
    )
    assert "cleanup-first race rejected analysis" in completed.stdout
