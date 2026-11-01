"""
PDF 上傳與查詢 API 整合測試 (PDF Upload & Inspection API Tests)
測試 API 路由之 HTTP 狀態碼、JSON 結構、繁體中文錯誤提示與安全驗證。
"""

from fastapi.testclient import TestClient
import pytest
try:
    import pymupdf as fitz
except ImportError:
    import fitz

from app import config
from app.main import app
from app.models.schemas import MetadataReviewStatus, MetadataValueSource
from app.services.pdf_service import PDFCorruptedError, PDFService
from app.services import metadata_service
from app.services.gemini_service import GeminiService
import app.services.pdf_service as pdf_service_module

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_upload_storage(tmp_path, monkeypatch):
    """API 測試只操作自己的暫存目錄，避免讀寫專案既有 storage 資料。"""
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    return upload_dir, result_dir


def make_pdf_bytes(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        p = doc.new_page()
        if text:
            p.insert_text((50, 72), text)
    b = doc.tobytes()
    doc.close()
    return b


def test_api_upload_success():
    """測試正常文字型 PDF 透過 API 上傳成功"""
    pdf_bytes = make_pdf_bytes([
        "Introduction: Deep learning models have demonstrated outstanding performance.",
        "Methodology: We propose a closed-domain citation extraction pipeline.",
    ])

    response = client.post(
        "/api/documents/upload",
        files={"file": ("academic_paper.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "document_id" in data
    assert data["original_filename"] == "academic_paper.pdf"
    assert data["total_pages"] == 2
    assert data["total_characters"] > 0
    assert "Introduction" in data["preview_excerpt"]
    assert "物理頁碼" in data["message"]

    doc_id = data["document_id"]

    # 驗證查詢文件資訊 API (GET /api/documents/{doc_id})
    info_res = client.get(f"/api/documents/{doc_id}")
    assert info_res.status_code == 200
    info_data = info_res.json()
    assert info_data["document_id"] == doc_id
    assert info_data["total_pages"] == 2

    # 驗證取得逐頁文字 API (GET /api/documents/{doc_id}/pages)
    pages_res = client.get(f"/api/documents/{doc_id}/pages")
    assert pages_res.status_code == 200
    pages_data = pages_res.json()
    assert pages_data["total_pages"] == 2
    assert len(pages_data["pages"]) == 2
    assert pages_data["pages"][0]["physical_page"] == 1
    assert "Introduction" in pages_data["pages"][0]["text"]
    assert pages_data["pages"][1]["physical_page"] == 2
    assert "Methodology" in pages_data["pages"][1]["text"]


def test_api_metadata_review_confirm_edit_skip_and_preserve_extraction(monkeypatch):
    pdf_bytes = make_pdf_bytes([
        "Title: A Careful Study of Academic Evidence\n"
        "Authors: Jane Doe; John Roe\n"
        "Publication year: 2024\n"
        "This paper examines available experimental evidence in sufficient detail.",
        "Second page with additional research content.",
    ])
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("metadata.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 200
    initial = upload.json()["metadata_review"]
    document_id = upload.json()["document_id"]
    assert initial["status"] == MetadataReviewStatus.PENDING_CONFIRMATION.value
    assert initial["title"]["evidence"]["page_number"] == 1
    assert "Title: A Careful Study" in initial["title"]["evidence"]["original_quote"]

    extraction_before = client.get(f"/api/documents/{document_id}/pages").json()
    monkeypatch.setattr(
        GeminiService,
        "analyze_literature",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini must not be called")),
    )
    confirmed = client.post(
        f"/api/documents/{document_id}/metadata",
        json={
            "decision": "confirmed",
            "title": initial["title"]["value"],
            "authors": ["Jane Edited"],
            "publication_year": initial["publication_year"]["value"],
            "detected_language": initial["detected_language"]["value"],
        },
    )
    assert confirmed.status_code == 200
    confirmed_data = confirmed.json()
    assert confirmed_data["status"] == MetadataReviewStatus.CONFIRMED.value
    assert confirmed_data["title"]["source"] == MetadataValueSource.PDF_DETECTED.value
    assert confirmed_data["title"]["evidence"] == initial["title"]["evidence"]
    assert confirmed_data["authors"]["source"] == MetadataValueSource.USER_PROVIDED.value
    assert confirmed_data["authors"]["evidence"] is None

    skipped = client.post(
        f"/api/documents/{document_id}/metadata",
        json={"decision": "skipped"},
    )
    assert skipped.status_code == 200
    assert skipped.json()["status"] == MetadataReviewStatus.SKIPPED.value
    assert skipped.json()["authors"]["source"] == MetadataValueSource.USER_PROVIDED.value
    assert client.get(f"/api/documents/{document_id}/metadata").json() == skipped.json()
    assert client.get(f"/api/documents/{document_id}/pages").json() == extraction_before


def test_metadata_detection_exception_does_not_fail_pdf_upload(monkeypatch):
    def fail_detection(_document):
        raise RuntimeError("synthetic metadata failure")

    monkeypatch.setattr(metadata_service, "get_or_detect", fail_detection)
    response = client.post(
        "/api/documents/upload",
        files={"file": ("metadata_failure.pdf", make_pdf_bytes([
            "This is enough ordinary academic text to produce a valid PDF extraction."
        ]), "application/pdf")},
    )
    assert response.status_code == 200
    review = response.json()["metadata_review"]
    assert review["status"] == MetadataReviewStatus.PENDING_CONFIRMATION.value
    assert review["title"]["value"] is None
    assert client.get(f"/api/documents/{response.json()['document_id']}/pages").status_code == 200


def test_api_upload_rejects_non_pdf():
    """測試非 PDF 檔案上傳被拒絕 (HTTP 400)"""
    response = client.post(
        "/api/documents/upload",
        files={"file": ("malicious.txt", b"plain text content", "text/plain")},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "INVALID_FILE_TYPE"
    assert "非 PDF 檔案格式" in data["message"]


def test_api_upload_rejects_oversize_stream_without_leaving_partial_file(monkeypatch, isolate_upload_storage):
    upload_dir, _ = isolate_upload_storage
    pdf_bytes = make_pdf_bytes(["Synthetic PDF content used for API size validation."])
    monkeypatch.setattr(config, "MAX_FILE_SIZE_BYTES", len(pdf_bytes) - 1)

    response = client.post(
        "/api/documents/upload",
        files={"file": ("too_large.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_TOO_LARGE"
    assert list(upload_dir.iterdir()) == []


def test_api_upload_rejects_corrupted_pdf():
    """測試損壞的 PDF 檔案上傳被拒絕 (HTTP 400)"""
    response = client.post(
        "/api/documents/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4 garbage corrupt content", "application/pdf")},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "CORRUPTED_PDF"
    assert "無法解析 PDF 檔案結構" in data["message"]


def test_api_parse_failure_removes_uploaded_pdf(monkeypatch, isolate_upload_storage):
    upload_dir, result_dir = isolate_upload_storage

    def fail_extraction(cls, **kwargs):
        raise PDFCorruptedError("synthetic parser failure")

    monkeypatch.setattr(PDFService, "extract_document", classmethod(fail_extraction))
    response = client.post(
        "/api/documents/upload",
        files={"file": ("parse_failure.pdf", make_pdf_bytes(["Synthetic valid text for parser failure."]), "application/pdf")},
    )

    assert response.status_code == 400
    assert list(upload_dir.iterdir()) == []
    assert list(result_dir.iterdir()) == []


def test_api_json_cache_failure_removes_pdf_and_partial_json(monkeypatch, isolate_upload_storage):
    upload_dir, result_dir = isolate_upload_storage
    original_replace = pdf_service_module.os.replace

    def fail_json_replace(source, destination):
        if str(destination).endswith(".json"):
            raise OSError("synthetic cache commit failure")
        return original_replace(source, destination)

    monkeypatch.setattr(pdf_service_module.os, "replace", fail_json_replace)
    response = client.post(
        "/api/documents/upload",
        files={"file": ("cache_failure.pdf", make_pdf_bytes(["Synthetic valid text for cache failure."]), "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json()["error_code"] == "STORAGE_ERROR"
    assert list(upload_dir.iterdir()) == []
    assert list(result_dir.iterdir()) == []


def test_api_upload_rejects_scanned_or_no_text_pdf():
    """測試無有效文字或純空白/掃描 PDF 上傳被拒絕 (HTTP 422)"""
    blank_pdf = make_pdf_bytes(["", ""])
    response = client.post(
        "/api/documents/upload",
        files={"file": ("scanned_blank.pdf", blank_pdf, "application/pdf")},
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "NO_EXTRACTABLE_TEXT"
    assert "為掃描圖檔或缺乏可擷取的純文字內容" in data["message"]


def test_api_get_nonexistent_document():
    """測試查詢不存在的文件回傳 HTTP 404"""
    response = client.get("/api/documents/nonexistent_id_999")
    assert response.status_code == 404
