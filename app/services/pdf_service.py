"""
PDF 處理與物理頁碼文字擷取服務模組 (PDF Processing Service)
使用 PyMuPDF (fitz) 實作高精確度之實體頁碼綁定、文字擷取、安全上傳與暫存清理。
"""

import os
import re
import json
import uuid
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Tuple

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from app import config
from app.models.schemas import PageTextItem, DocumentExtractionData
from app.services.analysis_service import analysis_service

logger = logging.getLogger(__name__)
_DOCUMENT_ARTIFACT_PATTERN = re.compile(
    r"^(?P<document_id>[0-9a-f]{32})(?:\.pdf|\.json(?:\.tmp)?|\.metadata\.json(?:\.tmp)?|\.report\.json(?:\.tmp)?)$"
)


# -------------------------------------------------------------
# 自訂結構化例外類別 (Custom Exceptions)
# -------------------------------------------------------------

class PDFServiceException(Exception):
    """PDF 處理基礎例外"""
    def __init__(self, message: str, error_code: str = "PDF_ERROR"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class PDFValidationError(PDFServiceException):
    """檔案格式驗證錯誤 (非 PDF / 未選擇檔案)"""
    def __init__(self, message: str):
        super().__init__(message, error_code="INVALID_FILE_TYPE")


class PDFSizeLimitExceededError(PDFServiceException):
    """檔案容量超限錯誤"""
    def __init__(self, message: str):
        super().__init__(message, error_code="FILE_TOO_LARGE")


class PDFPageLimitExceededError(PDFServiceException):
    """頁數超出系統上限錯誤"""
    def __init__(self, message: str):
        super().__init__(message, error_code="PAGE_LIMIT_EXCEEDED")


class PDFCorruptedError(PDFServiceException):
    """PDF 損毀或受密碼保護錯誤"""
    def __init__(self, message: str):
        super().__init__(message, error_code="CORRUPTED_PDF")


class PDFNoTextError(PDFServiceException):
    """掃描型 PDF 或缺乏有效文字內容錯誤"""
    def __init__(self, message: str):
        super().__init__(message, error_code="NO_EXTRACTABLE_TEXT")


# -------------------------------------------------------------
# PDF 服務核心類別
# -------------------------------------------------------------

class PDFService:
    """PDF 檔案驗證、實體頁碼逐頁文字擷取與暫存管理服務"""

    UPLOAD_CHUNK_SIZE = 64 * 1024

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """過濾檔名，嚴防路徑穿越 (Path Traversal) 與非法字元"""
        base_name = Path(filename).name
        # 僅保留一般文字、數字、底線、減號、點與 CJK 字元
        cleaned = re.sub(r'[^\w\s\.\-\(\)\[\]\u4e00-\u9fa5\u3040-\u30ff]', '_', base_name)
        return cleaned.strip() or "unnamed_document.pdf"

    @classmethod
    def save_upload_stream(cls, file_stream, filename: str) -> Tuple[str, Path, str]:
        """
        分塊讀取上傳串流，驗證並以隨機 document_id 暫存於 storage/temp_uploads/
        回傳: (document_id, saved_pdf_path, sanitized_filename)
        """
        # 先驗證副檔名，避免為無效檔名建立暫存檔。
        sanitized_name = cls.sanitize_filename(filename)
        if not sanitized_name.lower().endswith(".pdf"):
            raise PDFValidationError("非 PDF 檔案格式，本系統僅接受副檔名為 .pdf 之文件。")

        # 以 UUID 和 exclusive create 避免覆寫既有文件。
        document_id = uuid.uuid4().hex
        pdf_path = config.TEMP_UPLOADS_DIR / f"{document_id}.pdf"
        total_bytes = 0
        header_sample = bytearray()
        try:
            with open(pdf_path, "xb") as destination:
                while True:
                    chunk = file_stream.read(cls.UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise PDFServiceException("上傳串流回傳非二進位資料。", error_code="UPLOAD_READ_ERROR")

                    next_total = total_bytes + len(chunk)
                    if next_total > config.MAX_FILE_SIZE_BYTES:
                        raise PDFSizeLimitExceededError(
                            f"檔案大小超過系統限制（{config.MAX_FILE_SIZE_MB} MB）。"
                        )

                    if len(header_sample) < 1024:
                        header_sample.extend(chunk[: 1024 - len(header_sample)])
                    destination.write(chunk)
                    total_bytes = next_total

                    # PDF 標頭應位於前 1024 bytes，達到該範圍即可提早拒絕。
                    if len(header_sample) >= 1024 and b"%PDF-" not in header_sample:
                        raise PDFValidationError("檔案內容損壞或非標準 PDF 結構（無有效 PDF 標頭標記）。")

            if total_bytes == 0:
                raise PDFValidationError("未選擇檔案或上傳檔案為空，請重新選擇。")
            if b"%PDF-" not in header_sample:
                raise PDFValidationError("檔案內容損壞或非標準 PDF 結構（無有效 PDF 標頭標記）。")
        except Exception as e:
            cls._safe_unlink(pdf_path)
            if isinstance(e, PDFServiceException):
                raise
            raise PDFServiceException(f"暫存檔案寫入失敗：{str(e)}", error_code="STORAGE_ERROR") from e

        return document_id, pdf_path, sanitized_name

    @classmethod
    def validate_and_save_upload(cls, file_bytes: bytes, filename: str) -> Tuple[str, Path, str]:
        """相容既有 bytes 呼叫端；實際驗證與寫入仍使用分塊流程。"""
        import io

        return cls.save_upload_stream(io.BytesIO(file_bytes), filename)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("無法清理暫存檔：%s", path)

    @classmethod
    def cleanup_document_artifacts(cls, document_id: str) -> None:
        """只清除本服務 UUID 命名的單一文件及其已知暫存產物。"""
        if not re.fullmatch(r"[0-9a-f]{32}", document_id or ""):
            logger.warning("拒絕清理格式不符的 document_id")
            return

        def remove_artifacts() -> None:
            cls._safe_unlink(config.TEMP_UPLOADS_DIR / f"{document_id}.pdf")
            cls._safe_unlink(config.TEMP_RESULTS_DIR / f"{document_id}.json")
            cls._safe_unlink(config.TEMP_RESULTS_DIR / f"{document_id}.json.tmp")
            cls._safe_unlink(config.TEMP_RESULTS_DIR / f"{document_id}.metadata.json")
            cls._safe_unlink(config.TEMP_RESULTS_DIR / f"{document_id}.metadata.json.tmp")
            cls._safe_unlink(config.TEMP_RESULTS_DIR / f"{document_id}.report.json")
            cls._safe_unlink(config.TEMP_RESULTS_DIR / f"{document_id}.report.json.tmp")

        ran, _ = analysis_service.run_if_document_inactive(document_id, remove_artifacts)
        if not ran:
            logger.info("略過清理分析中的文件：%s", document_id)

    @classmethod
    def extract_document(cls, pdf_path: Path, document_id: str, original_filename: str) -> DocumentExtractionData:
        """
        使用 PyMuPDF 開啟 PDF，嚴格按 1-based 物理頁碼逐頁擷取原文純文字，
        驗證文字有效性，並將結構化結果儲存至 storage/temp_results/{document_id}.json
        """
        doc = None
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            raise PDFCorruptedError(f"無法解析 PDF 檔案結構，文件可能已損壞或格式異常。({str(e)})")

        try:
            # 1. 檢查是否加密且無法空密碼解密
            if doc.is_encrypted:
                if not doc.authenticate(""):
                    raise PDFCorruptedError("該 PDF 設有讀取密碼保護，系統無法直接解析。")

            total_pages = doc.page_count

            # 2. 檢查頁數是否為 0
            if total_pages == 0:
                raise PDFNoTextError("PDF 文件頁數為 0，無任何可讀取內容。")

            # 3. 檢查頁數上限 (依據 config.MAX_PAGES)
            if total_pages > config.MAX_PAGES:
                raise PDFPageLimitExceededError(
                    f"PDF 總頁數為 {total_pages} 頁，超過系統單次分析上限（{config.MAX_PAGES} 頁）。"
                )

            # 4. 逐頁擷取文字並精確錨定 1-based 物理頁碼
            pages_list: List[PageTextItem] = []
            total_chars = 0

            for page_idx in range(total_pages):
                # 剛性保證：物理頁碼絕對從 1 開始，與 PDF 閱讀器完全一致
                physical_page = page_idx + 1
                page = doc[page_idx]

                # 採用 sort=True 維護多欄排版下由上至下、由左至右的合理閱讀順序
                raw_text = page.get_text("text", sort=True)
                cleaned_text = raw_text.strip() if raw_text else ""
                char_count = len(cleaned_text)
                total_chars += char_count

                pages_list.append(
                    PageTextItem(
                        physical_page=physical_page,
                        text=cleaned_text,
                        char_count=char_count,
                    )
                )

            # 5. 檢核整份文件之文字有效性 (判定是否為純掃描檔/無字圖檔)
            if total_chars < config.MIN_TOTAL_CHARACTERS:
                raise PDFNoTextError(
                    "此 PDF 為掃描圖檔或缺乏可擷取的純文字內容。本系統僅支援具有數位純文字之學術 PDF，不支援純圖片掃描檔。"
                )

            # 6. 建構完整結構化結果物件
            created_at = datetime.now(timezone.utc).isoformat()
            extraction_data = DocumentExtractionData(
                document_id=document_id,
                original_filename=original_filename,
                total_pages=total_pages,
                total_characters=total_chars,
                pages=pages_list,
                created_at=created_at,
            )

            # 7. 儲存至 temp_results (提供後續 Gemini 分析階段直接調用)
            result_path = config.TEMP_RESULTS_DIR / f"{document_id}.json"
            partial_result_path = config.TEMP_RESULTS_DIR / f"{document_id}.json.tmp"
            try:
                with open(partial_result_path, "x", encoding="utf-8") as f:
                    f.write(extraction_data.model_dump_json(indent=2))
                os.replace(partial_result_path, result_path)
            except Exception as e:
                cls._safe_unlink(partial_result_path)
                raise PDFServiceException(
                    f"分析結構化快取寫入失敗：{str(e)}", error_code="STORAGE_ERROR"
                ) from e

            return extraction_data

        finally:
            if doc is not None:
                doc.close()

    @classmethod
    def get_document_data(cls, document_id: str) -> Optional[DocumentExtractionData]:
        """從 storage/temp_results/ 讀取已擷取之結構化資料"""
        # 防止 document_id 路徑穿越
        safe_id = Path(document_id).name
        result_path = config.TEMP_RESULTS_DIR / f"{safe_id}.json"
        if not result_path.exists():
            return None

        try:
            with open(result_path, "r", encoding="utf-8") as f:
                data_dict = json.load(f)
            return DocumentExtractionData(**data_dict)
        except Exception:
            return None

    @classmethod
    def get_document_pdf_path(cls, document_id: str) -> Optional[Path]:
        """取得暫存 PDF 實體檔案路徑 (若仍存在)"""
        safe_id = Path(document_id).name
        pdf_path = config.TEMP_UPLOADS_DIR / f"{safe_id}.pdf"
        return pdf_path if pdf_path.exists() else None

    @classmethod
    def cleanup_expired_files(cls, ttl_seconds: int = config.TEMP_FILE_TTL_SECONDS) -> int:
        """
        掃描暫存目錄，清理超過 TTL 生命週期之 PDF 與 JSON 暫存檔
        回傳刪除之檔案數量

        Each candidate's active-document check, fresh TTL check, and unlink are
        serialized with analysis registration by AnalysisService's state lock.
        """
        deleted_count = 0

        for target_dir in [config.TEMP_UPLOADS_DIR, config.TEMP_RESULTS_DIR]:
            if not target_dir.exists():
                continue
            for file_path in target_dir.iterdir():
                if file_path.name.startswith("."):
                    continue

                match = _DOCUMENT_ARTIFACT_PATTERN.fullmatch(file_path.name)
                document_id = match.group("document_id") if match else None

                def remove_if_expired() -> bool:
                    if not file_path.is_file():
                        return False
                    file_mtime = file_path.stat().st_mtime
                    if time.time() - file_mtime <= ttl_seconds:
                        return False
                    file_path.unlink(missing_ok=True)
                    return True

                try:
                    _, deleted = analysis_service.run_if_document_inactive(
                        document_id, remove_if_expired
                    )
                    if deleted:
                        deleted_count += 1
                except Exception:
                    logger.exception("清理逾時暫存檔失敗：%s", file_path)

        return deleted_count
