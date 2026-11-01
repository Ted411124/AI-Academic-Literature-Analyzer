"""End-to-end report acceptance tests using an injected local executor only."""

import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.models.schemas import (
    AnalysisMode,
    AnalysisReport,
    ContentStatus,
    DocumentExtractionData,
    EvidenceRef,
    GroundedStatement,
    KeyFindingItem,
    LanguageCode,
    LimitationsStatus,
    MetadataField,
    MetadataReview,
    MetadataReviewField,
    MetadataReviewStatus,
    MetadataSource,
    MetadataValueSource,
    MindMapCategory,
    MindMapData,
    MindMapNode,
    OutlineSection,
    PageTextItem,
    PaperMetadata,
    RelevanceLevel,
    ResearchLimitations,
    TopicRelevance,
)
from app.services import metadata_service, report_service
from app.services.analysis_service import analysis_service
from app.services.pdf_service import PDFService


DOCUMENT_ID = "c" * 32
SOURCE = (
    "Title: Sample Study. Authors: A. Writer. Year: 2024. English. Introduction. "
    "Background evidence. Objectives evidence. Method evidence. Findings evidence. "
    "Argument evidence. Conclusion evidence. Point one. Point two. Point three. "
    "Point four. Point five. Related evidence. Recommended evidence."
)


