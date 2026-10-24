import re
import uuid

from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from redis.exceptions import RedisError
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import services
from .models import (
    AuditEvent,
    Certification,
    CertificationType,
    Commitment,
    Inventory,
    Organization,
    OrganizationReference,
    Project,
    ResourceType,
    User,
)
from .permissions import AuditRead, InventoryWrite, NationalOnly, NationalWrite, ServiceOnly, is_national
from .serializers import (
    AuditSerializer,
    CertificationSerializer,
    CertificationTypeSerializer,
    CommitmentRequestSerializer,
    CommitmentSerializer,
    CompetenceSerializer,
    CompletionSerializer,
    HealthSerializer,
    InventoryCreateSerializer,
    InventorySerializer,
    InventoryUpdateSerializer,
    LoginSerializer,
    LogoutSerializer,
    OrganizationPrivateSerializer,
    OrganizationSerializer,
    OrganizationStatusSerializer,
    OrganizationUpdateSerializer,
    ProjectSerializer,
    ReasonSerializer,
    ReferenceSerializer,
    RefreshSerializer,
    RegistrationSerializer,
    ResourceTypeSerializer,
    UserSerializer,
    ValidationRequestSerializer,
    ValidationResponseSerializer,
)


def privileged_reader(user):
    return is_national(user) or getattr(user, "role", None) == User.Role.AUDITOR


def visible_organizations(user):
    query = Organization.objects.all()
    if not user.is_authenticated:
        return query.none()
    if not privileged_reader(user):
        query = query.filter(Q(status=Organization.Status.ENABLED) | Q(pk=user.organization_id))
    return query


def uuid_filter(query, request, parameter, field=None):
    value = request.query_params.get(parameter)
    if value:
        try:
            parsed = uuid.UUID(value)
        except ValueError as exc:
            raise ValidationError({parameter: "Debe ser un UUID válido."}) from exc
        query = query.filter(**{field or parameter: parsed})
    return query


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"
    authentication_classes = []


class RefreshView(TokenRefreshView):
    serializer_class = RefreshSerializer
    throttle_scope = "login"
    authentication_classes = []


class LogoutView(APIView):
    throttle_scope = "api"

    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            if str(token["user_id"]) != str(request.user.pk):
                raise PermissionDenied("El refresh token pertenece a otra cuenta.")
            token.blacklist()
        except TokenError as exc:
            raise InvalidToken(str(exc)) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class RegistrationResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    organization = OrganizationPrivateSerializer()


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "onboarding"

    @extend_schema(request=RegistrationSerializer, responses={201: RegistrationResponseSerializer})
    @transaction.atomic
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org = Organization.objects.create(
            registration_number=data["registration_number"],
            name=data["organization_name"],
            contact_email=data["email"],
            city=data["city"],
        )
        user = User.objects.create_user(
            username=data["username"],
            password=data["password"],
            email=data["email"],
            role=User.Role.NGO,
            organization=org,
        )
        services.audit(user, "organization.registered", organization=org)
        return Response(
            {"user": UserSerializer(user).data, "organization": OrganizationPrivateSerializer(org).data},
            status=201,
        )


