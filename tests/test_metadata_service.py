"""Tests for bounded local metadata detection and provenance-safe review."""

import pytest

from app.models.schemas import (
    DocumentExtractionData,
    LanguageCode,
    MetadataReviewDecision,
    MetadataReviewRequest,
    MetadataReviewStatus,
    MetadataValueSource,
    PageTextItem,
)
from app.services import metadata_service


def make_document(pages, document_id="a" * 32):
    page_items = [
        PageTextItem(physical_page=index, text=text, char_count=len(text))
        for index, text in enumerate(pages, start=1)
    ]
    return DocumentExtractionData(
        document_id=document_id,
        original_filename="sample.pdf",
        total_pages=len(page_items),
        total_characters=sum(item.char_count for item in page_items),
        pages=page_items,
        created_at="2026-10-30T00:00:00Z",
    )


def test_detects_title_authors_and_contextual_publication_year_with_page_evidence():
    document = make_document([
        "Title: A Careful Study of Academic Evidence\n"
        "Authors: Jane Doe; John Roe\n"
        "Publication year: 2024\n"
        "This paper examines the available experimental evidence in detail.",
        "Second page text.",
    ])

    result = metadata_service.detect_metadata(document)

    assert result.title.value == "A Careful Study of Academic Evidence"
    assert result.authors.value == ["Jane Doe", "John Roe"]
    assert result.publication_year.value == "2024"
    for field, quote in [
        (result.title, "Title: A Careful Study of Academic Evidence"),
        (result.authors, "Authors: Jane Doe; John Roe"),
        (result.publication_year, "Publication year: 2024"),
    ]:
        assert field.source == MetadataValueSource.PDF_DETECTED
        assert field.evidence.page_number == 1
        assert field.evidence.original_quote == quote
        assert quote in document.pages[0].text
    assert result.status == MetadataReviewStatus.PENDING_CONFIRMATION


def test_author_affiliation_is_not_mistaken_for_an_author():
    result = metadata_service.detect_metadata(make_document([
        "Title: A Study of Academic Evidence\n"
        "Authors: Department of History, Example University\n"
        "Publication year: 2022\n"
        "A sufficiently long English sentence to identify the document language."
    ]))
    assert result.authors.value is None
    assert result.authors.source is None


def test_metadata_detection_stops_at_two_pages_and_eight_thousand_characters(monkeypatch):
    document = make_document(["A" * 5000, "B" * 5000, "Title: This third page must not be read"])
    lines = metadata_service._bounded_lines(document)
    assert {page for page, _ in lines} <= {1, 2}
    assert sum(len(line) for _, line in lines) <= metadata_service.MAX_METADATA_CHARACTERS

    monkeypatch.setattr(metadata_service, "MAX_METADATA_CHARACTERS", 100)
    short_lines = metadata_service._bounded_lines(document)
    assert sum(len(line) for _, line in short_lines) <= 100


@pytest.mark.parametrize(
    "text,expected",
    [
        ("This research examines academic evidence and reports results.", LanguageCode.EN),
        ("本研究では学術資料と実験結果の関係を検討する。", LanguageCode.JA),
        ("本研究探讨学术资料与实验结果之间的关系。", LanguageCode.ZH_CN),
        ("本研究探討學術資料與實驗結果之間的關係。", LanguageCode.ZH_TW),
    ],
)
def test_detects_supported_languages_from_local_script_features(text, expected):
    result = metadata_service.detect_metadata(make_document([text]))
    assert result.detected_language.value == expected
    assert result.detected_language.source == MetadataValueSource.PDF_DETECTED
    assert result.detected_language.evidence.page_number == 1
    assert result.detected_language.evidence.original_quote in text


def test_ambiguous_or_short_language_sample_remains_unknown():
    result = metadata_service.detect_metadata(make_document(["Short title"]))
    assert result.detected_language.value is None
    assert result.detected_language.source is None
    assert result.detected_language.evidence is None


def test_missing_metadata_is_explicitly_unrecognized_and_pending():
    result = metadata_service.detect_metadata(make_document(["Abstract\nKeywords\nIntroduction"]))
    assert result.status == MetadataReviewStatus.PENDING_CONFIRMATION
    assert result.title.value is None
    assert result.authors.value is None
    assert result.publication_year.value is None
    assert result.detected_language.value is None


def test_detector_exception_returns_empty_review(monkeypatch):
    document = make_document(["Synthetic text"])
    monkeypatch.setattr(metadata_service, "_detect_bounded", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    result = metadata_service.detect_metadata(document)
    assert result.document_id == document.document_id
    assert result.status == MetadataReviewStatus.PENDING_CONFIRMATION
    assert result.title.value is None


def test_confirmation_preserves_pdf_evidence_but_modified_values_are_user_provided():
    document = make_document([
        "Title: A Careful Study of Academic Evidence\n"
        "Authors: Jane Doe\nPublication year: 2024\n"
        "This paper examines the available experimental evidence in detail."
    ])
    original = metadata_service.detect_metadata(document)
    before = document.model_dump_json()
    reviewed = metadata_service.apply_review(original, MetadataReviewRequest(
        decision=MetadataReviewDecision.CONFIRMED,
        title=original.title.value,
        authors=["Jane Modified"],
        publication_year=original.publication_year.value,
        detected_language=original.detected_language.value,
    ))

    assert reviewed.status == MetadataReviewStatus.CONFIRMED
    assert reviewed.title.source == MetadataValueSource.PDF_DETECTED
    assert reviewed.title.evidence == original.title.evidence
    assert reviewed.authors.source == MetadataValueSource.USER_PROVIDED
    assert reviewed.authors.value == ["Jane Modified"]
    assert reviewed.authors.evidence is None
    assert reviewed.publication_year.source == MetadataValueSource.PDF_DETECTED
    assert document.model_dump_json() == before


def test_skip_retains_candidate_origins_and_never_marks_them_confirmed():
    original = metadata_service.detect_metadata(make_document([
        "Title: A Careful Study of Academic Evidence\n"
        "This paper examines the available experimental evidence in detail."
    ]))
    skipped = metadata_service.apply_review(original, MetadataReviewRequest(
        decision=MetadataReviewDecision.SKIPPED,
        title="Ignored changed value",
    ))
    assert skipped.status == MetadataReviewStatus.SKIPPED
    assert skipped.title.value == original.title.value
    assert skipped.title.source == MetadataValueSource.PDF_DETECTED
    assert skipped.title.evidence == original.title.evidence


def test_metadata_sidecar_round_trip_does_not_modify_extraction_json(tmp_path, monkeypatch):
    document = make_document([
        "Title: A Careful Study of Academic Evidence\n"
        "This paper examines the available experimental evidence in detail."
    ])
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    monkeypatch.setattr(metadata_service.config, "TEMP_RESULTS_DIR", result_dir)
    extraction_path = result_dir / f"{document.document_id}.json"
    original_json = document.model_dump_json(indent=2)
    extraction_path.write_text(original_json, encoding="utf-8")

    review = metadata_service.get_or_detect(document)
    loaded = metadata_service.load_review(document.document_id)

    assert review == loaded
    assert extraction_path.read_text(encoding="utf-8") == original_json
    assert (result_dir / f"{document.document_id}.metadata.json").exists()
