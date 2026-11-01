"""
AI 學術文獻分析與雙語心智圖生成系統
FastAPI 主應用程式入口 (Main Application Entrypoint)
"""

from pathlib import Path
import logging
import time
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from pydantic import ValidationError

from app import config
from app.models.schemas import (
    HealthResponse,
    SystemInfoResponse,
    DocumentUploadResponse,
    DocumentInfoResponse,
    DocumentExtractionData,
    ErrorResponse,
    MetadataReviewRequest,
    MetadataReviewResponse,
    AnalysisRequest,
    AnalysisSubmissionResponse,
    AnalysisSuccessResponse,
    AnalysisReport,
    PaperMetadata,
    MetadataField,
    MetadataSource,
    MetadataValueSource,
    MetadataReviewStatus,
    LanguageCode,
)
from app.services.pdf_service import (
    PDFService,
    PDFServiceException,
    PDFValidationError,
    PDFSizeLimitExceededError,
    PDFPageLimitExceededError,
    PDFCorruptedError,
    PDFNoTextError,
)
from app.services import metadata_service
from app.services.analysis_service import (
    AnalysisBusyError,
    AnalysisDocumentUnavailableError,
    AnalysisReportRejectedError,
    AnalysisUnavailableError,
    analysis_service,
)
from app.services.analysis_validator import EvidenceValidationError, validate_report_against_document
from app.services.report_service import ReportPersistenceError, save_report, load_report
from app.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

# 將錯誤訊息保存到專案 logs 資料夾
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

error_file_handler = logging.FileHandler(
    LOG_DIR / "analysis_errors.log",
    encoding="utf-8",
)
error_file_handler.setLevel(logging.ERROR)
error_file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
)

logger.addHandler(error_file_handler)

# Gemini ?????????? API Client??????????? API?
ollama_service = OllamaService()
analysis_service.executor = ollama_service.analyze_literature

# 應用程式實例初始化
app = FastAPI(
    title=config.APP_NAME,
    description="封閉領域原文溯源・繁體中文雙語報告・互動式心智圖生成系統",
    version=config.APP_VERSION,
)

# 目錄路徑設定
CURRENT_DIR = Path(__file__).resolve().parent
STATIC_DIR = CURRENT_DIR / "static"
TEMPLATES_DIR = CURRENT_DIR / "templates"

# 掛載靜態資源與模板引擎
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# -------------------------------------------------------------
# 結構化例外處理器 (Exception Handlers)
# -------------------------------------------------------------

@app.exception_handler(PDFValidationError)
async def handle_pdf_validation_error(request: Request, exc: PDFValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
        ).model_dump(),
    )


@app.exception_handler(PDFSizeLimitExceededError)
async def handle_pdf_size_error(request: Request, exc: PDFSizeLimitExceededError):
    return JSONResponse(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        content=ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
        ).model_dump(),
    )


@app.exception_handler(PDFPageLimitExceededError)
async def handle_pdf_page_limit_error(request: Request, exc: PDFPageLimitExceededError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
        ).model_dump(),
    )


@app.exception_handler(PDFCorruptedError)
async def handle_pdf_corrupted_error(request: Request, exc: PDFCorruptedError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
        ).model_dump(),
    )


@app.exception_handler(PDFNoTextError)
async def handle_pdf_no_text_error(request: Request, exc: PDFNoTextError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
        ).model_dump(),
    )


@app.exception_handler(PDFServiceException)
async def handle_pdf_service_error(request: Request, exc: PDFServiceException):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
        ).model_dump(),
    )


# -------------------------------------------------------------
# 基礎網頁與系統狀態路由 (Core Routes)
# -------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, summary="系統首頁")
async def read_root(request: Request):
    """提供系統單頁式學術操作介面"""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": config.APP_NAME,
            "app_name_zh": config.APP_NAME_ZH,
            "version": config.APP_VERSION,
            "max_file_size_mb": config.MAX_FILE_SIZE_MB,
            "max_pages": config.MAX_PAGES,
            "supported_languages": config.SUPPORTED_LANGUAGES,
        },
    )


