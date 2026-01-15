"""
Document extraction orchestrator for DocConform.
Coordinates text extraction, term extraction, and validation.

This module serves as the main entry point for document processing.
All extraction is evidence-based - no hallucinated data allowed.
"""

import logging
from typing import List, Dict, Any, Optional, BinaryIO
from dataclasses import dataclass

from .services.text_extractor import (
    extract_text_with_pages,
    compute_sha256,
    PageText,
)
from .services.term_extractor import (
    extract_terms_from_text,
    TermExtractionResult,
    SourceType,
)
from .services.validation import (
    validate_terms,
    check_internal_consistency,
    ValidationIssue,
)
from .services.normalizer import normalize_term_value

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTermData:
    """Legacy compatibility class for term data."""
    key: str
    label: str
    value: str
    source: str
    confidence: float
    evidence_text: str
    evidence_location: str
    page: int = 1
    normalized: bool = False
    raw_value: str = ""
    
    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'label': self.label,
            'value': self.value,
            'source': self.source,
            'confidence': self.confidence,
            'evidence_text': self.evidence_text,
            'evidence_location': self.evidence_location,
            'page': self.page,
        }


def compute_file_hash(file_obj: BinaryIO) -> str:
    """
    Compute SHA-256 hash of a file for integrity verification.
    Wrapper for the service function.
    """
    return compute_sha256(file_obj)


def extract_text_from_pdf(file_obj: BinaryIO) -> str:
    """
    Extract all text from a PDF file.
    Returns combined text from all pages.
    """
    pages = extract_text_with_pages(file_obj)
    return "\n\n".join(p.text for p in pages if p.text)


def _convert_pages_to_dict(pages: List[PageText]) -> List[Dict[str, Any]]:
    """Convert PageText objects to dictionaries for term extraction."""
    return [
        {
            'page': p.page_number,
            'text': p.text,
        }
        for p in pages
    ]


def _convert_extraction_result(result: TermExtractionResult, apply_normalization: bool = True) -> ExtractedTermData:
    """Convert TermExtractionResult to ExtractedTermData with optional normalization."""
    value = result.value
    normalized = False
    raw_value = result.value
    
    if apply_normalization:
        normalized_value = normalize_term_value(result.key, result.value)
        if normalized_value != result.value:
            value = normalized_value
            normalized = True
    
    return ExtractedTermData(
        key=result.key,
        label=result.label,
        value=value,
        source=result.source,
        confidence=result.confidence,
        evidence_text=result.evidence_text,
        evidence_location=result.evidence_location,
        page=result.page,
        normalized=normalized,
        raw_value=raw_value,
    )


def extract_approved_terms(file_obj: BinaryIO, filename: str) -> List[ExtractedTermData]:
    """
    Extract terms from the Approved Credit Summary.
    
    REGULATORY REQUIREMENT:
    - All terms must have evidence from the document
    - No hallucination allowed
    
    Args:
        file_obj: File-like object containing the PDF
        filename: Original filename (for logging)
        
    Returns:
        List of extracted terms with evidence
    """
    logger.info(f"Extracting approved terms from: {filename}")
    
    try:
        # Extract text with page tracking
        pages = extract_text_with_pages(file_obj)
        pages_dict = _convert_pages_to_dict(pages)
        
        # Check if we got any text
        total_text = sum(len(p.text) for p in pages)
        if total_text < 100:
            logger.warning(f"Very little text extracted from {filename} ({total_text} chars)")
        
        # Extract terms using rule-based patterns
        extraction_results = extract_terms_from_text(
            pages_dict,
            source=SourceType.APPROVED.value
        )
        
        # Convert to legacy format with normalization
        terms = [
            _convert_extraction_result(result, apply_normalization=True)
            for result in extraction_results
        ]
        
        logger.info(f"Extracted {len(terms)} approved terms from {filename}")
        return terms
        
    except Exception as e:
        logger.error(f"Failed to extract approved terms from {filename}: {e}")
        raise