class MeView(APIView):
    throttle_scope = "api"

    @extend_schema(responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class BaseViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    throttle_scope = "api"
    lookup_value_regex = "[0-9a-fA-F-]{36}"


class CatalogViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    permission_classes = [IsAuthenticated, NationalWrite]

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        services.audit(
            self.request.user, f"{instance._meta.model_name}.created", detail={"id": str(instance.pk)}
        )


class OrganizationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        query = visible_organizations(self.request.user)
        requested_status = self.request.query_params.get("status")
        if requested_status:
            if requested_status not in Organization.Status.values:
                raise ValidationError({"status": "Estado inválido."})
            query = query.filter(status=requested_status)
        return query

    def get_serializer_class(self):
        if self.action == "partial_update":
            return OrganizationUpdateSerializer
        if privileged_reader(self.request.user):
            return OrganizationPrivateSerializer
        if self.action == "retrieve" and str(self.kwargs.get("pk")) == str(
            getattr(self.request.user, "organization_id", None)
        ):
            return OrganizationPrivateSerializer
        return OrganizationSerializer

    @extend_schema(request=OrganizationUpdateSerializer, responses=OrganizationPrivateSerializer)
    @transaction.atomic
    def partial_update(self, request, pk=None):
        org = self.get_object()
        if not is_national(request.user) and (
            request.user.role != User.Role.NGO or request.user.organization_id != org.pk
        ):
            raise PermissionDenied("Solo puede modificar su propia ONG.")
        org = Organization.objects.select_for_update().get(pk=org.pk)
        serializer = OrganizationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(org, field, value)
        org.save(update_fields=list(serializer.validated_data))
        services.audit(
            request.user, "organization.updated", organization=org, detail=serializer.validated_data
        )
        return Response(OrganizationPrivateSerializer(org).data)

    @extend_schema(request=OrganizationStatusSerializer, responses=OrganizationSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=[IsAuthenticated, NationalOnly], url_path="status"
    )
    @transaction.atomic
    def change_status(self, request, pk=None):
        org = self.get_object()
        org = Organization.objects.select_for_update().get(pk=org.pk)
        serializer = OrganizationStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        previous = org.status
        org.status = serializer.validated_data["status"]
        org.save(update_fields=["status"])
        services.audit(
            request.user,
            "organization.status_changed",
            organization=org,
            detail={"before": previous, **serializer.validated_data},
        )
        return Response(OrganizationSerializer(org).data)

    @extend_schema(responses=CompetenceSerializer)
    @action(detail=True, methods=["get"])
    def competence(self, request, pk=None):
        return Response(services.competence_profile(self.get_object()))


class ReferenceViewSet(CatalogViewSet):
    serializer_class = ReferenceSerializer
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        query = OrganizationReference.objects.all()
        user = self.request.user
        if not user.is_authenticated:
            return query.none()
        if user.role == User.Role.SERVICE and not user.is_superuser:
            query = query.filter(source_system=user.source_system)
        elif user.role == User.Role.NGO and not user.is_superuser:
            query = query.filter(organization=user.organization)
        if external_id := self.request.query_params.get("external_id"):
            query = query.filter(external_id=external_id)
        return uuid_filter(query, self.request, "source_system")


class ResourceTypeViewSet(CatalogViewSet):
    serializer_class = ResourceTypeSerializer
    queryset = ResourceType.objects.all()


class CertificationTypeViewSet(CatalogViewSet):
    serializer_class = CertificationTypeSerializer
    queryset = CertificationType.objects.all()


class CertificationViewSet(CatalogViewSet):
    serializer_class = CertificationSerializer

    def get_queryset(self):
        query = Certification.objects.filter(
            organization__in=visible_organizations(self.request.user)
        ).select_related("certification_type")
        return uuid_filter(query, self.request, "organization")

    @transaction.atomic
    def perform_create(self, serializer):
        org = serializer.validated_data["organization"]
        Organization.objects.select_for_update().get(pk=org.pk)
        cert = serializer.save()
        services.audit(
            self.request.user,
            "certification.issued",
            organization=org,
            detail={"certification": str(cert.pk)},
        )

    @extend_schema(request=ReasonSerializer, responses=CertificationSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, NationalOnly])
    @transaction.atomic
    def revoke(self, request, pk=None):
        cert = self.get_object()
        Organization.objects.select_for_update().get(pk=cert.organization_id)
        cert.refresh_from_db()
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not cert.revoked_at:
            cert.revoked_at = timezone.now()
            cert.save(update_fields=["revoked_at"])
            services.audit(
                request.user,
                "certification.revoked",
                organization=cert.organization,
                detail={"certification": str(cert.pk), **serializer.validated_data},
            )
        return Response(CertificationSerializer(cert).data)


@extend_schema_view(
    create=extend_schema(request=InventoryCreateSerializer, responses={201: InventorySerializer}),
)
class InventoryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    serializer_class = InventorySerializer
    permission_classes = [IsAuthenticated, InventoryWrite]

    def get_queryset(self):
        query = Inventory.objects.filter(
            organization__in=visible_organizations(self.request.user)
        ).select_related("resource_type")
        query = uuid_filter(query, self.request, "organization")
        if code := self.request.query_params.get("resource_code"):
            query = query.filter(resource_type__code=code)
        return query

    def create(self, request):
        serializer = InventoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stock = services.create_inventory(serializer.validated_data, request.user)
        return Response(InventorySerializer(stock).data, status=201)

    @extend_schema(request=InventoryUpdateSerializer, responses=InventorySerializer)
    def partial_update(self, request, pk=None):
        stock = self.get_object()
        serializer = InventoryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.update_inventory(stock.pk, serializer.validated_data, request.user)
        return Response(InventorySerializer(updated).data)

    @extend_schema(request=InventoryUpdateSerializer, responses=InventorySerializer)
    def update(self, request, pk=None):
        return self.partial_update(request, pk)


class AvailabilitySerializer(serializers.Serializer):
    resource_code = serializers.CharField()
    unit = serializers.CharField()
    total_quantity = serializers.IntegerField()
    reserved_quantity = serializers.IntegerField()
    available_quantity = serializers.IntegerField()


