"""Document-aware validation for report evidence and PDF physical page references.

There is currently no analysis API or report persistence path in the application.
When one is added, its acceptance order must be: construct/validate AnalysisReport,
call validate_report_against_document(report, document), then and only then return or
persist the report. This module intentionally does not simulate that absent entrypoint.
"""

import re
from typing import Iterable

from pydantic import BaseModel

from app.models.schemas import AnalysisReport, DocumentExtractionData, EvidenceRef


class EvidenceValidationError(ValueError):
    """Raised when report evidence cannot be verified against extracted PDF text."""


def _normalize_extracted_whitespace(value: str) -> str:
    """Normalize only whitespace differences; preserve every non-whitespace character."""
    return re.sub(r"\s+", " ", value).strip()


def _walk_evidence(value) -> Iterable[EvidenceRef]:
    if isinstance(value, EvidenceRef):
        yield value
    elif isinstance(value, BaseModel):
        for field_value in value.__dict__.values():
            yield from _walk_evidence(field_value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_evidence(item)


def validate_report_against_document(
    report: AnalysisReport, document: DocumentExtractionData
) -> None:
    """Check report identity, all physical page bounds, and exact normalized quote matches.

    Only whitespace runs are normalized for comparison. The report's original_quote is
    never rewritten; punctuation, wording, and other characters must match exactly.
    Call this after AnalysisReport schema validation and before any future analysis
    result is accepted, returned as successful, or persisted.
    """
    if report.document_id != document.document_id:
        raise EvidenceValidationError("報告文件識別碼與 PDF 擷取資料不一致。")
    if report.total_pages != document.total_pages:
        raise EvidenceValidationError("報告總頁數與 PDF 實際總頁數不一致。")

    pages_by_number = {page.physical_page: page for page in document.pages}
    if len(pages_by_number) != document.total_pages or set(pages_by_number) != set(
        range(1, document.total_pages + 1)
    ):
        raise EvidenceValidationError(
            "PDF 擷取頁面未依 1-based physical_page 完整對應實際總頁數。"
        )

    for section in report.outline:
        if section.start_page > document.total_pages or section.end_page > document.total_pages:
            raise EvidenceValidationError(
                f"文章大綱章節「{section.title}」頁碼超出 PDF 實際總頁數 {document.total_pages}。"
            )

    normalized_pages = {
        page_number: _normalize_extracted_whitespace(page.text)
        for page_number, page in pages_by_number.items()
    }
    for evidence in _walk_evidence(report):
        if evidence.page_number > document.total_pages:
            raise EvidenceValidationError(
                f"引句頁碼 {evidence.page_number} 超出 PDF 實際總頁數 {document.total_pages}。"
            )
        quote = _normalize_extracted_whitespace(evidence.original_quote)
        if not quote or quote not in normalized_pages[evidence.page_number]:
            raise EvidenceValidationError(
                f"引句驗證失敗：PDF 物理頁碼 {evidence.page_number} 的擷取文字中找不到原始引句。"
            )
