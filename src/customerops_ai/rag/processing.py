"""Bounded extraction, normalization, and deterministic page-aware character chunking."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader

from customerops_ai.core.config import Settings
from customerops_ai.core.errors import AppError


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[str]
    metadata: dict[str, str]
    content_hash: str


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int
    index: int
    start: int
    end: int


def validate_filename(filename: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}", filename):
        raise AppError(
            "invalid_filename", "Use a plain filename without paths or special characters.", 422
        )
    suffix = PurePath(filename).suffix.lower()
    if suffix not in {".pdf", ".md", ".txt"}:
        raise AppError(
            "unsupported_file", "Only PDF, Markdown, and UTF-8 text files are supported.", 415
        )
    return suffix


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        char for char in text if char in "\n\t" or not unicodedata.category(char).startswith("C")
    )
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_document(filename: str, content: bytes, settings: Settings) -> ExtractedDocument:
    suffix = validate_filename(filename)
    if not content or len(content) > settings.rag_max_upload_bytes:
        raise AppError("upload_size", "The file is empty or exceeds the upload limit.", 413)
    metadata: dict[str, str] = {}
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise AppError("invalid_pdf", "The uploaded file is not a valid PDF.", 422)
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise AppError("encrypted_pdf", "Encrypted PDFs are not supported.", 422)
            if len(reader.pages) > settings.rag_max_pages:
                raise AppError("document_limit", "The PDF exceeds the page limit.", 413)
            metadata = {
                str(key).lstrip("/"): str(value)[:500]
                for key, value in (reader.metadata or {}).items()
            }
            pages = []
            characters = 0
            for page in reader.pages:
                text = normalize_text(page.extract_text() or "")
                characters += len(text)
                if characters > settings.rag_max_text_characters:
                    raise AppError(
                        "document_limit", "Extracted text exceeds the document limit.", 413
                    )
                pages.append(text)
        except AppError:
            raise
        except Exception as exc:
            raise AppError("invalid_pdf", "The PDF could not be read.", 422) from exc
    else:
        if b"\x00" in content or content.startswith(b"%PDF-"):
            raise AppError("invalid_text", "The file must contain UTF-8 text.", 422)
        try:
            pages = [normalize_text(content.decode("utf-8-sig"))]
        except UnicodeError as exc:
            raise AppError("invalid_text", "The file must contain UTF-8 text.", 422) from exc
    combined = "\n\n".join(pages)
    if not combined.strip():
        raise AppError(
            "empty_document",
            "No readable text was found. Image-only PDFs require OCR, which is not available.",
            422,
        )
    if len(combined) > settings.rag_max_text_characters:
        raise AppError("document_limit", "Extracted text exceeds the document limit.", 413)
    return ExtractedDocument(pages, metadata, hashlib.sha256(combined.encode()).hexdigest())


def chunk_document(document: ExtractedDocument, settings: Settings) -> list[Chunk]:
    chunks: list[Chunk] = []
    for number, page in enumerate(document.pages, start=1):
        start = 0
        while start < len(page):
            end = min(start + settings.rag_chunk_size, len(page))
            text = page[start:end]
            if text.strip():
                chunks.append(Chunk(text, number, len(chunks), start, end))
            if len(chunks) > settings.rag_max_chunks:
                raise AppError("document_limit", "The document exceeds the chunk limit.", 413)
            if end == len(page):
                break
            start = end - settings.rag_chunk_overlap
    return chunks
