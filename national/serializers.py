from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AuditEvent,
    Certification,
    CertificationType,
    Commitment,
    CommitmentItem,
    Inventory,
    Organization,
    OrganizationReference,
    Project,
    ResourceType,
    RiskLevel,
    User,
)


class StrictInputMixin:
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Se requiere un objeto JSON.")
        allowed = {name for name, field in self.fields.items() if not field.read_only}
        unknown = set(data) - allowed
        if unknown:
            raise serializers.ValidationError({name: "Campo no permitido." for name in sorted(unknown)})
        return super().to_internal_value(data)


class StrictSerializer(StrictInputMixin, serializers.Serializer):
    pass


class StrictModelSerializer(StrictInputMixin, serializers.ModelSerializer):
    pass


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError("Debe ser un entero JSON, sin decimales ni booleanos.")
        return super().to_internal_value(data)


class LoginSerializer(StrictInputMixin, TokenObtainPairSerializer):
    def validate(self, attrs):
        result = super().validate(attrs)
        if self.user.role == User.Role.SERVICE and not self.user.source_system.is_active:
            raise serializers.ValidationError("El sistema de origen está deshabilitado.")
        return result


class RefreshSerializer(StrictInputMixin, TokenRefreshSerializer):
    def validate(self, attrs):
        token = RefreshToken(attrs["refresh"])
        user = User.objects.filter(pk=token["user_id"], is_active=True).first()
        if not user or (user.role == User.Role.SERVICE and not user.source_system.is_active):
            raise serializers.ValidationError("La cuenta ya no está habilitada.")
        return super().validate(attrs)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class LogoutSerializer(StrictSerializer):
    refresh = serializers.CharField()


class RegistrationSerializer(StrictSerializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    email = serializers.EmailField()
    organization_name = serializers.CharField(max_length=160)
    registration_number = serializers.CharField(max_length=40)
    city = serializers.CharField(max_length=120)

    def validate_username(self, value):
        for validator in User._meta.get_field("username").validators:
            validator(value)
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("El usuario ya está registrado.")
        return value

    def validate_registration_number(self, value):
        value = value.strip().upper()
        if Organization.objects.filter(registration_number=value).exists():
            raise serializers.ValidationError("La ONG ya está registrada. Solicite acceso al administrador.")
        return value

    def validate(self, attrs):
        try:
            validate_password(attrs["password"], User(username=attrs["username"], email=attrs["email"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "organization", "source_system"]
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "city", "status", "created_at"]
        read_only_fields = fields


class OrganizationPrivateSerializer(OrganizationSerializer):
    class Meta(OrganizationSerializer.Meta):
        fields = OrganizationSerializer.Meta.fields + ["registration_number", "contact_email"]
        read_only_fields = fields


class OrganizationUpdateSerializer(StrictSerializer):
    name = serializers.CharField(max_length=160, required=False)
    contact_email = serializers.EmailField(required=False)
    city = serializers.CharField(max_length=120, required=False)


class OrganizationStatusSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=Organization.Status.choices)
    reason = serializers.CharField(max_length=1000)


class ReferenceSerializer(StrictModelSerializer):
    class Meta:
        model = OrganizationReference
        fields = ["id", "source_system", "external_id", "organization"]
        read_only_fields = ["id"]


class ResourceTypeSerializer(StrictModelSerializer):
    class Meta:
        model = ResourceType
        fields = [
            "id",
            "code",
            "name",
            "category",
            "unit",
            "capability_code",
            "support_allowed",
            "support_max_risk",
        ]
        read_only_fields = ["id"]


class CertificationTypeSerializer(StrictModelSerializer):
    class Meta:
        model = CertificationType
        fields = ["id", "code", "name", "capability_code", "max_risk_level", "description"]
        read_only_fields = ["id"]


class CertificationSerializer(StrictModelSerializer):
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = Certification
        fields = [
            "id",
            "organization",
            "certification_type",
            "credential_number",
            "issuer",
            "valid_from",
            "valid_until",
            "revoked_at",
            "is_current",
            "created_at",
        ]
        read_only_fields = ["id", "revoked_at", "is_current", "created_at"]

    def get_is_current(self, obj) -> bool:
        today = timezone.now().date()
        return not obj.revoked_at and obj.valid_from <= today <= obj.valid_until

    def validate(self, attrs):
        if attrs["valid_from"] > attrs["valid_until"]:
            raise serializers.ValidationError({"valid_until": "Debe ser posterior o igual al inicio."})
        return attrs


class ReasonSerializer(StrictSerializer):
    reason = serializers.CharField(max_length=1000)


class InventorySerializer(serializers.ModelSerializer):
    resource_code = serializers.CharField(source="resource_type.code")
    unit = serializers.CharField(source="resource_type.unit")
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "id",
            "organization",
            "resource_type",
            "resource_code",
            "unit",
            "total_quantity",
            "reserved_quantity",
            "available_quantity",
            "version",
            "updated_at",
        ]
        read_only_fields = fields