@pytest.fixture
def acceptance_context(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    results = tmp_path / "results"
    uploads.mkdir()
    results.mkdir()
    monkeypatch.setattr(config, "TEMP_UPLOADS_DIR", uploads)
    monkeypatch.setattr(config, "TEMP_RESULTS_DIR", results)
    monkeypatch.setattr(config, "TEMP_FILE_TTL_SECONDS", 3600)
    monkeypatch.setattr(analysis_service, "_work_lock", threading.Lock())
    monkeypatch.setattr(analysis_service, "_active_state_lock", threading.Lock())
    monkeypatch.setattr(analysis_service, "_active_document_ids", set())
    monkeypatch.setattr(analysis_service, "executor", None)

    document = DocumentExtractionData(
        document_id=DOCUMENT_ID,
        original_filename="acceptance-test.pdf",
        total_pages=2,
        total_characters=len(SOURCE) + len("Second physical page."),
        pages=[
            PageTextItem(physical_page=1, text=SOURCE, char_count=len(SOURCE)),
            PageTextItem(
                physical_page=2,
                text="Second physical page.",
                char_count=len("Second physical page."),
            ),
        ],
        created_at="2026-10-31T00:00:00Z",
    )
    (uploads / f"{DOCUMENT_ID}.pdf").write_bytes(b"test-only-placeholder")
    (results / f"{DOCUMENT_ID}.json").write_text(
        document.model_dump_json(indent=2), encoding="utf-8"
    )
    review = _confirmed_review()
    metadata_service.save_review(review)
    return document, uploads, results, review


def _evidence(quote, page=1):
    return EvidenceRef(page_number=page, original_quote=quote)


def _supported(identifier, quote, summary):
    return GroundedStatement(
        statement_id=identifier,
        summary_tw=summary,
        summary_original=f"Source summary: {summary}",
        status=ContentStatus.SUPPORTED,
        source=MetadataSource.PDF_RECOGNITION,
        evidence=[_evidence(quote)],
    )


def _confirmed_review(status=MetadataReviewStatus.CONFIRMED):
    def field(value, quote):
        return MetadataReviewField(
            value=value,
            source=MetadataValueSource.PDF_DETECTED,
            evidence=_evidence(quote),
        )

    return MetadataReview(
        document_id=DOCUMENT_ID,
        status=status,
        title=field("Sample Study", "Sample Study."),
        authors=field(["A. Writer"], "A. Writer."),
        publication_year=field("2024", "2024."),
        detected_language=field(LanguageCode.EN, "English."),
    )


def make_candidate(mode=AnalysisMode.GENERAL):
    statements = {
        "background": _supported("background", "Background evidence.", "研究背景整理"),
        "objectives": _supported("objectives", "Objectives evidence.", "研究目的整理"),
        "methodology": _supported("methodology", "Method evidence.", "研究方法整理"),
        "findings": _supported("findings", "Findings evidence.", "研究成果整理"),
        "arguments": _supported("arguments", "Argument evidence.", "核心論點整理"),
        "conclusion": _supported("conclusion", "Conclusion evidence.", "結論整理"),
    }
    numbers = ["one", "two", "three", "four", "five"]
    key_points = [
        KeyFindingItem(
            finding_id=f"point-{index}",
            topic=f"重點 {index}",
            topic_tw=f"重要重點 {index}",
            statement=_supported(
                f"point-statement-{index}", f"Point {word}.", f"重要重點 {index}"
            ),
        )
        for index, word in enumerate(numbers, start=1)
    ]
    metadata = PaperMetadata(
        title=MetadataField(
            value="Sample Study", source=MetadataSource.PDF_RECOGNITION,
            evidence=_evidence("Sample Study."),
        ),
        authors=MetadataField(
            value=["A. Writer"], source=MetadataSource.PDF_RECOGNITION,
            evidence=_evidence("A. Writer."),
        ),
        publication_year=MetadataField(
            value="2024", source=MetadataSource.PDF_RECOGNITION,
            evidence=_evidence("2024."),
        ),
        detected_language=MetadataField(
            value=LanguageCode.EN, source=MetadataSource.PDF_RECOGNITION,
            evidence=_evidence("English."),
        ),
    )
    children = []
    for category, key in (
        (MindMapCategory.RESEARCH_BACKGROUND, "background"),
        (MindMapCategory.RESEARCH_OBJECTIVES, "objectives"),
        (MindMapCategory.METHODOLOGY, "methodology"),
        (MindMapCategory.CORE_ARGUMENTS, "arguments"),
        (MindMapCategory.RESEARCH_FINDINGS, "findings"),
        (MindMapCategory.CONCLUSION, "conclusion"),
    ):
        children.append(MindMapNode(
            category=category,
            label_tw=statements[key].summary_tw,
            label_original=f"Source label: {key}",
            source_item_ids=[statements[key].statement_id],
        ))

    relevance = None
    topic = None
    if mode == AnalysisMode.TOPIC:
        topic = "Research topic"
        reasons = _supported("relevance-reason", "Findings evidence.", "主題相關性理由")
        related = _supported("related-section", "Introduction.", "相關章節")
        recommended = _supported("recommended-reading", "Recommended evidence.", "優先研讀段落")
        relevance = TopicRelevance(
            level=RelevanceLevel.PARTIAL,
            reasons=[reasons],
            related_sections=[related],
            recommended_reading=[recommended],
        )
        children.append(MindMapNode(
            category=MindMapCategory.TOPIC_RELEVANCE,
            label_tw="主題相關性",
            label_original="Topic relevance",
            source_item_ids=[reasons.statement_id],
        ))

    return {
        "document_id": DOCUMENT_ID,
        "total_pages": 2,
        "metadata": metadata.model_dump(),
        "mode": mode,
        "topic": topic,
        "outline": [OutlineSection(
            section_id="outline-introduction",
            title="Introduction",
            title_tw="導論",
            start_page=1,
            end_page=1,
            evidence=[_evidence("Introduction.")],
        ).model_dump()],
        "research_background": statements["background"].model_dump(),
        "research_objectives": statements["objectives"].model_dump(),
        "methodology": statements["methodology"].model_dump(),
        "research_findings": statements["findings"].model_dump(),
        "core_arguments": statements["arguments"].model_dump(),
        "key_points": [item.model_dump() for item in key_points],
        "research_limitations": ResearchLimitations(
            status=LimitationsStatus.NOT_MENTIONED,
            items=[],
            summary_tw="【原文未提及】",
        ).model_dump(),
        "conclusion": statements["conclusion"].model_dump(),
        "topic_relevance": relevance.model_dump() if relevance else None,
        "mind_map": MindMapData(root=MindMapNode(
            category=MindMapCategory.PAPER_TITLE,
            label_tw="Sample Study",
            label_original="Sample Study",
            source_item_ids=["metadata.title"],
            children=children,
        )).model_dump(),
    }


def _post(payload=None):
    return TestClient(app).post(
        "/api/analysis",
        json=payload or {"document_id": DOCUMENT_ID, "analysis_mode": "general"},
    )


def _valid_request():
    return {"document_id": DOCUMENT_ID, "analysis_mode": "general"}


def test_valid_candidate_is_validated_saved_and_returns_reference(acceptance_context, monkeypatch):
    monkeypatch.setattr(analysis_service, "executor", lambda *_: make_candidate())

    response = _post(_valid_request())

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "report_id": DOCUMENT_ID,
    }
    saved = report_service.load_report(DOCUMENT_ID)
    assert saved is not None
    assert saved.document_id == DOCUMENT_ID
    assert saved.metadata.title.value == "Sample Study"


@pytest.mark.parametrize("invalid_kind", ["schema", "document", "quote", "page"])
def test_invalid_candidate_is_not_saved(acceptance_context, monkeypatch, invalid_kind):
    candidate = make_candidate()
    if invalid_kind == "schema":
        candidate["key_points"] = []
    elif invalid_kind == "document":
        candidate["document_id"] = "d" * 32
    elif invalid_kind == "quote":
        candidate["research_background"]["evidence"][0]["original_quote"] = "not in source"
    else:
        candidate["research_background"]["evidence"][0]["page_number"] = 2
    monkeypatch.setattr(analysis_service, "executor", lambda *_: candidate)

    response = _post(_valid_request())

    assert response.status_code == 502
    assert response.json()["error_code"] == "ANALYSIS_REPORT_INVALID"
    assert report_service.report_path(DOCUMENT_ID).exists() is False
    assert analysis_service.is_document_active(DOCUMENT_ID) is False
    assert analysis_service._work_lock.locked() is False


