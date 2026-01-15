from rest_framework import serializers
from .models import Review, ExtractedTerm, Issue, AuditEvent
from .extraction import compute_file_hash


class ExtractedTermSerializer(serializers.ModelSerializer):
    evidenceText = serializers.CharField(source='evidence_text', allow_blank=True, allow_null=True)
    evidenceLocation = serializers.CharField(source='evidence_location', allow_blank=True, allow_null=True)
    isMatch = serializers.BooleanField(source='is_match')

    class Meta:
        model = ExtractedTerm
        fields = ['id', 'key', 'label', 'value', 'source', 'confidence', 'evidenceText', 'evidenceLocation', 'isMatch']


class IssueSerializer(serializers.ModelSerializer):
    relatedTermKey = serializers.CharField(source='related_term_key', allow_blank=True, allow_null=True)
    relatedTermLabel = serializers.CharField(source='related_term_label', allow_blank=True, allow_null=True)
    regulationImpact = serializers.CharField(source='regulation_impact')
    approvedEvidence = serializers.CharField(source='approved_evidence', allow_blank=True, allow_null=True)
    executedEvidence = serializers.CharField(source='executed_evidence', allow_blank=True, allow_null=True)

    class Meta:
        model = Issue
        fields = ['id', 'severity', 'code', 'message', 'relatedTermKey', 'relatedTermLabel', 
                  'evidence', 'approvedEvidence', 'executedEvidence', 'regulationImpact']


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ['id', 'actor', 'action', 'timestamp', 'details', 'hash']


class ReviewListSerializer(serializers.ModelSerializer):
    borrowerName = serializers.CharField(source='borrower_name')
    facilityName = serializers.CharField(source='facility_name')
    createdAt = serializers.DateTimeField(source='created_at')
    executedFileName = serializers.CharField(source='executed_file_name')
    termSheetFileName = serializers.CharField(source='term_sheet_file_name', allow_null=True)
    issueCount = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ['id', 'status', 'borrowerName', 'facilityName', 'createdAt', 
                  'executedFileName', 'termSheetFileName', 'issueCount']

    def get_issueCount(self, obj):
        return obj.issues.count()


class ReviewDetailSerializer(serializers.ModelSerializer):
    borrowerName = serializers.CharField(source='borrower_name')
    facilityName = serializers.CharField(source='facility_name')
    createdAt = serializers.DateTimeField(source='created_at')
    executedFileName = serializers.CharField(source='executed_file_name')
    executedFileHash = serializers.CharField(source='executed_file_hash', allow_null=True)
    termSheetFileName = serializers.CharField(source='term_sheet_file_name', allow_null=True)
    termSheetFileHash = serializers.CharField(source='term_sheet_file_hash', allow_null=True)
    terms = ExtractedTermSerializer(many=True, read_only=True)
    issues = IssueSerializer(many=True, read_only=True)
    auditLog = AuditEventSerializer(source='audit_log', many=True, read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'status', 'borrowerName', 'facilityName', 'createdAt', 
                  'executedFileName', 'executedFileHash', 'termSheetFileName', 'termSheetFileHash',
                  'terms', 'issues', 'auditLog']


class ReviewCreateSerializer(serializers.Serializer):
    executedFile = serializers.FileField(required=True)
    termSheetFile = serializers.FileField(required=False, allow_null=True)

    def create(self, validated_data):
        executed_file = validated_data.get('executedFile')
        term_sheet_file = validated_data.get('termSheetFile')
        
        # Compute file hashes
        executed_hash = compute_file_hash(executed_file)
        term_sheet_hash = compute_file_hash(term_sheet_file) if term_sheet_file else None

        review = Review.objects.create(
            executed_file_name=executed_file.name,
            executed_file=executed_file,
            executed_file_hash=executed_hash,
            term_sheet_file_name=term_sheet_file.name if term_sheet_file else None,
            term_sheet_file=term_sheet_file,
            term_sheet_file_hash=term_sheet_hash,
            status='UPLOADED'
        )

        # Create initial audit event with hash
        AuditEvent.objects.create(
            review=review,
            actor='System User',
            action='UPLOAD',
            details=f'Uploaded {executed_file.name}' + (f' and {term_sheet_file.name}' if term_sheet_file else ''),
            hash=executed_hash[:16]
        )

        return review
