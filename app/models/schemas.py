"""Pydantic schemas for API, PDF extraction, and source-grounded analysis."""

from enum import Enum
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    """健康檢查回應模型"""

    status: str = Field(default="ok", description="服務運作狀態")
    app_name: str = Field(..., description="專案名稱")
    app_name_zh: str = Field(..., description="專案中文名稱")
    version: str = Field(..., description="系統版本")
    environment: str = Field(..., description="執行環境")
    supported_languages: List[str] = Field(..., description="支援之語言清單")


class SystemInfoResponse(BaseModel):
    """系統限制與規格資訊"""

    max_file_size_mb: int = Field(..., description="單一 PDF 最大容量限制 (MB)")
    max_pages: int = Field(..., description="單一 PDF 最大頁數建議限制")
    digital_text_only: bool = Field(default=True, description="是否僅支援文字型 PDF")
    single_upload_only: bool = Field(default=True, description="是否一次僅支援單篇分析")
    zero_cost_compliant: bool = Field(default=True, description="是否恪守零費用 NT$0 原則")


class LanguageCode(str, Enum):
    """正式支援的原文語言代碼；無法判斷時由欄位使用 None。"""

    EN = "en"
    JA = "ja"
    ZH_CN = "zh-CN"
    ZH_TW = "zh-TW"


class MetadataSource(str, Enum):
    """基本資料來源狀態，避免把使用者輸入冒充為 PDF 辨識結果。"""

    PDF_RECOGNITION = "pdf_recognition"
    USER_PROVIDED = "user_provided"
    UNRECOGNIZABLE = "unrecognizable"
    NOT_MENTIONED = "not_mentioned"
    PENDING_CONFIRMATION = "pending_confirmation"


class MetadataValueSource(str, Enum):
    """來源與使用者審閱狀態分離後的基本資料來源。"""

    PDF_DETECTED = "pdf_detected"
    USER_PROVIDED = "user_provided"


class MetadataReviewStatus(str, Enum):
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"


class MetadataReviewDecision(str, Enum):
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"


class ContentStatus(str, Enum):
    """分析內容狀態；原文缺漏與辨識失敗是不同狀態。"""

    SUPPORTED = "supported"
    NOT_MENTIONED = "not_mentioned"
    UNRECOGNIZABLE = "unrecognizable"
    PENDING_CONFIRMATION = "pending_confirmation"
    USER_PROVIDED = "user_provided"


class AnalysisMode(str, Enum):
    GENERAL = "general"
    TOPIC = "topic"


class AnalysisRequest(BaseModel):
    """Validated request to begin a paper analysis; it does not imply analysis ran."""

    document_id: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    analysis_mode: AnalysisMode
    topic: Optional[str] = None

    @model_validator(mode="after")
    def validate_mode_topic(self):
        if self.topic is not None:
            self.topic = self.topic.strip() or None
        if self.analysis_mode == AnalysisMode.TOPIC and self.topic is None:
            raise ValueError("主題導向分析必須提供非空白主題。")
        if self.analysis_mode == AnalysisMode.GENERAL and self.topic is not None:
            raise ValueError("一般分析不得提供主題。")
        return self


class AnalysisSubmissionResponse(BaseModel):
    """Explicit response while the actual analysis service is not implemented."""

    status: Literal["not_implemented"]
    analysis_started: Literal[False] = False
    message: str


class AnalysisSuccessResponse(BaseModel):
    """Reference to a report that has passed validation and been persisted."""

    status: Literal["completed"]
    report_id: str = Field(..., pattern=r"^[0-9a-f]{32}$")


class RelevanceLevel(str, Enum):
    HIGH = "highly_relevant"
    PARTIAL = "partially_relevant"
    LOW = "low_relevance"


class LimitationsStatus(str, Enum):
    PRESENT = "present"
    NOT_MENTIONED = "not_mentioned"


class PageTextItem(BaseModel):
    """單頁原文與 PDF 閱讀器使用的 1-based 物理頁碼。"""

    physical_page: int = Field(..., strict=True, ge=1, description="1-based PDF 物理頁碼")
    text: str = Field(..., description="該頁實際擷取之原始純文字")
    char_count: int = Field(..., strict=True, ge=0, description="該頁字元數量")