def extract_executed_terms(file_obj: BinaryIO, filename: str) -> List[ExtractedTermData]:
    """
    Extract terms from the Executed Agreement.
    
    REGULATORY REQUIREMENT:
    - All terms must have evidence from the document
    - No hallucination allowed
    
    Args:
        file_obj: File-like object containing the PDF
        filename: Original filename (for logging)
        
    Returns:
        List of extracted terms with evidence
    """
    logger.info(f"Extracting executed terms from: {filename}")
    
    try:
        # Extract text with page tracking
        pages = extract_text_with_pages(file_obj)
        pages_dict = _convert_pages_to_dict(pages)
        
        # Check if we got any text
        total_text = sum(len(p.text) for p in pages)
        if total_text < 100:
            logger.warning(f"Very little text extracted from {filename} ({total_text} chars)")
        
        # Extract terms using rule-based patterns
        extraction_results = extract_terms_from_text(
            pages_dict,
            source=SourceType.EXECUTED.value
        )
        
        # Convert to legacy format with normalization
        terms = [
            _convert_extraction_result(result, apply_normalization=True)
            for result in extraction_results
        ]
        
        logger.info(f"Extracted {len(terms)} executed terms from {filename}")
        return terms
        
    except Exception as e:
        logger.error(f"Failed to extract executed terms from {filename}: {e}")
        raise


def validate_terms_comparison(
    approved_terms: List[ExtractedTermData],
    executed_terms: List[ExtractedTermData]
) -> List[Dict[str, Any]]:
    """
    Compare approved terms against executed terms and generate issues.
    
    REGULATORY REQUIREMENT:
    - Every issue must have evidence from both documents
    - Severity must be justified based on regulatory impact
    
    Args:
        approved_terms: Terms from approved credit summary
        executed_terms: Terms from executed agreement
        
    Returns:
        List of issue dictionaries
    """
    logger.info(f"Validating {len(approved_terms)} approved vs {len(executed_terms)} executed terms")
    
    # Run validation
    issues = validate_terms(approved_terms, executed_terms)
    
    # Also check internal consistency
    approved_consistency = check_internal_consistency(approved_terms, 'APPROVED')
    executed_consistency = check_internal_consistency(executed_terms, 'EXECUTED')
    
    all_issues = issues + approved_consistency + executed_consistency
    
    # Convert to dictionaries
    issue_dicts = [issue.to_dict() for issue in all_issues]
    
    logger.info(f"Found {len(issue_dicts)} issues during validation")
    return issue_dicts


# Alias for backward compatibility with views.py
def validate_terms_legacy(
    approved_terms: List[ExtractedTermData],
    executed_terms: List[ExtractedTermData]
) -> List[Dict[str, Any]]:
    """Backward-compatible alias for validate_terms_comparison."""
    return validate_terms_comparison(approved_terms, executed_terms)


def extract_borrower_info(file_obj: BinaryIO) -> Dict[str, str]:
    """
    Extract borrower/facility info from a document.
    
    Returns:
        Dict with 'borrower_name' and 'facility_name' keys
    """
    try:
        pages = extract_text_with_pages(file_obj)
        pages_dict = _convert_pages_to_dict(pages)
        
        results = extract_terms_from_text(pages_dict, 'INFO')
        
        info = {
            'borrower_name': '',
            'facility_name': '',
        }
        
        for result in results:
            if result.key == 'borrower' and not info['borrower_name']:
                info['borrower_name'] = result.value
            elif result.key == 'facility_type' and not info['facility_name']:
                info['facility_name'] = result.value
        
        return info
        
    except Exception as e:
        logger.warning(f"Could not extract borrower info: {e}")
        return {'borrower_name': '', 'facility_name': ''}


def get_document_summary(file_obj: BinaryIO, filename: str) -> Dict[str, Any]:
    """
    Get a summary of a document including page count and detected terms.
    
    Args:
        file_obj: File-like object
        filename: Original filename
        
    Returns:
        Summary dictionary
    """
    try:
        file_hash = compute_sha256(file_obj)
        pages = extract_text_with_pages(file_obj)
        
        total_chars = sum(len(p.text) for p in pages)
        pages_with_text = sum(1 for p in pages if p.has_content)
        
        return {
            'filename': filename,
            'hash': file_hash,
            'page_count': len(pages),
            'pages_with_text': pages_with_text,
            'total_characters': total_chars,
            'extraction_methods': list(set(p.extraction_method for p in pages)),
        }
        
    except Exception as e:
        logger.error(f"Failed to get document summary: {e}")
        return {
            'filename': filename,
            'error': str(e),
        }
