from django.contrib import admin
from .models import Review, ExtractedTerm, Issue, AuditEvent


class ExtractedTermInline(admin.TabularInline):
    model = ExtractedTerm
    extra = 0
    readonly_fields = ['id']


class IssueInline(admin.TabularInline):
    model = Issue
    extra = 0
    readonly_fields = ['id']


class AuditEventInline(admin.TabularInline):
    model = AuditEvent
    extra = 0
    readonly_fields = ['id', 'timestamp']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['id', 'borrower_name', 'facility_name', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['borrower_name', 'facility_name', 'executed_file_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    inlines = [ExtractedTermInline, IssueInline, AuditEventInline]


@admin.register(ExtractedTerm)
class ExtractedTermAdmin(admin.ModelAdmin):
    list_display = ['label', 'value', 'source', 'confidence', 'is_match', 'review']
    list_filter = ['source', 'is_match']
    search_fields = ['label', 'value', 'key']


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ['severity', 'code', 'message', 'review']
    list_filter = ['severity', 'code']
    search_fields = ['message', 'evidence']


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ['action', 'actor', 'timestamp', 'review']
    list_filter = ['action', 'timestamp']
    search_fields = ['actor', 'details']
    readonly_fields = ['timestamp']
