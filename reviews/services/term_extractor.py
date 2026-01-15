"""
Term extraction service for DocConform.
Rule-based extraction with mandatory evidence.

REGULATORY REQUIREMENT: 
- Every extracted term MUST have evidence from the document
- No hallucination or inference allowed
- If evidence cannot be found, term is not created
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Pattern
from enum import Enum

logger = logging.getLogger(__name__)


class SourceType(str, Enum):
    EXECUTED = 'EXECUTED'
    APPROVED = 'APPROVED'
    TERMSHEET = 'TERMSHEET'


@dataclass
class TermExtractionResult:
    """
    Result of extracting a single term from a document.
    All fields are required for regulatory traceability.
    """
    key: str
    label: str
    value: str
    source: str
    page: int
    evidence_text: str
    evidence_location: str
    confidence: float
    raw_match: str = ""  # The actual regex match before normalization
    normalized: bool = False  # Whether value was normalized
    
    def to_dict(self) -> dict:
        return {
            'key': self.key,
            'label': self.label,
            'value': self.value,
            'source': self.source,
            'page': self.page,
            'evidence_text': self.evidence_text,
            'evidence_location': self.evidence_location,
            'confidence': self.confidence,
        }


@dataclass
class ExtractionRule:
    """
    Definition of a term extraction rule.
    """
    key: str
    label: str
    patterns: List[Pattern]  # Regex patterns to search for
    context_patterns: List[Pattern] = field(default_factory=list)  # Optional context hints
    extract_group: int = 1  # Which regex group contains the value
    confidence_base: float = 0.85
    normalizer: Optional[str] = None  # Name of normalizer to apply
    

# Define extraction rules for loan agreement terms
EXTRACTION_RULES: List[ExtractionRule] = [
    # Borrower / Obligor
    ExtractionRule(
        key='borrower',
        label='Borrower',
        patterns=[
            re.compile(r'(?:borrower|obligor)[:\s]+([A-Z][A-Za-z\s,\.]+(?:Inc\.|Corp\.|LLC|Company|Corporation|Limited))', re.IGNORECASE),
            re.compile(r'([A-Z][A-Z\s]+(?:COMPANY|CORPORATION|INC\.|CORP\.)),?\s*(?:a\s+\w+\s+corporation)', re.IGNORECASE),
            re.compile(r'"Borrower"\s+means?\s+([A-Za-z\s,\.]+(?:Inc\.|Corp\.|LLC|Company|Corporation))', re.IGNORECASE),
        ],
        confidence_base=0.90
    ),
    
    # Facility Amount
    ExtractionRule(
        key='facility_amount',
        label='Facility Amount',
        patterns=[
            re.compile(r'(?:aggregate\s+)?(?:commitment|facility)(?:\s+amount)?[:\s]*(?:USD|US\$|\$)\s*([\d,]+(?:\.\d+)?)', re.IGNORECASE),
            re.compile(r'(?:USD|US\$|\$)\s*([\d,]+(?:\.\d+)?)\s*(?:million|,000,000)', re.IGNORECASE),
            re.compile(r'(?:principal|total)\s+(?:amount|sum)[:\s]*(?:USD|US\$|\$)\s*([\d,]+(?:\.\d+)?)', re.IGNORECASE),
            re.compile(r'"Aggregate Commitments"[^$]*\$([\d,]+(?:\.\d+)?)', re.IGNORECASE),
        ],
        normalizer='currency',
        confidence_base=0.85
    ),
    
    # Currency
    ExtractionRule(
        key='currency',
        label='Currency',
        patterns=[
            re.compile(r'(?:currency|denomination)[:\s]*(USD|EUR|GBP|CHF|JPY|United States Dollars?)', re.IGNORECASE),
            re.compile(r'(Dollars?|USD|US\$)\s+(?:or\s+\$\s+)?refers?\s+to\s+(?:lawful\s+)?money', re.IGNORECASE),
            re.compile(r'(?:in|denominated\s+in)\s+(USD|EUR|GBP|United States Dollars)', re.IGNORECASE),
        ],
        confidence_base=0.95
    ),
    
    # Maturity Date
    ExtractionRule(
        key='maturity_date',
        label='Maturity Date',
        patterns=[
            re.compile(r'(?:maturity|termination|expiry)\s*date[:\s]*((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})', re.IGNORECASE),
            re.compile(r'"Maturity Date"\s+means?\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})', re.IGNORECASE),
            re.compile(r'(?:maturity|termination)\s*date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', re.IGNORECASE),
            re.compile(r'(?:maturity|termination)\s*date[:\s]*(\d{4}-\d{2}-\d{2})', re.IGNORECASE),
        ],
        normalizer='date',
        confidence_base=0.90
    ),
    
    # Interest Rate Benchmark
    ExtractionRule(
        key='benchmark',
        label='Interest Rate Benchmark',
        patterns=[
            re.compile(r'(?:benchmark|reference)\s*(?:rate)?[:\s]*(SOFR|LIBOR|EURIBOR|SONIA|Term SOFR|Adjusted Term SOFR)', re.IGNORECASE),
            re.compile(r'"Term SOFR"\s+means', re.IGNORECASE),
            re.compile(r'(SOFR|LIBOR|EURIBOR)\s*[+\-]', re.IGNORECASE),
        ],
        confidence_base=0.92
    ),
    
    # Applicable Margin (basis points)
    ExtractionRule(
        key='margin_bps',
        label='Applicable Margin',
        patterns=[
            re.compile(r'(?:applicable\s+)?(?:margin|spread)[:\s]*(\d+(?:\.\d+)?)\s*(?:basis\s+points|bps|bp)', re.IGNORECASE),
            re.compile(r'(?:applicable\s+)?(?:margin|spread)[:\s]*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE),
            re.compile(r'(?:SOFR|LIBOR|benchmark)\s*[+]\s*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE),
            re.compile(r'Applicable Rate[^%]*(\d+(?:\.\d+)?)\s*%', re.IGNORECASE),
        ],
        normalizer='basis_points',
        confidence_base=0.85
    ),
    
    # Total Net Leverage Covenant
    ExtractionRule(
        key='covenant_total_net_leverage',
        label='Total Net Leverage Covenant',
        patterns=[
            re.compile(r'(?:total\s+)?(?:net\s+)?leverage\s*(?:ratio)?[:\s]*(?:not\s+(?:to\s+)?exceed\s+)?(\d+(?:\.\d+)?)\s*(?:to\s*1(?:\.00)?|[x×])', re.IGNORECASE),
            re.compile(r'(?:maximum\s+)?(?:total\s+)?leverage\s*ratio[:\s]*(\d+(?:\.\d+)?)\s*(?:to\s*1|[x×])', re.IGNORECASE),
            re.compile(r'(\d+(?:\.\d+)?)\s*to\s*1(?:\.00)?\s*(?:leverage|debt)', re.IGNORECASE),
        ],
        confidence_base=0.88
    ),
    
    # Interest Coverage Ratio
    ExtractionRule(
        key='covenant_interest_coverage',
        label='Interest Coverage Covenant',
        patterns=[
            re.compile(r'interest\s+coverage\s*(?:ratio)?[:\s]*(?:not\s+(?:less\s+than|below)\s+)?(\d+(?:\.\d+)?)\s*(?:to\s*1|[x×])', re.IGNORECASE),
            re.compile(r'(?:minimum\s+)?interest\s+coverage[:\s]*(\d+(?:\.\d+)?)', re.IGNORECASE),
        ],
        confidence_base=0.88
    ),
    
    # Covenant Testing Frequency
    ExtractionRule(
        key='covenant_frequency',
        label='Covenant Testing Frequency',
        patterns=[
            re.compile(r'(?:testing|compliance)\s*(?:frequency|period)[:\s]*(quarterly|semi-annually|annually|monthly)', re.IGNORECASE),
            re.compile(r'(?:tested|measured)\s+(quarterly|semi-annually|annually|monthly)', re.IGNORECASE),
            re.compile(r'(quarterly|semi-annual|annual)\s+(?:testing|compliance|reporting)', re.IGNORECASE),
        ],
        confidence_base=0.85
    ),
    
    # Sanctions Clause
    ExtractionRule(
        key='sanctions_clause_present',
        label='Sanctions Clause Present',
        patterns=[
            re.compile(r'"Sanctions"\s+means?\s+(?:any\s+)?(?:economic\s+or\s+financial\s+)?sanctions', re.IGNORECASE),
            re.compile(r'OFAC[,\s]+(?:the\s+)?U\.?S\.?\s+Department\s+of\s+(?:the\s+)?Treasury', re.IGNORECASE),
            re.compile(r'sanctions\s+(?:administered|enforced)\s+(?:by|under)', re.IGNORECASE),
        ],
        confidence_base=0.92
    ),
    
    # Bail-In Clause
    ExtractionRule(
        key='bail_in_clause_present',
        label='Bail-In Clause Present',
        patterns=[
            re.compile(r'(?:acknowledgement|acknowledgment)\s+(?:and\s+)?(?:consent\s+)?(?:to\s+)?bail[-\s]?in', re.IGNORECASE),
            re.compile(r'(?:EU|EEA)\s+bail[-\s]?in\s+(?:legislation|clause|recognition)', re.IGNORECASE),
            re.compile(r'BRRD|Bank\s+Recovery\s+and\s+Resolution\s+Directive', re.IGNORECASE),
            re.compile(r'Affected\s+Financial\s+Institutions?.*bail[-\s]?in', re.IGNORECASE),
        ],
        confidence_base=0.92
    ),
    
    # Facility Type
    ExtractionRule(
        key='facility_type',
        label='Facility Type',
        patterns=[
            re.compile(r'((?:364[-\s]?day|revolving|term|bridge|swingline)\s+(?:credit\s+)?(?:facility|loan|agreement))', re.IGNORECASE),
            re.compile(r'(?:type\s+of\s+)?facility[:\s]*(revolving|term\s+loan|bridge|swingline)', re.IGNORECASE),
        ],
        confidence_base=0.88
    ),
]


def _get_context_snippet(text: str, match_start: int, match_end: int, context_chars: int = 100) -> str:
    """Extract a context snippet around a match for evidence."""
    start = max(0, match_start - context_chars)
    end = min(len(text), match_end + context_chars)
    
    snippet = text[start:end]
    
    # Clean up the snippet
    snippet = ' '.join(snippet.split())
    
    # Add ellipsis if truncated
    if start > 0:
        snippet = '...' + snippet
    if end < len(text):
        snippet = snippet + '...'
    
    return snippet


def _find_page_for_position(pages: List[dict], position: int) -> int:
    """
    Find which page a character position belongs to.
    
    Args:
        pages: List of {'page': int, 'text': str, 'start': int, 'end': int}
        position: Character position in combined text
        
    Returns:
        Page number (1-indexed)
    """
    for page_info in pages:
        if page_info['start'] <= position < page_info['end']:
            return page_info['page']
    return 1  # Default to page 1 if not found


def extract_terms_from_text(
    pages: List[dict],
    source: str,
    rules: Optional[List[ExtractionRule]] = None
) -> List[TermExtractionResult]:
    """
    Extract terms from document text using rule-based patterns.
    
    REGULATORY REQUIREMENT: Only returns terms with actual evidence.
    No terms are created without matching text in the document.
    
    Args:
        pages: List of {'page': int, 'text': str} for each page
        source: Source type (EXECUTED, APPROVED, TERMSHEET)
        rules: Optional custom rules, defaults to EXTRACTION_RULES
        
    Returns:
        List of extracted terms with evidence
    """
    if rules is None:
        rules = EXTRACTION_RULES
    
    # Build combined text with position tracking
    combined_text = ""
    page_positions = []
    
    for page_info in pages:
        start = len(combined_text)
        page_text = page_info.get('text', '')
        combined_text += page_text + "\n\n"
        page_positions.append({
            'page': page_info.get('page', 1),
            'text': page_text,
            'start': start,
            'end': len(combined_text)
        })
    
    extracted_terms = []
    found_keys = set()  # Track already-found terms to avoid duplicates
    
    for rule in rules:
        if rule.key in found_keys:
            continue
            
        best_match = None
        best_confidence = 0
        
        for pattern in rule.patterns:
            for match in pattern.finditer(combined_text):
                # Calculate confidence based on match quality
                confidence = rule.confidence_base
                
                # Boost confidence for longer matches (more context)
                if len(match.group(0)) > 50:
                    confidence += 0.05
                
                # Reduce confidence for partial matches
                if match.lastindex and match.lastindex < rule.extract_group:
                    confidence -= 0.10
                
                confidence = min(1.0, max(0.0, confidence))
                
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = match
        
        if best_match:
            # Extract the value
            try:
                if best_match.lastindex and best_match.lastindex >= rule.extract_group:
                    value = best_match.group(rule.extract_group)
                else:
                    value = best_match.group(0)
            except IndexError:
                value = best_match.group(0)
            
            # Find the page
            page_num = _find_page_for_position(page_positions, best_match.start())
            
            # Get evidence context
            evidence_text = _get_context_snippet(
                combined_text, 
                best_match.start(), 
                best_match.end()
            )
            
            # Special handling for boolean-like terms
            if rule.key in ('sanctions_clause_present', 'bail_in_clause_present'):
                value = 'Yes'
            
            # Clean up the value
            value = value.strip()
            
            extracted_terms.append(TermExtractionResult(
                key=rule.key,
                label=rule.label,
                value=value,
                source=source,
                page=page_num,
                evidence_text=evidence_text,
                evidence_location=f'Page {page_num}',
                confidence=best_confidence,
                raw_match=best_match.group(0),
                normalized=False
            ))
            found_keys.add(rule.key)
    
    return extracted_terms


def extract_with_custom_patterns(
    pages: List[dict],
    source: str,
    custom_patterns: Dict[str, List[str]]
) -> List[TermExtractionResult]:
    """
    Extract terms using custom regex patterns.
    
    Args:
        pages: Document pages
        source: Source type
        custom_patterns: Dict of {key: [pattern strings]}
        
    Returns:
        List of extracted terms
    """
    custom_rules = []
    
    for key, patterns in custom_patterns.items():
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        custom_rules.append(ExtractionRule(
            key=key,
            label=key.replace('_', ' ').title(),
            patterns=compiled_patterns
        ))
    
    return extract_terms_from_text(pages, source, custom_rules)


def verify_term_in_document(
    pages: List[dict],
    term_key: str,
    expected_value: str
) -> Optional[TermExtractionResult]:
    """
    Verify that a specific term exists in the document.
    Used for cross-validation.
    
    Returns:
        The extraction result if found, None otherwise
    """
    results = extract_terms_from_text(pages, 'VERIFICATION')
    
    for result in results:
        if result.key == term_key:
            return result
    
    return None
