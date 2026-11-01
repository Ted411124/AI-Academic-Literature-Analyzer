"""Tests for source-grounded analysis schemas and document-aware validation."""

import pytest
from pydantic import ValidationError

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
    MetadataSource,
    MindMapCategory,
    MindMapData,
    MindMapNode,
    OutlineSection,
    PageTextItem,
    PaperMetadata,
    RelevanceLevel,
    ResearchLimitationItem,
    ResearchLimitations,
    TopicRelevance,
)
from app.services.analysis_validator import EvidenceValidationError, validate_report_against_document


PDF_TEXT = (
    "Title: Sample Study. Authors: A. Writer. Year: 2024. English. Introduction. "
    "Background evidence. Objectives evidence. Method evidence. Findings evidence. "
    "Argument evidence. Conclusion evidence. Point one. Point two. Point three. "
    "Point four. Point five. Limitation evidence."
)


def evidence(quote="Background evidence.", page=1):
    return EvidenceRef(page_number=page, original_quote=quote)


def metadata_field(value, source=MetadataSource.PDF_RECOGNITION, quote="Sample Study."):
    return MetadataField(value=value, source=source, evidence=evidence(quote) if source in {
        MetadataSource.PDF_RECOGNITION, MetadataSource.PENDING_CONFIRMATION
    } else None)


def statement(statement_id, quote, summary=None):
    return GroundedStatement(
        statement_id=statement_id,
        summary_tw=summary or f"整理：{quote}",
        summary_original=f"Source summary: {quote}",
        status=ContentStatus.SUPPORTED,
        source=MetadataSource.PDF_RECOGNITION,
        evidence=[evidence(quote)],
    )


def make_document():
    return DocumentExtractionData(
        document_id="doc-1",
        original_filename="sample.pdf",
        total_pages=2,
        total_characters=len(PDF_TEXT) + len("Second page text."),
        pages=[
            PageTextItem(physical_page=1, text=PDF_TEXT, char_count=len(PDF_TEXT)),
            PageTextItem(physical_page=2, text="Second page text.", char_count=17),
        ],
        created_at="2026-10-30T00:00:00Z",
    )


def make_report(key_point_count=5, mode=AnalysisMode.GENERAL, **overrides):
    statements = {
        "background": statement("background", "Background evidence."),
        "objectives": statement("objectives", "Objectives evidence."),
        "methodology": statement("methodology", "Method evidence."),
        "findings": statement("findings", "Findings evidence."),
        "arguments": statement("arguments", "Argument evidence."),
        "conclusion": statement("conclusion", "Conclusion evidence."),
    }
    key_points = [
        KeyFindingItem(
            finding_id=f"point-{index}",
            topic=f"重點 {index}",
            topic_tw=f"重點 {index}",
            statement=statement(
                f"point-statement-{index}",
                f"Point {['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'][(index - 1) % 10]}.",
                f"繁中整理 {index}",
            ),
        )
        for index in range(1, key_point_count + 1)
    ]
    metadata = PaperMetadata(
        title=metadata_field("Sample Study", quote="Sample Study."),
        authors=metadata_field(["A. Writer"], quote="A. Writer."),
        publication_year=metadata_field("2024", quote="2024."),
        detected_language=metadata_field(LanguageCode.EN, quote="English."),
    )
    nodes = [
        MindMapNode(
            category=MindMapCategory.PAPER_TITLE,
            label_tw="Sample Study",
            label_original="Sample Study",
            source_item_ids=["metadata.title"],
        )
    ]
    for category, key in [
        (MindMapCategory.RESEARCH_BACKGROUND, "background"),
        (MindMapCategory.RESEARCH_OBJECTIVES, "objectives"),
        (MindMapCategory.METHODOLOGY, "methodology"),
        (MindMapCategory.CORE_ARGUMENTS, "arguments"),
        (MindMapCategory.RESEARCH_FINDINGS, "findings"),
        (MindMapCategory.CONCLUSION, "conclusion"),
    ]:
        nodes.append(MindMapNode(
            category=category,
            label_tw=f"節點 {key}",
            label_original=f"Source node {key}",
            source_item_ids=[statements[key].statement_id],
        ))
    if mode == AnalysisMode.TOPIC:
        nodes.append(MindMapNode(
            category=MindMapCategory.TOPIC_RELEVANCE,
            label_tw="主題相關性",
            label_original="Topic relevance",
            source_item_ids=["relevance-reason"],
        ))
    report_data = dict(
        document_id="doc-1",
        total_pages=2,
        metadata=metadata,
        mode=mode,
        topic="研究主題" if mode == AnalysisMode.TOPIC else None,
        outline=[OutlineSection(
            section_id="outline-introduction",
            title="Introduction",
            title_tw="導論",
            start_page=1,
            end_page=1,
            evidence=[evidence("Introduction.")],
        )],
        research_background=statements["background"],
        research_objectives=statements["objectives"],
        methodology=statements["methodology"],
        research_findings=statements["findings"],
        core_arguments=statements["arguments"],
        key_points=key_points,
        research_limitations=ResearchLimitations(
            status=LimitationsStatus.NOT_MENTIONED,
            items=[],
            summary_tw="【原文未提及】",
        ),
        conclusion=statements["conclusion"],
        topic_relevance=TopicRelevance(
            level=RelevanceLevel.PARTIAL,
            reasons=[statement("relevance-reason", "Findings evidence.", "與主題部分相關的原文依據")],
            related_sections=[statement("related-section", "Introduction.", "Introduction 章節")],
            recommended_reading=[statement("recommended-reading", "Findings evidence.", "優先研讀研究成果段落")],
        ) if mode == AnalysisMode.TOPIC else None,
        mind_map=MindMapData(root=nodes[0].model_copy(update={"children": nodes[1:]})),
    )
    report_data.update(overrides)
    return AnalysisReport(**report_data)


