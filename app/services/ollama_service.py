"""Local Ollama-based literature analysis executor."""

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.models.schemas import (
    AnalysisRequest,
    DocumentExtractionData,
)
from app.services.chunking_service import ChunkingService


logger = logging.getLogger(__name__)

# Write Ollama diagnostics to a dedicated log file.
diagnostic_log_path = (
    Path(__file__).resolve().parents[2]
    / "logs"
    / "ollama_diagnostics.log"
)
diagnostic_log_path.parent.mkdir(parents=True, exist_ok=True)

if not any(
    getattr(handler, "_ollama_diagnostic_handler", False)
    for handler in logger.handlers
):
    diagnostic_handler = logging.FileHandler(
        diagnostic_log_path,
        encoding="utf-8",
    )
    diagnostic_handler.setLevel(logging.INFO)
    diagnostic_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
    )
    diagnostic_handler._ollama_diagnostic_handler = True
    logger.addHandler(diagnostic_handler)

logger.setLevel(logging.INFO)


class OllamaServiceError(RuntimeError):
    """Raised when local Ollama analysis cannot produce a usable result."""


class OllamaService:
    """Analyze PDF chunks with a local Ollama chat model."""

    def __init__(
        self,
        model: str = "gemma4:e2b",
        base_url: str = "http://127.0.0.1:11434",
        chunk_size: int = 1800,
        timeout: int = 600,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.chunk_size = chunk_size
        self.timeout = timeout

    def _chat(self, system: str, user: str, num_predict: int = 1200) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "think": False,
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "num_ctx": 4096,
                "num_predict": num_predict,
                "temperature": 0.2,
            },
        }

        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OllamaServiceError(
                f"無法連接本機 Ollama：{exc}"
            ) from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaServiceError(
                f"Ollama 回應逾時或格式錯誤：{exc}"
            ) from exc

        content = result.get("message", {}).get("content")

        if not isinstance(content, str) or not content.strip():
            raise OllamaServiceError(
                "Ollama returned an empty response."
            )

        content = content.strip()

        # Preserve Ollama generation metadata when JSON is malformed.
        done_reason = result.get("done_reason", "unknown")
        eval_count = result.get("eval_count", "unknown")
        prompt_eval_count = result.get("prompt_eval_count", "unknown")

        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            response_tail = content[-500:].replace("\r", " ").replace("\n", " ")
            raise OllamaServiceError(
                "Ollama returned invalid JSON. "
                f"done_reason={done_reason}, "
                f"eval_count={eval_count}, "
                f"prompt_eval_count={prompt_eval_count}, "
                f"content_length={len(content)}, "
                f"json_error={exc}, "
                f"response_tail={response_tail}"
            ) from exc

        return content

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()

        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OllamaServiceError(
                f"Ollama 回傳的 JSON 無法解析：{exc}"
            ) from exc

        if not isinstance(result, dict):
            raise OllamaServiceError("Ollama 回傳內容不是 JSON 物件。")

        return result

    def _extract_chunk(
        self,
        chunk: Any,
        chunk_number: int,
        total_chunks: int,
        target_kinds: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        system = (
            "You are an academic source extraction assistant. "
            "Use only the supplied PDF text. Never use outside knowledge. "
            "Do not invent facts, quotations, or page numbers. "
            "Return JSON only."
        )

        kind_focus = ""
        if target_kinds:
            kind_focus = (
                "SUPPLEMENTAL EXTRACTION: Focus only on these missing "
                "categories: "
                + ", ".join(sorted(target_kinds))
                + ". Return an empty items array if this segment does not "
                "contain directly supported information for them. "
                "Do not use other categories."
            )

        user = f"""
Analyze this PDF text segment ({chunk_number}/{total_chunks}).

{kind_focus}

Return this JSON structure:
{{
  "items": [
    {{
      "kind": "background",
      "summary": "Concise description in the original language",
      "summary_tw": "繁體中文摘要",
      "quote": "An exact continuous quotation copied from this segment"
    }}
  ]
}}

Rules:
- Extract only clearly supported information.
- Return up to 3 useful items when the segment contains enough distinct information.
- Do not force the model to produce 3 items when fewer are supported.
- The kind field MUST be exactly ONE of these values: background, objective, method, finding, argument, conclusion, limitation. Never use other names or combine multiple values.
- Classify each item carefully:
  - background: historical context, prior conditions, or the problem that motivates the study.
  - objective: what the author explicitly aims to investigate, explain, or establish.
  - method: research methods, sources, data, analytical approach, or research procedure.
  - finding: results or discoveries presented by the author.
  - argument: a central claim, interpretation, or position defended by the author.
  - conclusion: the author's final conclusions, synthesized arguments, research implications, or direct answers to the research objectives. A conclusion does not need to appear under a section explicitly titled Conclusion, but it must be directly supported by the supplied PDF text.
  - limitation: a limitation explicitly acknowledged by the author.
- Do not confuse research background with research objectives.
- Do not confuse research methods with findings.
- Classify information as conclusion when the author presents a directly supported final judgment, synthesized argument, research implication, or answer to the research objectives. It does not need to appear under a section explicitly titled Conclusion.
- A segment may contain more than one distinct category.
- Prefer specific, directly supported information over vague descriptions.
- Keep each summary and summary_tw to one concise sentence.
- Each quote must be copied exactly from the supplied text.
- Keep quotes short and distinctive.
- Do not infer author-stated limitations.
- If nothing useful is present, return an empty items array.
- Do not invent page numbers.

SEGMENT:
{chunk.text}
"""

        result = self._parse_json(
            self._chat(system, user, num_predict=1200)
        )

        items = result.get("items", [])
        if not isinstance(items, list):
            raise OllamaServiceError(
                f"第 {chunk_number} 段的 items 格式錯誤。"
            )

        span = chunk.source_spans[0]
        verified = []

        # Diagnostic counters only; validation rules remain unchanged.
        kind_counts = {}
        non_dict_count = 0
        empty_quote_count = 0
        unmatched_quote_count = 0
        empty_summary_count = 0
        empty_summary_tw_count = 0

        for item in items:
            if not isinstance(item, dict):
                non_dict_count += 1
                continue

            raw_kind = str(item.get("kind", "other")).strip().lower()
            kind_counts[raw_kind] = kind_counts.get(raw_kind, 0) + 1

            summary = item.get("summary")
            summary_tw = item.get("summary_tw")

            if not isinstance(summary, str) or not summary.strip():
                empty_summary_count += 1

            if not isinstance(summary_tw, str) or not summary_tw.strip():
                empty_summary_tw_count += 1

            quote = item.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                empty_quote_count += 1
                continue

            # Normalize whitespace only, matching the document evidence validator.
            # The quotation itself remains unchanged; wording and punctuation
            # must still match the original source.
            normalized_quote = " ".join(quote.split())
            normalized_chunk_text = " ".join(chunk.text.split())

            if normalized_quote not in normalized_chunk_text:
                unmatched_quote_count += 1
                continue

            verified.append({
                "kind": str(item.get("kind", "other")),
                "summary": str(item.get("summary", "")),
                "summary_tw": str(item.get("summary_tw", "")),
                "quote": quote,
                "page_number": span.physical_page,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "chunk_id": chunk.chunk_id,
            })

        logger.info(
            "[OLLAMA_DIAG] chunk=%s/%s raw_items=%s kinds=%s "
            "non_dict=%s empty_quote=%s unmatched_quote=%s "
            "empty_summary=%s empty_summary_tw=%s verified=%s",
            chunk_number,
            total_chunks,
            len(items),
            kind_counts,
            non_dict_count,
            empty_quote_count,
            unmatched_quote_count,
            empty_summary_count,
            empty_summary_tw_count,
            len(verified),
        )

        return verified

    def analyze_literature(
        self,
        request: AnalysisRequest,
        document: DocumentExtractionData,
    ) -> dict[str, Any]:
        """Extract evidence first, then assemble a compact report in Python."""

        if document.document_id != request.document_id:
            raise OllamaServiceError("請求與 PDF 的 document_id 不一致。")

        chunks = ChunkingService.chunk_document(
            document,
            chunk_size=self.chunk_size,
        )

        if not chunks:
            raise OllamaServiceError("PDF 沒有可供分析的文字。")

        verified_items: list[dict[str, Any]] = []

        for index, chunk in enumerate(chunks, start=1):
            verified_items.extend(
                self._extract_chunk(chunk, index, len(chunks))
            )

        # SUPPLEMENTAL PASS: recover missing required categories.
        required_kinds = {
            "background", "objective", "method",
            "argument", "finding", "conclusion",
        }

        first_pass_kinds = {
            str(item.get("kind", "")).strip().lower()
            for item in verified_items
            if item.get("quote")
            and item.get("page_number")
            and item.get("summary")
            and item.get("summary_tw")
        }

        missing_kinds = required_kinds - first_pass_kinds

        if missing_kinds:
            chunk_count = len(chunks)
            selected_indices: set[int] = set()

            def add_candidate_window(
                start_ratio: float,
                end_ratio: float,
            ) -> None:
                start = int(chunk_count * start_ratio)
                end = min(
                    chunk_count,
                    max(start + 1, int(chunk_count * end_ratio + 0.999)),
                )
                # Search every chunk in the relevant document region.
                selected_indices.update(range(start, end))

            if {"background", "objective"} & missing_kinds:
                add_candidate_window(0.0, 0.45)

            if "method" in missing_kinds:
                add_candidate_window(0.0, 0.75)

            if {"argument", "finding"} & missing_kinds:
                add_candidate_window(0.2, 0.9)

            if "conclusion" in missing_kinds:
                add_candidate_window(0.6, 1.0)

            for index in sorted(selected_indices):
                supplemental_items = self._extract_chunk(
                    chunks[index],
                    index + 1,
                    chunk_count,
                    target_kinds=missing_kinds,
                )
                verified_items.extend(supplemental_items)

        if len(verified_items) < 5:
            raise OllamaServiceError(
                "成功核對的原文證據不足，無法可靠產生完整報告。"
            )

        # Diagnostic: compare verified records with usable records.
        verified_kind_counts = {}
        for item in verified_items:
            kind = str(item.get("kind", "other")).strip().lower()
            verified_kind_counts[kind] = verified_kind_counts.get(kind, 0) + 1

        logger.info(
            "[OLLAMA_DIAG] ALL_VERIFIED total=%s kinds=%s",
            len(verified_items),
            verified_kind_counts,
        )

        # Only retain records with usable summaries and verified quotations.
        usable_items = [
            item for item in verified_items
            if item.get("quote")
            and item.get("page_number")
            and item.get("summary")
            and item.get("summary_tw")
        ]

        usable_kind_counts = {}
        for item in usable_items:
            kind = str(item.get("kind", "other")).strip().lower()
            usable_kind_counts[kind] = usable_kind_counts.get(kind, 0) + 1

        logger.info(
            "[OLLAMA_DIAG] ALL_USABLE total=%s kinds=%s",
            len(usable_items),
            usable_kind_counts,
        )

        if len(usable_items) < 5:
            raise OllamaServiceError(
                "可用的雙語摘要及原文證據不足，無法產生可靠報告。"
            )

        kind_map = {
            "background": "research_background",
            "objective": "research_objectives",
            "method": "methodology",
            "argument": "core_arguments",
            "finding": "research_findings",
            "conclusion": "conclusion",
        }

        grouped: dict[str, list[dict[str, Any]]] = {
            name: [] for name in kind_map.values()
        }
        limitations: list[dict[str, Any]] = []

        for item in usable_items:
            kind = item.get("kind", "").strip().lower()
            target = kind_map.get(kind)

            if target:
                grouped[target].append(item)
            elif kind == "limitation":
                limitations.append(item)

        # Each required report section must have real PDF evidence.
        missing = [
            name for name, items in grouped.items()
            if not items
        ]
        if missing:
            raise OllamaServiceError(
                "PDF 原文目前缺少足以支持以下必要分析分類的證據："
                + "、".join(missing)
                + "。系統不會捏造內容補足，請稍後調整分析方式或檢查文章內容。"
            )

        def make_statement(item: dict[str, Any], statement_id: str) -> dict[str, Any]:
            return {
                "statement_id": statement_id,
                "summary_tw": item["summary_tw"],
                "summary_original": item["summary"],
                "status": "supported",
                "source": "pdf_recognition",
                "evidence": [
                    {
                        "page_number": item["page_number"],
                        "original_quote": item["quote"],
                    }
                ],
            }

        section_items: dict[str, dict[str, Any]] = {}
        report: dict[str, Any] = {
            "document_id": document.document_id,
            "total_pages": document.total_pages,
            "metadata": {},
            "mode": request.analysis_mode.value,
            "topic": request.topic,
            "outline": [],
            "research_background": None,
            "research_objectives": None,
            "methodology": None,
            "research_findings": None,
            "core_arguments": None,
            "key_points": [],
            "research_limitations": {},
            "conclusion": None,
            "topic_relevance": None,
            "mind_map": [],
        }

        category_labels = {
            "research_background": ("研究背景", "Research background"),
            "research_objectives": ("研究目的", "Research objectives"),
            "methodology": ("研究方法", "Methodology"),
            "core_arguments": ("核心論點", "Core arguments"),
            "research_findings": ("研究發現", "Research findings"),
            "conclusion": ("研究結論", "Conclusion"),
        }

        for section_name, items in grouped.items():
            item = items[0]
            statement_id = section_name
            section_items[section_name] = item
            report[section_name] = make_statement(item, statement_id)

        # Build 5–10 key points from distinct, verified source records.
        selected_key_items: list[dict[str, Any]] = []
        seen_quotes: set[str] = set()

        preferred = (
            grouped["research_findings"]
            + grouped["core_arguments"]
            + grouped["research_background"]
            + grouped["research_objectives"]
            + grouped["methodology"]
            + grouped["conclusion"]
        )

        for item in preferred + usable_items:
            quote = item["quote"]
            if quote in seen_quotes:
                continue
            seen_quotes.add(quote)
            selected_key_items.append(item)
            if len(selected_key_items) >= 8:
                break

        if len(selected_key_items) < 5:
            raise OllamaServiceError(
                "文章中可獨立核對的重點不足 5 項，無法符合報告 Schema。"
            )

        for index, item in enumerate(selected_key_items, start=1):
            report["key_points"].append({
                "finding_id": f"key_point_{index}",
                "topic": item["summary"],
                "topic_tw": item["summary_tw"],
                "statement": make_statement(
                    item,
                    f"key_point_statement_{index}",
                ),
            })

        # Limitations are included only when the extraction stage explicitly
        # classified them as author-stated limitations.
        if limitations:
            report["research_limitations"] = {
                "status": "present",
                "items": [
                    {
                        "statement": make_statement(
                            item,
                            f"limitation_{index}",
                        ),
                        "explicitly_stated_by_author": True,
                    }
                    for index, item in enumerate(limitations[:5], start=1)
                ],
                "summary_tw": None,
            }
        else:
            report["research_limitations"] = {
                "status": "not_mentioned",
                "items": [],
                "summary_tw": "【原文未提及】",
            }

        # One evidence-backed overview section. Its page range is derived
        # from verified evidence, never invented by the model.
        all_pages = [
            item["page_number"] for item in usable_items
        ]
        first_item = usable_items[0]

        report["outline"] = [{
            "section_id": "article_overview",
            "title": "Article overview",
            "title_tw": "全文概覽",
            "start_page": min(all_pages),
            "end_page": max(all_pages),
            "evidence": [
                {
                    "page_number": first_item["page_number"],
                    "original_quote": first_item["quote"],
                }
            ],
        }]

        # Build the mind map using only IDs that Python has created.
        root = {
            "category": "paper_title",
            "label_tw": "論文標題",
            "label_original": "Paper title",
            "source_item_ids": ["metadata.title"],
            "evidence": [],
            "children": [],
        }

        category_values = {
            "research_background": "research_background",
            "research_objectives": "research_objectives",
            "methodology": "methodology",
            "core_arguments": "core_arguments",
            "research_findings": "research_findings",
            "conclusion": "conclusion",
        }

        for section_name, item in section_items.items():
            label_tw, label_original = category_labels[section_name]
            root["children"].append({
                "category": category_values[section_name],
                "label_tw": label_tw + "：" + item["summary_tw"],
                "label_original": label_original + ": " + item["summary"],
                "source_item_ids": [section_name],
                "evidence": [{
                    "page_number": item["page_number"],
                    "original_quote": item["quote"],
                }],
                "children": [],
            })

        report["mind_map"] = {"root": root}

        # Topic relevance is generated separately with a compact evidence list.
        if request.topic:
            relevance_items = usable_items[:12]
            compact_records = [
                {
                    "index": index,
                    "kind": item["kind"],
                    "summary": item["summary"],
                    "summary_tw": item["summary_tw"],
                }
                for index, item in enumerate(relevance_items)
            ]

            relevance_system = (
                "You are an academic relevance evaluator. "
                "Use only the supplied PDF-derived summaries. "
                "Do not use outside knowledge. Return valid JSON only."
            )

            relevance_user = f"""
Evaluate how relevant this article is to the user's topic.

Topic: {request.topic}

Evidence records:
{json.dumps(compact_records, ensure_ascii=False)}

Return:
{{
  "level": "highly_relevant or partially_relevant or low_relevance",
  "reasons": [0],
  "related_sections": [0],
  "recommended_reading": [0]
}}

Rules:
- Each array must contain at least one valid record index.
- Use only indices shown above.
- Do not invent claims.
- Return JSON only.
"""

            relevance = self._parse_json(
                self._chat(
                    relevance_system,
                    relevance_user,
                    num_predict=500,
                )
            )

            def relevance_statements(field: str, prefix: str) -> list[dict[str, Any]]:
                indexes = relevance.get(field, [])
                if not isinstance(indexes, list):
                    indexes = []

                result = []
                for index in indexes:
                    if not isinstance(index, int):
                        continue
                    if index < 0 or index >= len(relevance_items):
                        continue

                    item = relevance_items[index]
                    result.append(
                        make_statement(item, f"{prefix}_{index}")
                    )

                if not result:
                    item = relevance_items[0]
                    result.append(
                        make_statement(item, f"{prefix}_fallback")
                    )
                return result

            level = relevance.get("level")
            if level not in (
                "highly_relevant",
                "partially_relevant",
                "low_relevance",
            ):
                level = "partially_relevant"

            report["topic_relevance"] = {
                "level": level,
                "reasons": relevance_statements("reasons", "relevance_reason"),
                "related_sections": relevance_statements(
                    "related_sections",
                    "relevance_section",
                ),
                "recommended_reading": relevance_statements(
                    "recommended_reading",
                    "relevance_reading",
                ),
            }

            relevance_node = {
                "category": "topic_relevance",
                "label_tw": "主題相關性：" + request.topic,
                "label_original": "Topic relevance: " + request.topic,
                "source_item_ids": [
                    statement["statement_id"]
                    for statement in report["topic_relevance"]["reasons"]
                ],
                "evidence": [],
                "children": [],
            }
            root["children"].append(relevance_node)

        return report
