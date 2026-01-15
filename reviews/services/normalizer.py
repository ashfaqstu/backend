"""
Normalizer service for DocConform.
Normalizes extracted values to standard formats.

REGULATORY REQUIREMENT:
- Normalization must be deterministic (no AI guessing)
- Original raw value must be preserved
- AI may only be used for format conversion, never for inference
"""

import re
import logging
from datetime import datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Month name mappings
MONTH_NAMES = {
    'january': '01', 'jan': '01',
    'february': '02', 'feb': '02',
    'march': '03', 'mar': '03',
    'april': '04', 'apr': '04',
    'may': '05',
    'june': '06', 'jun': '06',
    'july': '07', 'jul': '07',
    'august': '08', 'aug': '08',
    'september': '09', 'sep': '09', 'sept': '09',
    'october': '10', 'oct': '10',
    'november': '11', 'nov': '11',
    'december': '12', 'dec': '12',
}


def normalize_date(value: str) -> str:
    """
    Normalize a date string to ISO format (YYYY-MM-DD).
    
    Handles common formats:
    - August 25, 2026
    - Aug 25 2026
    - 08/25/2026
    - 25/08/2026
    - 2026-08-25
    
    Args:
        value: Raw date string
        
    Returns:
        ISO format date string, or original if parsing fails
    """
    if not value:
        return value
    
    value = value.strip()
    
    # Already in ISO format
    if re.match(r'^\d{4}-\d{2}-\d{2}$', value):
        return value
    
    # Format: Month DD, YYYY or Month DD YYYY
    match = re.match(
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})',
        value,
        re.IGNORECASE
    )
    if match:
        month = MONTH_NAMES[match.group(1).lower()]
        day = match.group(2).zfill(2)
        year = match.group(3)
        return f'{year}-{month}-{day}'
    
    # Format: MM/DD/YYYY
    match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', value)
    if match:
        month = match.group(1).zfill(2)
        day = match.group(2).zfill(2)
        year = match.group(3)
        return f'{year}-{month}-{day}'
    
    # Format: DD/MM/YYYY (European)
    match = re.match(r'(\d{1,2})-(\d{1,2})-(\d{4})', value)
    if match:
        # Assume DD-MM-YYYY for European format
        day = match.group(1).zfill(2)
        month = match.group(2).zfill(2)
        year = match.group(3)
        return f'{year}-{month}-{day}'
    
    # Format: YYYY/MM/DD
    match = re.match(r'(\d{4})/(\d{1,2})/(\d{1,2})', value)
    if match:
        year = match.group(1)
        month = match.group(2).zfill(2)
        day = match.group(3).zfill(2)
        return f'{year}-{month}-{day}'
    
    # Could not parse - return original
    logger.warning(f"Could not normalize date: {value}")
    return value


def normalize_currency_amount(value: str) -> Tuple[str, Optional[float]]:
    """
    Normalize a currency amount to standard format.
    
    Handles:
    - $6,000,000,000 -> USD 6,000,000,000
    - USD 300 million -> USD 300,000,000
    - 6 billion dollars -> USD 6,000,000,000
    
    Args:
        value: Raw currency string
        
    Returns:
        Tuple of (formatted string, numeric value or None)
    """
    if not value:
        return value, None
    
    value = value.strip()
    original = value
    
    # Detect currency
    currency = 'USD'  # Default
    if 'EUR' in value.upper() or '€' in value:
        currency = 'EUR'
    elif 'GBP' in value.upper() or '£' in value:
        currency = 'GBP'
    elif 'CHF' in value.upper():
        currency = 'CHF'
    elif 'JPY' in value.upper() or '¥' in value:
        currency = 'JPY'
    
    # Extract numeric value
    # Remove currency symbols and text
    cleaned = re.sub(r'[$€£¥]', '', value)
    cleaned = re.sub(r'(USD|EUR|GBP|CHF|JPY|dollars?|euros?|pounds?)', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    
    # Handle multipliers
    multiplier = 1
    if re.search(r'billion', value, re.IGNORECASE):
        multiplier = 1_000_000_000
    elif re.search(r'million', value, re.IGNORECASE):
        multiplier = 1_000_000
    elif re.search(r'thousand', value, re.IGNORECASE):
        multiplier = 1_000
    
    # Extract the numeric portion
    numeric_match = re.search(r'([\d,]+(?:\.\d+)?)', cleaned)
    if numeric_match:
        try:
            numeric_str = numeric_match.group(1).replace(',', '')
            numeric_value = float(numeric_str) * multiplier
            
            # Format with commas
            if numeric_value >= 1:
                formatted_value = f'{currency} {numeric_value:,.0f}'
            else:
                formatted_value = f'{currency} {numeric_value:,.2f}'
            
            return formatted_value, numeric_value
        except ValueError:
            pass
    
    # Could not parse - return original
    logger.warning(f"Could not normalize currency amount: {value}")
    return original, None


def normalize_basis_points(value: str) -> Tuple[str, Optional[int]]:
    """
    Normalize margin/spread to basis points.
    
    Handles:
    - 125 bps -> 125 bps
    - 1.25% -> 125 bps
    - SOFR + 1.25% -> 125 bps
    - 100-150 bps -> 100-150 bps (range)
    
    Args:
        value: Raw margin/spread string
        
    Returns:
        Tuple of (formatted string, numeric bps value or None)
    """
    if not value:
        return value, None
    
    value = value.strip()
    original = value
    
    # Check for range (e.g., "100-150 bps")
    range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:bps|bp|basis)', value, re.IGNORECASE)
    if range_match:
        low = int(range_match.group(1))
        high = int(range_match.group(2))
        return f'{low}-{high} bps', (low + high) // 2  # Return midpoint
    
    # Check for basis points directly
    bps_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:bps|bp|basis\s+points?)', value, re.IGNORECASE)
    if bps_match:
        bps = float(bps_match.group(1))
        return f'{int(bps)} bps', int(bps)
    
    # Check for percentage
    pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', value)
    if pct_match:
        pct = float(pct_match.group(1))
        bps = int(pct * 100)
        return f'{bps} bps', bps
    
    # Check for decimal (e.g., "0.0125" meaning 1.25%)
    decimal_match = re.search(r'^0\.(\d+)$', value)
    if decimal_match:
        pct = float(value) * 100
        bps = int(pct * 100)
        return f'{bps} bps', bps
    
    # Could not parse - return original
    logger.warning(f"Could not normalize basis points: {value}")
    return original, None


