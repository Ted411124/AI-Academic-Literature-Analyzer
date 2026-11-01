from types import SimpleNamespace

import pytest

from app.services.gemini_service import (
    GeminiService,
    GeminiServiceError,
    GeminiResponseError,
)


class FakeInteractions:
    def __init__(self, output_text='{"test": "success"}', error=None):
        self.output_text = output_text
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        if self.error:
            raise self.error

        return SimpleNamespace(output_text=self.output_text)


class FakeClient:
    def __init__(self, interactions):
        self.interactions = interactions


@pytest.fixture
def mock_request():
    return SimpleNamespace(
        mode=SimpleNamespace(value="general"),
        topic=None,
    )


@pytest.fixture
def mock_document():
    return SimpleNamespace(
        document_id="mock-document-001",
        total_pages=2,
        pages=[
            SimpleNamespace(
                physical_page=1,
                text="First page original text.",
            ),
            SimpleNamespace(
                physical_page=2,
                text="Second page original text.",
            ),
        ],
    )


def test_gemini_service_parses_json_response(mock_request, mock_document):
    interactions = FakeInteractions()
    service = GeminiService(client=FakeClient(interactions))

    result = service.analyze_literature(mock_request, mock_document)

    assert result == {"test": "success"}
    assert len(interactions.calls) == 1


def test_gemini_service_uses_expected_api_parameters(
    mock_request,
    mock_document,
):
    interactions = FakeInteractions()
    service = GeminiService(client=FakeClient(interactions))

    service.analyze_literature(mock_request, mock_document)

    call = interactions.calls[0]

    assert call["model"] == "gemini-3.8-flash"
    assert call["store"] is False
    assert call["response_format"]["mime_type"] == "application/json"
    assert "schema" in call["response_format"]
    assert "$defs" in call["response_format"]["schema"]


def test_gemini_service_preserves_pdf_pages(
    mock_request,
    mock_document,
):
    interactions = FakeInteractions()
    service = GeminiService(client=FakeClient(interactions))

    service.analyze_literature(mock_request, mock_document)

    prompt = interactions.calls[0]["input"]

    assert "PDF 實體第 1 頁" in prompt
    assert "PDF 實體第 2 頁" in prompt
    assert "First page original text." in prompt
    assert "Second page original text." in prompt


def test_gemini_service_includes_source_grounding_instruction(
    mock_request,
    mock_document,
):
    interactions = FakeInteractions()
    service = GeminiService(client=FakeClient(interactions))

    service.analyze_literature(mock_request, mock_document)

    instruction = interactions.calls[0]["system_instruction"]

    assert "不得使用外部知識" in instruction
    assert "不得捏造" in instruction


def test_gemini_service_rejects_invalid_json(
    mock_request,
    mock_document,
):
    service = GeminiService(
        client=FakeClient(
            FakeInteractions(output_text="not-json")
        )
    )

    with pytest.raises(GeminiResponseError):
        service.analyze_literature(mock_request, mock_document)


def test_gemini_service_rejects_empty_response(
    mock_request,
    mock_document,
):
    service = GeminiService(
        client=FakeClient(
            FakeInteractions(output_text="  ")
        )
    )

    with pytest.raises(GeminiResponseError):
        service.analyze_literature(mock_request, mock_document)


def test_gemini_service_converts_api_exception(
    mock_request,
    mock_document,
):
    service = GeminiService(
        client=FakeClient(
            FakeInteractions(error=RuntimeError("Mock network error"))
        )
    )

    with pytest.raises(GeminiServiceError):
        service.analyze_literature(mock_request, mock_document)
