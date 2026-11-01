"""
PDF 處理服務單元測試 (PDF Service Unit Tests)
測試物理頁碼錨定、文字擷取、多頁處理、邊界條件與暫存清理。
"""

import os
import time
import io
import pytest
try:
    import pymupdf as fitz
except ImportError:
    import fitz

from app import config
from app.services.pdf_service import (
    PDFService,
    PDFServiceException,
    PDFValidationError,
    PDFSizeLimitExceededError,
    PDFPageLimitExceededError,
    PDFCorruptedError,
    PDFNoTextError,
)


def create_in_memory_pdf(pages_text: list[str]) -> bytes:
    """使用 PyMuPDF 動態建立測試用記憶體 PDF 位元組"""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_sanitize_filename_prevents_path_traversal():
    """測試檔名過濾：防止路徑穿越與特殊危險字元"""
    malicious_names = [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("..\\..\\windows\\system32.pdf", "system32.pdf"),
        ("paper;rm -rf;.pdf", "paper_rm -rf_.pdf"),
        ("學術論文_2024 (Test).pdf", "學術論文_2024 (Test).pdf"),
        ("", "unnamed_document.pdf"),
    ]
    for raw, expected in malicious_names:
        sanitized = PDFService.sanitize_filename(raw)
        assert sanitized == expected
        assert ".." not in sanitized
        assert "/" not in sanitized
        assert "\\" not in sanitized


def test_validate_and_save_upload_success(isolated_storage):
    """測試合規 PDF 驗證與儲存"""
    sample_pdf = create_in_memory_pdf(["This is a valid academic paper test page."])
    doc_id, path, filename = PDFService.validate_and_save_upload(sample_pdf, "test_paper.pdf")
    try:
        assert doc_id is not None
        assert len(doc_id) == 32
        assert path.exists()
        assert filename == "test_paper.pdf"
    finally:
        if path.exists():
            path.unlink()


def test_validate_rejects_empty_file(isolated_storage):
    """測試拒絕空檔案"""
    with pytest.raises(PDFValidationError, match="未選擇檔案或上傳檔案為空"):
        PDFService.validate_and_save_upload(b"", "empty.pdf")


def test_validate_rejects_non_pdf(isolated_storage):
    """測試拒絕非 PDF 副檔名與非 PDF 內容"""
    # 非 PDF 副檔名
    with pytest.raises(PDFValidationError, match="非 PDF 檔案格式"):
        PDFService.validate_and_save_upload(b"%PDF-1.4 mock", "test.txt")

    # 假冒 PDF 副檔名但無 PDF Magic Bytes
    with pytest.raises(PDFValidationError, match="無有效 PDF 標頭標記"):
        PDFService.validate_and_save_upload(b"This is just a text file.", "fake.pdf")


def test_validate_rejects_file_size_exceeded(monkeypatch, isolated_storage):
    """測試拒絕超過容量上限之檔案"""
    sample_pdf = create_in_memory_pdf(["Some text"])
    # 臨時模擬 MAX_FILE_SIZE_BYTES 為極小值以測試觸發
    monkeypatch.setattr(config, "MAX_FILE_SIZE_BYTES", len(sample_pdf) - 5)
    with pytest.raises(PDFSizeLimitExceededError, match="超過系統限制"):
        PDFService.validate_and_save_upload(sample_pdf, "large.pdf")


def test_stream_upload_reads_in_bounded_chunks_and_saves(tmp_path, monkeypatch):
    """串流上傳只以固定大小讀取，且正常 PDF 可成功暫存。"""
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    monkeypatch.setattr(PDFService, "UPLOAD_CHUNK_SIZE", 128)

    class TrackingStream(io.BytesIO):
        read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            assert 0 < size <= PDFService.UPLOAD_CHUNK_SIZE
            return super().read(size)

    sample_pdf = create_in_memory_pdf(["A synthetic PDF used to verify bounded streaming reads."])
    stream = TrackingStream(sample_pdf)
    document_id, saved_path, sanitized_name = PDFService.save_upload_stream(stream, "streamed.pdf")

    assert saved_path.read_bytes() == sample_pdf
    assert sanitized_name == "streamed.pdf"
    assert len(stream.read_sizes) > 1
    assert all(size == PDFService.UPLOAD_CHUNK_SIZE for size in stream.read_sizes)
    PDFService.cleanup_document_artifacts(document_id)