class InventoryCreateSerializer(StrictSerializer):
    organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all(), required=False)
    resource_type = serializers.PrimaryKeyRelatedField(queryset=ResourceType.objects.all())
    total_quantity = StrictIntegerField(min_value=0, max_value=2147483647)


class InventoryUpdateSerializer(StrictSerializer):
    total_quantity = StrictIntegerField(min_value=0, max_value=2147483647)
    version = StrictIntegerField(min_value=1, max_value=2147483647)


class ValidationItemSerializer(StrictSerializer):
    organization = serializers.UUIDField()
    resource_code = serializers.SlugField(max_length=60)
    lot_ref = serializers.CharField(max_length=100)
    quantity = StrictIntegerField(min_value=1, max_value=2147483647)
    risk_level = serializers.ChoiceField(choices=RiskLevel.choices)


class ValidationRequestSerializer(StrictSerializer):
    items = ValidationItemSerializer(many=True, allow_empty=False, max_length=200)

    def validate_items(self, items):
        keys = [(item["organization"], item["resource_code"], item["lot_ref"]) for item in items]
        if len(set(keys)) != len(keys):
            raise serializers.ValidationError("Una ONG no puede repetir el mismo recurso en el mismo lote.")
        return items


class CommitmentRequestItemSerializer(ValidationItemSerializer):
    assignment = serializers.ChoiceField(choices=CommitmentItem.Assignment.choices)


class ProjectInputSerializer(StrictSerializer):
    external_id = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=160)
    bonita_case_id = serializers.CharField(max_length=100, required=False, default="", allow_blank=True)
    municipality_ref = serializers.CharField(max_length=100, required=False, default="", allow_blank=True)
    risk_level = serializers.ChoiceField(choices=RiskLevel.choices)


class CommitmentRequestSerializer(ValidationRequestSerializer):
    project = ProjectInputSerializer()
    items = CommitmentRequestItemSerializer(many=True, allow_empty=False, max_length=200)


class CapabilitySerializer(serializers.Serializer):
    capability_code = serializers.CharField()
    max_risk_level = serializers.ChoiceField(choices=RiskLevel.choices)
    allowed_risk_levels = serializers.ListField(child=serializers.CharField())
    certification_ids = serializers.ListField(child=serializers.UUIDField())


class CompetenceSerializer(serializers.Serializer):
    organization = serializers.UUIDField()
    organization_status = serializers.CharField()
    evaluated_at = serializers.DateTimeField()
    capabilities = CapabilitySerializer(many=True)
    support_capabilities = CapabilitySerializer(many=True)
    credential_observations = serializers.ListField(child=serializers.DictField())


class ValidationResultItemSerializer(ValidationItemSerializer):
    unit = serializers.CharField()
    available_quantity = serializers.IntegerField()
    max_assignable_quantity = serializers.IntegerField()
    main_allowed_risk_levels = serializers.ListField(child=serializers.CharField())
    support_allowed_risk_levels = serializers.ListField(child=serializers.CharField())
    recommended_assignment = serializers.ChoiceField(choices=["main", "support", "none"])
    observations = serializers.ListField(child=serializers.CharField())
    competence = CompetenceSerializer()


class ValidationResponseSerializer(serializers.Serializer):
    evaluated_at = serializers.DateTimeField()
    reserves_resources = serializers.BooleanField()
    items = ValidationResultItemSerializer(many=True)


class CommitmentItemSerializer(serializers.ModelSerializer):
    resource_code = serializers.CharField(source="inventory.resource_type.code")
    unit = serializers.CharField(source="inventory.resource_type.unit")

    class Meta:
        model = CommitmentItem
        fields = [
            "id",
            "inventory",
            "resource_code",
            "unit",
            "lot_ref",
            "quantity",
            "assignment",
            "risk_level",
            "competence_snapshot",
        ]
        read_only_fields = fields


class CommitmentSerializer(serializers.ModelSerializer):
    items = CommitmentItemSerializer(many=True)

    class Meta:
        model = Commitment
        fields = [
            "id",
            "project",
            "organization",
            "status",
            "items",
            "created_at",
            "completed_at",
            "completion_notes",
        ]
        read_only_fields = fields


class CompletionSerializer(StrictSerializer):
    notes = serializers.CharField(max_length=2000, required=False, default="", allow_blank=True)


class ProjectSerializer(serializers.ModelSerializer):
    commitments = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "source_system",
            "external_id",
            "title",
            "bonita_case_id",
            "municipality_ref",
            "risk_level",
            "status",
            "commitments",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields

    def get_commitments(self, obj) -> list[dict]:
        commitments = obj.commitments.all()
        user = self.context["request"].user
        if user.role == User.Role.NGO and not user.is_superuser:
            commitments = [c for c in commitments if c.organization_id == user.organization_id]
        return CommitmentSerializer(commitments, many=True).data


class AuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ["id", "actor", "organization", "project", "action", "detail", "created_at"]
        read_only_fields = fields


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
