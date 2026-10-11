import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from national.models import (
    Certification,
    CertificationType,
    Inventory,
    Organization,
    ResourceType,
    SourceSystem,
    User,
)
from national.services import audit


class Command(BaseCommand):
    help = "Carga cuentas y catálogo ficticios solo con DEBUG=true, sin restablecer cuentas ni inventarios."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("La demo está deshabilitada en producción.")
        password = os.environ.get("DEMO_PASSWORD", "")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("Defina DEMO_PASSWORD: " + "; ".join(exc.messages)) from exc
        source, _ = SourceSystem.objects.get_or_create(
            code="rescuesync-demo", defaults={"name": "RescueSync demo"}
        )
        org, _ = Organization.objects.get_or_create(
            registration_number="DEMO-ONG-001",
            defaults={
                "name": "Red Solidaria (demo)",
                "contact_email": "demo@example.org",
                "city": "La Plata",
                "status": "enabled",
            },
        )
        for username, role, organization, origin in [
            ("nacional_demo", "national", None, None),
            ("auditor_demo", "auditor", None, None),
            ("ong_demo", "ngo", org, None),
            ("bonita_demo", "service", None, source),
        ]:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "organization": organization, "source_system": origin},
            )
            if (
                user.role != role
                or user.organization_id != getattr(organization, "pk", None)
                or user.source_system_id != getattr(origin, "pk", None)
            ):
                raise CommandError(f"{username} ya existe con otro alcance. No se modificó.")
            if created:
                user.set_password(password)
                user.save(update_fields=["password"])
        actor = User.objects.get(username="nacional_demo")
        for code, name, category, unit, capability, support in [
            ("food-ration", "Ración alimentaria", "supplies", "ración", "food-distribution", True),
            ("paramedic", "Paramédico", "personnel", "persona", "emergency-health", False),
            ("rescue-boat", "Bote de rescate", "equipment", "unidad", "water-rescue", False),
        ]:
            resource, _ = ResourceType.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "unit": unit,
                    "capability_code": capability,
                    "support_allowed": support,
                },
            )
            kind, _ = CertificationType.objects.get_or_create(
                code=capability + "-license",
                defaults={
                    "name": "Habilitación: " + name,
                    "capability_code": capability,
                    "max_risk_level": "high",
                },
            )
            cert, cert_created = Certification.objects.get_or_create(
                organization=org,
                certification_type=kind,
                credential_number="DEMO-" + code,
                defaults={
                    "issuer": "Autoridad ficticia de demostración",
                    "valid_from": timezone.now().date(),
                    "valid_until": timezone.now().date() + timedelta(days=365),
                },
            )
            stock, stock_created = Inventory.objects.get_or_create(
                organization=org,
                resource_type=resource,
                defaults={"total_quantity": 1000 if category == "supplies" else 10},
            )
            if cert_created:
                audit(
                    actor,
                    "certification.issued",
                    organization=org,
                    detail={"certification": str(cert.pk), "demo": True},
                )
            if stock_created:
                audit(
                    actor,
                    "inventory.created",
                    organization=org,
                    detail={"inventory": str(stock.pk), "demo": True},
                )
        self.stdout.write(
            self.style.SUCCESS(f"Demo disponible. ONG nacional: {org.pk}. Sistema: {source.pk}.")
        )
