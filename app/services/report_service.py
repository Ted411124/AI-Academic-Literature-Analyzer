"""Atomic storage for fully validated analysis reports."""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from app import config
from app.models.schemas import AnalysisReport

logger = logging.getLogger(__name__)
_DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class ReportPersistenceError(OSError):
    """Raised when a validated report cannot be atomically persisted."""


def report_path(document_id: str) -> Path:
    if not _DOCUMENT_ID_PATTERN.fullmatch(document_id or ""):
        raise ValueError("無效的文件識別碼")
    return config.TEMP_RESULTS_DIR / f"{document_id}.report.json"


def save_report(report: AnalysisReport) -> Path:
    """Write beside the target and atomically replace only after full serialization."""
    target = report_path(report.document_id)
    temporary = target.with_name(f"{report.document_id}.report.json.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as stream:
            stream.write(report.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        return target
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            logger.exception("清理分析報告暫存檔失敗：%s", temporary)
        raise ReportPersistenceError("分析報告無法保存。") from exc


def load_report(document_id: str) -> Optional[AnalysisReport]:
    """Load a stored report, returning None for missing or invalid data."""
    try:
        path = report_path(document_id)
        if not path.is_file():
            return None
        return AnalysisReport.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("分析報告讀取或驗證失敗：%s", document_id)
        return None