@pytest.mark.parametrize("value", [0, -1, 1.5, 1.0])
def test_evidence_page_number_must_be_positive_strict_integer(value):
    with pytest.raises(ValidationError):
        EvidenceRef(page_number=value, original_quote="quote")


def test_outline_page_order_and_page_number_validation():
    base = dict(section_id="s1", title="Introduction", evidence=[evidence("Introduction.")])
    with pytest.raises(ValidationError):
        OutlineSection(**base, start_page=0, end_page=1)
    with pytest.raises(ValidationError, match="起始頁碼"):
        OutlineSection(**base, start_page=2, end_page=1)
    with pytest.raises(ValidationError):
        OutlineSection(**base, start_page=1.5, end_page=2)


def test_extraction_pages_must_match_1_based_physical_page_sequence():
    data = make_document().model_dump()
    data["pages"][0]["physical_page"] = 2
    with pytest.raises(ValidationError, match="physical_page"):
        DocumentExtractionData(**data)


@pytest.mark.parametrize("language", ["en", "ja", "zh-CN", "zh-TW"])
def test_supported_language_codes(language):
    assert LanguageCode(language).value == language


def test_language_can_be_unrecognized_none():
    assert MetadataField[LanguageCode | None](value=None, source=MetadataSource.UNRECOGNIZABLE).value is None


def _report_data_for_language(language):
    data = make_report().model_dump(mode="python")
    data["metadata"]["detected_language"]["value"] = language
    if language is None:
        data["metadata"]["detected_language"]["source"] = MetadataSource.UNRECOGNIZABLE
        data["metadata"]["detected_language"]["evidence"] = None
    if language in {LanguageCode.ZH_CN, LanguageCode.ZH_TW}:
        statements = [
            data["research_background"],
            data["research_objectives"],
            data["methodology"],
            data["research_findings"],
            data["core_arguments"],
            data["conclusion"],
            *(item["statement"] for item in data["key_points"]),
        ]
        for item in statements:
            item["summary_original"] = None
        if language == LanguageCode.ZH_TW:
            data["outline"][0]["title_tw"] = None
            for item in data["key_points"]:
                item["topic_tw"] = None
        stack = [data["mind_map"]["root"]]
        while stack:
            node = stack.pop()
            node["label_original"] = None
            stack.extend(node["children"])
    return data


@pytest.mark.parametrize("language", [LanguageCode.EN, LanguageCode.JA])
def test_english_and_japanese_reports_accept_source_and_traditional_chinese_fields(language):
    data = _report_data_for_language(language)
    report = AnalysisReport.model_validate(data)
    assert report.research_background.summary_original
    assert report.research_background.summary_tw
    assert report.outline[0].title_tw
    assert report.key_points[0].topic_tw
    assert report.mind_map.root.label_original


