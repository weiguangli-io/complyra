"""Tests for the document ingestion pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.ingest import (
    ChunkWithMetadata,
    PageContent,
    chunk_text,
    extract_text_from_bytes,
    extract_text_from_pdf,
    ingest_document,
    ingest_document_from_path,
    normalize_ingest_filename,
    smart_chunk_text,
    validate_ingest_filename,
    _enrich_with_image_descriptions,
)


class TestExtractTextFromBytes:
    def test_decodes_utf8(self):
        text = extract_text_from_bytes(b"hello world")
        assert text == "hello world"

    def test_handles_invalid_encoding(self):
        text = extract_text_from_bytes(b"\xff\xfe")
        assert isinstance(text, str)


class TestExtractTextFromPdf:
    def test_extracts_pages(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", False)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        page1 = MagicMock()
        page1.get_text.return_value = "Page 1 content"
        page2 = MagicMock()
        page2.get_text.return_value = "Page 2 content"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([page1, page2]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        import sys
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"fake-pdf-bytes")

        assert len(result) == 2
        assert result[0].text == "Page 1 content"
        assert result[0].page_number == 1
        assert result[1].text == "Page 2 content"
        assert result[1].page_number == 2

    def test_handles_empty_page_text(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", False)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        page = MagicMock()
        page.get_text.return_value = ""
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        import sys
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"fake-pdf")

        assert len(result) == 1
        assert result[0].text == ""

    @patch("app.services.ingest._ocr_page")
    def test_ocr_fallback_when_text_short(self, mock_ocr, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", True)
        monkeypatch.setattr("app.services.ingest.settings.ocr_min_text_threshold", 50)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        page = MagicMock()
        page.get_text.return_value = "ab"  # short text triggers OCR
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        mock_ocr.return_value = "OCR extracted text from scanned page"

        import sys
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"scanned-pdf")

        assert len(result) == 1
        assert result[0].text == "OCR extracted text from scanned page"
        mock_ocr.assert_called_once_with(page)


class TestChunkText:
    def test_chunks_long_text(self):
        text = "a " * 1000
        chunks = chunk_text(text)
        assert len(chunks) > 1

    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_single_chunk(self):
        chunks = chunk_text("short text here")
        assert len(chunks) == 1
        assert chunks[0] == "short text here"

    def test_whitespace_normalized(self):
        chunks = chunk_text("hello   world\n\nfoo")
        assert chunks[0] == "hello world foo"


class TestSmartChunkText:
    def test_paragraph_splitting(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 100)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 20)

        pages = [
            PageContent(text="First paragraph.\n\nSecond paragraph.", page_number=1),
            PageContent(text="Third paragraph on page two.", page_number=2),
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 1
        assert all(isinstance(c, ChunkWithMetadata) for c in chunks)
        # All chunks should have page numbers
        for c in chunks:
            assert len(c.page_numbers) >= 1

    def test_tracks_page_numbers(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 200)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)

        pages = [
            PageContent(text="Short text on page 1.", page_number=1),
            PageContent(text="Short text on page 2.", page_number=2),
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 1
        # First chunk should reference page 1
        assert 1 in chunks[0].page_numbers

    def test_empty_pages_returns_empty(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 100)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)

        pages = [PageContent(text="   ", page_number=1)]
        chunks = smart_chunk_text(pages)
        assert chunks == []

    def test_large_paragraph_splits_by_sentence(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 50)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 10)

        long_para = "This is sentence one. This is sentence two. This is sentence three."
        pages = [PageContent(text=long_para, page_number=1)]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 1
        for c in chunks:
            assert 1 in c.page_numbers


class TestEnrichWithImageDescriptions:
    @patch("app.services.llm.describe_image")
    def test_appends_image_description(self, mock_describe):
        mock_describe.return_value = "A chart showing revenue growth"

        mock_doc = MagicMock()
        mock_doc.extract_image.return_value = {
            "image": b"fake-image-bytes",
            "width": 200,
        }

        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42,)]  # list of image info tuples

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert "[Image description: A chart showing revenue growth]" in result
        assert result.startswith("Base text")

    @patch("app.services.llm.describe_image")
    def test_skips_small_images(self, mock_describe):
        mock_doc = MagicMock()
        mock_doc.extract_image.return_value = {
            "image": b"tiny-icon",
            "width": 50,
        }

        mock_page = MagicMock()
        mock_page.get_images.return_value = [(1,)]

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"
        mock_describe.assert_not_called()

    def test_handles_get_images_exception(self):
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_images.side_effect = Exception("corrupt page")

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"


class TestNormalizeIngestFilename:
    def test_valid_filename(self):
        assert normalize_ingest_filename("report.pdf") == "report.pdf"

    def test_strips_directory_traversal(self):
        result = normalize_ingest_filename("../../etc/passwd.txt")
        assert "/" not in result
        assert result.endswith(".txt")

    def test_sanitizes_special_chars(self):
        result = normalize_ingest_filename("my file (1).pdf")
        assert " " not in result
        assert "(" not in result

    def test_empty_filename_raises(self):
        with pytest.raises(ValueError, match="Filename is required"):
            normalize_ingest_filename("")

    def test_no_extension_raises(self):
        with pytest.raises(ValueError, match="extension"):
            normalize_ingest_filename("noextension")

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            normalize_ingest_filename("file.exe")

    def test_fallback_name_for_special_chars_only(self):
        result = normalize_ingest_filename("!!!.pdf")
        assert result == "document.pdf"


class TestValidateIngestFilename:
    def test_returns_extension(self):
        assert validate_ingest_filename("doc.pdf") == "pdf"

    def test_returns_txt(self):
        assert validate_ingest_filename("notes.txt") == "txt"

    def test_returns_md(self):
        assert validate_ingest_filename("readme.md") == "md"


class TestIngestDocument:
    @patch("app.services.ingest.upsert_chunks")
    def test_ingests_txt(self, mock_upsert):
        mock_upsert.return_value = "doc-123"
        doc_id, count = ingest_document(b"some content here", "file.txt", "tenant1")
        assert doc_id == "doc-123"
        assert count > 0

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.ingest.extract_text_from_pdf")
    def test_ingests_pdf_smart(self, mock_pdf, mock_upsert, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunking_strategy", "smart")
        mock_pdf.return_value = [
            PageContent(text="Page 1 text paragraph.", page_number=1),
            PageContent(text="Page 2 text paragraph.", page_number=2),
        ]
        mock_upsert.return_value = "doc-456"
        doc_id, count = ingest_document(b"pdf-bytes", "report.pdf", "tenant1")
        assert doc_id == "doc-456"
        assert count > 0
        mock_pdf.assert_called_once()

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.ingest.extract_text_from_pdf")
    def test_ingests_pdf_fixed(self, mock_pdf, mock_upsert, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunking_strategy", "fixed")
        mock_pdf.return_value = [
            PageContent(text="Page 1 text.", page_number=1),
        ]
        mock_upsert.return_value = "doc-789"
        doc_id, count = ingest_document(b"pdf-bytes", "report.pdf", "tenant1")
        assert doc_id == "doc-789"
        assert count > 0

    @patch("app.services.ingest.upsert_chunks")
    def test_empty_content_returns_no_chunks(self, mock_upsert):
        doc_id, count = ingest_document(b"", "empty.txt", "tenant1")
        assert doc_id == ""
        assert count == 0
        mock_upsert.assert_not_called()


class TestIngestDocumentFromPath:
    @patch("app.services.ingest.ingest_document")
    def test_reads_file_and_delegates(self, mock_ingest, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content")
        mock_ingest.return_value = ("doc-789", 1)

        doc_id, count = ingest_document_from_path(str(test_file), "test.txt", "t1")
        assert doc_id == "doc-789"
        mock_ingest.assert_called_once()


class TestOcrPage:
    def test_ocr_page(self, monkeypatch):
        from app.services.ingest import _ocr_page

        monkeypatch.setattr("app.services.ingest.settings.ocr_language", "eng")

        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.width = 100
        mock_pix.height = 100
        mock_pix.samples = b"\x00" * (100 * 100 * 3)
        mock_page.get_pixmap.return_value = mock_pix

        mock_tesseract = MagicMock()
        mock_tesseract.image_to_string.return_value = "OCR text"

        mock_pil_image = MagicMock()
        mock_img = MagicMock()
        mock_pil_image.frombytes.return_value = mock_img

        import sys
        with patch.dict(sys.modules, {
            "pytesseract": mock_tesseract,
            "PIL": MagicMock(Image=mock_pil_image),
            "PIL.Image": mock_pil_image,
        }):
            result = _ocr_page(mock_page)
            assert result == "OCR text"


class TestEnrichWithImageDescriptionsEdge:
    @patch("app.services.llm.describe_image")
    def test_skips_image_without_image_key(self, mock_describe):
        mock_doc = MagicMock()
        mock_doc.extract_image.return_value = {"width": 200}  # no "image" key

        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42,)]

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"
        mock_describe.assert_not_called()

    @patch("app.services.llm.describe_image")
    def test_skips_empty_description(self, mock_describe):
        mock_describe.return_value = ""

        mock_doc = MagicMock()
        mock_doc.extract_image.return_value = {"image": b"data", "width": 200}

        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42,)]

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"

    @patch("app.services.llm.describe_image")
    def test_handles_extract_image_exception(self, mock_describe):
        mock_doc = MagicMock()
        mock_doc.extract_image.side_effect = Exception("corrupt image")

        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42,)]

        result = _enrich_with_image_descriptions(mock_doc, mock_page, "Base text")
        assert result == "Base text"


class TestExtractTextFromPdfOcrException:
    @patch("app.services.ingest._ocr_page")
    def test_ocr_exception_keeps_fitz_text(self, mock_ocr, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", True)
        monkeypatch.setattr("app.services.ingest.settings.ocr_min_text_threshold", 50)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        page = MagicMock()
        page.get_text.return_value = "ab"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        mock_ocr.side_effect = Exception("tesseract not found")

        import sys
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"pdf-bytes")
        assert result[0].text == "ab"

    @patch("app.services.ingest._ocr_page")
    def test_ocr_returns_empty_keeps_fitz_text(self, mock_ocr, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", True)
        monkeypatch.setattr("app.services.ingest.settings.ocr_min_text_threshold", 50)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", False)

        page = MagicMock()
        page.get_text.return_value = "ab"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        mock_ocr.return_value = "   "  # empty OCR text

        import sys
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"pdf-bytes")
        assert result[0].text == "ab"

    @patch("app.services.ingest._enrich_with_image_descriptions")
    def test_multimodal_enabled(self, mock_enrich, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.ocr_enabled", False)
        monkeypatch.setattr("app.services.ingest.settings.multimodal_enabled", True)

        page = MagicMock()
        page.get_text.return_value = "Page text"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        mock_enrich.return_value = "Page text\n\n[Image description: chart]"

        import sys
        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = extract_text_from_pdf(b"pdf-bytes")
        assert "[Image description: chart]" in result[0].text
        mock_enrich.assert_called_once()


class TestSmartChunkTextEdgeCases:
    def test_overlap_carry_over(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 40)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 10)

        # Create segments that force multiple chunks with overlap
        pages = [
            PageContent(text="First paragraph text here.\n\nSecond paragraph text here.", page_number=1),
            PageContent(text="Third paragraph that is also long.", page_number=2),
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 2
        # Verify chunk indices are sequential
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_single_segment_exceeds_chunk_size(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 10)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)

        pages = [
            PageContent(text="This is a very long single paragraph without any paragraph breaks at all that exceeds chunk size.", page_number=1),
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 1

    def test_zero_overlap(self, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 30)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 0)

        pages = [
            PageContent(text="Short para.\n\nAnother para.\n\nThird para here.", page_number=1),
        ]
        chunks = smart_chunk_text(pages)
        assert len(chunks) >= 1


class TestIngestDocumentImages:
    @pytest.fixture(autouse=True)
    def _allow_images(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.ingest.settings.ingest_allowed_extensions",
            ["pdf", "txt", "md", "png", "jpg", "jpeg"],
        )

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.llm.describe_image")
    def test_ingests_image_file(self, mock_describe, mock_upsert):
        mock_describe.return_value = "A photo of a document"
        mock_upsert.return_value = "doc-img-123"

        doc_id, count = ingest_document(b"png-bytes", "photo.png", "tenant1")
        assert doc_id == "doc-img-123"
        assert count == 1

    @patch("app.services.llm.describe_image")
    def test_ingests_image_empty_description(self, mock_describe):
        mock_describe.return_value = ""

        doc_id, count = ingest_document(b"png-bytes", "photo.png", "tenant1")
        assert doc_id == ""
        assert count == 0

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.llm.describe_image")
    def test_ingests_jpeg_file(self, mock_describe, mock_upsert):
        mock_describe.return_value = "JPEG image content"
        mock_upsert.return_value = "doc-jpg-123"

        doc_id, count = ingest_document(b"jpeg-bytes", "photo.jpeg", "tenant1")
        assert doc_id == "doc-jpg-123"
        assert count == 1

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.llm.describe_image")
    def test_ingests_jpg_file(self, mock_describe, mock_upsert):
        mock_describe.return_value = "JPG image content"
        mock_upsert.return_value = "doc-jpg-456"

        doc_id, count = ingest_document(b"jpg-bytes", "photo.jpg", "tenant1")
        assert doc_id == "doc-jpg-456"
        assert count == 1

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.llm.describe_image")
    def test_ingests_image_large_description_chunks(self, mock_describe, mock_upsert, monkeypatch):
        # Make chunk_size very small so the image text gets chunked
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 10)
        monkeypatch.setattr("app.services.ingest.settings.chunk_overlap", 2)
        mock_describe.return_value = "A very long detailed description of an image that exceeds the chunk size"
        mock_upsert.return_value = "doc-chunked"

        doc_id, count = ingest_document(b"png-bytes", "photo.png", "tenant1")
        assert doc_id == "doc-chunked"
        assert count > 1  # multiple chunks

    @patch("app.services.ingest.chunk_text")
    @patch("app.services.llm.describe_image")
    def test_ingests_image_empty_chunks(self, mock_describe, mock_chunk, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunk_size", 5)
        mock_describe.return_value = "Some description"
        mock_chunk.return_value = []  # force empty chunks

        doc_id, count = ingest_document(b"png-bytes", "photo.png", "tenant1")
        assert doc_id == ""
        assert count == 0


class TestIngestDocumentPdfEdgeCases:
    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.ingest.extract_text_from_pdf")
    def test_smart_chunking_empty_returns_zero(self, mock_pdf, mock_upsert, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunking_strategy", "smart")
        mock_pdf.return_value = [PageContent(text="   ", page_number=1)]

        doc_id, count = ingest_document(b"pdf-bytes", "empty.pdf", "tenant1")
        assert doc_id == ""
        assert count == 0
        mock_upsert.assert_not_called()

    @patch("app.services.ingest.upsert_chunks")
    @patch("app.services.ingest.extract_text_from_pdf")
    def test_fixed_chunking_empty_returns_zero(self, mock_pdf, mock_upsert, monkeypatch):
        monkeypatch.setattr("app.services.ingest.settings.chunking_strategy", "fixed")
        mock_pdf.return_value = [PageContent(text="   ", page_number=1)]

        doc_id, count = ingest_document(b"pdf-bytes", "empty.pdf", "tenant1")
        assert doc_id == ""
        assert count == 0
        mock_upsert.assert_not_called()