def test_report_save_failure_does_not_return_success_or_leave_partial_file(
    acceptance_context, monkeypatch
):
    monkeypatch.setattr(analysis_service, "executor", lambda *_: make_candidate())
    monkeypatch.setattr(
        report_service.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic replace failure")),
    )

    response = _post(_valid_request())

    assert response.status_code == 500
    assert response.json()["error_code"] == "ANALYSIS_REPORT_SAVE_FAILED"
    assert not report_service.report_path(DOCUMENT_ID).exists()
    assert not (acceptance_context[2] / f"{DOCUMENT_ID}.report.json.tmp").exists()
    assert not analysis_service._work_lock.locked()
    assert not analysis_service.is_document_active(DOCUMENT_ID)


def test_failed_new_analysis_preserves_previous_success(acceptance_context, monkeypatch):
    old_report = report_service.save_report(AnalysisReport.model_validate(make_candidate()))
    previous_contents = old_report.read_text(encoding="utf-8")
    candidate = make_candidate()
    candidate["research_background"]["evidence"][0]["original_quote"] = "bad quote"
    monkeypatch.setattr(analysis_service, "executor", lambda *_: candidate)

    response = _post(_valid_request())

    assert response.status_code == 502
    assert old_report.read_text(encoding="utf-8") == previous_contents


@pytest.mark.parametrize("mode", [AnalysisMode.GENERAL, AnalysisMode.TOPIC])
def test_general_and_topic_reports_are_accepted(acceptance_context, monkeypatch, mode):
    candidate = make_candidate(mode)
    payload = {"document_id": DOCUMENT_ID, "analysis_mode": mode.value}
    if mode == AnalysisMode.TOPIC:
        payload["topic"] = "Research topic"
    monkeypatch.setattr(analysis_service, "executor", lambda *_: candidate)

    response = _post(payload)

    assert response.status_code == 200
    assert report_service.load_report(DOCUMENT_ID) is not None


def test_user_modified_metadata_is_taken_from_review_not_executor(acceptance_context, monkeypatch):
    document, _, _, review = acceptance_context
    review.title.source = MetadataValueSource.USER_PROVIDED
    review.title.value = "User corrected title"
    review.title.evidence = None
    metadata_service.save_review(review)
    candidate = make_candidate()
    monkeypatch.setattr(analysis_service, "executor", lambda *_: candidate)

    response = _post(_valid_request())

    assert response.status_code == 200
    saved = report_service.load_report(document.document_id)
    assert saved is not None
    assert saved.metadata.title.value == "User corrected title"
    assert saved.metadata.title.source == MetadataSource.USER_PROVIDED
    assert saved.metadata.title.evidence is None
    assert saved.mind_map.root.label_tw == "User corrected title"
    assert saved.mind_map.root.label_original is None


def test_skipped_unknown_metadata_is_not_invented_by_executor(acceptance_context, monkeypatch):
    review = metadata_service.unrecognized_review(DOCUMENT_ID).model_copy(
        update={"status": MetadataReviewStatus.SKIPPED}
    )
    metadata_service.save_review(review)
    monkeypatch.setattr(analysis_service, "executor", lambda *_: make_candidate())

    response = _post(_valid_request())

    assert response.status_code == 200
    saved = report_service.load_report(DOCUMENT_ID)
    assert saved is not None
    assert saved.metadata.title.value is None
    assert saved.metadata.title.source == MetadataSource.UNRECOGNIZABLE
    assert saved.mind_map.root.label_tw == "【無法辨識】"
    assert saved.mind_map.root.label_original is None


def test_report_artifacts_are_protected_during_analysis_and_ttl_cleanup(
    acceptance_context, monkeypatch
):
    document, uploads, results, _ = acceptance_context
    artifact_paths = [
        uploads / f"{DOCUMENT_ID}.pdf",
        results / f"{DOCUMENT_ID}.json",
        results / f"{DOCUMENT_ID}.metadata.json",
        results / f"{DOCUMENT_ID}.report.json",
        results / f"{DOCUMENT_ID}.report.json.tmp",
    ]
    artifact_paths[3].write_text("previous report", encoding="utf-8")
    artifact_paths[4].write_text("partial report", encoding="utf-8")
    cleanup_during_save = []

    def expire(path):
        old = time.time() - 7200
        os.utime(path, (old, old))

    original_replace = report_service.os.replace

    def replace_with_concurrent_cleanup(source, target):
        for path in artifact_paths:
            expire(path)
        cleanup_during_save.append(PDFService.cleanup_expired_files(ttl_seconds=3600))
        assert all(path.exists() for path in artifact_paths)
        return original_replace(source, target)

    monkeypatch.setattr(analysis_service, "executor", lambda *_: make_candidate())
    monkeypatch.setattr(report_service.os, "replace", replace_with_concurrent_cleanup)

    response = _post(_valid_request())

    assert response.status_code == 200
    assert cleanup_during_save == [0]
    assert report_service.report_path(DOCUMENT_ID).exists()
    artifact_paths[4].write_text("expired partial", encoding="utf-8")
    for path in [*artifact_paths[:4], artifact_paths[4]]:
        expire(path)
    deleted = PDFService.cleanup_expired_files(ttl_seconds=3600)
    assert deleted == len(artifact_paths)
    assert all(not path.exists() for path in artifact_paths)
