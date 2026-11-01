"""Gemini-based academic literature analysis service."""

import copy
import json
import os
from typing import Any, Dict, Optional

from app.config import GEMINI_API_KEY
from app.models.schemas import AnalysisReport


GEMINI_MODEL = "gemini-3.8-flash"


class GeminiServiceError(RuntimeError):
    """Base exception for Gemini service failures."""


class GeminiConfigurationError(GeminiServiceError):
    """Raised when Gemini configuration is missing."""


class GeminiResponseError(GeminiServiceError):
    """Raised when Gemini returns an unusable response."""


class GeminiService:
    """Generate a source-grounded candidate literature analysis."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Any = None,
        model: str = GEMINI_MODEL,
    ) -> None:
        self.api_key = api_key if api_key is not None else GEMINI_API_KEY
        self.client = client
        self.model = model

    @staticmethod
    def build_response_schema() -> Dict[str, Any]:
        """Build a Gemini schema copy without changing the original Pydantic schema."""
        schema = copy.deepcopy(AnalysisReport.model_json_schema())

        def remove_defaults(value: Any) -> None:
            if isinstance(value, dict):
                value.pop("default", None)
                for child in value.values():
                    remove_defaults(child)
            elif isinstance(value, list):
                for child in value:
                    remove_defaults(child)

        remove_defaults(schema)
        return schema

    def _get_client(self) -> Any:
        if self.client is not None:
            return self.client

        api_key = self.api_key or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise GeminiConfigurationError(
                "???? GEMINI_API_KEY????? Gemini ???"
            )

        try:
            from google import genai

            self.client = genai.Client(api_key=api_key)
        except Exception as exc:
            raise GeminiConfigurationError(
                "????? Google Gen AI SDK?"
            ) from exc

        return self.client

    @staticmethod
    def _build_document_text(document: Any) -> str:
        page_blocks = []
        for page in document.pages:
            page_blocks.append(
                f"===== PDF \u5be6\u9ad4\u7b2c {page.physical_page} \u9801 =====\n"
                f"{page.text}"
            )
        return "\n\n".join(page_blocks)

    @staticmethod
    def _build_input(request: Any, document: Any) -> str:
        mode = getattr(request.mode, "value", request.mode)
        topic = getattr(request, "topic", None)

        topic_instruction = (
            f"\u4f7f\u7528\u8005\u6307\u5b9a\u7684\u7814\u7a76\u4e3b\u984c\uff1a{topic}\n"
            if mode == "topic" and topic
            else "\u672c\u6b21\u70ba\u4e00\u822c\u6587\u737b\u5206\u6790\uff0c\u4e0d\u9032\u884c\u6307\u5b9a\u4e3b\u984c\u6bd4\u8f03\u3002\n"
        )

        document_text = GeminiService._build_document_text(document)

        return (
            "\u8acb\u5206\u6790\u4ee5\u4e0b\u5b78\u8853\u6587\u737b\u3002\n\n"
            f"\u5206\u6790\u6a21\u5f0f\uff1a{mode}\n"
            f"{topic_instruction}\n"
            f"\u6587\u4ef6\u8b58\u5225\u78bc\uff1a{document.document_id}\n"
            f"PDF \u7e3d\u9801\u6578\uff1a{document.total_pages}\n\n"
            "\u4ee5\u4e0b\u5167\u5bb9\u662f PDF \u64f7\u53d6\u51fa\u7684\u539f\u59cb\u6587\u5b57\u3002"
            "\u9801\u9762\u6a19\u8a18\u4ee3\u8868 PDF \u5be6\u9ad4\u9801\u78bc\uff0c\u4e0d\u662f\u6587\u7ae0\u5370\u5237\u9801\u78bc\u3002\n\n"
            f"{document_text}"
        )

    @staticmethod
    def _system_instruction() -> str:
        return """
\u4f60\u662f\u4e00\u500b\u56b4\u8b39\u7684\u5b78\u8853\u6587\u737b\u6574\u7406\u52a9\u624b\u3002

