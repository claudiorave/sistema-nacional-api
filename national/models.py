import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import F, Q


class RiskLevel(models.TextChoices):
    LOW = "low", "Bajo"
    MEDIUM = "medium", "Medio"
    HIGH = "high", "Alto"
    CRITICAL = "critical", "Crítico"


RISK_RANK = {risk: index for index, risk in enumerate(RiskLevel.values)}


class Organization(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente de revisión"
        ENABLED = "enabled", "Habilitada"
        SUSPENDED = "suspended", "Suspendida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration_number = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    contact_email = models.EmailField()
    city = models.CharField(max_length=120)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class SourceSystem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.code


class User(AbstractUser):
    class Role(models.TextChoices):
        NGO = "ngo", "Representante de ONG"
        NATIONAL = "national", "Operador nacional"
        SERVICE = "service", "Integración Bonita"
        AUDITOR = "auditor", "Auditor"

    role = models.CharField(max_length=12, choices=Role.choices, default=Role.AUDITOR)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.PROTECT)
    source_system = models.ForeignKey(SourceSystem, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(role="ngo", organization__isnull=False, source_system__isnull=True)
                    | Q(role="service", organization__isnull=True, source_system__isnull=False)
                    | Q(
                        role__in=["national", "auditor"],
                        organization__isnull=True,
                        source_system__isnull=True,
                    )
                ),
                name="user_role_scope",
            )
        ]


class OrganizationReference(models.Model):
    source_system = models.ForeignKey(SourceSystem, on_delete=models.PROTECT)
    external_id = models.CharField(max_length=100)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "external_id"], name="unique_local_ngo_reference"
            )
        ]


class ResourceType(models.Model):
    class Category(models.TextChoices):
        SUPPLIES = "supplies", "Suministros"
        PERSONNEL = "personnel", "Personal"
        EQUIPMENT = "equipment", "Equipamiento"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=12, choices=Category.choices)
    unit = models.CharField(max_length=60)
    capability_code = models.SlugField(max_length=60)
    support_allowed = models.BooleanField(default=False)
    support_max_risk = models.CharField(max_length=8, choices=RiskLevel.choices, default=RiskLevel.LOW)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.unit})"


class CertificationType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=160)
    capability_code = models.SlugField(max_length=60)
    max_risk_level = models.CharField(max_length=8, choices=RiskLevel.choices)
    description = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class Certification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, related_name="certifications", on_delete=models.PROTECT)
    certification_type = models.ForeignKey(CertificationType, on_delete=models.PROTECT)
    credential_number = models.CharField(max_length=100)
    issuer = models.CharField(max_length=160)
    valid_from = models.DateField()
    valid_until = models.DateField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["valid_until", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "certification_type", "credential_number"],
                name="unique_ngo_credential",
            ),
            models.CheckConstraint(
                condition=Q(valid_until__gte=F("valid_from")), name="certification_valid_dates"
            ),
        ]


class Inventory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, related_name="inventory", on_delete=models.PROTECT)
    resource_type = models.ForeignKey(ResourceType, on_delete=models.PROTECT)
    total_quantity = models.PositiveIntegerField()
    reserved_quantity = models.PositiveIntegerField(default=0, editable=False)
    version = models.PositiveIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization_id", "resource_type_id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "resource_type"], name="unique_ngo_resource"),
            models.CheckConstraint(
                condition=Q(total_quantity__gte=F("reserved_quantity")), name="inventory_no_overallocation"
            ),
            models.CheckConstraint(condition=Q(version__gte=1), name="inventory_positive_version"),
        ]

    @property
    def available_quantity(self):
        return self.total_quantity - self.reserved_quantity


class Project(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "En ejecución"
        COMPLETED = "completed", "Cerrado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_system = models.ForeignKey(SourceSystem, on_delete=models.PROTECT)
    external_id = models.CharField(max_length=100)
    title = models.CharField(max_length=160)
    bonita_case_id = models.CharField(max_length=100, blank=True)
    municipality_ref = models.CharField(max_length=100, blank=True)
    risk_level = models.CharField(max_length=8, choices=RiskLevel.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source_system", "external_id"], name="unique_source_project"),
            models.CheckConstraint(
                condition=(
                    Q(status="active", completed_at__isnull=True)
                    | Q(status="completed", completed_at__isnull=False)
                ),
                name="project_completion_state",
            ),
        ]


class Commitment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Comprometido"
        COMPLETED = "completed", "Actividad finalizada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, related_name="commitments", on_delete=models.PROTECT)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_notes = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["organization_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "organization"], name="unique_project_ngo_commitment"),
            models.CheckConstraint(
                condition=(
                    Q(status="active", completed_at__isnull=True)
                    | Q(status="completed", completed_at__isnull=False)
                ),
                name="commitment_completion_state",
            ),
        ]


class CommitmentItem(models.Model):
    class Assignment(models.TextChoices):
        MAIN = "main", "Principal"
        SUPPORT = "support", "Apoyo secundario"

    commitment = models.ForeignKey(Commitment, related_name="items", on_delete=models.PROTECT)
    inventory = models.ForeignKey(Inventory, on_delete=models.PROTECT)
    lot_ref = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    assignment = models.CharField(max_length=8, choices=Assignment.choices)
    risk_level = models.CharField(max_length=8, choices=RiskLevel.choices)
    competence_snapshot = models.JSONField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["commitment", "inventory", "lot_ref"], name="unique_commitment_resource_lot"
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="commitment_item_positive_quantity"),
        ]


class IdempotencyRecord(models.Model):
    source_system = models.ForeignKey(SourceSystem, on_delete=models.PROTECT)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    project = models.ForeignKey(Project, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source_system", "key"], name="unique_source_idempotency_key")
        ]


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.PROTECT)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=60)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
