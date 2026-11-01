"""Small local PDF extraction and JSON round-trip resource baseline."""

import ctypes
import io
import json
import os
import re
import threading
import textwrap
import time
import tracemalloc

import pytest

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from app import config
from app.models.schemas import DocumentExtractionData, PageTextItem
from app.services.pdf_service import PDFService


PAGE_TEXTS = [
    "PAGE_MARKER_001 Synthetic text verifies the first physical page extraction.",
    "PAGE_MARKER_002 Synthetic text verifies the second physical page extraction.",
    "PAGE_MARKER_003 Synthetic text verifies the third physical page extraction.",
]

B02_PAGE_COUNT = 12
B02_TARGET_CHARS_PER_PAGE = 1600
B02_LINE_WIDTH = 88
B03_TARGET_CHARS_PER_PAGE = 700
B04_PAGE_COUNT = 12
B04_TARGET_CHARS_PER_PAGE = 4000
B04_LINE_WIDTH = 72


def create_baseline_pdf(pages_text: list[str]) -> bytes:
    """Build a small in-memory PDF with one distinct text line per page."""
    document = fitz.open()
    try:
        for text in pages_text:
            page = document.new_page()
            page.insert_text((50, 72), text)
        return document.tobytes()
    finally:
        document.close()


def create_b02_medium_pdf() -> tuple[bytes, list[str]]:
    """Build a 12-page PDF with wrapped, page-specific text for B02."""
    document = fitz.open()
    pages_text = []
    try:
        for page_number in range(1, B02_PAGE_COUNT + 1):
            marker = f"B02_PAGE_{page_number:03d}"
            prefix = f"{marker} "
            filler = (
                f"The controlled synthetic research content for physical page {page_number:03d} "
                "records methods observations evidence and findings. "
            )
            raw_text = prefix + (filler * ((B02_TARGET_CHARS_PER_PAGE // len(filler)) + 2))
            raw_text = raw_text[:B02_TARGET_CHARS_PER_PAGE]
            page_text = "\n".join(
                textwrap.wrap(
                    raw_text,
                    width=B02_LINE_WIDTH,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
            pages_text.append(page_text)

            page = document.new_page()
            spare_height = page.insert_textbox(
                fitz.Rect(36, 36, page.rect.width - 36, page.rect.height - 36),
                page_text,
                fontsize=8,
                fontname="helv",
            )
            assert spare_height >= 0, f"B02 page {page_number} text did not fit"

        return document.tobytes(), pages_text
    finally:
        document.close()


def create_b03_limit_pdf(page_count: int) -> tuple[bytes, list[str]]:
    """Build an in-memory PDF at the requested page count with bounded text per page."""
    document = fitz.open()
    pages_text = []
    try:
        for page_number in range(1, page_count + 1):
            marker = f"B03_PAGE_{page_number:03d}"
            filler = (
                f"The synthetic resource baseline content for physical page {page_number:03d} "
                "records controlled observations and document evidence. "
            )
            raw_text = (marker + " " + filler * 20)[:B03_TARGET_CHARS_PER_PAGE]
            page_text = "\n".join(
                textwrap.wrap(
                    raw_text,
                    width=B02_LINE_WIDTH,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
            pages_text.append(page_text)

            page = document.new_page()
            spare_height = page.insert_textbox(
                fitz.Rect(36, 36, page.rect.width - 36, page.rect.height - 36),
                page_text,
                fontsize=8,
                fontname="helv",
            )
            assert spare_height >= 0, f"B03 page {page_number} text did not fit"

        return document.tobytes(), pages_text
    finally:
        document.close()


def create_b04_dense_pdf() -> tuple[bytes, list[str]]:
    """Build a 12-page, high-text-density PDF while preserving exact source text."""
    document = fitz.open()
    pages_text = []
    try:
        for page_number in range(1, B04_PAGE_COUNT + 1):
            marker = f"B04_PAGE_{page_number:03d}"
            filler = (
                f"The synthetic high-density research content for physical page {page_number:03d} "
                "records controlled observations methods evidence and findings. "
            )
            source_text = (marker + " " + filler * 100)[:B04_TARGET_CHARS_PER_PAGE]
            assert len(source_text) == B04_TARGET_CHARS_PER_PAGE
            layout_text = "\n".join(
                textwrap.wrap(
                    source_text,
                    width=B04_LINE_WIDTH,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
            pages_text.append(source_text)

            page = document.new_page()
            spare_height = page.insert_textbox(
                fitz.Rect(24, 24, page.rect.width - 24, page.rect.height - 24),
                layout_text,
                fontsize=7,
                fontname="helv",
            )
            assert spare_height >= 0, f"B04 page {page_number} text did not fit completely"

        return document.tobytes(), pages_text
    finally:
        document.close()


def create_b05_two_column_pdf() -> tuple[bytes, list[str]]:
    """Build one page with overlapping left/right column paragraph blocks."""
    document = fitz.open()
    try:
        page = document.new_page()
        expected_paragraphs = []
        paragraph_positions = (72, 222, 372)
        columns = (("LEFT", 36, 275), ("RIGHT", 320, 559))

        for column_name, left_x, right_x in columns:
            for paragraph_number, top in enumerate(paragraph_positions, start=1):
                marker = f"B05_COL_{column_name}_P{paragraph_number:02d}"
                paragraph = f"{marker} distinct paragraph evidence block {paragraph_number}."
                expected_paragraphs.append(paragraph)
                rect = fitz.Rect(left_x, top, right_x, top + 110)
                spare_height = page.insert_textbox(
                    rect,
                    paragraph,
                    fontsize=8,
                    fontname="helv",
                )
                assert spare_height >= 0, f"B05 {marker} text did not fit completely"

        return document.tobytes(), expected_paragraphs
    finally:
        document.close()


def create_b05_table_pdf() -> tuple[bytes, list[list[str]]]:
    """Build one page with a ruled three-column table and unique cell markers."""
    document = fitz.open()
    try:
        page = document.new_page()
        x_edges = (36, 210, 384, 558)
        y_edges = (72, 128, 184, 240, 296)
        expected_rows = [
            [f"B05_TBL_H_C{column:02d}" for column in range(1, 4)],
            *[
                [f"B05_TBL_R{row:02d}_C{column:02d}" for column in range(1, 4)]
                for row in range(1, 4)
            ],
        ]

        for x in x_edges:
            page.draw_line((x, y_edges[0]), (x, y_edges[-1]), color=(0, 0, 0), width=0.7)
        for y in y_edges:
            page.draw_line((x_edges[0], y), (x_edges[-1], y), color=(0, 0, 0), width=0.7)

        for row_index, row_markers in enumerate(expected_rows):
            for column_index, marker in enumerate(row_markers):
                cell = fitz.Rect(
                    x_edges[column_index] + 6,
                    y_edges[row_index] + 6,
                    x_edges[column_index + 1] - 6,
                    y_edges[row_index + 1] - 6,
                )
                spare_height = page.insert_textbox(
                    cell,
                    marker,
                    fontsize=9,
                    fontname="helv",
                )
                assert spare_height >= 0, f"B05 table cell {marker} text did not fit completely"

        return document.tobytes(), expected_rows
    finally:
        document.close()


def extract_b05_pdf_round_trip(pdf_bytes: bytes, filename: str):
    """Upload, extract, and read a B05 PDF using the isolated storage fixture paths."""
    document_id, pdf_path, _ = PDFService.save_upload_stream(io.BytesIO(pdf_bytes), filename)
    extracted_data = PDFService.extract_document(
        pdf_path=pdf_path,
        document_id=document_id,
        original_filename=filename,
    )
    json_path = config.TEMP_RESULTS_DIR / f"{document_id}.json"
    assert json_path.is_file()
    loaded_data = PDFService.get_document_data(document_id)
    assert loaded_data is not None
    return extracted_data, loaded_data


class B05ReadingOrderMismatch(AssertionError):
    """Expected xfail used only for a two-column reading-order mismatch."""


def _ordered_markers(text: str, markers: list[str]) -> list[str]:
    """Return markers in their appearance order in the extracted text."""
    normalized = normalize_pdf_text(text)
    assert len(set(markers)) == len(markers), "Expected marker list contains duplicates"
    positions = {marker: normalized.find(marker) for marker in markers}
    assert all(position >= 0 for position in positions.values()), (
        f"Expected marker(s) missing from extracted text: "
        f"{[marker for marker, position in positions.items() if position < 0]}"
    )
    assert all(normalized.count(marker) == 1 for marker in markers), (
        f"Expected each marker exactly once; counts: "
        f"{ {marker: normalized.count(marker) for marker in markers} }"
    )
    return sorted(markers, key=positions.__getitem__)


def _measure_phase(operation):
    """Return result, elapsed seconds, and Python allocation peak above phase entry."""
    current_before, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    started_at = time.perf_counter()
    result = operation()
    elapsed_seconds = time.perf_counter() - started_at
    _, peak_bytes = tracemalloc.get_traced_memory()
    peak_above_entry_bytes = max(0, peak_bytes - current_before)
    return result, elapsed_seconds, peak_above_entry_bytes


def _read_process_rss_bytes() -> int:
    """Return this Windows process's current working-set size in bytes."""
    if os.name != "nt":
        raise NotImplementedError("B07 RSS observation currently supports Windows only")

    get_process_memory_info = getattr(_read_process_rss_bytes, "_api", None)
    counters_type = getattr(_read_process_rss_bytes, "_counters_type", None)
    process_handle = getattr(_read_process_rss_bytes, "_process_handle", None)
    if get_process_memory_info is None:
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        api = psapi.GetProcessMemoryInfo
        api.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        api.restype = wintypes.BOOL

        _read_process_rss_bytes._api = api
        _read_process_rss_bytes._counters_type = ProcessMemoryCounters
        _read_process_rss_bytes._process_handle = kernel32.GetCurrentProcess()
        get_process_memory_info = api
        counters_type = ProcessMemoryCounters
        process_handle = _read_process_rss_bytes._process_handle

    counters = counters_type()
    counters.cb = ctypes.sizeof(counters)
    if not get_process_memory_info(
        process_handle,
        ctypes.byref(counters),
        counters.cb,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.WorkingSetSize)


def _measure_phase_with_memory(operation, sample_interval_seconds: float = 0.01):
    """Measure a phase with tracemalloc and sampled RSS, including boundary samples."""
    stop_sampling = threading.Event()
    sampler_ready = threading.Event()
    sampler_errors = []
    sampled_peak = [0]
    sample_lock = threading.Lock()

    def record_sample(rss_bytes: int):
        with sample_lock:
            sampled_peak[0] = max(sampled_peak[0], rss_bytes)

    def sample_rss():
        try:
            record_sample(_read_process_rss_bytes())
            sampler_ready.set()
            while not stop_sampling.wait(sample_interval_seconds):
                record_sample(_read_process_rss_bytes())
        except BaseException as exc:
            sampler_errors.append(exc)
            sampler_ready.set()
            stop_sampling.set()

    sampler = threading.Thread(target=sample_rss, name="b07-rss-sampler", daemon=True)
    sampler.start()
    result = None
    measurement = None
    operation_error = None
    rss_after = None
    try:
        sampler_ready.wait()
        if sampler_errors:
            raise RuntimeError("B07 RSS sampling failed") from sampler_errors[0]

        # Take the phase-entry RSS with the sampler already running, then include
        # this exact boundary sample in the observed range.
        rss_before = _read_process_rss_bytes()
        record_sample(rss_before)
        measurement = _measure_phase(operation)
        result = measurement[0]
    except BaseException as exc:
        operation_error = exc
    finally:
        try:
            rss_after = _read_process_rss_bytes()
            record_sample(rss_after)
        except BaseException as exc:
            sampler_errors.append(exc)
        finally:
            stop_sampling.set()
            sampler.join()

    if sampler_errors:
        raise RuntimeError("B07 RSS sampling failed") from sampler_errors[0]
    if operation_error is not None:
        raise operation_error

    _, elapsed_seconds, tracemalloc_peak_increment_bytes = measurement
    return (
        result,
        elapsed_seconds,
        tracemalloc_peak_increment_bytes,
        rss_before,
        sampled_peak[0],
        rss_after,
    )


def normalize_pdf_text(text: str) -> str:
    """Normalize whitespace only for exact synthetic-text comparisons."""
    return re.sub(r"\s+", " ", text).strip()


def test_small_pdf_extraction_resource_baseline(isolated_storage):
    """Check a three-page PDF round-trip and print measurements without thresholds."""
    pdf_bytes = create_baseline_pdf(PAGE_TEXTS)
    measurements = {}
    tracemalloc.start()
    try:
        (document_id, pdf_path, _), upload_seconds, upload_peak_bytes = _measure_phase(
            lambda: PDFService.save_upload_stream(io.BytesIO(pdf_bytes), "b01_small.pdf")
        )
        measurements["upload_storage_seconds"] = upload_seconds
        measurements["upload_python_peak_above_phase_entry_bytes"] = upload_peak_bytes

        saved_pdf_size_bytes = pdf_path.stat().st_size
        assert saved_pdf_size_bytes == len(pdf_bytes)

        extraction_data, extraction_and_json_save_seconds, extraction_peak_bytes = _measure_phase(
            lambda: PDFService.extract_document(
                pdf_path=pdf_path,
                document_id=document_id,
                original_filename="b01_small.pdf",
            )
        )
        measurements["pdf_extraction_and_json_save_seconds"] = extraction_and_json_save_seconds
        measurements["extraction_and_json_save_python_peak_above_phase_entry_bytes"] = (
            extraction_peak_bytes
        )

        json_path = config.TEMP_RESULTS_DIR / f"{document_id}.json"
        assert json_path.is_file()
        json_size_bytes = json_path.stat().st_size

        loaded_data, json_read_seconds, json_read_peak_bytes = _measure_phase(
            lambda: PDFService.get_document_data(document_id)
        )
        measurements["json_read_decode_and_model_validation_seconds"] = json_read_seconds
        measurements["json_read_python_peak_above_phase_entry_bytes"] = json_read_peak_bytes

        assert extraction_data.total_pages == 3
        assert [page.physical_page for page in extraction_data.pages] == [1, 2, 3]
        assert [page.text for page in extraction_data.pages] == PAGE_TEXTS
        assert loaded_data is not None
        assert loaded_data == extraction_data

        measurements["page_count"] = extraction_data.total_pages
        measurements["pdf_size_bytes"] = saved_pdf_size_bytes
        measurements["json_size_bytes"] = json_size_bytes
        measurements["overall_measured_seconds"] = (
            measurements["upload_storage_seconds"]
            + measurements["pdf_extraction_and_json_save_seconds"]
            + measurements["json_read_decode_and_model_validation_seconds"]
        )
        measurements["memory_measurement"] = (
            "tracemalloc Python allocation peak above each phase's entry baseline; "
            "does not include all PyMuPDF native memory or total process RSS"
        )
        measurements["timing_scope"] = {
            "upload_storage_seconds": "save_upload_stream, including validation and file write",
            "pdf_extraction_and_json_save_seconds": (
                "extract_document, including PDF open, text extraction, model creation, "
                "JSON serialization, write, and atomic replace"
            ),
            "json_read_decode_and_model_validation_seconds": (
                "get_document_data, including file read, JSON decode, and Pydantic validation"
            ),
        }
        print("B01_METRICS=" + json.dumps(measurements, ensure_ascii=False, sort_keys=True))
    finally:
        tracemalloc.stop()


def test_medium_pdf_extraction_resource_baseline(isolated_storage):
    """Check a 12-page PDF round-trip and print measurements without thresholds."""
    pdf_bytes, expected_pages_text = create_b02_medium_pdf()
    measurements = {}
    tracemalloc.start()
    try:
        (document_id, pdf_path, _), upload_seconds, upload_peak_bytes = _measure_phase(
            lambda: PDFService.save_upload_stream(io.BytesIO(pdf_bytes), "b02_medium.pdf")
        )
        measurements["upload_storage_seconds"] = upload_seconds
        measurements["upload_python_peak_above_phase_entry_bytes"] = upload_peak_bytes

        saved_pdf_size_bytes = pdf_path.stat().st_size
        assert saved_pdf_size_bytes == len(pdf_bytes)

        extraction_data, extraction_and_json_save_seconds, extraction_peak_bytes = _measure_phase(
            lambda: PDFService.extract_document(
                pdf_path=pdf_path,
                document_id=document_id,
                original_filename="b02_medium.pdf",
            )
        )
        measurements["pdf_extraction_and_json_save_seconds"] = extraction_and_json_save_seconds
        measurements["extraction_and_json_save_python_peak_above_phase_entry_bytes"] = (
            extraction_peak_bytes
        )

        json_path = config.TEMP_RESULTS_DIR / f"{document_id}.json"
        assert json_path.is_file()
        json_size_bytes = json_path.stat().st_size

        loaded_data, json_read_seconds, json_read_peak_bytes = _measure_phase(
            lambda: PDFService.get_document_data(document_id)
        )
        measurements["json_read_decode_and_model_validation_seconds"] = json_read_seconds
        measurements["json_read_python_peak_above_phase_entry_bytes"] = json_read_peak_bytes

        expected_page_numbers = list(range(1, B02_PAGE_COUNT + 1))
        expected_markers = [f"B02_PAGE_{page_number:03d}" for page_number in expected_page_numbers]
        assert len(expected_pages_text) == B02_PAGE_COUNT
        assert all(1500 <= len(text) <= 2000 for text in expected_pages_text)
        assert sum(map(len, expected_pages_text)) in range(18000, 24001)
        assert extraction_data.total_pages == B02_PAGE_COUNT
        assert [page.physical_page for page in extraction_data.pages] == expected_page_numbers
        extracted_pages_text = [page.text for page in extraction_data.pages]
        assert [normalize_pdf_text(text) for text in extracted_pages_text] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]
        assert [text.splitlines()[0].split()[0] for text in extracted_pages_text] == expected_markers
        assert len({page.physical_page for page in extraction_data.pages}) == B02_PAGE_COUNT
        assert loaded_data is not None
        assert loaded_data == extraction_data
        assert [normalize_pdf_text(page.text) for page in loaded_data.pages] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]

        measurements["page_count"] = extraction_data.total_pages
        measurements["characters_per_page"] = [len(text) for text in expected_pages_text]
        measurements["total_source_characters"] = sum(map(len, expected_pages_text))
        measurements["pdf_size_bytes"] = saved_pdf_size_bytes
        measurements["json_size_bytes"] = json_size_bytes
        measurements["overall_measured_seconds"] = (
            measurements["upload_storage_seconds"]
            + measurements["pdf_extraction_and_json_save_seconds"]
            + measurements["json_read_decode_and_model_validation_seconds"]
        )
        measurements["memory_measurement"] = (
            "tracemalloc Python allocation peak above each phase's entry baseline; "
            "does not include all PyMuPDF native memory or total process RSS"
        )
        measurements["timing_scope"] = {
            "upload_storage_seconds": "save_upload_stream, including validation and file write",
            "pdf_extraction_and_json_save_seconds": (
                "extract_document, including PDF open, text extraction, model creation, "
                "JSON serialization, write, and atomic replace"
            ),
            "json_read_decode_and_model_validation_seconds": (
                "get_document_data, including file read, JSON decode, and Pydantic validation"
            ),
        }
        print("B02_METRICS=" + json.dumps(measurements, ensure_ascii=False, sort_keys=True))
    finally:
        tracemalloc.stop()


def test_max_page_pdf_extraction_resource_baseline(isolated_storage):
    """Measure extraction and JSON round-trip at the runtime-configured page limit."""
    page_count = config.MAX_PAGES
    assert page_count >= 1, (
        "config.MAX_PAGES must be at least 1; refusing to reduce the configured page count"
    )
    pdf_bytes, expected_pages_text = create_b03_limit_pdf(page_count)
    measurements = {}
    tracemalloc.start()
    try:
        (document_id, pdf_path, _), upload_seconds, upload_peak_bytes = _measure_phase(
            lambda: PDFService.save_upload_stream(io.BytesIO(pdf_bytes), "b03_page_limit.pdf")
        )
        measurements["upload_storage_seconds"] = upload_seconds
        measurements["upload_python_peak_above_phase_entry_bytes"] = upload_peak_bytes

        saved_pdf_size_bytes = pdf_path.stat().st_size
        assert saved_pdf_size_bytes == len(pdf_bytes)

        extraction_data, extraction_and_json_save_seconds, extraction_peak_bytes = _measure_phase(
            lambda: PDFService.extract_document(
                pdf_path=pdf_path,
                document_id=document_id,
                original_filename="b03_page_limit.pdf",
            )
        )
        measurements["pdf_extraction_and_json_save_seconds"] = extraction_and_json_save_seconds
        measurements["extraction_and_json_save_python_peak_above_phase_entry_bytes"] = (
            extraction_peak_bytes
        )

        json_path = config.TEMP_RESULTS_DIR / f"{document_id}.json"
        assert json_path.is_file()
        json_size_bytes = json_path.stat().st_size

        loaded_data, json_read_seconds, json_read_peak_bytes = _measure_phase(
            lambda: PDFService.get_document_data(document_id)
        )
        measurements["json_read_decode_and_model_validation_seconds"] = json_read_seconds
        measurements["json_read_python_peak_above_phase_entry_bytes"] = json_read_peak_bytes

        expected_page_numbers = list(range(1, page_count + 1))
        expected_markers = [f"B03_PAGE_{number:03d}" for number in expected_page_numbers]
        assert extraction_data.total_pages == page_count == config.MAX_PAGES
        assert len(expected_pages_text) == page_count
        assert all(600 <= len(text) <= 800 for text in expected_pages_text)

        extracted_page_numbers = [page.physical_page for page in extraction_data.pages]
        extracted_pages_text = [page.text for page in extraction_data.pages]
        assert extracted_page_numbers == expected_page_numbers
        assert len(set(extracted_page_numbers)) == page_count
        assert [text.splitlines()[0].split()[0] for text in extracted_pages_text] == expected_markers
        assert [normalize_pdf_text(text) for text in extracted_pages_text] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]

        assert loaded_data is not None
        assert loaded_data.total_pages == page_count
        assert [page.physical_page for page in loaded_data.pages] == expected_page_numbers
        assert len({page.physical_page for page in loaded_data.pages}) == page_count
        assert loaded_data == extraction_data
        assert [normalize_pdf_text(page.text) for page in loaded_data.pages] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]

        total_source_characters = sum(map(len, expected_pages_text))
        measurements["page_count"] = extraction_data.total_pages
        measurements["configured_max_pages"] = config.MAX_PAGES
        measurements["characters_per_page_min"] = min(map(len, expected_pages_text))
        measurements["characters_per_page_max"] = max(map(len, expected_pages_text))
        measurements["total_source_characters"] = total_source_characters
        measurements["pdf_size_bytes"] = saved_pdf_size_bytes
        measurements["json_size_bytes"] = json_size_bytes
        measurements["overall_measured_seconds"] = (
            measurements["upload_storage_seconds"]
            + measurements["pdf_extraction_and_json_save_seconds"]
            + measurements["json_read_decode_and_model_validation_seconds"]
        )
        measurements["memory_measurement"] = (
            "tracemalloc Python allocation peak above each phase's entry baseline; "
            "does not include all PyMuPDF native memory or total process RSS"
        )
        measurements["timing_scope"] = {
            "upload_storage_seconds": "save_upload_stream, including validation and file write",
            "pdf_extraction_and_json_save_seconds": (
                "extract_document, including PDF open, text extraction, model creation, "
                "JSON serialization, write, and atomic replace"
            ),
            "json_read_decode_and_model_validation_seconds": (
                "get_document_data, including file read, JSON decode, and Pydantic validation"
            ),
        }
        print("B03_METRICS=" + json.dumps(measurements, ensure_ascii=False, sort_keys=True))
    finally:
        tracemalloc.stop()


def test_high_text_density_pdf_resource_baseline(isolated_storage):
    """Measure high-density PDF extraction and JSON round-trip without thresholds."""
    pdf_bytes, expected_pages_text = create_b04_dense_pdf()
    assert len(pdf_bytes) <= config.MAX_FILE_SIZE_BYTES, (
        f"B04 PDF is {len(pdf_bytes)} bytes, exceeding the configured upload limit "
        f"of {config.MAX_FILE_SIZE_BYTES} bytes"
    )

    measurements = {}
    tracemalloc.start()
    try:
        (document_id, pdf_path, _), upload_seconds, upload_peak_bytes = _measure_phase(
            lambda: PDFService.save_upload_stream(io.BytesIO(pdf_bytes), "b04_high_density.pdf")
        )
        measurements["upload_storage_seconds"] = upload_seconds
        measurements["upload_python_peak_above_phase_entry_bytes"] = upload_peak_bytes

        saved_pdf_size_bytes = pdf_path.stat().st_size
        assert saved_pdf_size_bytes == len(pdf_bytes)
        assert saved_pdf_size_bytes <= config.MAX_FILE_SIZE_BYTES

        extraction_data, extraction_and_json_save_seconds, extraction_peak_bytes = _measure_phase(
            lambda: PDFService.extract_document(
                pdf_path=pdf_path,
                document_id=document_id,
                original_filename="b04_high_density.pdf",
            )
        )
        measurements["pdf_extraction_and_json_save_seconds"] = extraction_and_json_save_seconds
        measurements["extraction_and_json_save_python_peak_above_phase_entry_bytes"] = (
            extraction_peak_bytes
        )

        json_path = config.TEMP_RESULTS_DIR / f"{document_id}.json"
        assert json_path.is_file()
        json_size_bytes = json_path.stat().st_size

        loaded_data, json_read_seconds, json_read_peak_bytes = _measure_phase(
            lambda: PDFService.get_document_data(document_id)
        )
        measurements["json_read_decode_and_model_validation_seconds"] = json_read_seconds
        measurements["json_read_python_peak_above_phase_entry_bytes"] = json_read_peak_bytes

        expected_page_numbers = list(range(1, B04_PAGE_COUNT + 1))
        expected_markers = [f"B04_PAGE_{number:03d}" for number in expected_page_numbers]
        assert len(expected_pages_text) == B04_PAGE_COUNT
        assert all(len(text) == B04_TARGET_CHARS_PER_PAGE for text in expected_pages_text)
        assert sum(map(len, expected_pages_text)) == 48000
        assert extraction_data.total_pages == B04_PAGE_COUNT

        extracted_page_numbers = [page.physical_page for page in extraction_data.pages]
        extracted_pages_text = [page.text for page in extraction_data.pages]
        assert extracted_page_numbers == expected_page_numbers
        assert len(set(extracted_page_numbers)) == B04_PAGE_COUNT
        assert [normalize_pdf_text(text).split()[0] for text in extracted_pages_text] == (
            expected_markers
        )
        assert [normalize_pdf_text(text) for text in extracted_pages_text] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]

        assert loaded_data is not None
        assert loaded_data.total_pages == B04_PAGE_COUNT
        assert [page.physical_page for page in loaded_data.pages] == expected_page_numbers
        assert len({page.physical_page for page in loaded_data.pages}) == B04_PAGE_COUNT
        assert loaded_data == extraction_data
        assert [normalize_pdf_text(page.text) for page in loaded_data.pages] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]

        measurements["page_count"] = extraction_data.total_pages
        measurements["characters_per_page_min"] = min(map(len, expected_pages_text))
        measurements["characters_per_page_max"] = max(map(len, expected_pages_text))
        measurements["total_source_characters"] = sum(map(len, expected_pages_text))
        measurements["pdf_size_bytes"] = saved_pdf_size_bytes
        measurements["json_size_bytes"] = json_size_bytes
        measurements["overall_measured_seconds"] = (
            measurements["upload_storage_seconds"]
            + measurements["pdf_extraction_and_json_save_seconds"]
            + measurements["json_read_decode_and_model_validation_seconds"]
        )
        measurements["memory_measurement"] = (
            "tracemalloc Python allocation peak above each phase's entry baseline; "
            "does not include all PyMuPDF native memory or total process RSS"
        )
        measurements["timing_scope"] = {
            "upload_storage_seconds": "save_upload_stream, including validation and file write",
            "pdf_extraction_and_json_save_seconds": (
                "extract_document, including PDF open, text extraction, model creation, "
                "JSON serialization, write, and atomic replace"
            ),
            "json_read_decode_and_model_validation_seconds": (
                "get_document_data, including file read, JSON decode, and Pydantic validation"
            ),
            "pdf_generation": (
                "create_b04_dense_pdf() PDF generation time is not included in any measured phase"
            ),
            "overall_measured_seconds": (
                "sum of upload/storage, PDF extraction/JSON save, and JSON read/decode/model "
                "validation only; it is not the full elapsed time from PDF generation to test end"
            ),
        }
        print("B04_METRICS=" + json.dumps(measurements, ensure_ascii=False, sort_keys=True))
    finally:
        tracemalloc.stop()


def test_b05_two_column_content_and_json_round_trip(isolated_storage):
    """Verify all two-column paragraphs are extracted once and survive JSON round-trip."""
    pdf_bytes, expected_paragraphs = create_b05_two_column_pdf()
    extracted_data, loaded_data = extract_b05_pdf_round_trip(
        pdf_bytes,
        "b05_two_column.pdf",
    )

    assert extracted_data.total_pages == 1
    assert [page.physical_page for page in extracted_data.pages] == [1]
    extracted_text = extracted_data.pages[0].text
    normalized_extracted = normalize_pdf_text(extracted_text)
    expected_markers = [paragraph.split()[0] for paragraph in expected_paragraphs]

    assert all(normalized_extracted.count(marker) == 1 for marker in expected_markers)
    assert all(
        normalized_extracted.count(normalize_pdf_text(paragraph)) == 1
        for paragraph in expected_paragraphs
    )
    assert loaded_data == extracted_data
    assert loaded_data.total_pages == 1
    assert [page.physical_page for page in loaded_data.pages] == [1]
    assert normalize_pdf_text(loaded_data.pages[0].text) == normalized_extracted


@pytest.mark.xfail(
    strict=False,
    raises=B05ReadingOrderMismatch,
    reason=(
        "PyMuPDF sort=True sorts by page coordinates and does not guarantee semantic "
        "column-major reading order"
    ),
)
def test_b05_two_column_reading_order_diagnostic(isolated_storage):
    """Xfail only when complete, validated content is returned in the wrong order."""
    pdf_bytes, expected_paragraphs = create_b05_two_column_pdf()
    extracted_data, loaded_data = extract_b05_pdf_round_trip(
        pdf_bytes,
        "b05_two_column_order.pdf",
    )
    expected_markers = [paragraph.split()[0] for paragraph in expected_paragraphs]

    # Keep setup, content, page, and JSON errors as ordinary failures. The custom
    # exception below is the only exception type recognized by this xfail marker.
    assert extracted_data.total_pages == 1
    assert [page.physical_page for page in extracted_data.pages] == [1]
    normalized_extracted = normalize_pdf_text(extracted_data.pages[0].text)
    assert all(normalized_extracted.count(marker) == 1 for marker in expected_markers)
    assert all(
        normalized_extracted.count(normalize_pdf_text(paragraph)) == 1
        for paragraph in expected_paragraphs
    )
    assert loaded_data == extracted_data
    assert loaded_data.total_pages == 1
    assert [page.physical_page for page in loaded_data.pages] == [1]
    assert normalize_pdf_text(loaded_data.pages[0].text) == normalized_extracted

    observed_markers = _ordered_markers(extracted_data.pages[0].text, expected_markers)
    if observed_markers != expected_markers:
        raise B05ReadingOrderMismatch(
            f"Expected complete left-column then right-column order; got {observed_markers}"
        )


def test_b05_table_content_and_json_round_trip(isolated_storage):
    """Verify each table cell marker is extracted once and preserved in JSON."""
    pdf_bytes, expected_rows = create_b05_table_pdf()
    extracted_data, loaded_data = extract_b05_pdf_round_trip(pdf_bytes, "b05_table.pdf")

    expected_markers = [marker for row in expected_rows for marker in row]
    assert extracted_data.total_pages == 1
    assert [page.physical_page for page in extracted_data.pages] == [1]
    normalized_extracted = normalize_pdf_text(extracted_data.pages[0].text)
    assert all(normalized_extracted.count(marker) == 1 for marker in expected_markers)

    assert loaded_data == extracted_data
    assert loaded_data.total_pages == 1
    assert [page.physical_page for page in loaded_data.pages] == [1]
    normalized_loaded = normalize_pdf_text(loaded_data.pages[0].text)
    assert normalized_loaded == normalized_extracted
    assert all(normalized_loaded.count(marker) == 1 for marker in expected_markers)


def test_b05_table_reading_order_diagnostic(isolated_storage):
    """Diagnose whether table cell text is extracted in row-major order."""
    pdf_bytes, expected_rows = create_b05_table_pdf()
    extracted_data, loaded_data = extract_b05_pdf_round_trip(pdf_bytes, "b05_table_order.pdf")
    expected_markers = [marker for row in expected_rows for marker in row]
    observed_markers = _ordered_markers(extracted_data.pages[0].text, expected_markers)

    assert observed_markers == expected_markers, (
        f"Expected table row-major order; got {observed_markers}"
    )
    assert loaded_data == extracted_data


def create_b06_unicode_document(document_id: str = "b06_unicode_round_trip"):
    """Build valid extraction data with Unicode and whitespace boundary cases."""
    page_texts = [
        "繁體中文：研究摘要。簡体中文：研究结果。 English phrase; mixed 中英語。",
        "日本語の本文です。句読点、全角！半角!? を含みます。",
        "混合語言：中文 / 日本語 / English；數字 0123456789；符號 © ™ § → ✓",
        "",
        "前置空格  連續空格\tTab\n單一換行\n\n連續換行與尾端空白  ",
    ]
    pages = [
        PageTextItem(
            physical_page=page_number,
            text=text,
            char_count=len(text),
        )
        for page_number, text in enumerate(page_texts, start=1)
    ]
    return DocumentExtractionData(
        document_id=document_id,
        original_filename="多語言・論文 (測試).pdf",
        total_pages=len(pages),
        total_characters=sum(page.char_count for page in pages),
        pages=pages,
        created_at="2026-10-31T12:00:00+08:00",
    )


def test_b06_document_json_serialization_and_read_round_trip(isolated_storage):
    """Verify exact model, Unicode text, and field preservation through JSON storage."""
    _, results_dir = isolated_storage
    original = create_b06_unicode_document()
    json_path = results_dir / f"{original.document_id}.json"

    serialization_started = time.perf_counter()
    serialized_json = original.model_dump_json(indent=2)
    serialization_seconds = time.perf_counter() - serialization_started

    write_started = time.perf_counter()
    json_path.write_text(serialized_json, encoding="utf-8")
    write_seconds = time.perf_counter() - write_started

    read_started = time.perf_counter()
    restored = PDFService.get_document_data(original.document_id)
    read_seconds = time.perf_counter() - read_started

    assert restored is not None
    assert restored == original
    assert restored.document_id == original.document_id
    assert restored.original_filename == original.original_filename
    assert restored.total_pages == original.total_pages
    assert restored.total_characters == original.total_characters
    assert restored.created_at == original.created_at
    assert [page.physical_page for page in restored.pages] == [
        page.physical_page for page in original.pages
    ]
    assert [page.text for page in restored.pages] == [page.text for page in original.pages]
    assert [page.char_count for page in restored.pages] == [
        page.char_count for page in original.pages
    ]
    assert restored.pages[3].text == ""

    print(
        "B06_METRICS="
        + json.dumps(
            {
                "json_size_bytes": json_path.stat().st_size,
                "serialization_seconds": serialization_seconds,
                "file_write_seconds": write_seconds,
                "read_decode_and_model_validation_seconds": read_seconds,
                "page_count": restored.total_pages,
                "total_characters": restored.total_characters,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(None, id="missing-file"),
        pytest.param("{invalid-json", id="malformed-json"),
        pytest.param('{"document_id":"b06_missing_document"}', id="schema-invalid-json"),
    ],
)
def test_b06_document_json_read_errors_return_none(isolated_storage, payload):
    """Confirm missing, malformed, and schema-invalid sidecars return None."""
    _, results_dir = isolated_storage
    document_id = "b06_missing_document"
    json_path = results_dir / f"{document_id}.json"
    if payload is not None:
        json_path.write_text(payload, encoding="utf-8")

    assert PDFService.get_document_data(document_id) is None


def test_pdf_processing_memory_observation(isolated_storage):
    """Observe Python allocations and sampled RSS across the three PDF stages."""
    if os.name != "nt":
        pytest.skip("B07 RSS observation currently supports Windows only")

    pdf_bytes, expected_pages_text = create_b02_medium_pdf()
    assert len(expected_pages_text) == 12
    assert all(len(text) == B02_TARGET_CHARS_PER_PAGE for text in expected_pages_text)
    assert sum(map(len, expected_pages_text)) == 19200

    stage_metrics = {}
    sample_interval_seconds = 0.01
    tracemalloc.start()
    try:
        (
            (document_id, pdf_path, _),
            elapsed_seconds,
            tracemalloc_peak_increment_bytes,
            rss_before_bytes,
            sampled_peak_rss_bytes,
            rss_after_bytes,
        ) = _measure_phase_with_memory(
            lambda: PDFService.save_upload_stream(
                io.BytesIO(pdf_bytes),
                "b07_memory_observation.pdf",
            ),
            sample_interval_seconds,
        )
        stage_metrics["upload_and_storage"] = {
            "elapsed_seconds": elapsed_seconds,
            "tracemalloc_peak_increment_bytes": tracemalloc_peak_increment_bytes,
            "rss_before_bytes": rss_before_bytes,
            "sampled_peak_rss_bytes": sampled_peak_rss_bytes,
            "rss_after_bytes": rss_after_bytes,
        }

        (
            extracted_data,
            elapsed_seconds,
            tracemalloc_peak_increment_bytes,
            rss_before_bytes,
            sampled_peak_rss_bytes,
            rss_after_bytes,
        ) = _measure_phase_with_memory(
            lambda: PDFService.extract_document(
                pdf_path=pdf_path,
                document_id=document_id,
                original_filename="b07_memory_observation.pdf",
            ),
            sample_interval_seconds,
        )
        stage_metrics["pdf_extraction_and_json_save"] = {
            "elapsed_seconds": elapsed_seconds,
            "tracemalloc_peak_increment_bytes": tracemalloc_peak_increment_bytes,
            "rss_before_bytes": rss_before_bytes,
            "sampled_peak_rss_bytes": sampled_peak_rss_bytes,
            "rss_after_bytes": rss_after_bytes,
        }

        (
            loaded_data,
            elapsed_seconds,
            tracemalloc_peak_increment_bytes,
            rss_before_bytes,
            sampled_peak_rss_bytes,
            rss_after_bytes,
        ) = _measure_phase_with_memory(
            lambda: PDFService.get_document_data(document_id),
            sample_interval_seconds,
        )
        stage_metrics["json_read_decode_and_model_validation"] = {
            "elapsed_seconds": elapsed_seconds,
            "tracemalloc_peak_increment_bytes": tracemalloc_peak_increment_bytes,
            "rss_before_bytes": rss_before_bytes,
            "sampled_peak_rss_bytes": sampled_peak_rss_bytes,
            "rss_after_bytes": rss_after_bytes,
        }

        assert extracted_data.total_pages == 12
        assert [page.physical_page for page in extracted_data.pages] == list(range(1, 13))
        assert [normalize_pdf_text(page.text) for page in extracted_data.pages] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]
        assert loaded_data is not None
        assert loaded_data == extracted_data
        assert [page.physical_page for page in loaded_data.pages] == list(range(1, 13))
        assert [normalize_pdf_text(page.text) for page in loaded_data.pages] == [
            normalize_pdf_text(text) for text in expected_pages_text
        ]

        for stage in stage_metrics.values():
            assert isinstance(stage["elapsed_seconds"], (int, float))
            assert stage["elapsed_seconds"] >= 0
            for key in (
                "tracemalloc_peak_increment_bytes",
                "rss_before_bytes",
                "sampled_peak_rss_bytes",
                "rss_after_bytes",
            ):
                assert isinstance(stage[key], int)
                assert stage[key] >= 0
            assert stage["sampled_peak_rss_bytes"] >= max(
                stage["rss_before_bytes"], stage["rss_after_bytes"]
            )

        print(
            "B07_MEMORY_METRICS="
            + json.dumps(
                {
                    "page_count": extracted_data.total_pages,
                    "characters_per_page": B02_TARGET_CHARS_PER_PAGE,
                    "total_characters": sum(map(len, expected_pages_text)),
                    "sample_interval_seconds": sample_interval_seconds,
                    "stage_metrics": stage_metrics,
                    "rss_metric": (
                        "WorkingSetSize in bytes; sampled_peak_rss_bytes is the highest "
                        "polling sample plus exact stage-boundary readings, not an absolute peak"
                    ),
                    "tracemalloc_metric": (
                        "Python allocation peak increment; not total process RSS and may include "
                        "small observer-thread allocations"
                    ),
                    "observer_overhead": (
                        "A polling thread samples RSS every 0.01 seconds and adds small overhead"
                    ),
                    "timing_scope": (
                        "PDF generation is excluded; only upload/storage, extraction/JSON save, "
                        "and JSON read/decode/model validation are measured"
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    finally:
        tracemalloc.stop()
