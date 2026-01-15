"""
DocConform document processing services.
All extraction is evidence-based - no hallucinated data allowed.
"""

from .text_extractor import (
    extract_text_from_pdf,
    extract_text_with_pages,
    compute_sha256,
)
from .term_extractor import (
    extract_terms_from_text,
    TermExtractionResult,
)
from .validation import (
    validate_terms,
    ValidationIssue,
)
from .normalizer import (
    normalize_date,
    normalize_currency_amount,
    normalize_basis_points,
)

__all__ = [
    'extract_text_from_pdf',
    'extract_text_with_pages',
    'compute_sha256',
    'extract_terms_from_text',
    'TermExtractionResult',
    'validate_terms',
    'ValidationIssue',
    'normalize_date',
    'normalize_currency_amount',
    'normalize_basis_points',
]
