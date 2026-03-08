"""Document ingestion pipeline.

Handles text extraction (PDF, plain text, images), chunking with overlap,
filename sanitization, and vector upsert into Qdrant.
Supports OCR fallback via pytesseract for scanned PDF pages and
multimodal image description via Gemini Vision.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

from app.core.config import settings
from app.services.retrieval import upsert_chunks

logger = logging.getLogger(__name__)

FILENAME_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class PageContent:
    """Text content extracted from a single PDF page."""
    text: str
    page_number: int


@dataclass
class ChunkWithMetadata:
    """A text chunk with metadata about its source pages."""
    text: str
    page_numbers: List[int] = field(default_factory=list)
    chunk_index: int = 0


def _ocr_page(page) -> str:
    """Run OCR on a PDF page using pytesseract."""
    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return pytesseract.image_to_string(img, lang=settings.ocr_language)


def _enrich_with_image_descriptions(doc, page, text: str) -> str:
    """Extract images from a PDF page and append Gemini Vision descriptions.

    Only processes images wider than 100 pixels to skip tiny icons/decorations.
    """
    from app.services.llm import describe_image

    try:
        image_list = page.get_images(full=True)
    except Exception:
        return text

    for img_info in image_list:
        xref = img_info[0]
        try:
            base_image = doc.extract_image(xref)
            if not base_image or "image" not in base_image:
                continue
            width = base_image.get("width", 0)
            if width <= 100:
                continue
            image_bytes = base_image["image"]
            description = describe_image(image_bytes)
            if description:
                text += f"\n\n[Image description: {description}]"
        except Exception:
            logger.debug("Failed to extract/describe image xref=%d", xref)
            continue

    return text


def extract_text_from_pdf(file_bytes: bytes) -> List[PageContent]:
    """Extract text from a PDF, with optional OCR fallback for scanned pages.

    Returns a list of PageContent with text and 1-based page numbers.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: List[PageContent] = []

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text() or ""

        if settings.ocr_enabled and len(text.strip()) < settings.ocr_min_text_threshold:
            try:
                ocr_text = _ocr_page(page)
                if ocr_text.strip():
                    text = ocr_text
            except Exception:
                pass  # Keep whatever text we got from fitz

        # Multimodal: extract and describe images on the page
        if settings.multimodal_enabled:
            text = _enrich_with_image_descriptions(doc, page, text)

        pages.append(PageContent(text=text, page_number=page_num))

    doc.close()
    return pages


def extract_text_from_bytes(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="ignore")


def chunk_text(text: str) -> List[str]:
    """Original fixed-size chunking (character-level with overlap)."""
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    chunks: List[str] = []
    step = max(settings.chunk_size - settings.chunk_overlap, 1)
    for start in range(0, len(normalized_text), step):
        end = start + settings.chunk_size
        chunk = normalized_text[start:end]
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized_text):
            break
    return chunks


def smart_chunk_text(pages: List[PageContent]) -> List[ChunkWithMetadata]:
    """Split pages into chunks using paragraph and sentence boundaries.

    Each chunk tracks which page(s) it came from. Respects chunk_size
    and chunk_overlap from settings.
    """
    chunk_size = settings.chunk_size
    chunk_overlap = settings.chunk_overlap

    # Build a list of (paragraph_text, page_number) tuples
    paragraphs: List[Tuple[str, int]] = []
    for page in pages:
        # Split by double newlines (paragraph boundaries)
        raw_paragraphs = re.split(r"\n\s*\n", page.text)
        for para in raw_paragraphs:
            cleaned = para.strip()
            if cleaned:
                paragraphs.append((cleaned, page.page_number))

    if not paragraphs:
        return []

    # Split paragraphs that exceed chunk_size into sentences
    segments: List[Tuple[str, int]] = []
    sentence_pattern = re.compile(r"(?<=[.!?。！？])\s+")
    for para_text, page_num in paragraphs:
        if len(para_text) <= chunk_size:
            segments.append((para_text, page_num))
        else:
            sentences = sentence_pattern.split(para_text)
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence:
                    segments.append((sentence, page_num))

    # Merge segments into chunks respecting chunk_size
    chunks: List[ChunkWithMetadata] = []
    current_text = ""
    current_pages: List[int] = []
    chunk_index = 0

    for seg_text, page_num in segments:
        candidate = (current_text + "\n\n" + seg_text).strip() if current_text else seg_text

        if len(candidate) <= chunk_size:
            current_text = candidate
            if page_num not in current_pages:
                current_pages.append(page_num)
        else:
            # Flush current chunk
            if current_text:
                chunks.append(ChunkWithMetadata(
                    text=current_text,
                    page_numbers=list(current_pages),
                    chunk_index=chunk_index,
                ))
                chunk_index += 1

                # Handle overlap: keep tail of current_text
                if chunk_overlap > 0 and len(current_text) > chunk_overlap:
                    overlap_text = current_text[-chunk_overlap:]
                    current_text = (overlap_text + "\n\n" + seg_text).strip()
                    current_pages = list(current_pages)  # carry over pages from overlap
                    if page_num not in current_pages:
                        current_pages.append(page_num)
                else:
                    current_text = seg_text
                    current_pages = [page_num]
            else:
                # Single segment exceeds chunk_size; include it as-is
                current_text = seg_text
                current_pages = [page_num]

    # Flush remaining
    if current_text.strip():
        chunks.append(ChunkWithMetadata(
            text=current_text,
            page_numbers=list(current_pages),
            chunk_index=chunk_index,
        ))

    return chunks