def test_simplified_chinese_report_uses_traditional_chinese_without_original_duplicate():
    report = AnalysisReport.model_validate(_report_data_for_language(LanguageCode.ZH_CN))
    assert report.research_background.summary_original is None
    assert report.outline[0].title_tw
    assert report.key_points[0].topic_tw
    assert report.mind_map.root.label_original is None


def test_traditional_chinese_report_does_not_duplicate_same_language_fields():
    report = AnalysisReport.model_validate(_report_data_for_language(LanguageCode.ZH_TW))
    assert report.research_background.summary_original is None
    assert report.outline[0].title_tw is None
    assert report.key_points[0].topic_tw is None
    assert report.mind_map.root.label_original is None


def test_unknown_report_language_keeps_optional_original_fields_optional():
    data = _report_data_for_language(None)
    data["research_background"]["summary_original"] = None
    data["outline"][0]["title_tw"] = None
    data["key_points"][0]["topic_tw"] = None
    data["mind_map"]["root"]["label_original"] = None
    report = AnalysisReport.model_validate(data)
    assert report.metadata.detected_language.value is None


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (("research_background", "summary_original"), "supported 整理"),
        (("outline", 0, "title_tw"), "章節標題"),
        (("key_points", 0, "topic_tw"), "重要重點主題"),
        (("mind_map", "root", "children", 0, "label_original"), "心智圖節點"),
    ],
)
def test_english_report_requires_original_and_traditional_chinese_fields(path, message):
    data = make_report().model_dump(mode="python")
    current = data
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = None
    with pytest.raises(ValidationError, match=message):
        AnalysisReport.model_validate(data)


@pytest.mark.parametrize(
    ("status", "source", "summary", "expected"),
    [
        (ContentStatus.NOT_MENTIONED, MetadataSource.NOT_MENTIONED, "【原文未提及】", "原文未提及"),
        (ContentStatus.UNRECOGNIZABLE, MetadataSource.UNRECOGNIZABLE, "無法辨識", "無法辨識"),
        (ContentStatus.PENDING_CONFIRMATION, MetadataSource.PENDING_CONFIRMATION, "待使用者確認", "待確認"),
        (ContentStatus.USER_PROVIDED, MetadataSource.USER_PROVIDED, "使用者提供內容", "使用者提供"),
    ],
)
def test_non_supported_status_cannot_be_misrepresented_as_original_summary(
    status, source, summary, expected
):
    with pytest.raises(ValidationError, match=expected):
        GroundedStatement(
            statement_id="state-item",
            summary_tw=summary,
            summary_original="fabricated original-language summary",
            status=status,
            source=source,
            evidence=[],
        )


def test_bilingual_report_json_round_trip_preserves_new_fields():
    report = make_report()
    restored = AnalysisReport.model_validate_json(report.model_dump_json(indent=2))
    assert restored == report
    assert restored.research_background.summary_original == report.research_background.summary_original
    assert restored.outline[0].title_tw == report.outline[0].title_tw
    assert restored.key_points[0].topic_tw == report.key_points[0].topic_tw
    assert restored.mind_map.root.label_original == report.mind_map.root.label_original


@pytest.mark.parametrize("count", [5, 6, 7, 8, 9, 10])
def test_analysis_report_accepts_five_to_ten_key_points(count):
    assert len(make_report(key_point_count=count).key_points) == count


@pytest.mark.parametrize("count", [4, 11])
def test_analysis_report_rejects_key_point_count_outside_five_to_ten(count):
    with pytest.raises(ValidationError):
        make_report(key_point_count=count)


def test_metadata_sources_keep_user_values_distinct_from_pdf_evidence():
    assert metadata_field("Sample Study").source == MetadataSource.PDF_RECOGNITION
    user_value = MetadataField(value="Edited title", source=MetadataSource.USER_PROVIDED)
    assert user_value.evidence is None
    assert MetadataField(value=None, source=MetadataSource.UNRECOGNIZABLE).value is None
    assert MetadataField(value=None, source=MetadataSource.NOT_MENTIONED).value is None
    pending = metadata_field("Candidate title", MetadataSource.PENDING_CONFIRMATION)
    assert pending.source == MetadataSource.PENDING_CONFIRMATION
    with pytest.raises(ValidationError, match="不得偽附"):
        MetadataField(value="Edited title", source=MetadataSource.USER_PROVIDED, evidence=evidence())


