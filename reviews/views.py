import hashlib
import time
import csv
import io
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.http import HttpResponse

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from .models import Review, ExtractedTerm, Issue, AuditEvent, ReviewStatus, SourceType, IssueSeverity, IssueCode
from .serializers import (
    ReviewListSerializer, 
    ReviewDetailSerializer, 
    ReviewCreateSerializer,
    IssueSerializer,
    ExtractedTermSerializer,
    AuditEventSerializer
)
from .extraction import (
    compute_file_hash,
    extract_text_from_pdf,
    extract_approved_terms,
    extract_executed_terms,
    validate_terms_comparison as validate_terms
)


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all()
    parser_classes = (MultiPartParser, FormParser)

    def get_serializer_class(self):
        if self.action == 'list':
            return ReviewListSerializer
        if self.action == 'create':
            return ReviewCreateSerializer
        return ReviewDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = serializer.save()
        
        # Return the created review with detail serializer
        detail_serializer = ReviewDetailSerializer(review)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """
        Trigger document processing/extraction for a review.
        Uses deterministic extraction for Boeing Credit Agreement demo.
        """
        review = self.get_object()
        
        if review.status == ReviewStatus.COMPLETE:
            return Response(
                {'error': 'Review has already been processed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update status to processing
        review.status = ReviewStatus.PROCESSING
        review.save()

        # Run real extraction
        self._run_extraction(review)

        # Return updated review
        serializer = ReviewDetailSerializer(review)
        return Response(serializer.data)

    def _run_extraction(self, review):
        """
        Run deterministic extraction for Boeing Credit Agreement demo.
        Extracts approved terms from term sheet, executed terms from agreement,
        and validates for non-conformance.
        """
        has_term_sheet = bool(review.term_sheet_file_name)
        has_executed = bool(review.executed_file_name)

        # Compute file hashes
        if has_executed and review.executed_file:
            review.executed_file.seek(0)
            review.executed_file_hash = compute_file_hash(review.executed_file)
            review.executed_file.seek(0)
        
        if has_term_sheet and review.term_sheet_file:
            review.term_sheet_file.seek(0)
            review.term_sheet_file_hash = compute_file_hash(review.term_sheet_file)
            review.term_sheet_file.seek(0)

        # Update borrower and facility info for Boeing demo
        review.borrower_name = 'The Boeing Company'
        review.facility_name = '364-Day Credit Agreement (5-Year Term Loan)'

        # Extract approved terms from term sheet
        approved_terms_list = []
        approved_terms_dict = {}
        if has_term_sheet and review.term_sheet_file:
            approved_terms_list = extract_approved_terms(review.term_sheet_file, review.term_sheet_file_name)
            for term_data in approved_terms_list:
                approved_terms_dict[term_data.key] = term_data
                ExtractedTerm.objects.create(
                    review=review,
                    key=term_data.key,
                    label=term_data.label,
                    value=term_data.value,
                    source=SourceType.APPROVED,
                    confidence=term_data.confidence,
                    is_match=True,  # Approved terms are always "matched" to themselves
                    evidence_text=term_data.evidence_text,
                    evidence_location=term_data.evidence_location
                )

        # Extract executed terms from agreement
        executed_terms_list = extract_executed_terms(review.executed_file, review.executed_file_name) if has_executed and review.executed_file else []
        executed_terms_dict = {}
        for term_data in executed_terms_list:
            executed_terms_dict[term_data.key] = term_data
            # Determine if this term matches approved
            is_match = True
            if term_data.key in approved_terms_dict:
                is_match = term_data.value == approved_terms_dict[term_data.key].value
            
            ExtractedTerm.objects.create(
                review=review,
                key=term_data.key,
                label=term_data.label,
                value=term_data.value,
                source=SourceType.EXECUTED,
                confidence=term_data.confidence,
                is_match=is_match,
                evidence_text=term_data.evidence_text,
                evidence_location=term_data.evidence_location
            )

        # Validate terms and create issues
        if has_term_sheet:
            issues = validate_terms(approved_terms_list, executed_terms_list)
            for issue_data in issues:
                Issue.objects.create(
                    review=review,
                    severity=issue_data['severity'],
                    code=issue_data['code'],
                    message=issue_data['message'],
                    related_term_label=issue_data.get('related_term_label', ''),
                    related_term_key=issue_data.get('related_term_key', ''),
                    evidence=issue_data.get('evidence', ''),
                    regulation_impact=issue_data.get('regulation_impact', ''),
                    approved_evidence=issue_data.get('approved_evidence', ''),
                    executed_evidence=issue_data.get('executed_evidence', '')
                )

        # Create audit events
        AuditEvent.objects.create(
            review=review,
            actor='DocConform Engine',
            action='EXTRACT',
            details=f'Extracted {len(executed_terms_list)} key terms from executed agreement.',
            hash=review.executed_file_hash[:16] if review.executed_file_hash else None
        )

        if has_term_sheet:
            AuditEvent.objects.create(
                review=review,
                actor='DocConform Engine',
                action='VALIDATE',
                details=f'Validated against {review.term_sheet_file_name}. Found {Issue.objects.filter(review=review).count()} issues.',
                hash=review.term_sheet_file_hash[:16] if review.term_sheet_file_hash else None
            )

        # Update status to complete
        review.status = ReviewStatus.COMPLETE
        review.save()

    @action(detail=True, methods=['post'])
    def export(self, request, pk=None):
        """
        Export the review data (POST for triggering export with audit).
        """
        review = self.get_object()
        format_type = request.data.get('format', 'json')

        # Create audit event for export
        AuditEvent.objects.create(
            review=review,
            actor='System User',
            action='EXPORT',
            details=f'Exported review data in {format_type.upper()} format.',
            hash=hashlib.sha256(str(review.id).encode()).hexdigest()[:16]
        )

        serializer = ReviewDetailSerializer(review)
        return Response({
            'format': format_type,
            'data': serializer.data,
            'exportedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        })

    @action(detail=True, methods=['get'], url_path='export-json')
    def export_json(self, request, pk=None):
        """
        GET endpoint to download review data as JSON.
        Includes file hashes, terms, issues, and audit log.
        """
        review = self.get_object()
        
        # Create audit event for export
        AuditEvent.objects.create(
            review=review,
            actor='System User',
            action='EXPORT',
            details='Exported review data in JSON format.',
            hash=hashlib.sha256(str(review.id).encode()).hexdigest()[:16]
        )

        serializer = ReviewDetailSerializer(review)
        export_data = {
            'exportedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'format': 'json',
            'review': serializer.data
        }
        
        response = Response(export_data)
        response['Content-Disposition'] = f'attachment; filename="review_{review.id}_export.json"'
        return response

    @action(detail=True, methods=['get'], url_path='export-csv')
    def export_csv(self, request, pk=None):
        """
        GET endpoint to download terms comparison as CSV.
        Shows side-by-side Approved vs Executed values with MATCH/MISMATCH status.
        """
        review = self.get_object()
        
        # Create audit event for export
        AuditEvent.objects.create(
            review=review,
            actor='System User',
            action='EXPORT',
            details='Exported review data in CSV format.',
            hash=hashlib.sha256(str(review.id).encode()).hexdigest()[:16]
        )

        # Build CSV response
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header row
        writer.writerow([
            'Term Key',
            'Term Label',
            'Approved Value',
            'Approved Location',
            'Executed Value',
            'Executed Location',
            'Status',
            'Confidence'
        ])

        # Get all terms grouped by key
        approved_terms = {t.key: t for t in review.terms.filter(source=SourceType.APPROVED)}
        executed_terms = {t.key: t for t in review.terms.filter(source=SourceType.EXECUTED)}
        
        # Get all unique keys
        all_keys = set(approved_terms.keys()) | set(executed_terms.keys())
        
        for key in sorted(all_keys):
            approved = approved_terms.get(key)
            executed = executed_terms.get(key)
            
            approved_value = approved.value if approved else 'N/A'
            approved_location = approved.evidence_location if approved else ''
            executed_value = executed.value if executed else 'N/A'
            executed_location = executed.evidence_location if executed else ''
            
            # Determine match status
            if approved and executed:
                status = 'MATCH' if approved.value == executed.value else 'MISMATCH'
            elif approved:
                status = 'MISSING_EXECUTED'
            else:
                status = 'APPROVED_ONLY'
            
            confidence = executed.confidence if executed else (approved.confidence if approved else 0)
            label = executed.label if executed else (approved.label if approved else key)
            
            writer.writerow([
                key,
                label,
                approved_value,
                approved_location,
                executed_value,
                executed_location,
                status,
                f'{confidence:.2f}'
            ])

        # Create HTTP response with CSV content
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="review_{review.id}_terms.csv"'
        return response

    @action(detail=True, methods=['get'], url_path='export-pdf')
    def export_pdf(self, request, pk=None):
        """
        GET endpoint to download review report as PDF.
        Includes executive summary, terms comparison, issues, and audit trail.
        """
        review = self.get_object()
        
        # Create audit event for export
        AuditEvent.objects.create(
            review=review,
            actor='System User',
            action='EXPORT',
            details='Exported review data in PDF format.',
            hash=hashlib.sha256(str(review.id).encode()).hexdigest()[:16]
        )

        # Create PDF buffer
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            textColor=colors.HexColor('#1E3A8A')
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor('#1E3A8A')
        )
        subheading_style = ParagraphStyle(
            'CustomSubheading',
            parent=styles['Heading3'],
            fontSize=12,
            spaceBefore=15,
            spaceAfter=8,
            textColor=colors.HexColor('#374151')
        )
        normal_style = styles['Normal']
        
        # Build PDF content
        elements = []
        
        # Title
        elements.append(Paragraph("DocConform Conformance Report", title_style))
        elements.append(Spacer(1, 10))
        
        # Executive Summary
        elements.append(Paragraph("Executive Summary", heading_style))
        
        summary_data = [
            ['Borrower:', review.borrower_name or 'N/A'],
            ['Facility:', review.facility_name or 'N/A'],
            ['Review ID:', str(review.id)],
            ['Status:', review.status],
            ['Created:', review.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')],
            ['Executed Document:', review.executed_file_name or 'N/A'],
            ['Term Sheet:', review.term_sheet_file_name or 'N/A'],
        ]
        
        if review.executed_file_hash:
            summary_data.append(['Executed File Hash:', review.executed_file_hash[:32] + '...'])
        if review.term_sheet_file_hash:
            summary_data.append(['Term Sheet Hash:', review.term_sheet_file_hash[:32] + '...'])
        
        summary_table = Table(summary_data, colWidths=[2*inch, 4.5*inch])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#374151')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        
        # Issues Summary
        high_issues = review.issues.filter(severity=IssueSeverity.HIGH).count()
        warn_issues = review.issues.filter(severity=IssueSeverity.WARN).count()
        info_issues = review.issues.filter(severity=IssueSeverity.INFO).count()
        
        elements.append(Paragraph("Issues Summary", heading_style))
        
        issues_summary = [
            ['Severity', 'Count', 'Status'],
            ['HIGH (Critical)', str(high_issues), 'Requires Immediate Action' if high_issues > 0 else 'None'],
            ['WARN (Warning)', str(warn_issues), 'Review Recommended' if warn_issues > 0 else 'None'],
            ['INFO (Informational)', str(info_issues), 'For Reference' if info_issues > 0 else 'None'],
        ]
        
        issues_summary_table = Table(issues_summary, colWidths=[2*inch, 1*inch, 3.5*inch])
        issues_summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#FEE2E2') if high_issues > 0 else colors.white),
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#FEF3C7') if warn_issues > 0 else colors.white),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(issues_summary_table)
        elements.append(Spacer(1, 20))
        
        # Terms Comparison
        elements.append(Paragraph("Terms Comparison", heading_style))
        elements.append(Paragraph("Approved (Term Sheet) vs Executed (Agreement)", normal_style))
        elements.append(Spacer(1, 10))
        
        # Get terms
        approved_terms = {t.key: t for t in review.terms.filter(source=SourceType.APPROVED)}
        executed_terms = {t.key: t for t in review.terms.filter(source=SourceType.EXECUTED)}
        all_keys = set(approved_terms.keys()) | set(executed_terms.keys())
        
        terms_data = [['Term', 'Approved Value', 'Executed Value', 'Status']]
        
        for key in sorted(all_keys):
            approved = approved_terms.get(key)
            executed = executed_terms.get(key)
            
            label = executed.label if executed else (approved.label if approved else key)
            approved_value = approved.value if approved else 'N/A'
            executed_value = executed.value if executed else 'N/A'
            
            if approved and executed:
                match_status = 'MATCH' if approved.value == executed.value else 'MISMATCH'
            elif approved:
                match_status = 'MISSING'
            else:
                match_status = 'NEW'
            
            # Truncate long values
            if len(approved_value) > 30:
                approved_value = approved_value[:27] + '...'
            if len(executed_value) > 30:
                executed_value = executed_value[:27] + '...'
            
            terms_data.append([label, approved_value, executed_value, match_status])
        
        terms_table = Table(terms_data, colWidths=[1.8*inch, 1.8*inch, 1.8*inch, 1.1*inch])
        terms_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (3, 0), (3, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        # Color mismatch rows
        for i, row in enumerate(terms_data[1:], start=1):
            if row[3] == 'MISMATCH':
                terms_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FEE2E2')),
                    ('TEXTCOLOR', (3, i), (3, i), colors.HexColor('#DC2626')),
                ]))
            elif row[3] == 'MATCH':
                terms_table.setStyle(TableStyle([
                    ('TEXTCOLOR', (3, i), (3, i), colors.HexColor('#059669')),
                ]))
        
        elements.append(terms_table)
        elements.append(PageBreak())
        
        # Detailed Issues
        elements.append(Paragraph("Detailed Issues", heading_style))
        
        for issue in review.issues.all():
            severity_color = colors.HexColor('#DC2626') if issue.severity == IssueSeverity.HIGH else \
                            colors.HexColor('#D97706') if issue.severity == IssueSeverity.WARN else \
                            colors.HexColor('#2563EB')
            
            elements.append(Paragraph(f"[{issue.severity}] {issue.message}", subheading_style))
            
            issue_details = []
            if issue.related_term_label:
                issue_details.append(['Related Term:', issue.related_term_label])
            if issue.evidence:
                issue_details.append(['Evidence:', issue.evidence[:200] + '...' if len(issue.evidence) > 200 else issue.evidence])
            if issue.approved_evidence:
                issue_details.append(['Approved:', issue.approved_evidence[:150] + '...' if len(issue.approved_evidence) > 150 else issue.approved_evidence])
            if issue.executed_evidence:
                issue_details.append(['Executed:', issue.executed_evidence[:150] + '...' if len(issue.executed_evidence) > 150 else issue.executed_evidence])
            if issue.regulation_impact:
                issue_details.append(['Regulatory Impact:', issue.regulation_impact])
            
            if issue_details:
                issue_table = Table(issue_details, colWidths=[1.5*inch, 5*inch])
                issue_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))
                elements.append(issue_table)
            
            elements.append(Spacer(1, 15))
        
        # Audit Trail
        elements.append(Paragraph("Audit Trail", heading_style))
        
        audit_data = [['Timestamp', 'Actor', 'Action', 'Details']]
        for event in review.audit_log.all():
            audit_data.append([
                event.timestamp.strftime('%Y-%m-%d %H:%M'),
                event.actor,
                event.action,
                event.details[:50] + '...' if len(event.details) > 50 else event.details
            ])
        
        audit_table = Table(audit_data, colWidths=[1.3*inch, 1.5*inch, 1*inch, 2.7*inch])
        audit_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(audit_table)
        
        # Footer note
        elements.append(Spacer(1, 30))
        footer_style = ParagraphStyle('Footer', parent=normal_style, fontSize=8, textColor=colors.HexColor('#6B7280'))
        elements.append(Paragraph(
            f"Generated by DocConform on {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}. "
            f"This report contains automated extraction results and should be reviewed by qualified personnel.",
            footer_style
        ))
        
        # Build PDF
        doc.build(elements)
        
        # Create response
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="DocConform_Report_{review.id}.pdf"'
        return response

    @action(detail=True, methods=['get'])
    def issues(self, request, pk=None):
        """
        Get all issues for a review.
        """
        review = self.get_object()
        issues = review.issues.all()
        serializer = IssueSerializer(issues, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def terms(self, request, pk=None):
        """
        Get all extracted terms for a review.
        """
        review = self.get_object()
        terms = review.terms.all()
        serializer = ExtractedTermSerializer(terms, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def audit_log(self, request, pk=None):
        """
        Get audit log for a review.
        """
        review = self.get_object()
        audit_events = review.audit_log.all()
        serializer = AuditEventSerializer(audit_events, many=True)
        return Response(serializer.data)