class ChunkSourceSpan(BaseModel):
    """A zero-based, half-open character range from one physical PDF page."""

    physical_page: int = Field(..., strict=True, ge=1)
    start_offset: int = Field(..., strict=True, ge=0)
    end_offset: int = Field(..., strict=True, ge=1)

    @model_validator(mode="after")
    def end_must_follow_start(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("source span end_offset 必須大於 start_offset")
        return self


class TextChunk(BaseModel):
    """An exact non-empty text slice with a single-page source reference."""

    chunk_id: str = Field(..., min_length=1)
    chunk_index: int = Field(..., strict=True, ge=0)
    text: str = Field(..., min_length=1)
    source_spans: List[ChunkSourceSpan] = Field(..., min_length=1, max_length=1)

    @model_validator(mode="after")
    def source_span_length_matches_text(self):
        span = self.source_spans[0]
        if span.end_offset - span.start_offset != len(self.text):
            raise ValueError("chunk text 長度必須等於其來源 offset 範圍")
        return self


class DocumentExtractionData(BaseModel):
    """PDF 完整逐頁擷取資料。"""

    document_id: str = Field(..., description="系統產生的唯一隨機文件識別碼")
    original_filename: str = Field(..., description="使用者上傳時的原始檔案名稱")
    total_pages: int = Field(..., strict=True, ge=1, description="PDF 實際總頁數")
    total_characters: int = Field(..., strict=True, ge=0, description="整份文件擷取到的文字總字數")
    pages: List[PageTextItem] = Field(..., min_length=1, description="依 1-based 物理頁碼排列的原文")
    created_at: str = Field(..., description="擷取完成之 ISO 8601 時間戳記")

    @model_validator(mode="after")
    def pages_match_total_and_physical_order(self):
        expected = list(range(1, self.total_pages + 1))
        actual = [page.physical_page for page in self.pages]
        if actual != expected:
            raise ValueError("pages 必須依序對應 PDF 1-based physical_page 1..total_pages")
        return self


class DocumentUploadResponse(BaseModel):
    """PDF 上傳與文字擷取成功回應模型。"""

    success: bool = Field(default=True, description="是否處理成功")
    document_id: str = Field(..., description="文件唯一識別碼")
    original_filename: str = Field(..., description="原始檔案名稱")
    total_pages: int = Field(..., description="總頁數 (物理頁碼數)")
    total_characters: int = Field(..., description="有效文字字元總數")
    preview_excerpt: str = Field(..., description="第一頁原文預覽片段")
    message: str = Field(..., description="繁體中文狀態提示訊息")
    metadata_review: Optional["MetadataReview"] = Field(
        None, description="本機基本資料辨識結果；辨識失敗不影響 PDF 上傳"
    )


class DocumentInfoResponse(BaseModel):
    """查詢已上傳文件基本資訊回應模型。"""

    document_id: str = Field(..., description="文件唯一識別碼")
    original_filename: str = Field(..., description="原始檔案名稱")
    total_pages: int = Field(..., description="總頁數")
    total_characters: int = Field(..., description="有效文字字元總數")
    created_at: str = Field(..., description="上傳時間戳記")


class ErrorResponse(BaseModel):
    """標準錯誤回應模型。"""

    error_code: str = Field(..., description="結構化錯誤代碼")
    message: str = Field(..., description="供前端直接顯示之繁體中文錯誤提示")
    detail: Optional[str] = Field(None, description="詳細除錯或系統說明資訊")


class EvidenceRef(BaseModel):
    """未改寫的 PDF 原文引句及其 1-based 物理頁碼。"""

    page_number: int = Field(..., strict=True, ge=1, description="1-based PDF 物理頁碼")
    original_quote: str = Field(..., min_length=1, description="未修改的 PDF 原文引句")

    @model_validator(mode="after")
    def quote_must_contain_non_whitespace(self):
        if not self.original_quote.strip():
            raise ValueError("original_quote 不可為空白")
        return self


class GroundedStatement(BaseModel):
    """具明確來源狀態的原文語言／繁體中文整理內容。"""

    statement_id: str = Field(..., min_length=1, description="報告內唯一識別碼，供心智圖節點引用")
    summary_tw: str = Field(..., min_length=1, description="繁體中文整理或明確狀態標記")
    summary_original: Optional[str] = Field(
        None, min_length=1, description="英文或日文原文語言整理；非支持內容不得填入"
    )
    status: ContentStatus = Field(..., description="支持、未提及、無法辨識、待確認或使用者提供")
    source: MetadataSource = Field(..., description="內容來源狀態")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="原文依據；支持的內容必填")

    @model_validator(mode="after")
    def status_matches_source_and_evidence(self):
        if self.status == ContentStatus.SUPPORTED:
            if self.source != MetadataSource.PDF_RECOGNITION or not self.evidence:
                raise ValueError("supported 內容必須來自 PDF 且至少附一項原文依據")
        elif self.status == ContentStatus.NOT_MENTIONED:
            if self.summary_original is not None:
                raise ValueError("原文未提及標記不得偽裝成原文語言摘要")
            if self.source != MetadataSource.NOT_MENTIONED:
                raise ValueError("not_mentioned 狀態必須明確標示來源為原文未提及")
            if self.summary_tw not in {"【原文未提及】", "【原文未探討此面向】"} or self.evidence:
                raise ValueError("原文未提及須使用規定標記且不可附造出的引句")
        elif self.status == ContentStatus.UNRECOGNIZABLE:
            if self.summary_original is not None:
                raise ValueError("無法辨識標記不得偽裝成原文語言摘要")
            if self.source != MetadataSource.UNRECOGNIZABLE or self.summary_tw != "無法辨識" or self.evidence:
                raise ValueError("無法辨識須使用獨立來源狀態，不可當作原文未提及")
        elif self.status == ContentStatus.PENDING_CONFIRMATION:
            if self.summary_original is not None:
                raise ValueError("待確認標記不得偽裝成原文語言摘要")
            if self.source != MetadataSource.PENDING_CONFIRMATION or self.summary_tw != "待使用者確認":
                raise ValueError("待確認狀態須明確標示待使用者確認")
        elif self.status == ContentStatus.USER_PROVIDED:
            if self.summary_original is not None:
                raise ValueError("使用者提供內容不得偽裝成原文語言摘要")
            if self.source != MetadataSource.USER_PROVIDED or self.evidence:
                raise ValueError("使用者提供內容須標示 user_provided 且不可冒充 PDF 引句")
        return self