@app.get("/api/health", response_model=HealthResponse, summary="服務健康檢查 API")
async def health_check():
    """回傳目前後端服務運作狀態、版本與支援語系"""
    return HealthResponse(
        status="ok",
        app_name=config.APP_NAME,
        app_name_zh=config.APP_NAME_ZH,
        version=config.APP_VERSION,
        environment=config.APP_ENV,
        supported_languages=config.SUPPORTED_LANGUAGES,
    )


@app.get("/api/info", response_model=SystemInfoResponse, summary="系統規格與限制資訊")
async def system_info():
    """提供前端查詢當前系統之硬性限制與防護規則"""
    return SystemInfoResponse(
        max_file_size_mb=config.MAX_FILE_SIZE_MB,
        max_pages=config.MAX_PAGES,
        digital_text_only=True,
        single_upload_only=True,
        zero_cost_compliant=True,
    )


# -------------------------------------------------------------
# 第二階段：PDF 文件上傳與文字擷取路由 (Document Upload & Extraction)
# -------------------------------------------------------------

@app.post(
    "/api/documents/upload",
    response_model=DocumentUploadResponse,
    responses={
        400: {"model": ErrorResponse, "description": "非 PDF 檔案、檔案損壞或格式不符"},
        413: {"model": ErrorResponse, "description": "檔案容量超過上限"},
        422: {"model": ErrorResponse, "description": "頁數超限或為無有效文字之純掃描檔"},
        500: {"model": ErrorResponse, "description": "伺服器內部暫存或處理錯誤"},
    },
    summary="上傳單一學術論文 PDF 並逐頁擷取物理頁碼文字",
)
async def upload_document(file: UploadFile = File(...)):
    """
    接收單一 PDF 檔案，進行深度格式檢驗（包含 Magic Bytes 檢查），
    精確按 1-based 物理頁碼逐頁擷取純文字，並暫存結構化結果以供後續 AI 分析。
    """
    # 執行過期暫存檔案清理 (隨請求自動維持無痕儲存環境)
    PDFService.cleanup_expired_files()

    if not file or not file.filename:
        raise PDFValidationError("未選擇任何檔案，請選取學術文獻 PDF 檔案後重新上傳。")

    # UploadFile 已先以 SpooledTemporaryFile 接收 multipart 內容；服務再以固定
    # 64 KiB 區塊讀取該檔案，避免將整份上傳內容複製到 Python 記憶體。
    try:
        await file.seek(0)
        document_id, pdf_path, sanitized_filename = await run_in_threadpool(
            PDFService.save_upload_stream,
            file.file,
            file.filename,
        )
    except PDFServiceException:
        raise
    except Exception as e:
        raise PDFServiceException(f"檔案讀取失敗：{str(e)}", error_code="UPLOAD_READ_ERROR") from e

    # 逐頁解析文字並錨定實體頁碼
    try:
        extraction_data = PDFService.extract_document(
            pdf_path=pdf_path,
            document_id=document_id,
            original_filename=sanitized_filename,
        )
    except Exception:
        # 只清理由本次 UUID 命名的檔案；保留其他上傳者及既有快取。
        PDFService.cleanup_document_artifacts(document_id)
        raise

    # 本機 metadata 規則只檢查現有擷取結果；任何辨識問題都不得使 PDF 上傳失敗。
    try:
        metadata_review = metadata_service.get_or_detect(extraction_data)
    except Exception:
        logger.exception("基本資料候選處理失敗，不影響 PDF 上傳：%s", document_id)
        metadata_review = metadata_service.unrecognized_review(document_id)

    # 取第一頁文字摘要供前端即時回饋
    first_page_text = extraction_data.pages[0].text if extraction_data.pages else ""
    preview_excerpt = first_page_text[:150].replace("\n", " ").strip()
    if len(first_page_text) > 150:
        preview_excerpt += "..."

    return DocumentUploadResponse(
        success=True,
        document_id=document_id,
        original_filename=sanitized_filename,
        total_pages=extraction_data.total_pages,
        total_characters=extraction_data.total_characters,
        preview_excerpt=preview_excerpt,
        message="PDF 上傳成功，已依 1-based 物理頁碼完成全書文字擷取！",
        metadata_review=metadata_review,
    )


