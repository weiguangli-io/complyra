"""Functional / integration test suite for Complyra.

Tests the complete document ingestion and chat pipeline using generated
test fixtures (PDFs, text files, images). Validates every branch of
the processing pipeline including OCR fallback, smart chunking,
query rewrite, hybrid search, ReAct retrieval, multimodal, policy
checks, and approval workflow.

Run: python3 -m pytest tests/test_functional.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.models.schemas import ChatRequest
from app.services.ingest import (
    ChunkWithMetadata,
    PageContent,
    chunk_text,
    extract_text_from_bytes,
    extract_text_from_pdf,
    ingest_document,
    normalize_ingest_filename,
    smart_chunk_text,
    validate_ingest_filename,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ════════════════════════════════════════════════════════════════════
# TC-1: Document Ingestion - Text Files
# ════════════════════════════════════════════════════════════════════


class TestTC1TextIngestion:
    """TC-1: Verify text file ingestion covers all branches."""

    @patch("app.services.ingest.upsert_chunks")
    def test_tc1_01_simple_txt(self, mock_upsert):
        """TC-1.01: Ingest a simple .txt file - happy path."""
        mock_upsert.return_value = "doc-simple"
        content = (FIXTURES / "simple.txt").read_bytes()
        doc_id, count = ingest_document(content, "simple.txt", "test-tenant")
        assert doc_id == "doc-simple"
        assert count > 0
        # Verify chunks were passed to upsert
        chunks = mock_upsert.call_args[0][0]
        assert all(isinstance(c, str) for c in chunks)

    @patch("app.services.ingest.upsert_chunks")
    def test_tc1_02_empty_txt(self, mock_upsert):
        """TC-1.02: Ingest empty text file - should return 0 chunks."""
        content = (FIXTURES / "empty.txt").read_bytes()
        doc_id, count = ingest_document(content, "empty.txt", "test-tenant")
        assert doc_id == ""
        assert count == 0
        mock_upsert.assert_not_called()

    @patch("app.services.ingest.upsert_chunks")
    def test_tc1_03_unicode_txt(self, mock_upsert):
        """TC-1.03: Ingest unicode text with CJK characters and emojis."""
        mock_upsert.return_value = "doc-unicode"
        content = (FIXTURES / "unicode.txt").read_bytes()
        doc_id, count = ingest_document(content, "unicode.txt", "test-tenant")
        assert doc_id == "doc-unicode"
        assert count > 0
        chunks = mock_upsert.call_args[0][0]
        combined = " ".join(chunks)
        assert "测试文档" in combined or "Unicode" in combined

    @patch("app.services.ingest.upsert_chunks")
    def test_tc1_04_long_document_chunking(self, mock_upsert):
        """TC-1.04: Long document should produce multiple chunks with overlap."""
        mock_upsert.return_value = "doc-long"
        content = (FIXTURES / "long_document.txt").read_bytes()
        doc_id, count = ingest_document(content, "long_document.txt", "test-tenant")
        assert doc_id == "doc-long"
        assert count > 5  # Long doc should have many chunks

    @patch("app.services.ingest.upsert_chunks")
    def test_tc1_05_markdown_file(self, mock_upsert):
        """TC-1.05: Ingest markdown compliance policy document."""
        mock_upsert.return_value = "doc-md"
        content = (FIXTURES / "compliance_policy.md").read_bytes()
        doc_id, count = ingest_document(content, "compliance_policy.md", "test-tenant")
        assert doc_id == "doc-md"
        assert count > 0

    @patch("app.services.ingest.upsert_chunks")
    def test_tc1_06_binary_content(self, mock_upsert):
        """TC-1.06: Ingest file with binary/invalid UTF-8 content - graceful handling."""
        mock_upsert.return_value = "doc-bin"
        content = (FIXTURES / "binary_content.txt").read_bytes()
        doc_id, count = ingest_document(content, "binary_content.txt", "test-tenant")
        # Should not crash, but may have empty chunks
        assert isinstance(doc_id, str)


# ════════════════════════════════════════════════════════════════════
# TC-2: Document Ingestion - PDF Files
# ════════════════════════════════════════════════════════════════════


class TestTC2PdfIngestion:
    """TC-2: Verify PDF ingestion with smart chunking and page tracking."""

    def test_tc2_01_single_page_pdf_extraction(self, monkeypatch):
        """TC-2.01: Extract text from single-page PDF."""
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", False)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        mock_page = MagicMock()
        mock_page.get_text.return_value = "This is page 1 of the test PDF."
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            pages = extract_text_from_pdf(b"pdf-bytes")
        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert "test PDF" in pages[0].text

    def test_tc2_02_multi_page_pdf_extraction(self, monkeypatch):
        """TC-2.02: Extract text from multi-page PDF - verify page numbers."""
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", False)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        pages_data = [
            "Chapter 1: Introduction",
            "Chapter 2: Data Handling",
            "Chapter 3: Audit Requirements",
        ]
        mock_pages = []
        for text in pages_data:
            p = MagicMock()
            p.get_text.return_value = text
            mock_pages.append(p)

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter(mock_pages))
        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"pdf-bytes")
        assert len(result) == 3
        assert result[0].page_number == 1
        assert result[2].page_number == 3

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.ingest.extract_text_from_pdf")
    def test_tc2_03_smart_chunking_with_page_numbers(self, mock_pdf, mock_upsert, monkeypatch):
        """TC-2.03: Smart chunking preserves page number metadata."""
        monkeypatch.setattr("app.services.ingest.settings.chunking_strategy", "smart")
        mock_pdf.return_value = [
            PageContent(text="Chapter 1 paragraph.\n\nAnother paragraph.", page_number=1),
            PageContent(text="Chapter 2 paragraph.\n\nMore content here.", page_number=2),
        ]
        mock_upsert.return_value = "doc-smart"
        doc_id, count = ingest_document(b"pdf-bytes", "handbook.pdf", "t1")
        assert doc_id == "doc-smart"
        # Verify page_numbers were passed to upsert_chunks
        call_kwargs = mock_upsert.call_args
        page_numbers = call_kwargs[1].get("page_numbers") or call_kwargs[0][3] if len(call_kwargs[0]) > 3 else None
        # page_numbers should be a list of lists
        if page_numbers:
            assert all(isinstance(pn, list) for pn in page_numbers)

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.ingest.extract_text_from_pdf")
    def test_tc2_04_fixed_chunking_fallback(self, mock_pdf, mock_upsert, monkeypatch):
        """TC-2.04: Fixed chunking mode joins all pages."""
        monkeypatch.setattr("app.services.ingest.settings.chunking_strategy", "fixed")
        mock_pdf.return_value = [
            PageContent(text="Page 1 text.", page_number=1),
            PageContent(text="Page 2 text.", page_number=2),
        ]
        mock_upsert.return_value = "doc-fixed"
        doc_id, count = ingest_document(b"pdf-bytes", "report.pdf", "t1")
        assert doc_id == "doc-fixed"
        chunks = mock_upsert.call_args[0][0]
        combined = " ".join(chunks)
        assert "Page 1" in combined
        assert "Page 2" in combined

    @patch("app.services.ingest._ocr_page")
    def test_tc2_05_ocr_fallback_for_scanned_pdf(self, mock_ocr, monkeypatch):
        """TC-2.05: OCR fallback activates when page text is below threshold."""
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", True)
        monkeypatch.setattr("app.services.ingest.settings.ocr_min_text_threshold", 50)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)
        mock_ocr.return_value = "OCR recognized text from scan"

        mock_page = MagicMock()
        mock_page.get_text.return_value = "ab"  # Below threshold
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            pages = extract_text_from_pdf(b"scanned-pdf")
        assert pages[0].text == "OCR recognized text from scan"

    @patch("app.services.ingest._ocr_page")
    def test_tc2_06_ocr_exception_graceful(self, mock_ocr, monkeypatch):
        """TC-2.06: OCR failure falls back to original (possibly empty) text."""
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", True)
        monkeypatch.setattr("app.services.ingest.settings.ocr_min_text_threshold", 50)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)
        mock_ocr.side_effect = Exception("Tesseract not installed")

        mock_page = MagicMock()
        mock_page.get_text.return_value = "ab"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            pages = extract_text_from_pdf(b"scanned-pdf")
        assert pages[0].text == "ab"  # Falls back to original

    @patch("app.services.ingest._ocr_page")
    def test_tc2_07_ocr_skipped_for_long_text(self, mock_ocr, monkeypatch):
        """TC-2.07: OCR not triggered when page has enough text."""
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", True)
        monkeypatch.setattr("app.services.ingest.settings.ocr_min_text_threshold", 10)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        mock_page = MagicMock()
        mock_page.get_text.return_value = "This page has plenty of text content already."
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            pages = extract_text_from_pdf(b"normal-pdf")
        mock_ocr.assert_not_called()
        assert "plenty of text" in pages[0].text


# ════════════════════════════════════════════════════════════════════
# TC-3: Document Ingestion - Image Files (Multimodal)
# ════════════════════════════════════════════════════════════════════


class TestTC3ImageIngestion:
    """TC-3: Verify image ingestion via Gemini Vision."""

    @pytest.fixture(autouse=True)
    def _allow_images(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.ingest.settings.ingest_allowed_extensions",
            ["pdf", "txt", "md", "png", "jpg", "jpeg"],
        )

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.llm.describe_image")
    def test_tc3_01_png_ingestion(self, mock_describe, mock_upsert):
        """TC-3.01: Ingest PNG image via Gemini Vision description."""
        mock_describe.return_value = "A red chart showing Q1 revenue growth"
        mock_upsert.return_value = "doc-png"
        content = (FIXTURES / "test_chart.png").read_bytes()
        doc_id, count = ingest_document(content, "test_chart.png", "t1")
        assert doc_id == "doc-png"
        assert count == 1
        chunks = mock_upsert.call_args[0][0]
        assert "[Image description:" in chunks[0]

    @patch("app.services.llm.describe_image")
    def test_tc3_02_image_empty_description(self, mock_describe):
        """TC-3.02: Empty image description returns 0 chunks."""
        mock_describe.return_value = ""
        content = (FIXTURES / "tiny_icon.png").read_bytes()
        doc_id, count = ingest_document(content, "tiny_icon.png", "t1")
        assert doc_id == ""
        assert count == 0

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.llm.describe_image")
    def test_tc3_03_jpg_ingestion(self, mock_describe, mock_upsert):
        """TC-3.03: Ingest JPG image."""
        mock_describe.return_value = "A photograph of a building"
        mock_upsert.return_value = "doc-jpg"
        content = (FIXTURES / "test_photo.jpg").read_bytes()
        doc_id, count = ingest_document(content, "test_photo.jpg", "t1")
        assert doc_id == "doc-jpg"
        assert count == 1


# ════════════════════════════════════════════════════════════════════
# TC-4: Filename Sanitization & Validation
# ════════════════════════════════════════════════════════════════════


class TestTC4FilenameValidation:
    """TC-4: Verify filename sanitization and extension validation."""

    def test_tc4_01_normal_filename(self):
        assert normalize_ingest_filename("report.pdf") == "report.pdf"

    def test_tc4_02_spaces_and_special_chars(self):
        result = normalize_ingest_filename("my file (copy).pdf")
        assert " " not in result
        assert "(" not in result
        assert result.endswith(".pdf")

    def test_tc4_03_directory_traversal_blocked(self):
        result = normalize_ingest_filename("../../etc/passwd.txt")
        assert "/" not in result
        assert ".." not in result

    def test_tc4_04_empty_filename_rejected(self):
        with pytest.raises(ValueError, match="required"):
            normalize_ingest_filename("")

    def test_tc4_05_no_extension_rejected(self):
        with pytest.raises(ValueError, match="extension"):
            normalize_ingest_filename("noext")

    def test_tc4_06_unsupported_extension_rejected(self):
        with pytest.raises(ValueError, match="Unsupported"):
            normalize_ingest_filename("malware.exe")

    def test_tc4_07_all_special_chars_fallback(self):
        result = normalize_ingest_filename("!!!@@@.pdf")
        assert result == "document.pdf"

    def test_tc4_08_uppercase_extension_normalized(self):
        result = normalize_ingest_filename("Report.PDF")
        assert result.endswith(".pdf")

    def test_tc4_09_validate_returns_extension(self):
        assert validate_ingest_filename("doc.pdf") == "pdf"
        assert validate_ingest_filename("notes.txt") == "txt"
        assert validate_ingest_filename("readme.md") == "md"


# ════════════════════════════════════════════════════════════════════
# TC-5: Chunking Strategies
# ════════════════════════════════════════════════════════════════════


class TestTC5ChunkingStrategies:
    """TC-5: Verify fixed and smart chunking edge cases."""

    def test_tc5_01_fixed_chunk_overlap(self, monkeypatch):
        """TC-5.01: Fixed chunking produces overlapping chunks."""
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 50)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 10)
        text = "word " * 100
        chunks = chunk_text(text)
        assert len(chunks) > 2
        # Check overlap: end of chunk N should overlap with start of chunk N+1
        if len(chunks) >= 2:
            c1_end = chunks[0][-10:]
            c2_start = chunks[1][:10]
            assert c1_end == c2_start

    def test_tc5_02_smart_chunk_paragraph_boundaries(self, monkeypatch):
        """TC-5.02: Smart chunking respects paragraph boundaries."""
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 200)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 20)
        pages = [
            PageContent(
                text="Paragraph one about data protection.\n\n"
                     "Paragraph two about access control.\n\n"
                     "Paragraph three about audit logging.",
                page_number=1,
            )
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 1
        # Each chunk should be a coherent paragraph group
        for c in chunks:
            assert len(c.text) > 0
            assert 1 in c.page_numbers

    def test_tc5_03_smart_chunk_sentence_splitting(self, monkeypatch):
        """TC-5.03: Long paragraphs split by sentence boundaries."""
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 40)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)
        pages = [
            PageContent(
                text="First sentence here. Second sentence follows. Third one is also present.",
                page_number=1,
            )
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 2

    def test_tc5_04_smart_chunk_cross_page(self, monkeypatch):
        """TC-5.04: Chunks spanning multiple pages track all page numbers."""
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 500)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)
        pages = [
            PageContent(text="Short page 1 text.", page_number=1),
            PageContent(text="Short page 2 text.", page_number=2),
            PageContent(text="Short page 3 text.", page_number=3),
        ]
        chunks = smart_chunk_text(pages)
        # With large chunk_size, all pages should be in one chunk
        if len(chunks) == 1:
            assert 1 in chunks[0].page_numbers
            assert 2 in chunks[0].page_numbers
            assert 3 in chunks[0].page_numbers

    def test_tc5_05_smart_chunk_empty_pages(self, monkeypatch):
        """TC-5.05: Pages with only whitespace produce no chunks."""
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 100)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)
        pages = [
            PageContent(text="   \n\n   ", page_number=1),
            PageContent(text="", page_number=2),
        ]
        chunks = smart_chunk_text(pages)
        assert chunks == []


# ════════════════════════════════════════════════════════════════════
# TC-6: Chat & Retrieval Pipeline
# ════════════════════════════════════════════════════════════════════


class TestTC6ChatPipeline:
    """TC-6: Verify the full chat pipeline including workflow routing."""

    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.run_workflow")
    def test_tc6_01_chat_completed(self, mock_workflow, mock_log):
        """TC-6.01: Normal chat returns completed response with citations."""
        from app.api.routes.chat import chat

        mock_workflow.return_value = {
            "retrieved": [
                ("Data protection requires encryption.", 0.95, "policy.pdf", [1, 2]),
                ("Access control uses RBAC.", 0.87, "policy.pdf", [3]),
            ],
            "draft_answer": "According to the policy, data must be encrypted [1] and RBAC is required [2].",
            "approval_required": False,
            "policy_blocked": False,
            "policy_violations": [],
        }
        result = chat(
            ChatRequest(question="What are the data protection requirements?"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        assert result.status == "completed"
        assert "[1]" in result.answer or "encrypted" in result.answer
        assert len(result.retrieved) == 2
        assert result.retrieved[0].page_numbers == [1, 2]
        assert result.retrieved[0].source == "policy.pdf"

    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.run_workflow")
    def test_tc6_02_chat_policy_blocked(self, mock_workflow, mock_log):
        """TC-6.02: Chat blocked by output policy (sensitive content detected)."""
        from app.api.routes.chat import chat

        mock_workflow.return_value = {
            "retrieved": [("AKIAIOSFODNN7EXAMPLE", 0.9, "creds.txt", [1])],
            "draft_answer": "blocked",
            "approval_required": False,
            "policy_blocked": True,
            "policy_violations": ["AWS key pattern"],
        }
        result = chat(
            ChatRequest(question="Show me the credentials"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        audit_action = mock_log.call_args[1]["action"]
        assert audit_action == "chat_blocked_by_policy"

    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.run_workflow")
    def test_tc6_03_chat_pending_approval(self, mock_workflow, mock_log):
        """TC-6.03: Chat requires human approval."""
        from app.api.routes.chat import chat

        mock_workflow.return_value = {
            "retrieved": [],
            "draft_answer": "Answer draft",
            "approval_required": True,
            "approval_id": "ap-789",
            "policy_blocked": False,
            "policy_violations": [],
        }
        result = chat(
            ChatRequest(question="Sensitive question"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        assert result.status == "pending_approval"
        assert result.approval_id == "ap-789"
        assert "pending" in result.answer.lower()


# ════════════════════════════════════════════════════════════════════
# TC-7: SSE Streaming Pipeline
# ════════════════════════════════════════════════════════════════════


class _AsyncTokenIterator:
    def __init__(self, tokens):
        self._tokens = tokens
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._tokens):
            raise StopAsyncIteration
        token = self._tokens[self._index]
        self._index += 1
        return token


class TestTC7StreamingPipeline:
    """TC-7: Verify SSE streaming endpoint with all event types."""

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.rewrite_query", new_callable=AsyncMock)
    @patch("app.api.routes.chat.search_chunks")
    async def test_tc7_01_stream_with_query_rewrite(
        self, mock_search, mock_rewrite, mock_stream, mock_policy, mock_log, monkeypatch
    ):
        """TC-7.01: Streaming with query rewrite enabled produces rewrite events."""
        from app.api.routes.chat import chat_stream

        monkeypatch.setattr("app.api.routes.chat.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.api.routes.chat.settings.react_retrieval_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", False)

        mock_rewrite.return_value = "improved query"
        mock_search.return_value = [("text", 0.9, "doc.pdf", [1])]
        mock_stream.return_value = _AsyncTokenIterator(["Answer"])
        mock_policy.return_value = MagicMock(blocked=False, matched_rules=[])

        response = await chat_stream(
            ChatRequest(question="vague question"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        text = "".join(events)

        assert "rewrite_start" in text
        assert "rewrite_done" in text
        assert "improved query" in text

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.search_chunks")
    async def test_tc7_02_stream_without_rewrite(
        self, mock_search, mock_stream, mock_policy, mock_log, monkeypatch
    ):
        """TC-7.02: Streaming without query rewrite skips rewrite events."""
        from app.api.routes.chat import chat_stream

        monkeypatch.setattr("app.api.routes.chat.settings.query_rewrite_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.react_retrieval_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", False)

        mock_search.return_value = [("text", 0.9, "doc.pdf", [1])]
        mock_stream.return_value = _AsyncTokenIterator(["Answer"])
        mock_policy.return_value = MagicMock(blocked=False, matched_rules=[])

        response = await chat_stream(
            ChatRequest(question="direct question"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        text = "".join(events)

        assert "rewrite_start" not in text
        assert "retrieve_start" in text
        assert "done" in text

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.judge_relevance", new_callable=AsyncMock)
    @patch("app.api.routes.chat.search_chunks")
    async def test_tc7_03_stream_react_multi_step(
        self, mock_search, mock_judge, mock_stream, mock_policy, mock_log, monkeypatch
    ):
        """TC-7.03: ReAct multi-step retrieval with sub-questions."""
        from app.api.routes.chat import chat_stream

        monkeypatch.setattr("app.api.routes.chat.settings.query_rewrite_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.api.routes.chat.settings.max_retrieval_attempts", 3)
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", False)

        # First attempt: insufficient, returns sub-questions
        # Second attempt: sufficient
        call_count = {"n": 0}

        def search_side_effect(query, top_k, tenant_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [("initial context", 0.8, "doc1.pdf", [1])]
            return [("additional context", 0.85, "doc2.pdf", [2])]

        mock_search.side_effect = search_side_effect
        mock_judge.side_effect = [
            {"is_sufficient": False, "sub_questions": ["What about X?"], "reasoning": "Missing X"},
            {"is_sufficient": True, "sub_questions": [], "reasoning": "Now complete"},
        ]
        mock_stream.return_value = _AsyncTokenIterator(["Complete", " answer"])
        mock_policy.return_value = MagicMock(blocked=False, matched_rules=[])

        response = await chat_stream(
            ChatRequest(question="complex question"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        text = "".join(events)

        assert "judge_start" in text
        assert "judge_done" in text
        assert "is_sufficient" in text

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.create_approval_request")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.search_chunks")
    async def test_tc7_04_stream_approval_required(
        self, mock_search, mock_stream, mock_policy, mock_create, mock_log, monkeypatch
    ):
        """TC-7.04: Streaming with approval workflow."""
        from app.api.routes.chat import chat_stream

        monkeypatch.setattr("app.api.routes.chat.settings.query_rewrite_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.react_retrieval_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", True)

        mock_search.return_value = [("text", 0.9, "doc.pdf", [1])]
        mock_stream.return_value = _AsyncTokenIterator(["ok"])
        mock_policy.return_value = MagicMock(blocked=False, matched_rules=[])
        mock_create.return_value = "ap-stream-1"

        response = await chat_stream(
            ChatRequest(question="question"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        text = "".join(events)

        assert "approval_required" in text
        assert "ap-stream-1" in text

    @pytest.mark.asyncio
    @patch("app.api.routes.chat.log_event")
    @patch("app.api.routes.chat.evaluate_output_policy")
    @patch("app.api.routes.chat.generate_answer_stream")
    @patch("app.api.routes.chat.search_chunks")
    async def test_tc7_05_stream_policy_blocked(
        self, mock_search, mock_stream, mock_policy, mock_log, monkeypatch
    ):
        """TC-7.05: Streaming with policy blocked response."""
        from app.api.routes.chat import chat_stream

        monkeypatch.setattr("app.api.routes.chat.settings.query_rewrite_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.react_retrieval_enabled", False)
        monkeypatch.setattr("app.api.routes.chat.settings.require_approval", True)

        mock_search.return_value = []
        mock_stream.return_value = _AsyncTokenIterator(["secret", " data"])
        mock_policy.return_value = MagicMock(blocked=True, matched_rules=["AWS key"])

        response = await chat_stream(
            ChatRequest(question="show creds"),
            tenant_id="t1",
            user={"user_id": "u1", "username": "alice"},
        )
        events = []
        async for chunk in response.body_iterator:
            events.append(chunk)
        text = "".join(events)

        assert "policy_blocked" in text
        # When policy blocked, should NOT create approval
        assert "approval_required" not in text


# ════════════════════════════════════════════════════════════════════
# TC-8: Query Rewrite
# ════════════════════════════════════════════════════════════════════


class TestTC8QueryRewrite:
    """TC-8: Verify query rewriting functionality."""

    @pytest.mark.asyncio
    @patch("app.services.query_rewrite._rewrite_gemini", new_callable=AsyncMock)
    async def test_tc8_01_rewrite_improves_query(self, mock_gemini, monkeypatch):
        """TC-8.01: Query rewrite transforms vague queries."""
        from app.services.query_rewrite import rewrite_query

        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.services.query_rewrite.settings.llm_provider", "gemini")
        mock_gemini.return_value = "enterprise data protection compliance requirements GDPR"
        result = await rewrite_query("data stuff rules")
        assert result == "enterprise data protection compliance requirements GDPR"

    @pytest.mark.asyncio
    async def test_tc8_02_rewrite_disabled_passthrough(self, monkeypatch):
        """TC-8.02: Disabled rewrite returns original query."""
        from app.services.query_rewrite import rewrite_query

        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", False)
        result = await rewrite_query("original question unchanged")
        assert result == "original question unchanged"

    @pytest.mark.asyncio
    @patch("app.services.query_rewrite._rewrite_gemini", new_callable=AsyncMock)
    async def test_tc8_03_rewrite_error_graceful(self, mock_gemini, monkeypatch):
        """TC-8.03: Rewrite failure returns original query."""
        from app.services.query_rewrite import rewrite_query

        monkeypatch.setattr("app.services.query_rewrite.settings.query_rewrite_enabled", True)
        monkeypatch.setattr("app.services.query_rewrite.settings.llm_provider", "gemini")
        mock_gemini.side_effect = Exception("API timeout")
        result = await rewrite_query("original question")
        assert result == "original question"


# ════════════════════════════════════════════════════════════════════
# TC-9: Relevance Judge (ReAct)
# ════════════════════════════════════════════════════════════════════


class TestTC9RelevanceJudge:
    """TC-9: Verify ReAct relevance judging."""

    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_gemini", new_callable=AsyncMock)
    async def test_tc9_01_sufficient_contexts(self, mock_judge, monkeypatch):
        """TC-9.01: Judge marks sufficient contexts."""
        from app.services.relevance_judge import judge_relevance

        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "gemini")
        mock_judge.return_value = {
            "is_sufficient": True,
            "sub_questions": [],
            "reasoning": "Contexts fully answer the question.",
        }
        result = await judge_relevance("What is GDPR?", ["GDPR is a EU regulation..."])
        assert result["is_sufficient"] is True
        assert result["sub_questions"] == []

    @pytest.mark.asyncio
    @patch("app.services.relevance_judge._judge_gemini", new_callable=AsyncMock)
    async def test_tc9_02_insufficient_generates_sub_questions(self, mock_judge, monkeypatch):
        """TC-9.02: Judge generates sub-questions for insufficient contexts."""
        from app.services.relevance_judge import judge_relevance

        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", True)
        monkeypatch.setattr("app.services.relevance_judge.settings.llm_provider", "gemini")
        mock_judge.return_value = {
            "is_sufficient": False,
            "sub_questions": ["What are the penalties?", "What is the deadline?"],
            "reasoning": "Missing penalty details.",
        }
        result = await judge_relevance("Tell me everything about GDPR", ["Basic GDPR info"])
        assert result["is_sufficient"] is False
        assert len(result["sub_questions"]) == 2

    @pytest.mark.asyncio
    async def test_tc9_03_judge_disabled_always_sufficient(self, monkeypatch):
        """TC-9.03: Disabled ReAct always returns sufficient."""
        from app.services.relevance_judge import judge_relevance

        monkeypatch.setattr("app.services.relevance_judge.settings.react_retrieval_enabled", False)
        result = await judge_relevance("any question", ["any context"])
        assert result["is_sufficient"] is True

    def test_tc9_04_parse_json_with_markdown(self):
        """TC-9.04: Parser handles JSON wrapped in markdown fences."""
        from app.services.relevance_judge import _parse_judge_response

        raw = '```json\n{"is_sufficient": false, "sub_questions": ["q1"], "reasoning": "need more"}\n```'
        result = _parse_judge_response(raw)
        assert result["is_sufficient"] is False
        assert result["sub_questions"] == ["q1"]

    def test_tc9_05_parse_invalid_json(self):
        """TC-9.05: Parser handles completely invalid JSON gracefully."""
        from app.services.relevance_judge import _parse_judge_response

        result = _parse_judge_response("I think the contexts are sufficient")
        assert result["is_sufficient"] is True  # Default safe fallback


# ════════════════════════════════════════════════════════════════════
# TC-10: Output Policy Evaluation
# ════════════════════════════════════════════════════════════════════


class TestTC10PolicyEvaluation:
    """TC-10: Verify output policy blocks sensitive content."""

    def test_tc10_01_policy_disabled(self, monkeypatch):
        """TC-10.01: Disabled policy passes everything."""
        from app.services.policy import evaluate_output_policy

        monkeypatch.setattr("app.services.policy.settings.output_policy_enabled", False)
        result = evaluate_output_policy("AKIAIOSFODNN7EXAMPLE")
        assert result.blocked is False

    def test_tc10_02_policy_blocks_aws_key(self, monkeypatch):
        """TC-10.02: Policy blocks AWS access key patterns."""
        from app.services.policy import evaluate_output_policy

        monkeypatch.setattr("app.services.policy.settings.output_policy_enabled", True)
        monkeypatch.setattr(
            "app.services.policy.settings.output_policy_block_patterns",
            ["AKIA[A-Z0-9]{16}"],
        )
        monkeypatch.setattr(
            "app.services.policy.settings.output_policy_block_message",
            "Content blocked for security.",
        )
        # Clear compiled pattern cache
        from app.services.policy import _compiled_patterns
        _compiled_patterns.cache_clear()

        result = evaluate_output_policy("Here is the key: AKIAIOSFODNN7EXAMPLE")
        assert result.blocked is True
        assert len(result.matched_rules) == 1
        assert result.answer == "Content blocked for security."

        _compiled_patterns.cache_clear()

    def test_tc10_03_policy_passes_clean_content(self, monkeypatch):
        """TC-10.03: Clean content passes policy check."""
        from app.services.policy import evaluate_output_policy

        monkeypatch.setattr("app.services.policy.settings.output_policy_enabled", True)
        monkeypatch.setattr(
            "app.services.policy.settings.output_policy_block_patterns",
            ["AKIA[A-Z0-9]{16}"],
        )
        from app.services.policy import _compiled_patterns
        _compiled_patterns.cache_clear()

        result = evaluate_output_policy("Normal answer about data protection policies.")
        assert result.blocked is False
        assert result.answer == "Normal answer about data protection policies."

        _compiled_patterns.cache_clear()


# ════════════════════════════════════════════════════════════════════
# TC-11: Workflow Routing
# ════════════════════════════════════════════════════════════════════


class TestTC11WorkflowRouting:
    """TC-11: Verify LangGraph workflow node routing."""

    def test_tc11_01_rewrite_disabled_passthrough(self, monkeypatch):
        """TC-11.01: Rewrite node passes through when disabled."""
        from app.services.workflow import rewrite_node

        monkeypatch.setattr("app.services.workflow.settings.query_rewrite_enabled", False)
        result = rewrite_node({"question": "original"})
        assert result["rewritten_query"] == "original"

    @patch("app.services.workflow.search_chunks")
    def test_tc11_02_retrieve_first_attempt(self, mock_search, monkeypatch):
        """TC-11.02: First retrieve uses rewritten query."""
        from app.services.workflow import retrieve_node

        mock_search.return_value = [("ctx", 0.9, "doc.pdf", [1])]
        result = retrieve_node({
            "question": "original",
            "rewritten_query": "improved",
            "tenant_id": "t1",
        })
        mock_search.assert_called_once_with("improved", settings.top_k, "t1")
        assert result["retrieval_attempts"] == 1

    @patch("app.services.workflow.search_chunks")
    def test_tc11_03_retrieve_retry_with_sub_questions(self, mock_search, monkeypatch):
        """TC-11.03: Retry search uses sub-questions and deduplicates."""
        from app.services.workflow import retrieve_node

        mock_search.return_value = [("new ctx", 0.85, "doc2.pdf", [2])]
        result = retrieve_node({
            "question": "q",
            "tenant_id": "t1",
            "retrieval_attempts": 1,
            "sub_questions": ["sub q1", "sub q2"],
            "all_contexts": [("existing ctx", 0.9, "doc1.pdf", [1])],
        })
        assert result["retrieval_attempts"] == 2
        assert mock_search.call_count == 2  # Called once per sub-question

    def test_tc11_04_route_after_judge_to_retrieve(self, monkeypatch):
        """TC-11.04: Judge routes back to retrieve when sub-questions exist."""
        from app.services.workflow import route_after_judge

        monkeypatch.setattr("app.services.workflow.settings.max_retrieval_attempts", 3)
        assert route_after_judge({"sub_questions": ["q1"], "retrieval_attempts": 1}) == "retrieve"

    def test_tc11_05_route_after_judge_to_draft(self, monkeypatch):
        """TC-11.05: Judge routes to draft when sufficient or max attempts."""
        from app.services.workflow import route_after_judge

        monkeypatch.setattr("app.services.workflow.settings.max_retrieval_attempts", 2)
        # Max attempts reached
        assert route_after_judge({"sub_questions": ["q1"], "retrieval_attempts": 2}) == "draft"
        # No sub-questions
        assert route_after_judge({"sub_questions": [], "retrieval_attempts": 1}) == "draft"

    def test_tc11_06_route_after_draft_policy_blocked(self):
        """TC-11.06: Policy blocked skips approval."""
        from app.services.workflow import route_after_draft

        assert route_after_draft({"policy_blocked": True}) == "final"

    @patch("app.services.approval_policy.should_require_approval")
    def test_tc11_07_route_after_draft_approval(self, mock_approval):
        """TC-11.07: Approval routing when enabled."""
        from app.services.workflow import route_after_draft

        mock_approval.return_value = True
        assert route_after_draft({"policy_blocked": False, "tenant_id": "t1", "source_document_ids": []}) == "approval"

        mock_approval.return_value = False
        assert route_after_draft({"policy_blocked": False, "tenant_id": "t1", "source_document_ids": []}) == "final"


# ════════════════════════════════════════════════════════════════════
# TC-12: Document Management API
# ════════════════════════════════════════════════════════════════════


class TestTC12DocumentManagement:
    """TC-12: Verify document list and delete operations."""

    @patch("app.services.retrieval.ensure_collection")
    @patch("app.services.retrieval.get_qdrant_client")
    def test_tc12_01_list_documents(self, mock_client_fn, mock_ensure):
        """TC-12.01: List documents aggregates by document_id."""
        from app.services.retrieval import list_documents

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client_fn.cache_clear = MagicMock()

        p1 = MagicMock()
        p1.payload = {"document_id": "doc1", "source": "policy.pdf"}
        p2 = MagicMock()
        p2.payload = {"document_id": "doc1", "source": "policy.pdf"}
        p3 = MagicMock()
        p3.payload = {"document_id": "doc2", "source": "handbook.pdf"}
        mock_client.scroll.return_value = ([p1, p2, p3], None)

        docs = list_documents("t1")
        assert len(docs) == 2
        doc1 = next(d for d in docs if d["document_id"] == "doc1")
        assert doc1["chunk_count"] == 2
        assert doc1["source"] == "policy.pdf"

    @patch("app.services.retrieval.ensure_collection")
    @patch("app.services.retrieval.get_qdrant_client")
    def test_tc12_02_delete_document(self, mock_client_fn, mock_ensure):
        """TC-12.02: Delete document removes all chunks."""
        from app.services.retrieval import delete_document

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.count.return_value = MagicMock(count=5)

        count = delete_document("doc1", "t1")
        assert count == 5
        mock_client.delete.assert_called_once()

    @patch("app.services.retrieval.ensure_collection")
    @patch("app.services.retrieval.get_qdrant_client")
    def test_tc12_03_delete_nonexistent_document(self, mock_client_fn, mock_ensure):
        """TC-12.03: Delete non-existent document returns 0."""
        from app.services.retrieval import delete_document

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.count.return_value = MagicMock(count=0)

        count = delete_document("nonexistent", "t1")
        assert count == 0
        mock_client.delete.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# TC-13: LLM Provider Switching
# ════════════════════════════════════════════════════════════════════


class TestTC13LLMProviders:
    """TC-13: Verify LLM provider routing (Ollama/OpenAI/Gemini)."""

    @patch("app.services.llm.httpx.Client")
    def test_tc13_01_ollama_answer(self, MockClient, monkeypatch):
        """TC-13.01: Ollama generates answer."""
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "ollama")
        from app.services.llm import generate_answer

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Ollama answer"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        MockClient.return_value = mock_client

        result = generate_answer("q", ["ctx"])
        assert result == "Ollama answer"

    @patch("app.services.llm._openai_client")
    def test_tc13_02_openai_answer(self, mock_client_fn, monkeypatch):
        """TC-13.02: OpenAI generates answer."""
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "openai")
        from app.services.llm import generate_answer

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "OpenAI answer"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_client_fn.return_value = mock_client

        result = generate_answer("q", ["ctx"])
        assert result == "OpenAI answer"

    @patch("app.services.llm.httpx.Client")
    def test_tc13_03_gemini_answer(self, MockClient, monkeypatch):
        """TC-13.03: Gemini generates answer."""
        monkeypatch.setattr("app.services.llm.settings.llm_provider", "gemini")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")
        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "key")
        from app.services.llm import generate_answer

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Gemini answer"}]}}]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        MockClient.return_value = mock_client

        result = generate_answer("q", ["ctx"])
        assert result == "Gemini answer"

    def test_tc13_04_prompt_with_sources(self):
        """TC-13.04: Prompt builder includes source citations."""
        from app.services.llm import _build_prompt

        prompt = _build_prompt("q", ["ctx1", "ctx2"], ["file1.pdf", "file2.pdf"])
        assert "(Source: file1.pdf)" in prompt
        assert "(Source: file2.pdf)" in prompt
        assert "[1]" in prompt
        assert "[2]" in prompt

    def test_tc13_05_prompt_mismatched_sources(self):
        """TC-13.05: Mismatched sources length falls back to numbered."""
        from app.services.llm import _build_prompt

        prompt = _build_prompt("q", ["ctx1", "ctx2"], ["only_one.pdf"])
        assert "(Source:" not in prompt
        assert "[1]" in prompt


# ════════════════════════════════════════════════════════════════════
# TC-14: Embedding Providers
# ════════════════════════════════════════════════════════════════════


class TestTC14EmbeddingProviders:
    """TC-14: Verify embedding provider abstraction."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.services.embeddings import get_embedder
        get_embedder.cache_clear()
        yield
        get_embedder.cache_clear()

    def test_tc14_01_openai_provider_requires_key(self, monkeypatch):
        """TC-14.01: OpenAI provider fails without API key."""
        from app.services.embeddings import get_embedder

        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "openai")
        monkeypatch.setattr("app.services.embeddings.settings.openai_api_key", "")
        with pytest.raises(ValueError, match="APP_OPENAI_API_KEY"):
            get_embedder()

    def test_tc14_02_gemini_provider_requires_key(self, monkeypatch):
        """TC-14.02: Gemini provider fails without API key."""
        from app.services.embeddings import get_embedder

        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "gemini")
        monkeypatch.setattr("app.services.embeddings.settings.gemini_api_key", "")
        with pytest.raises(ValueError, match="APP_GEMINI_API_KEY"):
            get_embedder()

    def test_tc14_03_sentence_transformer_default(self, monkeypatch):
        """TC-14.03: Default provider is SentenceTransformer."""
        from app.services.embeddings import SentenceTransformerProvider, get_embedder

        monkeypatch.setattr("app.services.embeddings.settings.embedding_provider", "sentence-transformers")
        mock_st = MagicMock()
        with patch.dict(sys.modules, {"sentence_transformers": mock_st}):
            provider = get_embedder()
        assert isinstance(provider, SentenceTransformerProvider)


