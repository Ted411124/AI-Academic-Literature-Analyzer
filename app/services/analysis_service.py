"""Single-process execution guard for synchronous analysis work."""

from threading import Lock
from typing import Callable, Optional, TypeVar

from app.models.schemas import AnalysisRequest, DocumentExtractionData


class AnalysisBusyError(RuntimeError):
    """Raised when another analysis is already running in this process."""


class AnalysisUnavailableError(RuntimeError):
    """Raised while no real analysis executor has been configured."""


class AnalysisDocumentUnavailableError(RuntimeError):
    """Raised when the final preflight finds the document expired or removed."""


class AnalysisReportRejectedError(RuntimeError):
    """Raised when an executor result fails report schema or document validation."""


AnalysisExecutor = Callable[[AnalysisRequest, DocumentExtractionData], object]
T = TypeVar("T")


class AnalysisService:
    """Run one synchronous analysis at a time in this Python process.

    The lock is process-local. It does not coordinate multiple worker processes,
    Render instances, or survive a process restart.
    """

    def __init__(self, executor: Optional[AnalysisExecutor] = None) -> None:
        self.executor = executor
        self._work_lock = Lock()
        self._active_state_lock = Lock()
        self._active_document_ids: set[str] = set()

    def is_document_active(self, document_id: str) -> bool:
        """Return whether this process currently has an analysis using the document."""
        with self._active_state_lock:
            return document_id in self._active_document_ids

    def run_if_document_inactive(
        self, document_id: Optional[str], operation: Callable[[], T]
    ) -> tuple[bool, Optional[T]]:
        """Run one cleanup operation atomically with active-document registration.

        The operation must include the final TTL check and unlink. The state lock
        is intentionally held only for this short per-file operation.
        """
        with self._active_state_lock:
            if document_id is not None and document_id in self._active_document_ids:
                return False, None
            return True, operation()

    def run(
        self,
        request: AnalysisRequest,
        document: DocumentExtractionData,
        *,
        preflight: Optional[Callable[[], bool]] = None,
        accept_result: Optional[Callable[[object], object]] = None,
    ):
        """Run once under the process-local work lock and track its document.

        Lock order is always work lock, then active-state lock. Cleanup takes
        only the active-state lock, so it never creates a reverse lock order.
        """
        executor = self.executor
        if executor is None:
            raise AnalysisUnavailableError("分析服務尚未設定執行器。")

        if not self._work_lock.acquire(blocking=False):
            raise AnalysisBusyError("目前已有分析工作執行中，請稍後再試。")

        registered = False
        try:
            # Recheck file presence/TTL while cleanup is excluded, then register
            # the active document in the same critical section.
            with self._active_state_lock:
                if preflight is not None and not preflight():
                    raise AnalysisDocumentUnavailableError(
                        "文件在分析啟動前已不存在或逾期。"
                    )
                self._active_document_ids.add(request.document_id)
                registered = True

            candidate = executor(request, document)
            # The API supplies the report acceptance callback here so schema
            # validation, document evidence checks, and persistence all finish
            # before this method releases the active-document protection/lock.
            return accept_result(candidate) if accept_result is not None else candidate
        finally:
            try:
                if registered:
                    with self._active_state_lock:
                        self._active_document_ids.discard(request.document_id)
            finally:
                self._work_lock.release()
analysis_service = AnalysisService()