def normalize_ingest_filename(filename: str) -> str:
    if not filename:
        raise ValueError("Filename is required")

    # Keep only the basename to prevent directory traversal payloads.
    basename = Path(filename).name.strip()
    if not basename or "." not in basename:
        raise ValueError("Filename must include an extension")

    name_part, extension = basename.rsplit(".", 1)
    extension = extension.lower()
    if extension not in settings.ingest_allowed_extensions:
        allowed = ", ".join(settings.ingest_allowed_extensions)
        raise ValueError(f"Unsupported file type. Allowed extensions: {allowed}")

    normalized_name = FILENAME_SANITIZE_PATTERN.sub("_", name_part).strip("._-")
    if not normalized_name:
        normalized_name = "document"

    return f"{normalized_name}.{extension}"


def validate_ingest_filename(filename: str) -> str:
    normalized = normalize_ingest_filename(filename)
    return normalized.rsplit(".", 1)[-1]


def ingest_document(file_bytes: bytes, filename: str, tenant_id: str) -> Tuple[str, int]:
    import time
    from app.core.metrics import DOCUMENT_INGEST_TOTAL, DOCUMENT_INGEST_DURATION, CHUNKS_PRODUCED_TOTAL

    ingest_start = time.perf_counter()
    extension = validate_ingest_filename(filename)

    try:
        if extension in ("png", "jpg", "jpeg"):
            from app.services.llm import describe_image

            description = describe_image(file_bytes)
            if not description:
                DOCUMENT_INGEST_TOTAL.labels(file_type=extension, status="empty").inc()
                return "", 0
            text = f"[Image: {filename}]\n\n[Image description: {description}]"
            chunks = chunk_text(text) if len(text) > settings.chunk_size else [text]
            if not chunks:
                DOCUMENT_INGEST_TOTAL.labels(file_type=extension, status="empty").inc()
                return "", 0
            document_id = upsert_chunks(chunks, source=filename, tenant_id=tenant_id)
            CHUNKS_PRODUCED_TOTAL.inc(len(chunks))
            DOCUMENT_INGEST_TOTAL.labels(file_type=extension, status="success").inc()
            DOCUMENT_INGEST_DURATION.labels(file_type=extension).observe(time.perf_counter() - ingest_start)
            return document_id, len(chunks)
        elif extension == "pdf":
            pages = extract_text_from_pdf(file_bytes)

            if settings.chunking_strategy == "smart":
                smart_chunks = smart_chunk_text(pages)
                if not smart_chunks:
                    DOCUMENT_INGEST_TOTAL.labels(file_type="pdf", status="empty").inc()
                    return "", 0
                chunk_texts = [c.text for c in smart_chunks]
                chunk_page_numbers = [c.page_numbers for c in smart_chunks]
                document_id = upsert_chunks(
                    chunk_texts,
                    source=filename,
                    tenant_id=tenant_id,
                    page_numbers=chunk_page_numbers,
                )
                CHUNKS_PRODUCED_TOTAL.inc(len(smart_chunks))
                DOCUMENT_INGEST_TOTAL.labels(file_type="pdf", status="success").inc()
                DOCUMENT_INGEST_DURATION.labels(file_type="pdf").observe(time.perf_counter() - ingest_start)
                return document_id, len(smart_chunks)
            else:
                full_text = "\n".join(p.text for p in pages)
                chunks = chunk_text(full_text)
                if not chunks:
                    DOCUMENT_INGEST_TOTAL.labels(file_type="pdf", status="empty").inc()
                    return "", 0
                document_id = upsert_chunks(chunks, source=filename, tenant_id=tenant_id)
                CHUNKS_PRODUCED_TOTAL.inc(len(chunks))
                DOCUMENT_INGEST_TOTAL.labels(file_type="pdf", status="success").inc()
                DOCUMENT_INGEST_DURATION.labels(file_type="pdf").observe(time.perf_counter() - ingest_start)
                return document_id, len(chunks)
        else:
            text = extract_text_from_bytes(file_bytes)
            chunks = chunk_text(text)
            if not chunks:
                DOCUMENT_INGEST_TOTAL.labels(file_type=extension, status="empty").inc()
                return "", 0
            document_id = upsert_chunks(chunks, source=filename, tenant_id=tenant_id)
            CHUNKS_PRODUCED_TOTAL.inc(len(chunks))
            DOCUMENT_INGEST_TOTAL.labels(file_type=extension, status="success").inc()
            DOCUMENT_INGEST_DURATION.labels(file_type=extension).observe(time.perf_counter() - ingest_start)
            return document_id, len(chunks)
    except Exception:
        DOCUMENT_INGEST_TOTAL.labels(file_type=extension, status="error").inc()
        raise


def ingest_document_from_path(file_path: str, filename: str, tenant_id: str) -> Tuple[str, int]:
    bytes_data = Path(file_path).read_bytes()
    return ingest_document(bytes_data, filename, tenant_id)
