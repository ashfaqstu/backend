import uuid
from django.db import models


class ReviewStatus(models.TextChoices):
    UPLOADED = 'UPLOADED', 'Uploaded'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETE = 'COMPLETE', 'Complete'
    FAILED = 'FAILED', 'Failed'


class SourceType(models.TextChoices):
    EXECUTED = 'EXECUTED', 'Executed'
    APPROVED = 'APPROVED', 'Approved'
    TERMSHEET = 'TERMSHEET', 'Term Sheet'


class IssueSeverity(models.TextChoices):
    INFO = 'INFO', 'Info'
    WARN = 'WARN', 'Warning'
    HIGH = 'HIGH', 'High'


class IssueCode(models.TextChoices):
    MISMATCH = 'MISMATCH', 'Mismatch'
    MULTIPLE_VALUES = 'MULTIPLE_VALUES', 'Multiple Values'
    MISSING_CLAUSE = 'MISSING_CLAUSE', 'Missing Clause'
    CLAUSE_PRESENT = 'CLAUSE_PRESENT', 'Clause Present'
    COMPLETENESS = 'COMPLETENESS', 'Completeness Check'
    CONSISTENCY_FAIL = 'CONSISTENCY_FAIL', 'Consistency Failure'


class AuditAction(models.TextChoices):
    UPLOAD = 'UPLOAD', 'Upload'
    EXTRACT = 'EXTRACT', 'Extract'
    EXPORT = 'EXPORT', 'Export'
    VALIDATE = 'VALIDATE', 'Validate'


class Review(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.UPLOADED
    )
    borrower_name = models.CharField(max_length=255, blank=True)
    facility_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    executed_file_name = models.CharField(max_length=255)
    executed_file = models.FileField(upload_to='documents/executed/', blank=True, null=True)
    executed_file_hash = models.CharField(max_length=64, blank=True, null=True)
    term_sheet_file_name = models.CharField(max_length=255, blank=True, null=True)
    term_sheet_file = models.FileField(upload_to='documents/termsheets/', blank=True, null=True)
    term_sheet_file_hash = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.borrower_name} - {self.facility_name} ({self.status})"


class ExtractedTerm(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='terms')
    key = models.CharField(max_length=100)
    label = models.CharField(max_length=255)
    value = models.TextField()
    source = models.CharField(max_length=20, choices=SourceType.choices)
    confidence = models.FloatField(default=0.0)
    evidence_text = models.TextField(blank=True, null=True)
    evidence_location = models.CharField(max_length=100, blank=True, null=True)
    is_match = models.BooleanField(default=True)

    class Meta:
        ordering = ['source', 'key']

    def __str__(self):
        return f"{self.label}: {self.value}"


class Issue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='issues')
    severity = models.CharField(max_length=10, choices=IssueSeverity.choices)
    code = models.CharField(max_length=30, choices=IssueCode.choices)
    message = models.TextField()
    related_term_key = models.CharField(max_length=100, blank=True, null=True)
    related_term_label = models.CharField(max_length=255, blank=True, null=True)
    evidence = models.TextField()
    approved_evidence = models.TextField(blank=True, null=True)
    executed_evidence = models.TextField(blank=True, null=True)
    regulation_impact = models.TextField()

    class Meta:
        ordering = ['-severity', 'code']

    def __str__(self):
        return f"[{self.severity}] {self.message}"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='audit_log')
    actor = models.CharField(max_length=255)
    action = models.CharField(max_length=20, choices=AuditAction.choices)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField()
    hash = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.actor} - {self.action} at {self.timestamp}"
