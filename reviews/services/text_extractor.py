"""
Text extraction service for DocConform.
Extracts text from PDF documents with OCR fallback.

REGULATORY REQUIREMENT: All text must be traceable to page numbers.
No text generation or inference allowed.
"""

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import List, Optional, BinaryIO, Union

logger = logging.getLogger(__name__)

# Try importing PDF libraries
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available - PDF text extraction limited")

try:
    from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    logger.warning("PyPDF2 not available - fallback PDF extraction disabled")

try:
    from PIL import Image
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pytesseract/PIL not available - OCR disabled")


@dataclass
class PageText:
    """Text extracted from a single page with metadata."""
    page_number: int
    text: str
    extraction_method: str  # 'pdfplumber', 'pypdf2', 'ocr'
    has_content: bool
    
    def __str__(self) -> str:
        return f"Page {self.page_number}: {len(self.text)} chars ({self.extraction_method})"


def compute_sha256(file_obj: BinaryIO) -> str:
    """
    Compute SHA-256 hash of a file for integrity verification.
    
    Args:
        file_obj: File-like object to hash
        
    Returns:
        Hexadecimal SHA-256 hash string
    """
    sha256_hash = hashlib.sha256()
    file_obj.seek(0)
    
    for chunk in iter(lambda: file_obj.read(8192), b""):
        sha256_hash.update(chunk)
    
    file_obj.seek(0)
    return sha256_hash.hexdigest()


def _extract_with_pdfplumber(file_obj: BinaryIO) -> List[PageText]:
    """Extract text using pdfplumber (primary method)."""
    if not PDFPLUMBER_AVAILABLE:
        return []
    
    pages = []
    file_obj.seek(0)
    
    try:
        with pdfplumber.open(file_obj) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages.append(PageText(
                    page_number=i,
                    text=text.strip(),
                    extraction_method='pdfplumber',
                    has_content=bool(text.strip())
                ))
    except Exception as e:
        logger.error(f"pdfplumber extraction failed: {e}")
        return []
    
    return pages


def _extract_with_pypdf2(file_obj: BinaryIO) -> List[PageText]:
    """Extract text using PyPDF2 (fallback method)."""
    if not PYPDF2_AVAILABLE:
        return []
    
    pages = []
    file_obj.seek(0)
    
    try:
        reader = PdfReader(file_obj)
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(
                page_number=i,
                text=text.strip(),
                extraction_method='pypdf2',
                has_content=bool(text.strip())
            ))
    except Exception as e:
        logger.error(f"PyPDF2 extraction failed: {e}")
        return []
    
    return pages


def _extract_with_ocr(file_obj: BinaryIO, page_number: int) -> Optional[str]:
    """
    Extract text from a page using OCR.
    Used as fallback when text layer is empty.
    """
    if not OCR_AVAILABLE or not PDFPLUMBER_AVAILABLE:
        return None
    
    try:
        file_obj.seek(0)
        with pdfplumber.open(file_obj) as pdf:
            if page_number <= len(pdf.pages):
                page = pdf.pages[page_number - 1]
                # Convert page to image
                img = page.to_image(resolution=300)
                # Run OCR
                text = pytesseract.image_to_string(img.original)
                return text.strip()
    except Exception as e:
        logger.error(f"OCR extraction failed for page {page_number}: {e}")
    
    return None


def extract_text_with_pages(file_obj: BinaryIO, use_ocr_fallback: bool = True) -> List[PageText]:
    """
    Extract text from a PDF file, returning text per page.
    
    This is the primary extraction function. It:
    1. Tries pdfplumber first (best quality)
    2. Falls back to PyPDF2 if pdfplumber fails
    3. Uses OCR for pages with no text layer (if enabled)
    
    Args:
        file_obj: File-like object containing PDF data
        use_ocr_fallback: Whether to use OCR for empty pages
        
    Returns:
        List of PageText objects, one per page
        
    REGULATORY NOTE: Page numbers are preserved for evidence traceability.
    """
    # Try pdfplumber first
    pages = _extract_with_pdfplumber(file_obj)
    
    # Fallback to PyPDF2 if pdfplumber failed completely
    if not pages:
        pages = _extract_with_pypdf2(file_obj)
    
    if not pages:
        raise ValueError("Failed to extract text from PDF - no extraction method succeeded")
    
    # Apply OCR fallback for empty pages if enabled
    if use_ocr_fallback and OCR_AVAILABLE:
        for page in pages:
            if not page.has_content:
                ocr_text = _extract_with_ocr(file_obj, page.page_number)
                if ocr_text:
                    page.text = ocr_text
                    page.extraction_method = 'ocr'
                    page.has_content = True
    
    return pages


def extract_text_from_pdf(file_obj: BinaryIO) -> str:
    """
    Extract all text from a PDF as a single string.
    
    This is a convenience wrapper around extract_text_with_pages.
    For regulatory purposes, prefer extract_text_with_pages to preserve
    page number evidence.
    
    Args:
        file_obj: File-like object containing PDF data
        
    Returns:
        Combined text from all pages
    """
    pages = extract_text_with_pages(file_obj)
    return "\n\n".join(p.text for p in pages if p.text)


def get_text_at_page(pages: List[PageText], page_number: int) -> Optional[str]:
    """Get text from a specific page."""
    for page in pages:
        if page.page_number == page_number:
            return page.text
    return None


def search_in_pages(pages: List[PageText], pattern: str) -> List[dict]:
    """
    Search for a pattern across all pages.
    
    Returns:
        List of matches with page numbers for evidence
    """
    import re
    matches = []
    
    for page in pages:
        for match in re.finditer(pattern, page.text, re.IGNORECASE | re.MULTILINE):
            matches.append({
                'page': page.page_number,
                'match': match.group(0),
                'start': match.start(),
                'end': match.end(),
                'context': page.text[max(0, match.start()-50):match.end()+50]
            })
    
    return matches