T = TypeVar("T")


class MetadataField(BaseModel, Generic[T]):
    """帶來源與狀態的基本資料值。"""

    value: Optional[T] = Field(None, description="辨識、待確認或使用者提供的欄位值")
    source: MetadataSource = Field(..., description="PDF 辨識、使用者提供或各種未完成狀態")
    evidence: Optional[EvidenceRef] = Field(None, description="PDF 辨識值的原文依據")

    @model_validator(mode="after")
    def source_matches_value_and_evidence(self):
        if self.source == MetadataSource.PDF_RECOGNITION:
            if self.value is None or self.evidence is None:
                raise ValueError("PDF 辨識的基本資料必須有值及原文依據")
        elif self.source == MetadataSource.USER_PROVIDED:
            if self.value is None or self.evidence is not None:
                raise ValueError("使用者提供的基本資料須有值且不得偽附 PDF 依據")
        elif self.source == MetadataSource.PENDING_CONFIRMATION:
            if self.value is None or self.evidence is None:
                raise ValueError("待確認候選值必須保留候選值及其 PDF 依據")
        elif self.value is not None or self.evidence is not None:
            raise ValueError("無法辨識或原文未提及時不得保留未驗證值或引句")
        return self


class PaperMetadata(BaseModel):
    """論文基本資料；各欄位分別追蹤來源，使用者修正不會覆蓋 PDF 證據。"""

    title: MetadataField[str]
    authors: MetadataField[List[str]]
    publication_year: MetadataField[str]
    detected_language: MetadataField[Optional[LanguageCode]]


class MetadataReviewField(BaseModel, Generic[T]):
    """基本資料值；來源和整筆審閱狀態分開記錄。"""

    value: Optional[T] = None
    source: Optional[MetadataValueSource] = None
    evidence: Optional[EvidenceRef] = None

    @model_validator(mode="after")
    def source_matches_value_and_evidence(self):
        if self.source == MetadataValueSource.PDF_DETECTED:
            if self.value is None or self.evidence is None:
                raise ValueError("PDF 偵測值必須有候選值及原文依據")
        elif self.source == MetadataValueSource.USER_PROVIDED:
            if self.value is None or self.evidence is not None:
                raise ValueError("使用者提供值必須有值且不得保留 PDF 引據")
        elif self.value is not None or self.evidence is not None:
            raise ValueError("沒有來源的欄位不可保留值或 PDF 引據")
        return self


