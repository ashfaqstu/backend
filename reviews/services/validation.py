"""
Validation service for DocConform.
Compares approved vs executed terms and generates regulatory issues.

REGULATORY REQUIREMENT:
- All issues must cite evidence from both documents
- No warnings without traceable evidence
- Issue severity must be justified
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class IssueSeverity(str, Enum):
    INFO = 'INFO'
    WARN = 'WARN'
    HIGH = 'HIGH'


class IssueCode(str, Enum):
    MISMATCH = 'MISMATCH'
    MULTIPLE_VALUES = 'MULTIPLE_VALUES'
    MISSING_CLAUSE = 'MISSING_CLAUSE'
    CLAUSE_PRESENT = 'CLAUSE_PRESENT'
    COMPLETENESS = 'COMPLETENESS'
    CONSISTENCY_FAIL = 'CONSISTENCY_FAIL'


@dataclass
class ValidationIssue:
    """
    A validation issue found during term comparison.
    All fields support regulatory traceability.
    """
    code: str
    severity: str
    message: str
    related_term_key: str
    related_term_label: str
    evidence: str
    approved_evidence: str
    executed_evidence: str
    regulation_impact: str
    
    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'severity': self.severity,
            'message': self.message,
            'related_term_key': self.related_term_key,
            'related_term_label': self.related_term_label,
            'evidence': self.evidence,
            'approved_evidence': self.approved_evidence,
            'executed_evidence': self.executed_evidence,
            'regulation_impact': self.regulation_impact,
        }


# Define validation rules with regulatory impacts
VALIDATION_RULES = {
    'facility_amount': {
        'high_severity': True,
        'regulation_impact': 'Material economic divergence exceeds approved credit limit. Requires immediate credit committee escalation and re-approval before drawdown.',
        'comparison': 'exact',  # exact, numeric, contains
    },
    'maturity_date': {
        'high_severity': True,
        'regulation_impact': 'Tenor mismatch affects facility classification and liquidity reporting. Verify whether deviation was authorized.',
        'comparison': 'date',
    },
    'margin_bps': {
        'high_severity': False,
        'regulation_impact': 'Pricing deviation may affect profitability calculations. Review against approved ROE thresholds.',
        'comparison': 'numeric',
    },
    'benchmark': {
        'high_severity': True,
        'regulation_impact': 'Benchmark rate change affects interest rate risk hedging requirements and regulatory reporting.',
        'comparison': 'exact',
    },
    'covenant_total_net_leverage': {
        'high_severity': False,
        'regulation_impact': 'Covenant threshold deviation may affect credit risk assessment and provisioning.',
        'comparison': 'numeric',
    },
    'covenant_interest_coverage': {
        'high_severity': False,
        'regulation_impact': 'Interest coverage covenant change may affect debt serviceability analysis.',
        'comparison': 'numeric',
    },
    'currency': {
        'high_severity': True,
        'regulation_impact': 'Currency mismatch affects FX risk calculations and regulatory capital requirements.',
        'comparison': 'exact',
    },
    'borrower': {
        'high_severity': True,
        'regulation_impact': 'Obligor identity mismatch is a critical error. Verify counterparty due diligence.',
        'comparison': 'fuzzy',
    },
}

# Required clauses that must be present
REQUIRED_CLAUSES = {
    'sanctions_clause_present': {
        'label': 'Sanctions Clause',
        'regulation_impact': 'Sanctions clause required per OFAC compliance policy. Missing clause may block drawdown.',
    },
    'bail_in_clause_present': {
        'label': 'Bail-In Clause',
        'regulation_impact': 'Bail-In recognition clause required per Article 55 BRRD for contracts with EU/EEA counterparties.',
    },
}


def _normalize_for_comparison(value: str) -> str:
    """Normalize a value for comparison."""
    if not value:
        return ""
    
    # Convert to lowercase and strip
    normalized = value.lower().strip()
    
    # Remove common variations
    normalized = normalized.replace(',', '')
    normalized = normalized.replace('$', '')
    normalized = normalized.replace('usd', '')
    normalized = normalized.replace('  ', ' ')
    
    return normalized


def _values_match(approved_val: str, executed_val: str, comparison_type: str) -> bool:
    """
    Compare two values based on comparison type.
    """
    if comparison_type == 'exact':
        return _normalize_for_comparison(approved_val) == _normalize_for_comparison(executed_val)
    
    elif comparison_type == 'numeric':
        # Extract numeric portions
        import re
        approved_nums = re.findall(r'[\d.]+', approved_val)
        executed_nums = re.findall(r'[\d.]+', executed_val)
        
        if not approved_nums or not executed_nums:
            return _normalize_for_comparison(approved_val) == _normalize_for_comparison(executed_val)
        
        try:
            approved_num = float(approved_nums[0])
            executed_num = float(executed_nums[0])
            # Allow 0.1% tolerance for numeric comparisons
            return abs(approved_num - executed_num) / max(approved_num, 1) < 0.001
        except ValueError:
            return False
    
    elif comparison_type == 'date':
        # Normalize date formats
        from .normalizer import normalize_date
        approved_normalized = normalize_date(approved_val)
        executed_normalized = normalize_date(executed_val)
        return approved_normalized == executed_normalized
    
    elif comparison_type == 'fuzzy':
        # Check if one contains the other (for entity names)
        approved_clean = _normalize_for_comparison(approved_val)
        executed_clean = _normalize_for_comparison(executed_val)
        return approved_clean in executed_clean or executed_clean in approved_clean
    
    elif comparison_type == 'contains':
        return _normalize_for_comparison(approved_val) in _normalize_for_comparison(executed_val)
    
    return False


def validate_terms(
    approved_terms: List[Any],
    executed_terms: List[Any]
) -> List[ValidationIssue]:
    """
    Compare approved terms against executed terms and generate issues.
    
    REGULATORY REQUIREMENT:
    - Every issue must cite evidence from both documents
    - HIGH severity for material deviations
    - WARN for non-material deviations
    - INFO for confirmations (clauses present)
    
    Args:
        approved_terms: List of terms from approved credit summary
        executed_terms: List of terms from executed agreement
        
    Returns:
        List of validation issues
    """
    issues = []
    
    # Build lookup dictionaries
    approved_lookup = {}
    for term in approved_terms:
        key = term.key if hasattr(term, 'key') else term.get('key')
        approved_lookup[key] = term
    
    executed_lookup = {}
    for term in executed_terms:
        key = term.key if hasattr(term, 'key') else term.get('key')
        executed_lookup[key] = term
    
    # 1) Compare matching terms
    for term_key, rule in VALIDATION_RULES.items():
        if term_key in approved_lookup and term_key in executed_lookup:
            approved_term = approved_lookup[term_key]
            executed_term = executed_lookup[term_key]
            
            # Get values
            approved_val = approved_term.value if hasattr(approved_term, 'value') else approved_term.get('value', '')
            executed_val = executed_term.value if hasattr(executed_term, 'value') else executed_term.get('value', '')
            
            # Get evidence
            approved_evidence = approved_term.evidence_text if hasattr(approved_term, 'evidence_text') else approved_term.get('evidence_text', '')
            executed_evidence = executed_term.evidence_text if hasattr(executed_term, 'evidence_text') else executed_term.get('evidence_text', '')
            
            # Get label
            label = approved_term.label if hasattr(approved_term, 'label') else approved_term.get('label', term_key)
            
            # Compare values
            if not _values_match(approved_val, executed_val, rule['comparison']):
                severity = IssueSeverity.HIGH.value if rule['high_severity'] else IssueSeverity.WARN.value
                
                issues.append(ValidationIssue(
                    code=IssueCode.MISMATCH.value,
                    severity=severity,
                    message=f'{label} differs between Approved Credit Summary and Executed Agreement',
                    related_term_key=term_key,
                    related_term_label=label,
                    evidence=f'Approved: {approved_val} vs Executed: {executed_val}',
                    approved_evidence=approved_evidence,
                    executed_evidence=executed_evidence,
                    regulation_impact=rule['regulation_impact']
                ))
    
    # 2) Check for required clauses
    for clause_key, clause_info in REQUIRED_CLAUSES.items():
        # Check if required in approved
        approved_key = clause_key.replace('_present', '_required')
        is_required = approved_key in approved_lookup
        
        if not is_required:
            # Also check if the clause itself is marked as required
            is_required = clause_key in approved_lookup
        
        # Check if present in executed
        is_present = clause_key in executed_lookup
        if is_present:
            executed_term = executed_lookup[clause_key]
            executed_val = executed_term.value if hasattr(executed_term, 'value') else executed_term.get('value', '')
            is_present = executed_val.lower() in ('yes', 'true', 'present', '1')
        
        if is_present:
            # Clause is present - INFO level confirmation
            executed_term = executed_lookup[clause_key]
            executed_evidence = executed_term.evidence_text if hasattr(executed_term, 'evidence_text') else executed_term.get('evidence_text', '')
            
            issues.append(ValidationIssue(
                code=IssueCode.CLAUSE_PRESENT.value,
                severity=IssueSeverity.INFO.value,
                message=f'{clause_info["label"]} is present in executed agreement',
                related_term_key=clause_key,
                related_term_label=clause_info['label'],
                evidence=f'{clause_info["label"]} found in executed document',
                approved_evidence='Required per credit policy',
                executed_evidence=executed_evidence,
                regulation_impact=clause_info['regulation_impact'].replace('Missing clause', 'Clause present -')
            ))
        elif is_required:
            # Required but missing - WARN level
            issues.append(ValidationIssue(
                code=IssueCode.MISSING_CLAUSE.value,
                severity=IssueSeverity.WARN.value,
                message=f'{clause_info["label"]} is required but not found in executed agreement',
                related_term_key=clause_key,
                related_term_label=clause_info['label'],
                evidence=f'{clause_info["label"]} not detected in executed document',
                approved_evidence='Required per credit policy',
                executed_evidence='Not found',
                regulation_impact=clause_info['regulation_impact']
            ))
    
    # 3) Check for missing expected terms
    for term_key in approved_lookup:
        if term_key not in executed_lookup and term_key in VALIDATION_RULES:
            approved_term = approved_lookup[term_key]
            label = approved_term.label if hasattr(approved_term, 'label') else approved_term.get('label', term_key)
            approved_evidence = approved_term.evidence_text if hasattr(approved_term, 'evidence_text') else approved_term.get('evidence_text', '')
            
            issues.append(ValidationIssue(
                code=IssueCode.COMPLETENESS.value,
                severity=IssueSeverity.WARN.value,
                message=f'{label} was approved but not found in executed agreement',
                related_term_key=term_key,
                related_term_label=label,
                evidence=f'Approved: Found vs Executed: Not found',
                approved_evidence=approved_evidence,
                executed_evidence='Term not detected in executed document',
                regulation_impact='Missing term may indicate incomplete agreement or extraction failure. Manual review recommended.'
            ))
    
    return issues


def check_internal_consistency(
    terms: List[Any],
    source: str
) -> List[ValidationIssue]:
    """
    Check for internal consistency within a single document.
    
    Looks for:
    - Multiple different values for the same term
    - Contradictory information
    
    Args:
        terms: List of extracted terms from one document
        source: Document source (APPROVED/EXECUTED)
        
    Returns:
        List of consistency issues
    """
    issues = []
    
    # Group terms by key
    terms_by_key: Dict[str, List[Any]] = {}
    for term in terms:
        key = term.key if hasattr(term, 'key') else term.get('key')
        if key not in terms_by_key:
            terms_by_key[key] = []
        terms_by_key[key].append(term)
    
    # Check for multiple values
    for key, term_list in terms_by_key.items():
        if len(term_list) > 1:
            values = set()
            for term in term_list:
                val = term.value if hasattr(term, 'value') else term.get('value', '')
                values.add(_normalize_for_comparison(val))
            
            if len(values) > 1:
                # Multiple different values found
                label = term_list[0].label if hasattr(term_list[0], 'label') else term_list[0].get('label', key)
                all_values = [term.value if hasattr(term, 'value') else term.get('value', '') for term in term_list]
                
                issues.append(ValidationIssue(
                    code=IssueCode.MULTIPLE_VALUES.value,
                    severity=IssueSeverity.WARN.value,
                    message=f'Multiple different values found for {label} in {source} document',
                    related_term_key=key,
                    related_term_label=label,
                    evidence=f'Values found: {", ".join(all_values)}',
                    approved_evidence='' if source == 'EXECUTED' else f'Values: {", ".join(all_values)}',
                    executed_evidence=f'Values: {", ".join(all_values)}' if source == 'EXECUTED' else '',
                    regulation_impact='Internal inconsistency may indicate drafting errors. Verify which value is authoritative.'
                ))
    
    return issues
