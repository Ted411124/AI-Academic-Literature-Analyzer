"""Bounded, local-only paper metadata candidates and review persistence."""

import logging
import re
from pathlib import Path
from typing import Optional

from app import config
from app.models.schemas import (
    DocumentExtractionData,
    EvidenceRef,
    LanguageCode,
    MetadataReview,
    MetadataReviewDecision,
    MetadataReviewField,
    MetadataReviewRequest,
    MetadataReviewStatus,
    MetadataValueSource,
)

logger = logging.getLogger(__name__)

MAX_METADATA_PAGES = 2
MAX_METADATA_CHARACTERS = 8_000

_TRADITIONAL_MARKERS = set("體國學術論語這個為與來發現後經過時種點問題資料關係實驗結果個們從開發讓東業產會說應對將進行專業還長樂書車電門親愛臺灣")
_SIMPLIFIED_MARKERS = set("体国学术论语这个为与来发现后经过时种点问题资料关系实验结果个们从开发让东业产会说应对将进行专业还长乐书车电门亲爱台湾")
_TRADITIONAL_ONLY = _TRADITIONAL_MARKERS - _SIMPLIFIED_MARKERS
_SIMPLIFIED_ONLY = _SIMPLIFIED_MARKERS - _TRADITIONAL_MARKERS
_AFFILIATION_MARKERS = (
    "university", "department", "institute", "faculty", "laboratory", "school of",
    "college", "地址", "學院", "学院", "大學", "大学", "研究所", "研究中心", "郵編", "邮编",
)
_AUTHOR_LABEL = re.compile(r"^\s*(?:authors?|author\s+names?|by|作者群?)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)
_YEAR_LABEL = re.compile(
    r"(?:publication\s+(?:year|date)|published(?:\s+online)?|copyright|©|出版年份|出版年|出版日期|發表年份|发表年份)"
    r"[^\r\n]{0,50}?((?:18|19|20|21)\d{2})\b",
    re.IGNORECASE,
)
_TITLE_LABEL = re.compile(r"^\s*(?:paper\s+)?title\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)


def _empty_field():
    return MetadataReviewField(value=None, source=None, evidence=None)


def unrecognized_review(document_id: str) -> MetadataReview:
    """Return an explicitly empty, still-pending result after detection failure."""
    return MetadataReview(
        document_id=document_id,
        status=MetadataReviewStatus.PENDING_CONFIRMATION,
        title=_empty_field(),
        authors=_empty_field(),
        publication_year=_empty_field(),
        detected_language=_empty_field(),
    )


def _bounded_lines(document: DocumentExtractionData):
    remaining = MAX_METADATA_CHARACTERS
    result = []
    for page in document.pages[:MAX_METADATA_PAGES]:
        if remaining <= 0:
            break
        text = page.text[:remaining]
        truncated = len(page.text) > len(text)
        lines = text.splitlines()
        if truncated and lines:
            # Do not treat a cut-off final fragment as a complete metadata line.
            lines.pop()
        result.extend((page.physical_page, line.strip()) for line in lines if line.strip())
        remaining -= len(text)
    return result


def _evidence(page: int, quote: str) -> EvidenceRef:
    return EvidenceRef(page_number=page, original_quote=quote)


def _metadata_field(value, page: int, quote: str):
    return MetadataReviewField(
        value=value,
        source=MetadataValueSource.PDF_DETECTED,
        evidence=_evidence(page, quote),
    )


def _is_affiliation_or_noise(line: str) -> bool:
    lowered = line.casefold()
    return (
        "@" in line
        or bool(re.search(r"https?://|doi\s*:", lowered))
        or any(marker in lowered for marker in _AFFILIATION_MARKERS)
    )


def _detect_title(lines):
    first_page = [(page, line) for page, line in lines if page == 1]
    for page, line in first_page[:14]:
        labeled = _TITLE_LABEL.match(line)
        if labeled:
            candidate = labeled.group(1).strip()
            if 5 <= len(candidate) <= 240 and not _is_affiliation_or_noise(candidate):
                return _metadata_field(candidate, page, line)

    exclusions = re.compile(
        r"^(abstract|keywords?|introduction|contents|doi|issn|received|accepted|copyright)\b",
        re.IGNORECASE,
    )
    candidates = []
    for index, (page, line) in enumerate(first_page[:14]):
        if (
            12 <= len(line) <= 240
            and not exclusions.search(line)
            and not _is_affiliation_or_noise(line)
            and re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", line)
        ):
            candidates.append((index, page, line))
    if not candidates:
        return _empty_field()
    # Prefer an early, substantial line; this is a candidate only and remains pending.
    _, page, line = max(candidates, key=lambda item: (min(len(item[2]), 120), -item[0]))
    return _metadata_field(line, page, line)


def _detect_authors(lines):
    for page, line in lines[:20]:
        match = _AUTHOR_LABEL.match(line)
        if not match:
            continue
        author_text = match.group(1).strip()
        if not author_text or _is_affiliation_or_noise(author_text):
            continue
        names = [name.strip() for name in re.split(r"\s*(?:;|、|，|,|\band\b|&)\s*", author_text, flags=re.IGNORECASE) if name.strip()]
        if not names or any(len(name) < 2 or _is_affiliation_or_noise(name) for name in names):
            continue
        return _metadata_field(names, page, line)
    return _empty_field()


def _detect_year(lines):
    for page, line in lines:
        match = _YEAR_LABEL.search(line)
        if match:
            return _metadata_field(match.group(1), page, line)
    return _empty_field()


def _script_counts(text: str):
    latin = sum(char.isalpha() and char.isascii() for char in text)
    kana = sum("\u3040" <= char <= "\u30ff" for char in text)
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    traditional = sum(char in _TRADITIONAL_ONLY for char in text)
    simplified = sum(char in _SIMPLIFIED_ONLY for char in text)
    return latin, kana, cjk, traditional, simplified


def _detect_language(lines):
    # Count only the already bounded sample; do not join or copy the full document.
    latin = kana = cjk = traditional = simplified = 0
    for _, line in lines:
        counts = _script_counts(line)
        latin += counts[0]
        kana += counts[1]
        cjk += counts[2]
        traditional += counts[3]
        simplified += counts[4]

    if kana >= 2:
        code = LanguageCode.JA
        predicate = lambda line: _script_counts(line)[1] >= 2
    elif cjk >= 8 and traditional >= 2 and simplified == 0:
        code = LanguageCode.ZH_TW
        predicate = lambda line: _script_counts(line)[3] >= 2
    elif cjk >= 8 and simplified >= 2 and traditional == 0:
        code = LanguageCode.ZH_CN
        predicate = lambda line: _script_counts(line)[4] >= 2
    elif latin >= 35 and cjk == 0 and kana == 0:
        code = LanguageCode.EN
        predicate = lambda line: _script_counts(line)[0] >= 8
    else:
        return _empty_field()

    for page, line in lines:
        if predicate(line):
            return _metadata_field(code, page, line)
    return _empty_field()


def _detect_bounded(document: DocumentExtractionData) -> MetadataReview:
    lines = _bounded_lines(document)
    return MetadataReview(
        document_id=document.document_id,
        status=MetadataReviewStatus.PENDING_CONFIRMATION,
        title=_detect_title(lines),
        authors=_detect_authors(lines),
        publication_year=_detect_year(lines),
        detected_language=_detect_language(lines),
    )


def detect_metadata(document: DocumentExtractionData) -> MetadataReview:
    """Detect conservative candidates locally; all exceptions degrade to empty fields."""
    try:
        return _detect_bounded(document)
    except Exception:
        logger.exception("基本資料辨識失敗，保留 PDF 擷取流程：%s", document.document_id)
        return unrecognized_review(document.document_id)


class MetadataEvidenceValidationError(ValueError):
    """Raised when metadata evidence does not match its extracted PDF page."""


def validate_metadata_evidence(review: MetadataReview, document: DocumentExtractionData) -> None:
    """Verify metadata quotes against their 1-based source page; normalize whitespace only."""
    if review.document_id != document.document_id:
        raise MetadataEvidenceValidationError("基本資料文件識別碼不一致。")
    pages = {page.physical_page: page.text for page in document.pages}
    for field_name in ("title", "authors", "publication_year", "detected_language"):
        field = getattr(review, field_name)
        evidence = field.evidence
        if evidence is None:
            continue
        source_text = pages.get(evidence.page_number)
        if source_text is None:
            raise MetadataEvidenceValidationError(
                f"{field_name} 引句頁碼 {evidence.page_number} 不在 PDF 擷取結果中。"
            )
        normalize = lambda value: re.sub(r"\s+", " ", value).strip()
        quote = normalize(evidence.original_quote)
        if not quote or quote not in normalize(source_text):
            raise MetadataEvidenceValidationError(
                f"{field_name} 引句無法在 PDF 物理頁碼 {evidence.page_number} 找到。"
            )


def _normalize_value(value):
    if isinstance(value, list):
        return [item.strip() for item in value if item and item.strip()]
    return value.strip() if isinstance(value, str) else value


def _review_field(candidate: MetadataReviewField, submitted_value):
    submitted_value = _normalize_value(submitted_value)
    candidate_value = _normalize_value(candidate.value)
    if submitted_value is None or submitted_value == "" or submitted_value == []:
        return _empty_field()
    if candidate.source == MetadataValueSource.PDF_DETECTED and submitted_value == candidate_value:
        return candidate
    return MetadataReviewField(
        value=submitted_value,
        source=MetadataValueSource.USER_PROVIDED,
        evidence=None,
    )


def apply_review(candidate: MetadataReview, request: MetadataReviewRequest) -> MetadataReview:
    """Apply a user decision without trusting client-supplied source or evidence."""
    if request.decision == MetadataReviewDecision.SKIPPED:
        return candidate.model_copy(update={"status": MetadataReviewStatus.SKIPPED})
    return MetadataReview(
        document_id=candidate.document_id,
        status=MetadataReviewStatus.CONFIRMED,
        title=_review_field(candidate.title, request.title),
        authors=_review_field(candidate.authors, request.authors),
        publication_year=_review_field(candidate.publication_year, request.publication_year),
        detected_language=_review_field(candidate.detected_language, request.detected_language),
    )


def _review_path(document_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", document_id or ""):
        raise ValueError("無效的文件識別碼")
    return config.TEMP_RESULTS_DIR / f"{document_id}.metadata.json"


def save_review(review: MetadataReview) -> None:
    """Atomically save a metadata sidecar; the extraction JSON remains untouched."""
    target = _review_path(review.document_id)
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(review.model_dump_json(indent=2))
        temporary.replace(target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            logger.exception("清理基本資料暫存檔失敗：%s", temporary)
        raise


def load_review(document_id: str) -> Optional[MetadataReview]:
    try:
        target = _review_path(document_id)
        if not target.exists():
            return None
        with open(target, "r", encoding="utf-8") as stream:
            return MetadataReview.model_validate_json(stream.read())
    except Exception:
        logger.exception("讀取基本資料 sidecar 失敗：%s", document_id)
        return None


def get_or_detect(document: DocumentExtractionData) -> MetadataReview:
    existing = load_review(document.document_id)
    if existing is not None:
        try:
            validate_metadata_evidence(existing, document)
            return existing
        except MetadataEvidenceValidationError:
            logger.exception("基本資料 sidecar 引據驗證失敗，重新產生待確認候選：%s", document.document_id)
    review = detect_metadata(document)
    validate_metadata_evidence(review, document)
    try:
        save_review(review)
    except Exception:
        logger.exception("基本資料無法暫存；PDF 文件資料仍可使用：%s", document.document_id)
    return review