class AvailabilityView(APIView):
    throttle_scope = "api"

    @extend_schema(
        responses=AvailabilitySerializer(many=True),
        parameters=[
            OpenApiParameter("organization", OpenApiTypes.UUID, description="UUID nacional de la ONG."),
            OpenApiParameter("resource_code", str, description="Código del recurso, ej. food-ration."),
        ],
    )
    def get(self, request):
        query = Inventory.objects.filter(organization__status=Organization.Status.ENABLED)
        query = uuid_filter(query, request, "organization")
        if code := request.query_params.get("resource_code"):
            query = query.filter(resource_type__code=code)
        rows = (
            query.values("resource_type__code", "resource_type__unit")
            .annotate(total=Sum("total_quantity"), reserved=Sum("reserved_quantity"))
            .order_by("resource_type__code")
        )
        return Response(
            [
                {
                    "resource_code": row["resource_type__code"],
                    "unit": row["resource_type__unit"],
                    "total_quantity": row["total"],
                    "reserved_quantity": row["reserved"],
                    "available_quantity": row["total"] - row["reserved"],
                }
                for row in rows
            ]
        )


class ValidationView(APIView):
    throttle_scope = "api"

    @extend_schema(
        request=ValidationRequestSerializer,
        responses=ValidationResponseSerializer,
        description="Consulta sin persistencia de ofertas ni reservas. Cada ítem declara el riesgo de la tarea concreta. La recomendación de apoyo puede requerir adaptar ese riesgo.",
    )
    def post(self, request):
        serializer = ValidationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(services.validate_resources(serializer.validated_data["items"], request.user))


def projects_for(user):
    query = Project.objects.all()
    if not user.is_authenticated:
        return query.none()
    if privileged_reader(user):
        return query
    if user.role == User.Role.SERVICE:
        return query.filter(source_system=user.source_system)
    return query.filter(commitments__organization=user.organization).distinct()


class ProjectViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        query = projects_for(self.request.user).prefetch_related(
            "commitments__items__inventory__resource_type"
        )
        if external_id := self.request.query_params.get("external_id"):
            query = query.filter(external_id=external_id)
        return uuid_filter(query, self.request, "source_system")

    @extend_schema(request=None, responses=ProjectSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        # La ONG participa finalizando su actividad; la confirmación bilateral llega desde Bonita.
        project = self.get_object()
        if request.data:
            raise ValidationError("El cierre no recibe campos adicionales.")
        project = services.close_project(project.pk, request.user)
        return Response(ProjectSerializer(project, context={"request": request}).data)


class CommitmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    serializer_class = CommitmentSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), ServiceOnly()]
        return super().get_permissions()

    def get_queryset(self):
        query = Commitment.objects.filter(project__in=projects_for(self.request.user)).prefetch_related(
            "items__inventory__resource_type"
        )
        if getattr(self.request.user, "role", None) == User.Role.NGO and not self.request.user.is_superuser:
            query = query.filter(organization=self.request.user.organization)
        query = uuid_filter(query, self.request, "organization")
        return uuid_filter(query, self.request, "project")

    @extend_schema(
        request=CommitmentRequestSerializer,
        responses={201: ProjectSerializer, 200: ProjectSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Clave estable por adjudicación, 1–128 caracteres alfanuméricos, guion, punto, dos puntos o guion bajo.",
            )
        ],
        description="Solo integración Bonita. Crea el proyecto adjudicado y todos sus compromisos en una transacción PostgreSQL. Reevalúa competencia y disponibilidad bajo lock. Reintento idéntico: 200; clave reutilizada con otro contenido: 409.",
    )
    def create(self, request):
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
            raise ValidationError({"Idempotency-Key": "Cabecera requerida, de 1 a 128 caracteres válidos."})
        serializer = CommitmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project, created = services.commit_resources(serializer.validated_data, request.user, key)
        return Response(
            ProjectSerializer(project, context={"request": request}).data, status=201 if created else 200
        )

    @extend_schema(request=CompletionSerializer, responses=CommitmentSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        target = self.get_object()
        serializer = CompletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        commitment = services.complete_commitment(target.pk, request.user, serializer.validated_data["notes"])
        return Response(CommitmentSerializer(commitment).data)


class AuditViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BaseViewSet):
    serializer_class = AuditSerializer
    queryset = AuditEvent.objects.all()
    lookup_value_regex = "[0-9]+"

    permission_classes = [IsAuthenticated, AuditRead]


class LiveView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(responses=HealthSerializer)
    def get(self, request):
        return Response({"status": "ok"})


class ReadyView(LiveView):
    @extend_schema(responses={200: HealthSerializer, 503: HealthSerializer})
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            cache.set("national-readiness", "ok", timeout=10)
            if cache.get("national-readiness") != "ok":
                return Response({"status": "unavailable"}, status=503)
        except (DatabaseError, OSError, RedisError):
            return Response({"status": "unavailable"}, status=503)
        return Response({"status": "ok"})