@app.get(
    "/api/documents/{document_id}",
    response_model=DocumentInfoResponse,
    responses={404: {"model": ErrorResponse, "description": "找不到指定的文件暫存"}},
    summary="取得已上傳文件的基本統計資訊",
)
async def get_document_info(document_id: str):
    """供前端或外部查詢已上傳文件之處理狀態與統計數據"""
    data = PDFService.get_document_data(document_id)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到文件識別碼 {document_id} 的暫存紀錄，可能已過期或未完成上傳。",
        )
    return DocumentInfoResponse(
        document_id=data.document_id,
        original_filename=data.original_filename,
        total_pages=data.total_pages,
        total_characters=data.total_characters,
        created_at=data.created_at,
    )


@app.get(
    "/api/documents/{document_id}/pages",
    response_model=DocumentExtractionData,
    responses={404: {"model": ErrorResponse, "description": "找不到指定的文件暫存"}},
    summary="取得完整逐頁文字與實體物理頁碼（後續 Gemini 分析服務調用）",
)
async def get_document_pages(document_id: str):
    """
    提供給後端分析管線直接調用，取得依 1-based 物理頁碼組織之每頁完整原文。
    """
    data = PDFService.get_document_data(document_id)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到文件識別碼 {document_id} 的暫存紀錄，可能已過期或未完成上傳。",
        )
    return data


def _get_metadata_review(document: DocumentExtractionData):
    try:
        return metadata_service.get_or_detect(document)
    except Exception:
        logger.exception("基本資料辨識失敗，不影響文件資料：%s", document.document_id)
        return metadata_service.unrecognized_review(document.document_id)


@app.get(
    "/api/documents/{document_id}/metadata",
    response_model=MetadataReviewResponse,
    responses={404: {"model": ErrorResponse, "description": "找不到指定的文件暫存"}},
    summary="取得本機辨識的基本資料候選",
)
async def get_document_metadata(document_id: str):
    """Read the independent metadata sidecar or create bounded candidates from cached pages."""
    document = PDFService.get_document_data(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="找不到指定的文件暫存。")
    return _get_metadata_review(document)


@app.post(
    "/api/documents/{document_id}/metadata",
    response_model=MetadataReviewResponse,
    responses={404: {"model": ErrorResponse, "description": "找不到指定的文件暫存"}},
    summary="確認、修改或略過基本資料候選",
)
async def review_document_metadata(document_id: str, request: MetadataReviewRequest):
    """Persist only metadata review state; this endpoint never invokes the analysis service."""
    document = PDFService.get_document_data(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="找不到指定的文件暫存。")
    current = _get_metadata_review(document)
    reviewed = metadata_service.apply_review(current, request)
    try:
        metadata_service.save_review(reviewed)
    except Exception as exc:
        logger.exception("基本資料審閱結果無法保存：%s", document_id)
        raise HTTPException(status_code=500, detail="基本資料審閱結果暫存失敗，請稍後重試。") from exc
    return reviewed