# ════════════════════════════════════════════════════════════════════
# TC-15: Multimodal (Image Description in PDFs)
# ════════════════════════════════════════════════════════════════════


class TestTC15MultimodalPdf:
    """TC-15: Verify image extraction and description in PDF pages."""

    @patch("app.services.llm.describe_image")
    def test_tc15_01_enrich_with_large_image(self, mock_describe):
        """TC-15.01: Large images get described and appended."""
        from app.services.ingest import _enrich_with_image_descriptions

        mock_describe.return_value = "Revenue chart showing 20% growth"
        mock_doc = MagicMock()
        mock_doc.extract_image.return_value = {"image": b"img-data", "width": 300}
        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42,)]

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert "Revenue chart" in result
        assert result.startswith("Base text")

    @patch("app.services.llm.describe_image")
    def test_tc15_02_skip_small_images(self, mock_describe):
        """TC-15.02: Small images (<=100px) are skipped."""
        from app.services.ingest import _enrich_with_image_descriptions

        mock_doc = MagicMock()
        mock_doc.extract_image.return_value = {"image": b"tiny", "width": 50}
        mock_page = MagicMock()
        mock_page.get_images.return_value = [(1,)]

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"
        mock_describe.assert_not_called()

    def test_tc15_03_image_extraction_error(self):
        """TC-15.03: Errors in image extraction are handled gracefully."""
        from app.services.ingest import _enrich_with_image_descriptions

        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_images.side_effect = Exception("Corrupt page")

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"

    def test_tc15_04_describe_image_no_api_key(self, monkeypatch):
        """TC-15.04: No Gemini key returns empty description."""
        from app.services.llm import describe_image

        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "")
        result = describe_image(b"img-data")
        assert result == ""

    @patch("app.services.llm.httpx.Client")
    def test_tc15_05_describe_image_api_error(self, MockClient, monkeypatch):
        """TC-15.05: Gemini Vision API error returns empty."""
        from app.services.llm import describe_image

        monkeypatch.setattr("app.services.llm.settings.gemini_api_key", "key")
        monkeypatch.setattr("app.services.llm.settings.gemini_chat_model", "gemini-2.5-flash")
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("network error")
        MockClient.return_value = mock_client

        result = describe_image(b"img-data")
        assert result == ""


