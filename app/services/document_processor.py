from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".pdf", ".docx", ".xlsx"}

STOP_WORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "been",
    "before",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "more",
    "most",
    "no",
    "not",
    "of",
    "on",
    "or",
    "our",
    "shall",
    "she",
    "should",
    "so",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "to",
    "under",
    "upon",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
}

CLAUSE_KEYWORDS = {
    "confidentiality": ("confidential", "non-disclosure", "nda"),
    "termination": ("termination", "terminate", "notice period"),
    "payment": ("payment", "fees", "compensation", "invoice"),
    "indemnity": ("indemnity", "indemnify", "hold harmless"),
    "liability": ("limitation of liability", "liable", "liability"),
    "governing_law": ("governing law", "jurisdiction", "laws of"),
    "intellectual_property": ("intellectual property", "copyright", "ownership"),
    "force_majeure": ("force majeure", "act of god"),
    "dispute_resolution": ("arbitration", "dispute resolution", "mediation"),
    "data_protection": ("data protection", "privacy", "personal data"),
}


@dataclass(slots=True)
class ExtractionResult:
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParserLimits:
    max_text_bytes: int = 2_000_000
    max_extracted_text_chars: int = 500_000
    max_pdf_pages: int = 100
    max_office_uncompressed_bytes: int = 50_000_000
    max_office_compression_ratio: int = 100
    max_worksheets: int = 25
    max_rows: int = 20_000
    max_cells: int = 200_000


class DocumentProcessingError(ValueError):
    """A stable, public processing error with a machine-readable code."""

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


