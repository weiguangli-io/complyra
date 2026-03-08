"""Generate test documents (PDF, text, images) for functional testing.

Run: python3 tests/generate_test_docs.py
Generates files in tests/fixtures/
"""
from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)


# ── PDF generation (pure Python, no dependencies) ──────────────────


def _create_pdf(pages: list[str], filename: str) -> Path:
    """Create a minimal valid PDF file with given page content."""
    filepath = FIXTURES_DIR / filename

    objects: list[bytes] = []
    offsets: list[int] = []

    def add_obj(content: bytes) -> int:
        obj_num = len(objects) + 1
        objects.append(content)
        return obj_num

    # Object 1: Catalog
    catalog = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    add_obj(catalog)

    # Object 2: Pages (placeholder, will be updated)
    pages_kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    pages_obj = f"2 0 obj\n<< /Type /Pages /Kids [{pages_kids}] /Count {len(pages)} >>\nendobj\n".encode()
    add_obj(pages_obj)

    # For each page: Page object + Content stream
    font_obj_num = None
    for i, text in enumerate(pages):
        page_obj_num = 3 + i * 2
        content_obj_num = 4 + i * 2

        # Escape special PDF characters in text
        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines = safe_text.split("\n")
        text_ops = []
        for j, line in enumerate(lines):
            if j == 0:
                text_ops.append(f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET")
            else:
                text_ops.append(f"BT /F1 12 Tf 72 {720 - j * 16} Td ({line}) Tj ET")
        stream_content = "\n".join(text_ops)
        stream_bytes = stream_content.encode("latin-1", errors="replace")

        if font_obj_num is None:
            font_obj_num = content_obj_num + 1

        page = (
            f"{page_obj_num} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Contents {content_obj_num} 0 R "
            f"/Resources << /Font << /F1 {3 + len(pages) * 2} 0 R >> >> >>\n"
            f"endobj\n"
        ).encode()
        add_obj(page)

        content = (
            f"{content_obj_num} 0 obj\n"
            f"<< /Length {len(stream_bytes)} >>\n"
            f"stream\n"
        ).encode() + stream_bytes + b"\nendstream\nendobj\n"
        add_obj(content)

    # Font object
    font_num = 3 + len(pages) * 2
    font = f"{font_num} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n".encode()
    add_obj(font)

    # Write PDF
    pdf = bytearray(b"%PDF-1.4\n")
    for i, obj in enumerate(objects):
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_offset = len(pdf)
    pdf.extend(b"xref\n")
    pdf.extend(f"0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets:
        pdf.extend(f"{off:010d} 00000 n \n".encode())

    pdf.extend(b"trailer\n")
    pdf.extend(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode())
    pdf.extend(b"startxref\n")
    pdf.extend(f"{xref_offset}\n".encode())
    pdf.extend(b"%%EOF\n")

    filepath.write_bytes(bytes(pdf))
    print(f"  Created: {filepath}")
    return filepath


def _create_png(width: int, height: int, color: tuple[int, int, int], filename: str) -> Path:
    """Create a minimal valid PNG image."""
    filepath = FIXTURES_DIR / filename

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = zlib.crc32(c) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + c + struct.pack(">I", crc)

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # IDAT - raw pixel data
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00"  # filter byte
        for _ in range(width):
            raw_data += bytes(color)
    compressed = zlib.compress(raw_data)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr_data)
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")

    filepath.write_bytes(png)
    print(f"  Created: {filepath}")
    return filepath


def generate_all():
    print("Generating test fixtures...\n")

    # ── 1. Normal text documents ──
    print("[Text Documents]")
    (FIXTURES_DIR / "simple.txt").write_text(
        "This is a simple text document for testing.\n"
        "It has multiple lines.\n"
        "The ingestion pipeline should handle it correctly.\n"
    )
    print(f"  Created: {FIXTURES_DIR / 'simple.txt'}")

    (FIXTURES_DIR / "empty.txt").write_text("")
    print(f"  Created: {FIXTURES_DIR / 'empty.txt'}")

    (FIXTURES_DIR / "unicode.txt").write_text(
        "Unicode test: cafe\u0301, na\u00efve, re\u0301sume\u0301\n"
        "Chinese: \u6d4b\u8bd5\u6587\u6863\n"
        "Japanese: \u30c6\u30b9\u30c8\u6587\u66f8\n"
        "Emoji: \u2705 \u274c \u26a0\ufe0f\n"
    )
    print(f"  Created: {FIXTURES_DIR / 'unicode.txt'}")

    long_text = "This is paragraph number {i}. " * 20 + "\n\n"
    (FIXTURES_DIR / "long_document.txt").write_text(
        "".join(long_text.replace("{i}", str(i)) for i in range(50))
    )
    print(f"  Created: {FIXTURES_DIR / 'long_document.txt'}")

    (FIXTURES_DIR / "compliance_policy.md").write_text(
        "# Data Protection Policy\n\n"
        "## 1. Purpose\n\n"
        "This policy defines the requirements for protecting sensitive data.\n\n"
        "## 2. Scope\n\n"
        "This policy applies to all employees, contractors, and third parties.\n\n"
        "## 3. Data Classification\n\n"
        "### 3.1 Confidential\n"
        "- Customer PII (names, addresses, SSN)\n"
        "- Financial records\n"
        "- Trade secrets\n\n"
        "### 3.2 Internal\n"
        "- Internal memos\n"
        "- Project plans\n"
        "- Meeting notes\n\n"
        "### 3.3 Public\n"
        "- Marketing materials\n"
        "- Published reports\n\n"
        "## 4. Access Control\n\n"
        "Access to confidential data must follow the principle of least privilege.\n"
        "All access must be logged and audited quarterly.\n\n"
        "## 5. Incident Response\n\n"
        "Any suspected data breach must be reported within 24 hours.\n"
        "The security team will investigate and notify affected parties.\n"
    )
    print(f"  Created: {FIXTURES_DIR / 'compliance_policy.md'}")

    # ── 2. PDF documents ──
    print("\n[PDF Documents]")

    _create_pdf(
        ["This is page 1 of the test PDF.\nIt contains basic text content."],
        "single_page.pdf",
    )

    _create_pdf(
        [
            "Chapter 1: Introduction\n\nThis document covers enterprise compliance requirements.\nAll organizations must adhere to data protection regulations.",
            "Chapter 2: Data Handling\n\nSensitive data must be encrypted at rest and in transit.\nAccess controls must be implemented with RBAC.",
            "Chapter 3: Audit Requirements\n\nAll data access must be logged.\nAudit logs must be retained for 7 years.\nQuarterly reviews are mandatory.",
        ],
        "multi_page.pdf",
    )

    _create_pdf(
        [
            "Employee Handbook - Section 1\n\nWelcome to the company. This handbook outlines policies and procedures for all employees.",
            "Employee Handbook - Section 2\n\nWork Hours: Standard hours are 9 AM to 6 PM.\nRemote Work: Employees may work remotely up to 3 days per week.",
            "Employee Handbook - Section 3\n\nLeave Policy:\n- Annual leave: 15 days\n- Sick leave: 10 days\n- Parental leave: 90 days",
            "Employee Handbook - Section 4\n\nCode of Conduct:\n- Maintain professional behavior\n- Protect company assets\n- Report conflicts of interest\n- Follow data security policies",
            "Employee Handbook - Section 5\n\nPerformance Reviews:\n- Conducted semi-annually\n- Self-assessment required\n- 360-degree feedback for managers",
        ],
        "employee_handbook.pdf",
    )

    _create_pdf(
        [
            "API Security Guidelines v2.1\n\n"
            "1. Authentication\n"
            "All API endpoints must require authentication.\n"
            "Use OAuth 2.0 or JWT tokens.\n"
            "Token expiry should not exceed 1 hour.\n\n"
            "2. Rate Limiting\n"
            "Implement rate limiting on all public endpoints.\n"
            "Default: 100 requests per minute per API key.\n\n"
            "3. Input Validation\n"
            "Validate all input parameters.\n"
            "Sanitize to prevent SQL injection and XSS.\n"
            "Maximum payload size: 10MB.\n\n"
            "4. Encryption\n"
            "TLS 1.2+ required for all API traffic.\n"
            "Sensitive fields must be encrypted at rest.\n"
            "API keys must never appear in URLs.",
        ],
        "api_security.pdf",
    )

    _create_pdf(
        ["  \n  \n  "],  # Nearly empty page (triggers OCR path)
        "scanned_empty.pdf",
    )

    # ── 3. Image files ──
    print("\n[Image Files]")
    _create_png(200, 150, (255, 0, 0), "test_chart.png")
    _create_png(50, 50, (0, 0, 255), "tiny_icon.png")  # Small, should be skipped
    _create_png(400, 300, (0, 128, 0), "large_diagram.png")

    # Create a JPEG-like file (minimal valid JFIF)
    jpeg_path = FIXTURES_DIR / "test_photo.jpg"
    # Minimal JPEG: SOI + APP0 (JFIF) + minimal data + EOI
    jpeg_data = bytes([
        0xFF, 0xD8,  # SOI
        0xFF, 0xE0,  # APP0
        0x00, 0x10,  # Length
        0x4A, 0x46, 0x49, 0x46, 0x00,  # JFIF\0
        0x01, 0x01,  # Version
        0x00,  # Units
        0x00, 0x01,  # X density
        0x00, 0x01,  # Y density
        0x00, 0x00,  # Thumbnail
        0xFF, 0xD9,  # EOI
    ])
    jpeg_path.write_bytes(jpeg_data)
    print(f"  Created: {jpeg_path}")

    # ── 4. Edge case files ──
    print("\n[Edge Case Files]")

    (FIXTURES_DIR / "special chars!@#.txt").write_text("File with special characters in name.")
    print(f"  Created: {FIXTURES_DIR / 'special chars!@#.txt'}")

    (FIXTURES_DIR / "binary_content.txt").write_bytes(b"\xff\xfe\x00\x01\x80\x81")
    print(f"  Created: {FIXTURES_DIR / 'binary_content.txt'}")

    # Policy-triggering content (should be blocked by output policy)
    (FIXTURES_DIR / "sensitive_content.txt").write_text(
        "This document contains AWS access keys.\n"
        "Access Key ID: AKIAIOSFODNN7EXAMPLE\n"
        "Secret Access Key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
    )
    print(f"  Created: {FIXTURES_DIR / 'sensitive_content.txt'}")

    print(f"\nAll test fixtures generated in: {FIXTURES_DIR}")
    print(f"Total files: {len(list(FIXTURES_DIR.iterdir()))}")


if __name__ == "__main__":
    generate_all()