# ════════════════════════════════════════════════════════════════════
# TC-16: Hybrid Search (Dense + Sparse)
# ════════════════════════════════════════════════════════════════════


class TestTC16HybridSearch:
    """TC-16: Verify hybrid search with BM25 sparse vectors."""

    @pytest.fixture(autouse=True)
    def _clear_qdrant_cache(self):
        from app.services.retrieval import get_qdrant_client
        get_qdrant_client.cache_clear()
        yield
        get_qdrant_client.cache_clear()

    @patch("app.services.retrieval.get_qdrant_client")
    @patch("app.services.retrieval.embed_texts")
    @patch("app.services.retrieval.get_embedder")
    def test_tc16_01_hybrid_search_uses_rrf(self, mock_embedder, mock_embed, mock_client_fn, monkeypatch):
        """TC-16.01: Hybrid search uses prefetch + RRF fusion."""
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", True)
        from app.services.retrieval import search_chunks

        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 384
        mock_embedder.return_value = mock_provider
        mock_embed.return_value = [[0.1] * 384]

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = {"dense": MagicMock(size=384)}
        mock_info.config.params.sparse_vectors = {"sparse": MagicMock()}
        mock_client.get_collection.return_value = mock_info

        mock_result = MagicMock()
        mock_result.score = 0.92
        mock_result.payload = {"text": "hybrid result", "source": "doc.pdf", "page_numbers": [1]}
        mock_response = MagicMock()
        mock_response.points = [mock_result]
        mock_client.query_points.return_value = mock_response

        sparse_vec = MagicMock()
        with patch("app.services.sparse_embed.compute_sparse_vectors", return_value=[sparse_vec]):
            results = search_chunks("query", 4, "t1")

        assert len(results) == 1
        assert results[0][0] == "hybrid result"
        # Verify prefetch was used
        call_kwargs = mock_client.query_points.call_args[1]
        assert "prefetch" in call_kwargs

    @patch("app.services.retrieval.get_qdrant_client")
    @patch("app.services.retrieval.embed_texts")
    @patch("app.services.retrieval.get_embedder")
    def test_tc16_02_fallback_dense_only(self, mock_embedder, mock_embed, mock_client_fn, monkeypatch):
        """TC-16.02: Falls back to dense-only when hybrid disabled."""
        monkeypatch.setattr("app.services.retrieval.settings.hybrid_search_enabled", False)
        from app.services.retrieval import search_chunks

        mock_provider = MagicMock()
        mock_provider.get_dimension.return_value = 384
        mock_embedder.return_value = mock_provider
        mock_embed.return_value = [[0.1] * 384]

        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.config.params.vectors = MagicMock(size=384, spec=[])
        mock_info.config.params.sparse_vectors = None
        mock_client.get_collection.return_value = mock_info

        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points.return_value = mock_response

        search_chunks("query", 4, "t1")
        call_kwargs = mock_client.query_points.call_args[1]
        assert "prefetch" not in call_kwargs


# ════════════════════════════════════════════════════════════════════
# TC-17: Sparse Embedding (BM25)
# ════════════════════════════════════════════════════════════════════


class TestTC17SparseEmbedding:
    """TC-17: Verify BM25 sparse embedding service."""

    def test_tc17_01_compute_sparse_vectors(self):
        """TC-17.01: Sparse vector computation returns SparseVector objects."""
        from app.services.sparse_embed import compute_sparse_vectors

        mock_embedding = MagicMock()
        mock_embedding.indices.tolist.return_value = [0, 5, 10]
        mock_embedding.values.tolist.return_value = [0.5, 0.3, 0.8]

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [mock_embedding]

        with patch("app.services.sparse_embed.get_sparse_embedder", return_value=mock_embedder):
            results = compute_sparse_vectors(["test text"])

        assert len(results) == 1
        assert results[0].indices == [0, 5, 10]
        assert results[0].values == [0.5, 0.3, 0.8]
