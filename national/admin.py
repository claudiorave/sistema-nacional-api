from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AuditEvent,
    Certification,
    CertificationType,
    Commitment,
    CommitmentItem,
    IdempotencyRecord,
    Inventory,
    Organization,
    OrganizationReference,
    Project,
    ResourceType,
    SourceSystem,
    User,
)


@admin.register(User)
class NationalUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Ámbito nacional", {"fields": ("role", "organization", "source_system")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Ámbito nacional", {"fields": ("role", "organization", "source_system")}),
    )
    list_display = ["username", "role", "organization", "source_system", "is_active"]

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    """Los registros operativos se modifican por servicios que toman los locks."""

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


for model in [
    Organization,
    SourceSystem,
    OrganizationReference,
    ResourceType,
    CertificationType,
    Certification,
    Inventory,
    Project,
    Commitment,
    CommitmentItem,
    IdempotencyRecord,
    AuditEvent,
]:
    admin.site.register(model, ReadOnlyAdmin)
