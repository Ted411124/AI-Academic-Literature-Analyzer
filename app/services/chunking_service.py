"""Exact, page-preserving text chunking for extracted PDF documents."""

from app.models.schemas import ChunkSourceSpan, DocumentExtractionData, TextChunk


class ChunkingService:
    """Split each extracted page independently without changing its text."""

    @classmethod
    def chunk_document(
        cls,
        document: DocumentExtractionData,
        chunk_size: int,
    ) -> list[TextChunk]:
        """Return non-overlapping character slices, retaining page and offset provenance.

        ``chunk_size`` counts Python string characters (Unicode code points); it is not
        a model token limit. Empty page text produces no chunk, while all non-empty
        characters, including whitespace, are preserved exactly.
        """
        if not isinstance(document, DocumentExtractionData):
            raise TypeError("document 必須是 DocumentExtractionData")
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise TypeError("chunk_size 必須是正整數")
        if chunk_size <= 0:
            raise ValueError("chunk_size 必須大於 0")
        if len(document.pages) != document.total_pages:
            raise ValueError("pages 數量必須等於 total_pages")

        expected_pages = list(range(1, document.total_pages + 1))
        actual_pages = [page.physical_page for page in document.pages]
        if actual_pages != expected_pages:
            raise ValueError("頁面必須依序對應 1-based physical_page")

        actual_total_characters = 0
        for page in document.pages:
            if page.char_count != len(page.text):
                raise ValueError(
                    f"第 {page.physical_page} 頁 char_count 與文字長度不一致"
                )
            actual_total_characters += len(page.text)
        if document.total_characters != actual_total_characters:
            raise ValueError("total_characters 與逐頁文字長度總和不一致")

        chunks = []
        chunk_index = 0
        for page in document.pages:
            if not page.text:
                continue

            page_chunk_index = 0
            for start_offset in range(0, len(page.text), chunk_size):
                end_offset = min(start_offset + chunk_size, len(page.text))
                chunk_text = page.text[start_offset:end_offset]
                chunks.append(
                    TextChunk(
                        chunk_id=(
                            f"{document.document_id}:p{page.physical_page:04d}:"
                            f"c{page_chunk_index:04d}"
                        ),
                        chunk_index=chunk_index,
                        text=chunk_text,
                        source_spans=[
                            ChunkSourceSpan(
                                physical_page=page.physical_page,
                                start_offset=start_offset,
                                end_offset=end_offset,
                            )
                        ],
                    )
                )
                chunk_index += 1
                page_chunk_index += 1

        return chunks