def test_stream_upload_rejects_size_limit_and_removes_partial_file(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    sample_pdf = create_in_memory_pdf(["Synthetic PDF content for size limit test."])
    monkeypatch.setattr(config, "MAX_FILE_SIZE_BYTES", len(sample_pdf) - 1)

    with pytest.raises(PDFSizeLimitExceededError):
        PDFService.save_upload_stream(io.BytesIO(sample_pdf), "too_large.pdf")

    assert list(upload_dir.iterdir()) == []


def test_stream_upload_read_failure_removes_partial_file(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)

    class FailingStream:
        def __init__(self):
            self.read_count = 0

        def read(self, size):
            self.read_count += 1
            if self.read_count == 1:
                return b"%PDF-1.7\npartial content"
            raise OSError("synthetic mid-stream read failure")

    with pytest.raises(PDFServiceException, match="暫存檔案寫入失敗"):
        PDFService.save_upload_stream(FailingStream(), "interrupted.pdf")

    assert list(upload_dir.iterdir()) == []


def test_cleanup_document_artifacts_only_removes_requested_document(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    result_dir = tmp_path / "results"
    upload_dir.mkdir()
    result_dir.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", result_dir)
    requested_id = "a" * 32
    other_id = "b" * 32
    for document_id in (requested_id, other_id):
        (upload_dir / f"{document_id}.pdf").write_bytes(b"synthetic")
        (result_dir / f"{document_id}.json").write_text("{}", encoding="utf-8")
        (result_dir / f"{document_id}.json.tmp").write_text("partial", encoding="utf-8")
        (result_dir / f"{document_id}.metadata.json").write_text("{}", encoding="utf-8")
        (result_dir / f"{document_id}.metadata.json.tmp").write_text("partial", encoding="utf-8")

    PDFService.cleanup_document_artifacts(requested_id)

    assert not (upload_dir / f"{requested_id}.pdf").exists()
    assert not (result_dir / f"{requested_id}.json").exists()
    assert not (result_dir / f"{requested_id}.json.tmp").exists()
    assert not (result_dir / f"{requested_id}.metadata.json").exists()
    assert not (result_dir / f"{requested_id}.metadata.json.tmp").exists()
    assert (upload_dir / f"{other_id}.pdf").exists()
    assert (result_dir / f"{other_id}.json").exists()
    assert (result_dir / f"{other_id}.json.tmp").exists()
    assert (result_dir / f"{other_id}.metadata.json").exists()
    assert (result_dir / f"{other_id}.metadata.json.tmp").exists()


def test_extract_document_physical_pages_and_order(isolated_storage):
    """測試逐頁擷取、物理頁碼從 1 開始且不偏移、多頁依序對齊"""
    pages_content = [
        "First physical page content for testing.",
        "Second physical page content with research findings.",
        "Third physical page content with conclusion and references.",
    ]
    pdf_bytes = create_in_memory_pdf(pages_content)
    doc_id, pdf_path, _ = PDFService.validate_and_save_upload(pdf_bytes, "multipage.pdf")

    try:
        result = PDFService.extract_document(pdf_path, doc_id, "multipage.pdf")
        assert result.total_pages == 3
        assert len(result.pages) == 3

        # 驗證物理頁碼嚴格從 1 開始遞增
        for idx, page_item in enumerate(result.pages):
            expected_physical_page = idx + 1
            assert page_item.physical_page == expected_physical_page
            assert pages_content[idx] in page_item.text
            assert page_item.char_count == len(page_item.text)

        assert result.total_characters > 0
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
        result_path = config.TEMP_RESULTS_DIR / f"{doc_id}.json"
        if result_path.exists():
            result_path.unlink()


def test_printed_page_number_does_not_override_physical_page(isolated_storage):
    """測試印刷自訂頁碼 (例如期刊印刷頁 Page 345) 不會取代 PDF 實體頁碼 1"""
    # 刻意在第一頁文字印刷 "Page 345"，第二頁印刷 "Page 346"
    pages_content = [
        "Journal of Artificial Intelligence, Vol. 10. Page 345. Introduction and background.",
        "Journal of Artificial Intelligence, Vol. 10. Page 346. Methodology and setup.",
    ]
    pdf_bytes = create_in_memory_pdf(pages_content)
    doc_id, pdf_path, _ = PDFService.validate_and_save_upload(pdf_bytes, "printed_pages.pdf")

    try:
        result = PDFService.extract_document(pdf_path, doc_id, "printed_pages.pdf")
        assert result.pages[0].physical_page == 1  # 實體頁碼依然為 1
        assert "Page 345" in result.pages[0].text
        assert result.pages[1].physical_page == 2  # 實體頁碼依然為 2
        assert "Page 346" in result.pages[1].text
    finally:
        if pdf_path.exists():
            pdf_path.unlink()
        result_path = config.TEMP_RESULTS_DIR / f"{doc_id}.json"
        if result_path.exists():
            result_path.unlink()


def test_reject_blank_or_scanned_pdf(isolated_storage):
    """測試空白或純圖片/掃描無文字型 PDF 會被拒絕"""
    blank_pdf = create_in_memory_pdf(["", "", ""])
    doc_id, pdf_path, _ = PDFService.validate_and_save_upload(blank_pdf, "blank.pdf")

    try:
        with pytest.raises(PDFNoTextError, match="為掃描圖檔或缺乏可擷取的純文字內容"):
            PDFService.extract_document(pdf_path, doc_id, "blank.pdf")
    finally:
        if pdf_path.exists():
            pdf_path.unlink()


def test_reject_page_limit_exceeded(monkeypatch, isolated_storage):
    """測試超過 50 頁上限之 PDF 會被拒絕"""
    # 臨時設置 MAX_PAGES 為 3 頁以進行邊界測試
    monkeypatch.setattr(config, "MAX_PAGES", 3)
    four_pages = create_in_memory_pdf([f"Page content {i} with sufficient text." for i in range(4)])
    doc_id, pdf_path, _ = PDFService.validate_and_save_upload(four_pages, "four_pages.pdf")

    try:
        with pytest.raises(PDFPageLimitExceededError, match="超過系統單次分析上限"):
            PDFService.extract_document(pdf_path, doc_id, "four_pages.pdf")
    finally:
        if pdf_path.exists():
            pdf_path.unlink()


def test_reject_corrupted_pdf(tmp_path):
    """測試損毀之 PDF 結構會被拒絕"""
    corrupt_file = tmp_path / "corrupt.pdf"
    corrupt_file.write_bytes(b"%PDF-1.4\nCorrupted content without valid xref or trailer.")
    doc_id = "test_corrupt_id"

    with pytest.raises(PDFCorruptedError, match="無法解析 PDF 檔案結構"):
        PDFService.extract_document(corrupt_file, doc_id, "corrupt.pdf")


def test_cleanup_expired_files(tmp_path, monkeypatch):
    """測試逾時清理功能：刪除過期檔案但保留新建立之檔案"""
    test_upload_dir = tmp_path / "uploads"
    test_result_dir = tmp_path / "results"
    test_upload_dir.mkdir()
    test_result_dir.mkdir()

    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", test_upload_dir)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", test_result_dir)

    old_file = test_upload_dir / "old_doc.pdf"
    new_file = test_upload_dir / "new_doc.pdf"

    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")

    # 將 old_file 的修改時間設定為 2 小時前 (7200 秒前)
    past_time = time.time() - 7200
    os.utime(old_file, (past_time, past_time))

    # 執行清理 (TTL 設為 3600 秒)
    deleted = PDFService.cleanup_expired_files(ttl_seconds=3600)
    assert deleted == 1
    assert not old_file.exists()
    assert new_file.exists()
