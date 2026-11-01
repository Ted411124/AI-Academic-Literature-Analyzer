"""Unit tests for exact, page-preserving PDF text chunking."""

import pytest

from app.models.schemas import DocumentExtractionData, PageTextItem
from app.services.chunking_service import ChunkingService


def make_document(page_texts: list[str]) -> DocumentExtractionData:
    """Build an in-memory extraction model with consistent character counts."""
    pages = [
        PageTextItem(
            physical_page=page_number,
            text=text,
            char_count=len(text),
        )
        for page_number, text in enumerate(page_texts, start=1)
    ]
    return DocumentExtractionData(
        document_id="b08".ljust(32, "0"),
        original_filename="chunking-test.pdf",
        total_pages=len(pages),
        total_characters=sum(page.char_count for page in pages),
        pages=pages,
        created_at="2026-10-31T12:00:00+00:00",
    )


def assert_exact_page_reconstruction(
    document: DocumentExtractionData,
    chunks,
) -> None:
    """Check single-page provenance, contiguous offsets, and exact page rebuilds."""
    assert all(len(chunk.source_spans) == 1 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert [
        (chunk.source_spans[0].physical_page, chunk.source_spans[0].start_offset)
        for chunk in chunks
    ] == sorted(
        (
            chunk.source_spans[0].physical_page,
            chunk.source_spans[0].start_offset,
        )
        for chunk in chunks
    )

    for page in document.pages:
        page_chunks = [
            chunk
            for chunk in chunks
            if chunk.source_spans[0].physical_page == page.physical_page
        ]
        if not page.text:
            assert page_chunks == []
            continue

        rebuilt_parts = []
        expected_start = 0
        for chunk in page_chunks:
            span = chunk.source_spans[0]
            assert span.start_offset == expected_start
            assert span.end_offset > span.start_offset
            assert span.end_offset <= len(page.text)
            assert chunk.text == page.text[span.start_offset : span.end_offset]
            rebuilt_parts.append(chunk.text)
            expected_start = span.end_offset

        assert expected_start == len(page.text)
        assert "".join(rebuilt_parts) == page.text


def test_chunk_single_page_preserves_tail_and_exact_offsets():
    document = make_document(["ABCDEFGHIJ"])

    chunks = ChunkingService.chunk_document(document, chunk_size=4)

    assert [chunk.text for chunk in chunks] == ["ABCD", "EFGH", "IJ"]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [
        (chunk.source_spans[0].start_offset, chunk.source_spans[0].end_offset)
        for chunk in chunks
    ] == [(0, 4), (4, 8), (8, 10)]
    assert_exact_page_reconstruction(document, chunks)


def test_chunk_multiple_pages_without_cross_page_spans():
    document = make_document(["abcde", "1234567", "xy"])

    chunks = ChunkingService.chunk_document(document, chunk_size=3)

    assert [chunk.text for chunk in chunks] == ["abc", "de", "123", "456", "7", "xy"]
    assert [chunk.chunk_index for chunk in chunks] == list(range(6))
    assert [chunk.source_spans[0].physical_page for chunk in chunks] == [1, 1, 2, 2, 2, 3]
    assert all(len(chunk.source_spans) == 1 for chunk in chunks)
    assert_exact_page_reconstruction(document, chunks)


def test_chunk_short_empty_and_whitespace_only_pages():
    page_texts = ["", "x", "   \t\n", ""]
    document = make_document(page_texts)
    original_pages = list(document.pages)

    chunks = ChunkingService.chunk_document(document, chunk_size=5)

    assert [chunk.text for chunk in chunks] == ["x", "   \t\n"]
    assert [chunk.source_spans[0].physical_page for chunk in chunks] == [2, 3]
    assert document.pages == original_pages
    assert [page.physical_page for page in document.pages] == [1, 2, 3, 4]
    assert_exact_page_reconstruction(document, chunks)


def test_chunk_preserves_multilingual_unicode_and_whitespace_exactly():
    page_texts = [
        "English; 繁體中文：保留。简体中文：结果。日本語、句読点！",
        "  spaces  \tTab\nline one\n\nline three  ",
        "全形（）／半形() + 0123456789 © ™ § → ✓",
    ]
    document = make_document(page_texts)

    chunks = ChunkingService.chunk_document(document, chunk_size=7)

    assert_exact_page_reconstruction(document, chunks)
    assert "".join(
        chunk.text
        for chunk in chunks
        if chunk.source_spans[0].physical_page == 2
    ) == page_texts[1]


@pytest.mark.parametrize("chunk_size", [0, -1, -20])
def test_chunk_rejects_non_positive_chunk_size(chunk_size):
    with pytest.raises(ValueError, match="chunk_size"):
        ChunkingService.chunk_document(make_document(["text"]), chunk_size)


@pytest.mark.parametrize("chunk_size", [True, 1.5, "4"])
def test_chunk_rejects_non_integer_chunk_size(chunk_size):
    with pytest.raises(TypeError, match="chunk_size"):
        ChunkingService.chunk_document(make_document(["text"]), chunk_size)


def test_chunk_rejects_non_document_input():
    with pytest.raises(TypeError, match="DocumentExtractionData"):
        ChunkingService.chunk_document({"pages": []}, chunk_size=4)


def test_chunk_rejects_inconsistent_page_character_count():
    page = PageTextItem(physical_page=1, text="abc", char_count=2)
    document = DocumentExtractionData(
        document_id="b08".ljust(32, "0"),
        original_filename="inconsistent.pdf",
        total_pages=1,
        total_characters=2,
        pages=[page],
        created_at="test",
    )

    with pytest.raises(ValueError, match="char_count"):
        ChunkingService.chunk_document(document, chunk_size=2)


def test_chunk_rejects_inconsistent_document_character_count():
    document = make_document(["abc"])
    document.total_characters = 2

    with pytest.raises(ValueError, match="total_characters"):
        ChunkingService.chunk_document(document, chunk_size=2)