\u3010\u6700\u9ad8\u539f\u5247\uff1a\u53ea\u80fd\u4f9d\u64da\u63d0\u4f9b\u7684 PDF \u539f\u6587\u3011
1. \u4e0d\u5f97\u4f7f\u7528\u5916\u90e8\u77e5\u8b58\u3001\u7db2\u8def\u8cc7\u6599\u6216\u81ea\u884c\u88dc\u5145\u80cc\u666f\u3002
2. \u4e0d\u5f97\u634f\u9020\u4f5c\u8005\u3001\u5e74\u4efd\u3001\u7814\u7a76\u65b9\u6cd5\u3001\u6578\u5b57\u3001\u5f15\u6587\u6216\u9801\u78bc\u3002
3. \u5fc5\u9808\u5340\u5206\u4f5c\u8005\u660e\u78ba\u9673\u8ff0\u8207\u4f60\u81ea\u5df1\u7684\u6574\u7406\u3002
4. \u53ea\u6709\u539f\u6587\u660e\u78ba\u63d0\u51fa\u7684\u7814\u7a76\u9650\u5236\uff0c\u624d\u80fd\u5217\u70ba\u4f5c\u8005\u63d0\u51fa\u7684\u9650\u5236\u3002
5. \u6bcf\u4e00\u9805\u91cd\u8981\u8ad6\u8ff0\u90fd\u61c9\u63d0\u4f9b\u53ef\u5728\u539f\u6587\u627e\u5230\u7684\u7cbe\u78ba\u5f15\u53e5\u53ca PDF \u5be6\u9ad4\u9801\u78bc\u3002
6. \u5f15\u53e5\u5fc5\u9808\u9010\u5b57\u53d6\u81ea\u63d0\u4f9b\u7684\u6587\u5b57\uff0c\u4e0d\u5f97\u6539\u5beb\u6210\u5f15\u53e5\u3002
7. \u627e\u4e0d\u5230\u8b49\u64da\u6642\uff0c\u4e0d\u5f97\u5047\u88dd\u6709\u8b49\u64da\u3002
8. \u539f\u6587\u672a\u63d0\u53ca\u6642\uff0c\u4f9d\u7167\u8cc7\u6599 Schema \u7684\u72c0\u614b\u898f\u5247\u6a19\u8a18\u3002
9. \u7121\u6cd5\u8fa8\u8b58\u6642\uff0c\u5fc5\u9808\u6a19\u8a18\u7121\u6cd5\u8fa8\u8b58\uff0c\u4e0d\u53ef\u81ea\u884c\u731c\u6e2c\u3002
10. \u82f1\u6587\u53ca\u65e5\u6587\u4f86\u6e90\u9700\u8981\u540c\u6642\u63d0\u4f9b\u539f\u6587\u8a9e\u8a00\u8207\u7e41\u9ad4\u4e2d\u6587\u6574\u7406\u3002
11. \u7c21\u9ad4\u4e2d\u6587\u4f86\u6e90\u63d0\u4f9b\u7c21\u9ad4\u4e2d\u6587\u53ca\u7e41\u9ad4\u4e2d\u6587\u6574\u7406\u3002
12. \u7e41\u9ad4\u4e2d\u6587\u4f86\u6e90\u53ea\u63d0\u4f9b\u7e41\u9ad4\u4e2d\u6587\uff0c\u4e0d\u8981\u91cd\u8907\u540c\u4e00\u5167\u5bb9\u3002
13. \u5fc3\u667a\u5716\u53ea\u80fd\u6574\u7406\u5831\u544a\u4e2d\u5df2\u6709\u7684\u5167\u5bb9\uff0c\u4e0d\u5f97\u5275\u9020\u65b0\u8ad6\u9ede\u3002
14. \u5fc3\u667a\u5716 source_item_ids \u5fc5\u9808\u5f15\u7528\u5831\u544a\u4e2d\u771f\u5be6\u5b58\u5728\u7684\u9805\u76ee\u8b58\u5225\u78bc\u3002
15. \u4e0d\u5f97\u5c07 AI \u63a8\u8ad6\u5192\u5145\u4f5c\u8005\u4e3b\u5f35\u3002

\u8acb\u5b8c\u6574\u5206\u6790\u6587\u4ef6\uff0c\u4e26\u9075\u5b88\u56de\u61c9 Schema \u7684\u6b04\u4f4d\u3001\u578b\u5225\u53ca\u5fc5\u8981\u6b04\u4f4d\u8981\u6c42\u3002
\u4e0d\u8981\u8f38\u51fa Schema \u4ee5\u5916\u7684\u8aaa\u660e\u6587\u5b57\u3002
"""
    def analyze_literature(
        self,
        request: Any,
        document: Any,
    ) -> Dict[str, Any]:
        """Call Gemini and return a candidate dictionary for server validation."""
        client = self._get_client()
        prompt = self._build_input(request, document)
        response_schema = self.build_response_schema()

        try:
            interaction = client.interactions.create(
                model=self.model,
                input=prompt,
                system_instruction=self._system_instruction(),
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema,
                },
                store=False,
            )
        except Exception as exc:
            raise GeminiServiceError(
                "Gemini API ???????????"
            ) from exc

        output_text = getattr(interaction, "output_text", None)

        if not isinstance(output_text, str) or not output_text.strip():
            raise GeminiResponseError(
                "Gemini ????????????"
            )

        try:
            result = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise GeminiResponseError(
                "Gemini ????????? JSON?"
            ) from exc

        if not isinstance(result, dict):
            raise GeminiResponseError(
                "Gemini ??????????? JSON ???"
            )

        return result
