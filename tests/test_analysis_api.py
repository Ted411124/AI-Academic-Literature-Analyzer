"""Tests for the analysis request validation boundary (no AI service is called)."""

import os
import subprocess
import sys
import threading
import textwrap
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import config
from app.main import app
from app.models.schemas import (
    DocumentExtractionData,
    MetadataReviewDecision,
    MetadataReviewRequest,
)
from app.services import metadata_service
from app.services.analysis_service import analysis_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def disable_default_analysis_executor(monkeypatch):
    """Keep API boundary tests isolated from the production Gemini executor."""
    monkeypatch.setattr(analysis_service, "executor", None)

DOCUMENT_ID = "a" * 32


@pytest.fixture
def analysis_document(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    monkeypatch.setattr(config, "TEMP_FILE_TTL_SECONDS", 3600)

    document = DocumentExtractionData(
        document_id=DOCUMENT_ID,
        original_filename="paper.pdf",
        total_pages=1,
        total_characters=40,
        pages=[{"physical_page": 1, "text": "A short extracted research paper text.", "char_count": 40}],
        created_at="2026-10-30T00:00:00+00:00",
    )
    (result_dir / f"{DOCUMENT_ID}.json").write_text(document.model_dump_json(), encoding="utf-8")
    (upload_dir / f"{DOCUMENT_ID}.pdf").write_bytes(b"test-only-placeholder")
    return document, upload_dir, result_dir


def set_review(document, decision):
    pending = metadata_service.unrecognized_review(document.document_id)
    review = metadata_service.apply_review(
        pending,
        MetadataReviewRequest(decision=decision),
    )
    metadata_service.save_review(review)
    return review


@pytest.fixture
def isolated_analysis_service(monkeypatch):
    """Give each lock test a fresh process-local lock and no default executor."""
    monkeypatch.setattr(analysis_service, "_work_lock", threading.Lock())
    monkeypatch.setattr(analysis_service, "executor", None)
    return analysis_service


@pytest.mark.parametrize("mode", ["general", "topic"])
def test_valid_general_and_topic_requests_reach_not_implemented_response(analysis_document, mode):
    document, _, _ = analysis_document
    set_review(document, MetadataReviewDecision.CONFIRMED)
    payload = {"document_id": DOCUMENT_ID, "analysis_mode": mode}
    if mode == "topic":
        payload["topic"] = "Transatlantic trade"

    response = client.post("/api/analysis", json=payload)

    assert response.status_code == 501
    assert response.json() == {
        "status": "not_implemented",
        "analysis_started": False,
        "message": "分析服務尚未啟用；請求資料已驗證，但尚未開始分析或產生報告。",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"document_id": DOCUMENT_ID, "analysis_mode": "other"},
        {"document_id": DOCUMENT_ID, "analysis_mode": "topic"},
        {"document_id": DOCUMENT_ID, "analysis_mode": "topic", "topic": "   \n "},
        {"document_id": DOCUMENT_ID, "analysis_mode": "general", "topic": "unexpected"},
        {"document_id": "bad-id", "analysis_mode": "general"},
    ],
)
def test_invalid_analysis_request_is_rejected(analysis_document, payload):
    response = client.post("/api/analysis", json=payload)
    assert response.status_code == 422


def test_general_request_accepts_null_topic_and_skipped_metadata(analysis_document):
    document, _, _ = analysis_document
    set_review(document, MetadataReviewDecision.SKIPPED)

    response = client.post("/api/analysis", json={
        "document_id": DOCUMENT_ID,
        "analysis_mode": "general",
        "topic": None,
    })

    assert response.status_code == 501
    assert response.json()["analysis_started"] is False


def test_unknown_or_expired_document_is_rejected(analysis_document):
    _, upload_dir, result_dir = analysis_document
    missing = client.post("/api/analysis", json={
        "document_id": "b" * 32,
        "analysis_mode": "general",
    })
    assert missing.status_code == 404

    old_time = time.time() - config.TEMP_FILE_TTL_SECONDS - 10
    for path in (upload_dir / f"{DOCUMENT_ID}.pdf", result_dir / f"{DOCUMENT_ID}.json"):
        os.utime(path, (old_time, old_time))
    expired = client.post("/api/analysis", json={
        "document_id": DOCUMENT_ID,
        "analysis_mode": "general",
    })
    assert expired.status_code == 404


def test_pending_metadata_blocks_request_but_confirmed_or_skipped_does_not(analysis_document):
    document, _, _ = analysis_document
    pending = metadata_service.unrecognized_review(document.document_id)
    metadata_service.save_review(pending)

    response = client.post("/api/analysis", json={
        "document_id": DOCUMENT_ID,
        "analysis_mode": "general",
    })
    assert response.status_code == 409

    set_review(document, MetadataReviewDecision.SKIPPED)
    response = client.post("/api/analysis", json={
        "document_id": DOCUMENT_ID,
        "analysis_mode": "general",
    })
    assert response.status_code == 501