MIME_TYPES: dict[str, set[str]] = {
    ".txt": {"text/plain"},
    ".md": {"text/plain", "text/markdown"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _raise_limit(message: str) -> None:
    raise DocumentProcessingError("resource_limit_exceeded", message)


def _check_office_archive(path: Path, extension: str, limits: ParserLimits) -> None:
    if not zipfile.is_zipfile(path):
        raise DocumentProcessingError(
            "invalid_signature", "The file content does not match its extension"
        )

    required_member = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = {member.filename for member in members}
        if "[Content_Types].xml" not in names or required_member not in names:
            raise DocumentProcessingError(
                "invalid_signature", "The Office file content does not match its extension"
            )

        total_uncompressed = 0
        for member in members:
            if member.flag_bits & 0x1:
                raise DocumentProcessingError(
                    "encrypted_document", "Encrypted Office files are not supported"
                )
            total_uncompressed += member.file_size
            if total_uncompressed > limits.max_office_uncompressed_bytes:
                _raise_limit("Office archive exceeds the uncompressed-size limit")
            if member.file_size and member.compress_size == 0:
                _raise_limit("Office archive contains an unsafe compressed entry")
            compression_ratio = (
                member.file_size / member.compress_size if member.compress_size else 0
            )
            if compression_ratio > limits.max_office_compression_ratio:
                _raise_limit("Office archive exceeds the compression-ratio limit")


def validate_document_file(
    path: Path,
    extension: str,
    supplied_mime: str | None = None,
    limits: ParserLimits | None = None,
) -> None:
    """Validate extension, claimed MIME, signature, and cheap pre-parse bounds."""

    limits = limits or ParserLimits()
    extension = extension.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentProcessingError("unsupported_type", "Unsupported document type")

    mime = (supplied_mime or "").split(";", 1)[0].strip().lower()
    if mime and mime not in {"application/octet-stream", "binary/octet-stream"}:
        allowed = MIME_TYPES.get(extension, set())
        if mime not in allowed:
            raise DocumentProcessingError(
                "mime_mismatch", "The declared content type does not match the file extension"
            )

    if extension == ".pdf":
        with path.open("rb") as file_handle:
            signature = file_handle.read(5)
        if signature != b"%PDF-":
            raise DocumentProcessingError(
                "invalid_signature", "The file content does not match its extension"
            )
    elif extension in {".docx", ".xlsx"}:
        _check_office_archive(path, extension, limits)
    else:
        if path.stat().st_size > limits.max_text_bytes:
            _raise_limit("Text-based document exceeds the byte limit")
        with path.open("rb") as file_handle:
            sample = file_handle.read(8192)
        if b"\x00" in sample:
            raise DocumentProcessingError(
                "invalid_signature", "The file is not a supported text document"
            )
        try:
            sample.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentProcessingError(
                "invalid_encoding", "Text-based documents must use UTF-8 encoding"
            ) from exc


def extract_text(
    path: Path,
    max_chars: int | None = None,
    *,
    limits: ParserLimits | None = None,
) -> ExtractionResult:
    limits = limits or ParserLimits()
    if max_chars is not None:
        limits = ParserLimits(
            max_text_bytes=limits.max_text_bytes,
            max_extracted_text_chars=max_chars,
            max_pdf_pages=limits.max_pdf_pages,
            max_office_uncompressed_bytes=limits.max_office_uncompressed_bytes,
            max_office_compression_ratio=limits.max_office_compression_ratio,
            max_worksheets=limits.max_worksheets,
            max_rows=limits.max_rows,
            max_cells=limits.max_cells,
        )
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentProcessingError("unsupported_type", "Unsupported document type")

    validate_document_file(path, extension, limits=limits)

    extractor = {
        ".txt": _extract_plain_text,
        ".md": _extract_plain_text,
        ".csv": _extract_csv,
        ".json": _extract_json,
        ".pdf": _extract_pdf,
        ".docx": _extract_docx,
        ".xlsx": _extract_xlsx,
    }[extension]

    result = extractor(path, limits)
    text = normalize_text(result.text)
    if not text:
        message = "No extractable text was found"
        if extension == ".pdf":
            message += "; scanned PDFs require OCR, which is not enabled in this lightweight build"
        raise DocumentProcessingError("no_extractable_text", message)

    truncated = len(text) > limits.max_extracted_text_chars
    if truncated:
        text = text[: limits.max_extracted_text_chars]

    metadata = {**result.metadata, "text_truncated": truncated}
    return ExtractionResult(text=text, metadata=metadata)


def _extract_plain_text(path: Path, limits: ParserLimits) -> ExtractionResult:
    if path.stat().st_size > limits.max_text_bytes:
        _raise_limit("Text document exceeds the byte limit")
    text = path.read_text(encoding="utf-8-sig", errors="strict")
    return ExtractionResult(text=text, metadata={"format": path.suffix.lower()[1:]})


def _extract_csv(path: Path, limits: ParserLimits) -> ExtractionResult:
    rows: list[str] = []
    row_count = 0
    cell_count = 0
    if path.stat().st_size > limits.max_text_bytes:
        _raise_limit("CSV document exceeds the byte limit")
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as file_handle:
        for row in csv.reader(file_handle):
            row_count += 1
            cell_count += len(row)
            if row_count > limits.max_rows:
                _raise_limit("CSV document exceeds the row limit")
            if cell_count > limits.max_cells:
                _raise_limit("CSV document exceeds the cell limit")
            rows.append(" | ".join(cell.strip() for cell in row))
    return ExtractionResult(
        text="\n".join(rows),
        metadata={"format": "csv", "rows": row_count, "cells": cell_count},
    )


def _extract_json(path: Path, limits: ParserLimits) -> ExtractionResult:
    if path.stat().st_size > limits.max_text_bytes:
        _raise_limit("JSON document exceeds the byte limit")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    pretty = json.dumps(data, ensure_ascii=False, indent=2)
    return ExtractionResult(
        text=pretty, metadata={"format": "json", "root_type": type(data).__name__}
    )


def _extract_pdf(path: Path, limits: ParserLimits) -> ExtractionResult:
    reader = PdfReader(str(path))
    if len(reader.pages) > limits.max_pdf_pages:
        _raise_limit("PDF document exceeds the page limit")
    pages: list[str] = []
    extracted_chars = 0
    for page in reader.pages:
        page_text = page.extract_text() or ""
        extracted_chars += len(page_text)
        if extracted_chars > limits.max_extracted_text_chars:
            _raise_limit("PDF document exceeds the extracted-text limit")
        pages.append(page_text)
    metadata = {
        "format": "pdf",
        "pages": len(reader.pages),
        "pdf_metadata": {
            str(key).lstrip("/"): str(value)
            for key, value in (reader.metadata or {}).items()
            if value is not None
        },
    }
    return ExtractionResult(text="\n\n".join(pages), metadata=metadata)


def _extract_docx(path: Path, limits: ParserLimits) -> ExtractionResult:
    _check_office_archive(path, ".docx", limits)
    document = Document(str(path))
    lines: list[str] = []
    extracted_chars = 0
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            extracted_chars += len(paragraph.text)
            if extracted_chars > limits.max_extracted_text_chars:
                _raise_limit("DOCX document exceeds the extracted-text limit")
            lines.append(paragraph.text)
    table_rows = 0
    cell_count = 0
    for table in document.tables:
        for row in table.rows:
            table_rows += 1
            cell_count += len(row.cells)
            if table_rows > limits.max_rows or cell_count > limits.max_cells:
                _raise_limit("DOCX document exceeds the table limit")
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            extracted_chars += len(row_text)
            if extracted_chars > limits.max_extracted_text_chars:
                _raise_limit("DOCX document exceeds the extracted-text limit")
            lines.append(row_text)
    return ExtractionResult(
        text="\n".join(lines),
        metadata={
            "format": "docx",
            "paragraphs": len(document.paragraphs),
            "tables": len(document.tables),
            "table_rows": table_rows,
            "cells": cell_count,
        },
    )


def _extract_xlsx(path: Path, limits: ParserLimits) -> ExtractionResult:
    _check_office_archive(path, ".xlsx", limits)
    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    if len(workbook.worksheets) > limits.max_worksheets:
        workbook.close()
        _raise_limit("XLSX document exceeds the worksheet limit")
    lines: list[str] = []
    sheet_stats: list[dict[str, Any]] = []
    total_rows = 0
    total_cells = 0
    extracted_chars = 0
    for worksheet in workbook.worksheets:
        remaining_rows = limits.max_rows - total_rows
        remaining_cells = limits.max_cells - total_cells
        if worksheet.max_row > remaining_rows:
            workbook.close()
            _raise_limit("XLSX document exceeds the row limit")
        if worksheet.max_column and worksheet.max_row * worksheet.max_column > remaining_cells:
            workbook.close()
            _raise_limit("XLSX document exceeds the cell limit")
        lines.append(f"Sheet: {worksheet.title}")
        rows = 0
        for row in worksheet.iter_rows(values_only=True):
            total_rows += 1
            total_cells += len(row)
            if total_rows > limits.max_rows:
                workbook.close()
                _raise_limit("XLSX document exceeds the row limit")
            if total_cells > limits.max_cells:
                workbook.close()
                _raise_limit("XLSX document exceeds the cell limit")
            values = ["" if value is None else str(value) for value in row]
            if any(value.strip() for value in values):
                row_text = " | ".join(values)
                extracted_chars += len(row_text)
                if extracted_chars > limits.max_extracted_text_chars:
                    workbook.close()
                    _raise_limit("XLSX document exceeds the extracted-text limit")
                lines.append(row_text)
                rows += 1
        sheet_stats.append({"name": worksheet.title, "rows": rows})
    workbook.close()
    return ExtractionResult(
        text="\n".join(lines),
        metadata={"format": "xlsx", "sheets": sheet_stats},
    )


def process_document(
    path: Path,
    requested_type: str = "auto",
    max_chars: int | None = None,
    *,
    limits: ParserLimits | None = None,
) -> tuple[str, dict[str, Any]]:
    extraction = extract_text(path, max_chars=max_chars, limits=limits)
    text = extraction.text
    predicted_type, confidence, signals = classify_document(text)
    document_type = predicted_type if requested_type == "auto" else requested_type

    result: dict[str, Any] = {
        "document_type": document_type,
        "classification": {
            "requested_type": requested_type,
            "predicted_type": predicted_type,
            "confidence": confidence,
            "signals": signals,
        },
        "summary": summarize(text),
        "statistics": statistics(text),
        "entities": extract_entities(text),
        "keywords": top_keywords(text),
        "extraction": extraction.metadata,
    }

    if document_type == "invoice":
        result["invoice"] = analyze_invoice(text)
    elif document_type == "contract":
        result["contract"] = analyze_contract(text)

    return text, result


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9'\-]{1,}", text.lower())


def content_words(text: str) -> list[str]:
    return [word for word in words(text) if word not in STOP_WORDS and len(word) > 2]


def statistics(text: str) -> dict[str, Any]:
    word_list = words(text)
    paragraphs = [item for item in re.split(r"\n\s*\n", text) if item.strip()]
    sentences = split_sentences(text)
    return {
        "characters": len(text),
        "characters_without_spaces": len(re.sub(r"\s", "", text)),
        "words": len(word_list),
        "unique_words": len(set(word_list)),
        "sentences": len(sentences),
        "paragraphs": len(paragraphs),
        "lines": len(text.splitlines()),
        "estimated_reading_minutes": max(1, round(len(word_list) / 200)),
    }


def split_sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return []
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", compact) if item.strip()]


def summarize(text: str, sentence_limit: int = 3) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return ""
    if len(sentences) <= sentence_limit:
        return " ".join(sentences)

    frequencies = Counter(content_words(text))
    if not frequencies:
        return " ".join(sentences[:sentence_limit])

    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        sentence_words = content_words(sentence)
        if not sentence_words:
            continue
        score = sum(frequencies[word] for word in sentence_words) / len(sentence_words)
        scored.append((score, index, sentence))

    selected = sorted(scored, reverse=True)[:sentence_limit]
    selected.sort(key=lambda item: item[1])
    return " ".join(item[2] for item in selected)


def top_keywords(text: str, limit: int = 12) -> list[dict[str, Any]]:
    return [
        {"term": term, "count": count}
        for term, count in Counter(content_words(text)).most_common(limit)
    ]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        normalized = item.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return output


def extract_entities(text: str) -> dict[str, list[str]]:
    emails = re.findall(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, flags=re.I)
    urls = re.findall(r"\bhttps?://[^\s<>()]+", text, flags=re.I)
    phones = re.findall(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text)
    dates = re.findall(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b",
        text,
        flags=re.I,
    )
    amounts = re.findall(
        r"(?<!\w)(?:USD|EUR|GBP|PKR|Rs\.?|\$|€|£)\s?\d[\d,]*(?:\.\d{1,2})?",
        text,
        flags=re.I,
    )
    return {
        "emails": _dedupe(emails)[:25],
        "urls": _dedupe(urls)[:25],
        "phone_numbers": _dedupe(phones)[:25],
        "dates": _dedupe(dates)[:25],
        "monetary_amounts": _dedupe(amounts)[:25],
    }


def classify_document(text: str) -> tuple[str, float, list[str]]:
    lowered = text.lower()
    invoice_terms = {
        "invoice": 4,
        "invoice number": 4,
        "amount due": 3,
        "subtotal": 2,
        "tax": 1,
        "bill to": 3,
        "payment terms": 2,
        "quantity": 1,
        "unit price": 2,
    }
    contract_terms = {
        "agreement": 3,
        "contract": 4,
        "party": 1,
        "parties": 2,
        "whereas": 3,
        "termination": 2,
        "governing law": 3,
        "confidential": 2,
        "hereby": 2,
        "shall": 1,
    }

    invoice_score = sum(weight for term, weight in invoice_terms.items() if term in lowered)
    contract_score = sum(weight for term, weight in contract_terms.items() if term in lowered)
    signals: list[str] = []
    for term, weight in invoice_terms.items():
        if term in lowered:
            signals.append(f"invoice:{term}(+{weight})")
    for term, weight in contract_terms.items():
        if term in lowered:
            signals.append(f"contract:{term}(+{weight})")

    total = invoice_score + contract_score
    if total < 3:
        return "unknown", 0.0, signals[:12]
    if invoice_score >= contract_score:
        predicted = "invoice"
        leading = invoice_score
    else:
        predicted = "contract"
        leading = contract_score

    confidence = 0.5 if total == 0 else round(leading / total, 2)
    return predicted, confidence, signals[:12]


def _first_match(patterns: Iterable[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.M)
        if match:
            return match.group(1).strip()
    return None


def analyze_invoice(text: str) -> dict[str, Any]:
    invoice_number = _first_match(
        [
            r"^\s*invoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]+)\s*$",
            r"^\s*inv\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]+)\s*$",
        ],
        text,
    )
    total = _first_match(
        [
            r"^\s*(?:grand\s+total|amount\s+due|balance\s+due|total)\s*[:\-]?\s*"
            r"((?:USD|EUR|GBP|PKR|Rs\.?|\$|€|£)?\s?\d[\d,]*(?:\.\d{1,2})?)\s*$",
        ],
        text,
    )
    due_date = _first_match(
        [
            r"due\s+date\s*[:\-]?\s*([^\n|]{4,40})",
            r"payment\s+due\s*[:\-]?\s*([^\n|]{4,40})",
        ],
        text,
    )
    tax = _first_match(
        [
            r"(?:tax|vat|gst)\s*[:\-]?\s*"
            r"((?:USD|EUR|GBP|PKR|Rs\.?|\$|€|£)?\s?\d[\d,]*(?:\.\d{1,2})?)"
        ],
        text,
    )
    return {
        "invoice_number": invoice_number,
        "total": total,
        "tax": tax,
        "due_date": due_date,
        "fields_detected": sum(
            value is not None for value in (invoice_number, total, tax, due_date)
        ),
    }


def analyze_contract(text: str) -> dict[str, Any]:
    lowered = text.lower()
    clauses = [
        name
        for name, keywords in CLAUSE_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    effective_date = _first_match(
        [
            r"effective\s+(?:as\s+of\s+|date\s*[:\-]?\s*)([^\n,.]{4,50})",
            r"dated\s+(?:as\s+of\s+)?([^\n,.]{4,50})",
        ],
        text,
    )
    party_match = re.search(
        r"between\s+(.{2,120}?)\s+and\s+(.{2,120}?)(?:\.|,|\n)",
        text,
        flags=re.I,
    )
    party_list = [party_match.group(1).strip(), party_match.group(2).strip()] if party_match else []
    return {
        "effective_date": effective_date,
        "parties": party_list,
        "clauses_detected": clauses,
        "clause_coverage": len(clauses),
    }