@pytest.mark.parametrize(
    "status,source,text,quotes,valid",
    [
        (ContentStatus.SUPPORTED, MetadataSource.PDF_RECOGNITION, "有依據整理", [evidence()], True),
        (ContentStatus.NOT_MENTIONED, MetadataSource.NOT_MENTIONED, "【原文未提及】", [], True),
        (ContentStatus.UNRECOGNIZABLE, MetadataSource.UNRECOGNIZABLE, "無法辨識", [], True),
        (ContentStatus.PENDING_CONFIRMATION, MetadataSource.PENDING_CONFIRMATION, "待使用者確認", [], True),
        (ContentStatus.USER_PROVIDED, MetadataSource.USER_PROVIDED, "使用者提供內容", [], True),
        (ContentStatus.SUPPORTED, MetadataSource.USER_PROVIDED, "錯誤來源", [evidence()], False),
        (ContentStatus.NOT_MENTIONED, MetadataSource.NOT_MENTIONED, "沒有資料", [], False),
        (ContentStatus.UNRECOGNIZABLE, MetadataSource.UNRECOGNIZABLE, "【原文未提及】", [], False),
        (ContentStatus.SUPPORTED, MetadataSource.PDF_RECOGNITION, "缺少引句", [], False),
    ],
)
def test_grounded_statement_status_and_evidence_rules(status, source, text, quotes, valid):
    payload = dict(statement_id="s1", summary_tw=text, status=status, source=source, evidence=quotes)
    if valid:
        assert GroundedStatement(**payload)
    else:
        with pytest.raises(ValidationError):
            GroundedStatement(**payload)


def test_research_limitations_require_explicit_author_statement_or_not_mentioned_marker():
    assert ResearchLimitations(
        status=LimitationsStatus.NOT_MENTIONED,
        items=[],
        summary_tw="【原文未提及】",
    )
    explicit = ResearchLimitationItem(
        statement=statement("author-limitation", "Limitation evidence."),
        explicitly_stated_by_author=True,
    )
    assert ResearchLimitations(status=LimitationsStatus.PRESENT, items=[explicit])
    with pytest.raises(ValidationError):
        ResearchLimitationItem(
            statement=statement("inferred-limitation", "Limitation evidence."),
            explicitly_stated_by_author=False,
        )
    with pytest.raises(ValidationError, match="原文未提及"):
        ResearchLimitations(
            status=LimitationsStatus.NOT_MENTIONED,
            items=[explicit],
            summary_tw="【原文未提及】",
        )


def test_report_requires_complete_mind_map_and_referenced_report_items():
    report = make_report()
    assert report.mind_map.root.category == MindMapCategory.PAPER_TITLE
    data = report.model_dump()
    data["mind_map"]["root"]["children"].pop()
    with pytest.raises(ValidationError, match="缺少正式規格要求"):
        AnalysisReport(**data)

    data = report.model_dump()
    data["mind_map"]["root"]["source_item_ids"] = ["not-a-report-item"]
    with pytest.raises(ValidationError, match="不存在的報告項目"):
        AnalysisReport(**data)


@pytest.mark.parametrize(
    "node_index,source_id",
    [(0, "objectives"), (1, "methodology"), (2, "findings"), (3, "findings"), (4, "conclusion"), (5, "background")],
)
def test_mind_map_rejects_source_from_another_category(node_index, source_id):
    data = make_report().model_dump()
    data["mind_map"]["root"]["children"][node_index]["source_item_ids"] = [source_id]
    with pytest.raises(ValidationError, match="不相符的報告來源"):
        AnalysisReport(**data)


def test_mind_map_rejects_unverified_report_source():
    data = make_report().model_dump()
    data["research_background"]["status"] = ContentStatus.PENDING_CONFIRMATION.value
    data["research_background"]["source"] = MetadataSource.PENDING_CONFIRMATION.value
    data["research_background"]["summary_tw"] = "待使用者確認"
    data["research_background"]["summary_original"] = None
    data["research_background"]["evidence"] = []
    with pytest.raises(ValidationError, match="缺少 PDF 原文依據"):
        AnalysisReport(**data)


