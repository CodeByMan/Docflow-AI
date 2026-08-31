from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter

from app.services.document_processor import (
    DocumentProcessingError,
    ParserLimits,
    analyze_contract,
    analyze_invoice,
    classify_document,
    extract_text,
    process_document,
    validate_document_file,
)

INVOICE_TEXT = """INVOICE
Invoice Number: KHI-2026-100
Invoice Date: August 26, 2026
Bill To: Clifton Harbour Traders
Subtotal: PKR 100,000.00
Tax: PKR 15,000.00
Amount Due: PKR 115,000.00
Due Date: September 10, 2026
Contact: billing@example.test
"""

CONTRACT_TEXT = """SERVICE AGREEMENT
This Agreement is made between Seaview Labs and Korangi Systems.
The effective date is August 26, 2026. The parties agree to confidentiality,
payment terms, termination rights, limitation of liability, and governing law.
"""


def _write_text_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(payload)


def test_plain_text_invoice_processing(tmp_path: Path):
    source = tmp_path / "invoice.txt"
    source.write_text(INVOICE_TEXT, encoding="utf-8")
    extracted, result = process_document(source, requested_type="auto")
    assert "KHI-2026-100" in extracted
    assert result["document_type"] == "invoice"
    assert result["invoice"]["invoice_number"] == "KHI-2026-100"
    assert result["entities"]["emails"] == ["billing@example.test"]


def test_contract_analysis_detects_parties_and_clauses():
    predicted, confidence, _ = classify_document(CONTRACT_TEXT)
    result = analyze_contract(CONTRACT_TEXT)
    assert predicted == "contract"
    assert confidence >= 0.5
    assert result["parties"] == ["Seaview Labs", "Korangi Systems"]
    assert "confidentiality" in result["clauses_detected"]


def test_invoice_analysis_extracts_pkr_fields():
    result = analyze_invoice(INVOICE_TEXT)
    assert result["invoice_number"] == "KHI-2026-100"
    assert "115,000.00" in result["total"]


def test_low_evidence_classification_is_unknown():
    assert classify_document("A short general project note.") == ("unknown", 0.0, [])


def test_supported_text_csv_json_and_markdown_fixtures(tmp_path: Path):
    fixtures = {
        "note.txt": "Karachi operations report",
        "readme.md": "# Karachi Operations\nDeterministic report",
        "records.csv": "vendor,amount\nSeaview Supplies,PKR 5000",
        "record.json": json.dumps({"vendor": "Seaview Supplies", "currency": "PKR"}),
    }
    for name, contents in fixtures.items():
        source = tmp_path / name
        source.write_text(contents, encoding="utf-8")
        result = extract_text(source)
        assert result.text


def test_docx_xlsx_and_pdf_fixtures(tmp_path: Path):
    docx_path = tmp_path / "contract.docx"
    document = Document()
    document.add_paragraph(CONTRACT_TEXT)
    document.save(docx_path)
    assert "Seaview Labs" in extract_text(docx_path).text

    xlsx_path = tmp_path / "invoice.xlsx"
    workbook = Workbook()
    workbook.active.append(["Invoice Number", "KHI-77"])
    workbook.active.append(["Amount Due", "PKR 4500"])
    workbook.save(xlsx_path)
    assert "KHI-77" in extract_text(xlsx_path).text

    pdf_path = tmp_path / "invoice.pdf"
    _write_text_pdf(pdf_path, "INVOICE KHI-88 Amount Due PKR 9000")
    assert "KHI-88" in extract_text(pdf_path).text


def test_invalid_signature_and_mime_are_rejected(tmp_path: Path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(DocumentProcessingError, match="does not match"):
        validate_document_file(fake, ".pdf", "application/pdf")

    text = tmp_path / "notes.txt"
    text.write_text("Karachi notes", encoding="utf-8")
    with pytest.raises(DocumentProcessingError, match="content type"):
        validate_document_file(text, ".txt", "application/pdf")


def test_pdf_page_limit(tmp_path: Path):
    path = tmp_path / "pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(DocumentProcessingError, match="page limit"):
        extract_text(path, limits=ParserLimits(max_pdf_pages=1))


def test_csv_text_xlsx_row_cell_and_sheet_limits(tmp_path: Path):
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("a,b\nc,d\ne,f\n", encoding="utf-8")
    with pytest.raises(DocumentProcessingError, match="row limit"):
        extract_text(csv_path, limits=ParserLimits(max_rows=2))

    text_path = tmp_path / "large.txt"
    text_path.write_text("x" * 20, encoding="utf-8")
    with pytest.raises(DocumentProcessingError, match="byte limit"):
        extract_text(text_path, limits=ParserLimits(max_text_bytes=10))

    xlsx_path = tmp_path / "large.xlsx"
    workbook = Workbook()
    workbook.active.append(["a", "b", "c"])
    workbook.create_sheet("Second")
    workbook.save(xlsx_path)
    with pytest.raises(DocumentProcessingError, match="worksheet limit"):
        extract_text(xlsx_path, limits=ParserLimits(max_worksheets=1))
    with pytest.raises(DocumentProcessingError, match="cell limit"):
        extract_text(xlsx_path, limits=ParserLimits(max_cells=2))


def test_invalid_text_encoding_is_rejected(tmp_path: Path):
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"Karachi\xff")
    with pytest.raises(DocumentProcessingError, match="UTF-8"):
        validate_document_file(path, ".txt", "text/plain")


def test_office_uncompressed_size_and_compression_ratio_limits(tmp_path: Path):
    path = tmp_path / "archive.xlsx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "x" * 10_000)

    with pytest.raises(DocumentProcessingError, match="uncompressed-size"):
        validate_document_file(
            path,
            ".xlsx",
            limits=ParserLimits(max_office_uncompressed_bytes=1_000),
        )

    with pytest.raises(DocumentProcessingError, match="compression-ratio"):
        validate_document_file(
            path,
            ".xlsx",
            limits=ParserLimits(
                max_office_uncompressed_bytes=50_000,
                max_office_compression_ratio=2,
            ),
        )