@app.post(
    "/api/analysis",
    response_model=AnalysisSuccessResponse,
    responses={
        404: {"model": ErrorResponse, "description": "文件不存在或已過期"},
        409: {"model": ErrorResponse, "description": "前置狀態衝突或已有分析工作執行中"},
        501: {"model": AnalysisSubmissionResponse, "description": "分析服務尚未實作"},
        502: {"model": ErrorResponse, "description": "分析候選結果未通過驗收"},
        500: {"model": ErrorResponse, "description": "報告保存或分析處理失敗"},
    },
    summary="驗證分析請求並驗收已完成報告",
)
async def submit_analysis_request(request: AnalysisRequest):
    """Accept and persist only executor reports validated against the extracted PDF.

    The executor is still disabled by default. A configured executor result must pass
    the AnalysisReport schema and document evidence validator before atomic persistence.
    """
    document = PDFService.get_document_data(request.document_id)
    pdf_path = PDFService.get_document_pdf_path(request.document_id)
    result_path = config.TEMP_RESULTS_DIR / f"{request.document_id}.json"
    if (
        document is None
        or document.document_id != request.document_id
        or pdf_path is None
        or not result_path.is_file()
    ):
        raise HTTPException(status_code=404, detail="文件不存在或暫存資料已過期，請重新上傳 PDF。")

    now = time.time()
    try:
        is_expired = any(
            now - path.stat().st_mtime > config.TEMP_FILE_TTL_SECONDS
            for path in (pdf_path, result_path)
        )
    except OSError:
        is_expired = True
    if is_expired:
        raise HTTPException(status_code=404, detail="文件暫存資料已過期，請重新上傳 PDF。")

    review = _get_metadata_review(document)
    if review.document_id != request.document_id or review.status == MetadataReviewStatus.PENDING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="請先確認或略過文章基本資料，再送出分析請求。")

    # Keep the real analysis disabled until a report-producing implementation is
    # configured. The same acceptance path is used by test executors.
    if analysis_service.executor is not None:
        def final_document_preflight() -> bool:
            """Recheck file presence and TTL atomically with active registration."""
            try:
                current_pdf_path = PDFService.get_document_pdf_path(request.document_id)
                current_result_path = config.TEMP_RESULTS_DIR / f"{request.document_id}.json"
                if (
                    current_pdf_path is None
                    or not current_pdf_path.is_file()
                    or not current_result_path.is_file()
                ):
                    return False
                checked_at = time.time()
                return all(
                    checked_at - path.stat().st_mtime <= config.TEMP_FILE_TTL_SECONDS
                    for path in (current_pdf_path, current_result_path)
                )
            except OSError:
                return False

        def accept_candidate(candidate: object) -> AnalysisReport:
            try:
                if candidate is None:
                    raise AnalysisUnavailableError("分析執行器尚未產生報告。")
                if isinstance(candidate, AnalysisReport):
                    candidate_data = candidate.model_dump(mode="python")
                elif isinstance(candidate, dict):
                    candidate_data = dict(candidate)
                else:
                    raise TypeError("分析執行器必須回傳 AnalysisReport 或其字典資料。")

                # Metadata is controlled by the server-side review record, never
                # accepted from the executor as an unverified replacement.
                report_metadata = _paper_metadata_from_review(review)
                candidate_data["metadata"] = report_metadata
                mind_map = candidate_data.get("mind_map")
                root = mind_map.get("root") if isinstance(mind_map, dict) else None
                if isinstance(root, dict) and report_metadata.title.value is None:
                    root["label_tw"] = (
                        "【原文未提及】"
                        if report_metadata.title.source == MetadataSource.NOT_MENTIONED
                        else "【無法辨識】"
                    )
                    root["label_original"] = None
                elif (
                    isinstance(root, dict)
                    and report_metadata.title.source == MetadataSource.USER_PROVIDED
                ):
                    # A user-edited title may use a different language from the
                    # PDF; display it as user-provided Traditional Chinese text,
                    # never as an original-language title.
                    root["label_tw"] = report_metadata.title.value
                    root["label_original"] = None
                elif isinstance(root, dict) and report_metadata.title.value is not None:
                    language = report_metadata.detected_language.value
                    if language in {LanguageCode.EN, LanguageCode.JA}:
                        root["label_original"] = report_metadata.title.value
                    elif language in {LanguageCode.ZH_CN, LanguageCode.ZH_TW}:
                        root["label_original"] = None
                report = AnalysisReport.model_validate(candidate_data)
                if report.mode != request.analysis_mode or report.topic != request.topic:
                    raise ValueError("分析報告模式或主題與原始請求不一致。")
                validate_report_against_document(report, document)
            except (ValidationError, EvidenceValidationError, TypeError, ValueError) as exc:
                logger.exception("[REPORT_VALIDATION_DIAG] ????????????????")
                raise AnalysisReportRejectedError("分析候選報告未通過驗收。") from exc

            save_report(report)
            return report

        try:
            accepted_report = await run_in_threadpool(
                analysis_service.run,
                request,
                document,
                preflight=final_document_preflight,
                accept_result=accept_candidate,
            )
            if accepted_report is None:
                raise AnalysisUnavailableError("分析執行器尚未產生報告。")
        except AnalysisBusyError as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content=ErrorResponse(
                    error_code="ANALYSIS_BUSY",
                    message=str(exc),
                ).model_dump(),
            )
        except AnalysisDocumentUnavailableError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件在分析啟動前已不存在或暫存資料已過期，請重新上傳 PDF。",
            )
        except AnalysisUnavailableError:
            # Keep the original explicit not-implemented response if the
            # executor disappears or does not produce a candidate report.
            return JSONResponse(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                content=AnalysisSubmissionResponse(
                    status="not_implemented",
                    analysis_started=False,
                    message="分析服務尚未啟用；請求資料已驗證，但尚未開始分析或產生報告。",
                ).model_dump(),
            )
        except AnalysisReportRejectedError as exc:
            logger.warning("分析候選報告未通過驗收：%s", request.document_id)
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content=ErrorResponse(
                    error_code="ANALYSIS_REPORT_INVALID",
                    message="分析結果未通過原文與資料格式驗證，未保存報告。",
                ).model_dump(),
            )
        except ReportPersistenceError:
            logger.exception("分析報告保存失敗：%s", request.document_id)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=ErrorResponse(
                    error_code="ANALYSIS_REPORT_SAVE_FAILED",
                    message="分析報告保存失敗，請稍後重試。",
                ).model_dump(),
            )
        except Exception as exc:
            logger.exception("分析工作失敗：%s", request.document_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="分析處理失敗，請稍後重試。",
            ) from exc

        return AnalysisSuccessResponse(
            status="completed",
            report_id=accepted_report.document_id,
        )

    # Never report success or fabricate a report at this stage, even when a test
    # has injected a mock executor to exercise the lock lifecycle.
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=AnalysisSubmissionResponse(
            status="not_implemented",
            analysis_started=False,
            message="分析服務尚未啟用；請求資料已驗證，但尚未開始分析或產生報告。",
        ).model_dump(),
    )


def _paper_metadata_from_review(review) -> PaperMetadata:
    """Translate the persisted review's values/provenance into report metadata."""
    def convert(field):
        if field.source == MetadataValueSource.PDF_DETECTED:
            return MetadataField(
                value=field.value,
                source=MetadataSource.PDF_RECOGNITION,
                evidence=field.evidence,
            )
        if field.source == MetadataValueSource.USER_PROVIDED:
            return MetadataField(value=field.value, source=MetadataSource.USER_PROVIDED)
        # MetadataReview does not distinguish “not mentioned” from “not detected”.
        # Do not infer absence from that missing distinction.
        return MetadataField(value=None, source=MetadataSource.UNRECOGNIZABLE)

    return PaperMetadata(
        title=convert(review.title),
        authors=convert(review.authors),
        publication_year=convert(review.publication_year),
        detected_language=convert(review.detected_language),
    )

@app.get(
    "/api/reports/{report_id}",
    response_model=AnalysisReport,
    summary="取得已完成的學術分析報告",
)
async def read_analysis_report(report_id: str):
    """Return a previously saved analysis report without running analysis again."""
    report = load_report(report_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis report not found",
        )

    return report