def normalize_ratio(value: str) -> Tuple[str, Optional[float]]:
    """
    Normalize a financial ratio.
    
    Handles:
    - 3.50 to 1.00 -> 3.50x
    - 3.50:1 -> 3.50x
    - 3.5x -> 3.50x
    
    Args:
        value: Raw ratio string
        
    Returns:
        Tuple of (formatted string, numeric value or None)
    """
    if not value:
        return value, None
    
    value = value.strip()
    
    # Format: X.XX to 1.00 or X.XX to 1
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:to|:)\s*1(?:\.00)?', value, re.IGNORECASE)
    if match:
        ratio = float(match.group(1))
        return f'{ratio:.2f}x', ratio
    
    # Format: X.XXx
    match = re.search(r'(\d+(?:\.\d+)?)\s*[x×]', value, re.IGNORECASE)
    if match:
        ratio = float(match.group(1))
        return f'{ratio:.2f}x', ratio
    
    # Just a number
    match = re.search(r'^(\d+(?:\.\d+)?)$', value)
    if match:
        ratio = float(match.group(1))
        return f'{ratio:.2f}x', ratio
    
    return value, None


def normalize_boolean(value: str) -> str:
    """
    Normalize boolean-like values.
    
    Args:
        value: Raw boolean string
        
    Returns:
        'Yes' or 'No'
    """
    if not value:
        return 'No'
    
    value = value.strip().lower()
    
    positive = ['yes', 'true', '1', 'present', 'found', 'included', 'required']
    if value in positive or any(p in value for p in positive):
        return 'Yes'
    
    return 'No'


def normalize_term_value(key: str, value: str) -> str:
    """
    Normalize a term value based on its key.
    
    This is the main entry point for normalization.
    Uses the appropriate normalizer based on the term type.
    
    Args:
        key: The term key (e.g., 'maturity_date', 'facility_amount')
        value: The raw extracted value
        
    Returns:
        Normalized value string
    """
    if not value:
        return value
    
    # Date fields
    if 'date' in key.lower():
        return normalize_date(value)
    
    # Amount fields
    if 'amount' in key.lower() or 'facility_amount' in key:
        normalized, _ = normalize_currency_amount(value)
        return normalized
    
    # Margin/spread fields
    if 'margin' in key.lower() or 'spread' in key.lower() or 'bps' in key.lower():
        normalized, _ = normalize_basis_points(value)
        return normalized
    
    # Ratio fields
    if 'ratio' in key.lower() or 'leverage' in key.lower() or 'coverage' in key.lower():
        normalized, _ = normalize_ratio(value)
        return normalized
    
    # Boolean fields
    if 'present' in key.lower() or 'required' in key.lower():
        return normalize_boolean(value)
    
    # Currency field
    if key == 'currency':
        value_upper = value.upper().strip()
        if 'DOLLAR' in value_upper or 'USD' in value_upper or '$' in value:
            return 'USD'
        elif 'EURO' in value_upper or 'EUR' in value_upper or '€' in value:
            return 'EUR'
        elif 'POUND' in value_upper or 'GBP' in value_upper or '£' in value:
            return 'GBP'
        return value_upper[:3] if len(value) >= 3 else value
    
    # Default: return as-is
    return value.strip()