class MetadataReview(BaseModel):
    """獨立保存的基本資料候選及審閱狀態，不修改 PDF 抽取結果。"""

    document_id: str = Field(..., min_length=1)
    status: MetadataReviewStatus = MetadataReviewStatus.PENDING_CONFIRMATION
    title: MetadataReviewField[str]
    authors: MetadataReviewField[List[str]]
    publication_year: MetadataReviewField[str]
    detected_language: MetadataReviewField[Optional[LanguageCode]]


class MetadataReviewRequest(BaseModel):
    """使用者只提交欄位值與決定；來源及 PDF 證據由後端保管。"""

    decision: MetadataReviewDecision
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    publication_year: Optional[str] = None
    detected_language: Optional[LanguageCode] = None


class MetadataReviewResponse(MetadataReview):
    pass


class OutlineSection(BaseModel):
    """文章章節與其 PDF 物理頁碼範圍。"""

    section_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, description="原文章節標題")
    title_tw: Optional[str] = Field(None, min_length=1, description="英文或日文章節標題的繁體中文翻譯")
    start_page: int = Field(..., strict=True, ge=1, description="起始 PDF 物理頁碼")
    end_page: int = Field(..., strict=True, ge=1, description="結束 PDF 物理頁碼")
    evidence: List[EvidenceRef] = Field(..., min_length=1, description="章節標題或頁碼範圍的原文依據")

    @model_validator(mode="after")
    def start_not_after_end(self):
        if self.start_page > self.end_page:
            raise ValueError("章節起始頁碼不得大於結束頁碼")
        return self


class KeyFindingItem(BaseModel):
    """一項重要重點，必須有 PDF 原文支持。"""

    finding_id: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1, description="重點標題")
    topic_tw: Optional[str] = Field(None, min_length=1, description="英文或日文重點標題的繁體中文翻譯")
    statement: GroundedStatement

    @model_validator(mode="after")
    def finding_must_be_supported(self):
        if self.statement.status != ContentStatus.SUPPORTED:
            raise ValueError("重要重點必須是有 PDF 原文依據的 supported 內容")
        return self