def test_concurrent_analysis_is_rejected_and_lock_releases_after_success(
    analysis_document
):
    _, upload_dir, result_dir = analysis_document
    child_script = textwrap.dedent(
        '''
        import importlib
        import json
        import os
        import sys
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path

        from fastapi.testclient import TestClient

        document_id, upload_path, result_path = sys.argv[1:]
        upload_dir = Path(upload_path)
        result_dir = Path(result_path)
        project_storage = (Path.cwd() / "storage").resolve()
        original_makedirs = os.makedirs

        def prevent_formal_storage_creation(path, *args, **kwargs):
            candidate = Path(path).resolve()
            try:
                candidate.relative_to(project_storage)
            except ValueError:
                return original_makedirs(path, *args, **kwargs)
            return None

        os.makedirs = prevent_formal_storage_creation
        try:
            config = importlib.import_module("app.config")
        finally:
            os.makedirs = original_makedirs

        config.TEMP_UPLOADS_DIR = upload_dir
        config.TEMP_RESULTS_DIR = result_dir
        main_module = importlib.import_module("app.main")
        from app.models.schemas import MetadataReviewStatus

        main_module._get_metadata_review = lambda document: type(
            "ConfirmedReview", (), {
                "document_id": document.document_id,
                "status": MetadataReviewStatus.CONFIRMED,
            }
        )()

        started = threading.Event()
        release = threading.Event()
        calls = []

        def mock_executor(request, document):
            calls.append((request.document_id, document.document_id))
            if len(calls) == 1:
                started.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("child executor release timed out")
            return None

        main_module.analysis_service._work_lock = threading.Lock()
        main_module.analysis_service.executor = mock_executor
        payload = {"document_id": document_id, "analysis_mode": "general"}

        def post_in_independent_client():
            with TestClient(main_module.app) as test_client:
                return test_client.post("/api/analysis", json=payload)

        pool = ThreadPoolExecutor(max_workers=1)
        future = None
        try:
            future = pool.submit(post_in_independent_client)
            if not started.wait(timeout=5):
                raise TimeoutError("first analysis request did not enter executor")

            with TestClient(main_module.app) as second_client:
                second = second_client.post("/api/analysis", json=payload)
            assert second.status_code == 409
            assert second.json()["error_code"] == "ANALYSIS_BUSY"
            assert len(calls) == 1

            release.set()
            first = future.result(timeout=5)
            assert first.status_code == 501
            assert first.json()["analysis_started"] is False

            with TestClient(main_module.app) as third_client:
                third = third_client.post("/api/analysis", json=payload)
            assert third.status_code == 501
            assert third.json()["analysis_started"] is False
            assert len(calls) == 2
            print(json.dumps({"first": 501, "second": 409, "third": 501, "executor_calls": 2}))
        finally:
            release.set()
            pool.shutdown(wait=True, cancel_futures=True)
        '''
    )

    command = [
        sys.executable,
        "-B",
        "-c",
        child_script,
        DOCUMENT_ID,
        str(upload_dir),
        str(result_dir),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "並行分析子程序超過 20 秒；subprocess.run 已終止並回收子程序。 "
            f"stdout={exc.stdout!r}; stderr={exc.stderr!r}"
        )

    assert completed.returncode == 0, (
        "並行分析子程序失敗：\n"
        f"stdout={completed.stdout}\n"
        f"stderr={completed.stderr}"
    )
    assert '"second": 409' in completed.stdout
    assert '"executor_calls": 2' in completed.stdout


def test_analysis_exception_releases_lock_for_later_request(
    analysis_document, isolated_analysis_service, monkeypatch
):
    document, _, _ = analysis_document
    set_review(document, MetadataReviewDecision.CONFIRMED)
    payload = {"document_id": DOCUMENT_ID, "analysis_mode": "general"}
    calls = []

    def fail_once_executor(_request, _document):
        calls.append("called")
        if len(calls) == 1:
            raise RuntimeError("synthetic analysis failure")
        return None

    monkeypatch.setattr(isolated_analysis_service, "executor", fail_once_executor)

    failed = client.post("/api/analysis", json=payload)
    assert failed.status_code == 500
    assert "traceback" not in failed.text.lower()

    retried = client.post("/api/analysis", json=payload)
    assert retried.status_code == 501
    assert retried.json()["analysis_started"] is False
    assert calls == ["called", "called"]


def test_invalid_analysis_request_does_not_call_executor_or_hold_lock(
    analysis_document, isolated_analysis_service, monkeypatch
):
    document, _, _ = analysis_document
    calls = []
    monkeypatch.setattr(
        isolated_analysis_service,
        "executor",
        lambda _request, _document: calls.append("called"),
    )

    invalid = client.post("/api/analysis", json={
        "document_id": DOCUMENT_ID,
        "analysis_mode": "topic",
        "topic": "   ",
    })
    assert invalid.status_code == 422
    assert calls == []

    set_review(document, MetadataReviewDecision.SKIPPED)
    valid = client.post("/api/analysis", json={
        "document_id": DOCUMENT_ID,
        "analysis_mode": "general",
    })
    assert valid.status_code == 501
    assert valid.json()["analysis_started"] is False
    assert calls == ["called"]