def test_report_topic_relevance_is_only_allowed_in_topic_mode():
    topic_report = make_report(mode=AnalysisMode.TOPIC)
    assert topic_report.topic_relevance is not None
    with pytest.raises(ValidationError, match="一般模式不得"):
        make_report(topic_relevance=TopicRelevance(
            level=RelevanceLevel.HIGH,
            reasons=[statement("r1", "Findings evidence.")],
            related_sections=[statement("s1", "Introduction.")],
            recommended_reading=[statement("p1", "Findings evidence.")],
        ))


def test_topic_relevance_requires_grounded_sections_and_recommended_reading():
    report = make_report(mode=AnalysisMode.TOPIC)
    assert report.topic_relevance.related_sections[0].evidence[0].page_number == 1
    assert report.topic_relevance.recommended_reading[0].evidence[0].original_quote == "Findings evidence."

    with pytest.raises(ValidationError):
        TopicRelevance(
            level=RelevanceLevel.HIGH,
            reasons=[statement("r1", "Findings evidence.")],
            related_sections=[],
            recommended_reading=[statement("p1", "Findings evidence.")],
        )


def test_topic_relevance_details_are_checked_against_document_text():
    data = make_report(mode=AnalysisMode.TOPIC).model_dump()
    data["topic_relevance"]["related_sections"][0]["evidence"][0]["original_quote"] = "Wrong section."
    report = AnalysisReport(**data)
    with pytest.raises(EvidenceValidationError, match="找不到原始引句"):
        validate_report_against_document(report, make_document())


def test_report_does_not_accept_user_input_as_author_analysis():
    report = make_report()
    data = report.model_dump()
    data["research_background"]["status"] = ContentStatus.USER_PROVIDED.value
    data["research_background"]["source"] = MetadataSource.USER_PROVIDED.value
    data["research_background"]["summary_original"] = None
    data["research_background"]["evidence"] = []
    with pytest.raises(ValidationError, match="不可作為作者"):
        AnalysisReport(**data)


def test_document_validator_checks_actual_page_limit_and_quote_normalized_whitespace():
    report = make_report()
    data = report.model_dump()
    data["research_background"]["evidence"][0]["original_quote"] = "Background\n evidence."
    report = AnalysisReport(**data)
    validate_report_against_document(report, make_document())

    out_of_range = EvidenceRef(page_number=3, original_quote="missing")
    data = report.model_dump()
    data["research_background"]["evidence"] = [out_of_range.model_dump()]
    report_with_bad_page = AnalysisReport(**data)
    with pytest.raises(EvidenceValidationError, match="超出 PDF 實際總頁數"):
        validate_report_against_document(report_with_bad_page, make_document())


def test_document_validator_rejects_wrong_page_and_non_exact_quote_without_mutating_quote():
    original_quote = "Background evidences."
    data = make_report().model_dump()
    data["research_background"]["evidence"][0]["original_quote"] = original_quote
    report = AnalysisReport(**data)
    with pytest.raises(EvidenceValidationError, match="找不到原始引句"):
        validate_report_against_document(report, make_document())
    assert report.research_background.evidence[0].original_quote == original_quote

    data = make_report().model_dump()
    data["research_background"]["evidence"][0]["page_number"] = 2
    report_wrong_page = AnalysisReport(**data)
    with pytest.raises(EvidenceValidationError, match="找不到原始引句"):
        validate_report_against_document(report_wrong_page, make_document())


def test_document_validator_rejects_report_with_wrong_document_or_total_pages():
    document = make_document()
    report = make_report(document_id="other-document")
    with pytest.raises(EvidenceValidationError, match="識別碼"):
        validate_report_against_document(report, document)

    report = make_report(total_pages=3)
    with pytest.raises(EvidenceValidationError, match="總頁數"):
        validate_report_against_document(report, document)


def test_document_validator_rejects_outline_range_past_pdf_end():
    data = make_report().model_dump()
    data["outline"][0]["end_page"] = 3
    report = AnalysisReport(**data)
    with pytest.raises(EvidenceValidationError, match="大綱章節.*超出"):
        validate_report_against_document(report, make_document())