class TopicRelevance(BaseModel):
    """主題導向模式的相關性判斷及原文依據。"""

    level: RelevanceLevel
    reasons: List[GroundedStatement] = Field(..., min_length=1)
    related_sections: List[GroundedStatement] = Field(
        ..., min_length=1, description="相關章節及其原文依據"
    )
    recommended_reading: List[GroundedStatement] = Field(
        ..., min_length=1, description="建議優先研讀段落及其原文依據"
    )

    @model_validator(mode="after")
    def topic_details_must_be_pdf_grounded(self):
        items = [*self.reasons, *self.related_sections, *self.recommended_reading]
        if any(item.status != ContentStatus.SUPPORTED for item in items):
            raise ValueError("主題相關性、相關章節及優先研讀段落必須由 PDF 原文支持")
        ids = [item.statement_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("主題相關性項目識別碼必須唯一")
        return self


class ResearchLimitationItem(BaseModel):
    """作者明確提出的一項研究限制；一般可推論的限制不得放入此模型。"""

    statement: GroundedStatement
    explicitly_stated_by_author: Literal[True] = Field(
        ..., description="必須確認原文將此內容明確列為作者提出的限制"
    )

    @model_validator(mode="after")
    def limitation_must_be_explicit_and_grounded(self):
        if not self.explicitly_stated_by_author:
            raise ValueError("研究限制只能收錄原文明確提出的作者限制")
        if self.statement.status != ContentStatus.SUPPORTED:
            raise ValueError("作者明確提出的研究限制必須附 PDF 原文依據")
        return self


class ResearchLimitations(BaseModel):
    """研究限制；全文未提及時必須使用指定標記，不能自行推論。"""

    status: LimitationsStatus
    items: List[ResearchLimitationItem] = Field(default_factory=list)
    summary_tw: Optional[str] = None

    @model_validator(mode="after")
    def status_matches_items(self):
        if self.status == LimitationsStatus.NOT_MENTIONED:
            if self.items or self.summary_tw != "【原文未提及】":
                raise ValueError("未提及研究限制時必須使用【原文未提及】且不得列出限制")
        elif not self.items or self.summary_tw is not None:
            raise ValueError("已提及研究限制時須逐項列出作者明確提出且有依據的限制")
        return self


class MindMapCategory(str, Enum):
    PAPER_TITLE = "paper_title"
    RESEARCH_BACKGROUND = "research_background"
    RESEARCH_OBJECTIVES = "research_objectives"
    METHODOLOGY = "methodology"
    CORE_ARGUMENTS = "core_arguments"
    RESEARCH_FINDINGS = "research_findings"
    CONCLUSION = "conclusion"
    TOPIC_RELEVANCE = "topic_relevance"


class MindMapNode(BaseModel):
    """心智圖節點；必須回指報告項目，不能新增無來源論點。"""

    category: MindMapCategory
    label_tw: str = Field(..., min_length=1)
    label_original: Optional[str] = Field(None, min_length=1, description="英文或日文心智圖節點原文語言標籤")
    source_item_ids: List[str] = Field(..., min_length=1, description="報告內已驗證項目的識別碼")
    evidence: List[EvidenceRef] = Field(default_factory=list)
    children: List["MindMapNode"] = Field(default_factory=list)


class MindMapData(BaseModel):
    root: MindMapNode


class AnalysisReport(BaseModel):
    """依 PROJECT_SPEC.md 固定構面的完整來源封閉式分析資料。"""

    document_id: str = Field(..., min_length=1)
    total_pages: int = Field(..., strict=True, ge=1)
    metadata: PaperMetadata
    mode: AnalysisMode
    topic: Optional[str] = Field(None, description="主題導向模式的使用者主題")
    outline: List[OutlineSection] = Field(..., description="文章大綱及章節頁碼範圍")
    research_background: GroundedStatement
    research_objectives: GroundedStatement
    methodology: GroundedStatement
    research_findings: GroundedStatement
    core_arguments: GroundedStatement
    key_points: List[KeyFindingItem] = Field(..., min_length=5, max_length=10)
    research_limitations: ResearchLimitations
    conclusion: GroundedStatement
    topic_relevance: Optional[TopicRelevance] = None
    mind_map: MindMapData

    @model_validator(mode="after")
    def report_mode_and_mind_map_references(self):
        self._validate_language_fields()
        if self.mode == AnalysisMode.GENERAL:
            if self.topic is not None or self.topic_relevance is not None:
                raise ValueError("一般模式不得包含主題或主題相關性評估")
        elif not self.topic or self.topic_relevance is None:
            raise ValueError("主題導向模式必須包含使用者主題及主題相關性評估")

        statements = {
            "research_background": self.research_background,
            "research_objectives": self.research_objectives,
            "methodology": self.methodology,
            "research_findings": self.research_findings,
            "core_arguments": self.core_arguments,
            "conclusion": self.conclusion,
        }
        if any(statement.status == ContentStatus.USER_PROVIDED for statement in statements.values()):
            raise ValueError("使用者提供內容不可作為作者的分析觀點")
        # This registry ties every mind-map category to semantically matching,
        # PDF-grounded report items. Document-level quote/page validation is a
        # separate required step before a report can be accepted or saved.
        category_sources = {
            MindMapCategory.PAPER_TITLE: {"metadata.title"},
            MindMapCategory.RESEARCH_BACKGROUND: {self.research_background.statement_id},
            MindMapCategory.RESEARCH_OBJECTIVES: {self.research_objectives.statement_id},
            MindMapCategory.METHODOLOGY: {self.methodology.statement_id},
            MindMapCategory.CORE_ARGUMENTS: {self.core_arguments.statement_id},
            MindMapCategory.RESEARCH_FINDINGS: {self.research_findings.statement_id},
            MindMapCategory.CONCLUSION: {self.conclusion.statement_id},
        }
        grounded_report_ids = {
            statement.statement_id
            for statement in statements.values()
            if statement.status == ContentStatus.SUPPORTED and statement.evidence
        }
        grounded_report_ids.update(
            item.statement.statement_id for item in self.research_limitations.items
        )
        grounded_report_ids.update(
            item.statement.statement_id for item in self.key_points
        )
        grounded_report_ids.update(section.section_id for section in self.outline)
        title_field = self.metadata.title
        if title_field.source in {
            MetadataSource.PDF_RECOGNITION,
            MetadataSource.PENDING_CONFIRMATION,
        } and title_field.evidence is not None:
            grounded_report_ids.add("metadata.title")

        all_ids = set().union(*category_sources.values())
        all_ids.update(grounded_report_ids)
        if self.topic_relevance:
            topic_items = [
                *self.topic_relevance.reasons,
                *self.topic_relevance.related_sections,
                *self.topic_relevance.recommended_reading,
            ]
            topic_ids = {item.statement_id for item in topic_items}
            all_ids.update(topic_ids)
            grounded_report_ids.update(
                item.statement_id
                for item in topic_items
                if item.status == ContentStatus.SUPPORTED and item.evidence
            )
            category_sources[MindMapCategory.TOPIC_RELEVANCE] = topic_ids

        report_ids = [statement.statement_id for statement in statements.values()]
        report_ids.extend(item.statement.statement_id for item in self.research_limitations.items)
        report_ids.extend(item.statement.statement_id for item in self.key_points)
        report_ids.extend(section.section_id for section in self.outline)
        report_ids.append("metadata.title")
        if self.topic_relevance:
            report_ids.extend(
                item.statement_id
                for item in [
                    *self.topic_relevance.reasons,
                    *self.topic_relevance.related_sections,
                    *self.topic_relevance.recommended_reading,
                ]
            )
        if len(report_ids) != len(set(report_ids)):
            raise ValueError("報告項目識別碼必須唯一，避免心智圖來源連結含糊")

        nodes = []
        if self.mind_map.root.category != MindMapCategory.PAPER_TITLE:
            raise ValueError("心智圖 root 必須是論文標題節點")
        pending = [self.mind_map.root]
        while pending:
            node = pending.pop()
            nodes.append(node)
            pending.extend(node.children)
            unknown_ids = set(node.source_item_ids) - all_ids
            if unknown_ids:
                raise ValueError(f"心智圖節點引用不存在的報告項目：{sorted(unknown_ids)}")
            if node.category not in category_sources:
                raise ValueError(f"心智圖節點類別不適用於目前分析模式：{node.category.value}")
            invalid_category_ids = set(node.source_item_ids) - category_sources[node.category]
            if invalid_category_ids:
                raise ValueError(
                    f"心智圖節點類別 {node.category.value} 引用了不相符的報告來源："
                    f"{sorted(invalid_category_ids)}"
                )
            # A user-supplied title is bibliographic metadata, not an author
            # claim. An unavailable title may only appear as its explicit status.
            title_field = self.metadata.title
            title_reference_is_nonclaim = (
                node is self.mind_map.root
                and node.category == MindMapCategory.PAPER_TITLE
                and "metadata.title" in node.source_item_ids
                and (
                    title_field.source == MetadataSource.USER_PROVIDED
                    or (
                        title_field.source == MetadataSource.UNRECOGNIZABLE
                        and title_field.value is None
                        and node.label_tw == "【無法辨識】"
                    )
                    or (
                        title_field.source == MetadataSource.NOT_MENTIONED
                        and title_field.value is None
                        and node.label_tw == "【原文未提及】"
                    )
                )
            )
            ungrounded_ids = set(node.source_item_ids) - grounded_report_ids
            if title_reference_is_nonclaim:
                ungrounded_ids.discard("metadata.title")
            if ungrounded_ids:
                raise ValueError(
                    f"心智圖不得引用缺少 PDF 原文依據的報告項目：{sorted(ungrounded_ids)}"
                )

        required = {
            MindMapCategory.PAPER_TITLE,
            MindMapCategory.RESEARCH_BACKGROUND,
            MindMapCategory.RESEARCH_OBJECTIVES,
            MindMapCategory.METHODOLOGY,
            MindMapCategory.CORE_ARGUMENTS,
            MindMapCategory.RESEARCH_FINDINGS,
            MindMapCategory.CONCLUSION,
        }
        present = {node.category for node in nodes}
        if not required.issubset(present):
            missing = sorted(category.value for category in required - present)
            raise ValueError(f"心智圖缺少正式規格要求的節點：{missing}")
        if self.mode == AnalysisMode.TOPIC and MindMapCategory.TOPIC_RELEVANCE not in present:
            raise ValueError("主題導向模式心智圖必須包含主題相關性分支")
        return self

    def _validate_language_fields(self) -> None:
        """Enforce bilingual fields from the confirmed PDF language without guessing."""
        language = self.metadata.detected_language.value
        statements = [
            self.research_background,
            self.research_objectives,
            self.methodology,
            self.research_findings,
            self.core_arguments,
            self.conclusion,
            *(item.statement for item in self.key_points),
            *(item.statement for item in self.research_limitations.items),
        ]
        if self.topic_relevance is not None:
            statements.extend(
                [
                    *self.topic_relevance.reasons,
                    *self.topic_relevance.related_sections,
                    *self.topic_relevance.recommended_reading,
                ]
            )
        nodes = []
        pending_nodes = [self.mind_map.root]
        while pending_nodes:
            node = pending_nodes.pop()
            nodes.append(node)
            pending_nodes.extend(node.children)

        if language in {LanguageCode.EN, LanguageCode.JA}:
            for statement in statements:
                if statement.status == ContentStatus.SUPPORTED and not statement.summary_original:
                    raise ValueError("英文或日文的 supported 整理必須提供原文語言與繁體中文")
            if any(not section.title_tw for section in self.outline):
                raise ValueError("英文或日文章節標題必須提供繁體中文翻譯")
            if any(not item.topic_tw for item in self.key_points):
                raise ValueError("英文或日文重要重點主題必須提供繁體中文翻譯")

            title = self.metadata.title
            root = self.mind_map.root
            root_is_user_title = title.source == MetadataSource.USER_PROVIDED
            root_is_unavailable = title.source in {
                MetadataSource.NOT_MENTIONED,
                MetadataSource.UNRECOGNIZABLE,
            }
            for node in nodes:
                is_root_title = node is root and node.category == MindMapCategory.PAPER_TITLE
                if is_root_title and (root_is_user_title or root_is_unavailable):
                    if node.label_original is not None:
                        raise ValueError("使用者提供或缺漏的標題不得偽裝成原文語言標題")
                    continue
                if not node.label_original:
                    raise ValueError("英文或日文心智圖節點必須提供原文語言與繁體中文標籤")
            if title.source in {
                MetadataSource.PDF_RECOGNITION,
                MetadataSource.PENDING_CONFIRMATION,
            } and title.value is not None and root.label_original != title.value:
                raise ValueError("心智圖原文標題必須與伺服器確認的 PDF 標題一致")
            if root_is_user_title and root.label_tw != title.value:
                raise ValueError("使用者確認的標題必須同步顯示於心智圖繁體中文根節點")
            if title.value is None:
                expected_marker = (
                    "【原文未提及】"
                    if title.source == MetadataSource.NOT_MENTIONED
                    else "【無法辨識】"
                )
                if root.label_tw != expected_marker:
                    raise ValueError("缺漏標題的心智圖根節點必須使用對應狀態標記")
        elif language in {LanguageCode.ZH_CN, LanguageCode.ZH_TW}:
            if any(statement.summary_original is not None for statement in statements):
                raise ValueError("中文文獻不應重複保存原文語言摘要欄位")
            if any(node.label_original is not None for node in nodes):
                raise ValueError("中文文獻不應重複保存心智圖原文語言欄位")
            if language == LanguageCode.ZH_CN:
                if any(not section.title_tw for section in self.outline):
                    raise ValueError("簡體中文章節標題必須提供繁體中文呈現")
                if any(not item.topic_tw for item in self.key_points):
                    raise ValueError("簡體中文重要重點主題必須提供繁體中文呈現")
            elif any(section.title_tw is not None for section in self.outline) or any(
                item.topic_tw is not None for item in self.key_points
            ):
                raise ValueError("繁體中文文獻不應重複保存相同語言的章節或重點欄位")


MindMapNode.model_rebuild()
DocumentUploadResponse.model_rebuild()
