from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from national.models import (
    Certification,
    CertificationType,
    Inventory,
    Organization,
    ResourceType,
    SourceSystem,
    User,
)

PASSWORD = "RescatePruebas2026!"
API = "/api/v1/"


class FixtureMixin:
    def create_fixtures(self):
        self.source = SourceSystem.objects.create(code="rescuesync", name="RescueSync")
        self.other_source = SourceSystem.objects.create(code="other", name="Otro sistema")
        self.org = Organization.objects.create(
            registration_number="ONG-1",
            name="Rescate",
            contact_email="uno@example.org",
            city="La Plata",
            status="enabled",
        )
        self.other_org = Organization.objects.create(
            registration_number="ONG-2",
            name="Apoyo",
            contact_email="dos@example.org",
            city="Berisso",
            status="enabled",
        )
        self.national = User.objects.create_user("nacional", password=PASSWORD, role="national")
        self.service = User.objects.create_user(
            "bonita", password=PASSWORD, role="service", source_system=self.source
        )
        self.other_service = User.objects.create_user(
            "other_bonita", password=PASSWORD, role="service", source_system=self.other_source
        )
        self.ngo = User.objects.create_user("ong", password=PASSWORD, role="ngo", organization=self.org)
        self.other_ngo = User.objects.create_user(
            "ong2", password=PASSWORD, role="ngo", organization=self.other_org
        )
        self.auditor = User.objects.create_user("auditor", password=PASSWORD, role="auditor")
        self.food = ResourceType.objects.create(
            code="food-ration",
            name="Ración de alimentos",
            category="supplies",
            unit="ración",
            capability_code="food-distribution",
            support_allowed=True,
        )
        self.medics = ResourceType.objects.create(
            code="paramedic",
            name="Paramédico",
            category="personnel",
            unit="persona",
            capability_code="emergency-health",
            support_allowed=False,
        )
        self.food_cert = CertificationType.objects.create(
            code="food-license",
            name="Distribución alimentaria",
            capability_code="food-distribution",
            max_risk_level="high",
        )
        self.health_cert = CertificationType.objects.create(
            code="health-license",
            name="Atención sanitaria",
            capability_code="emergency-health",
            max_risk_level="critical",
        )
        today = timezone.now().date()
        self.certificate = Certification.objects.create(
            organization=self.org,
            certification_type=self.food_cert,
            credential_number="FOOD-001",
            issuer="Autoridad nacional",
            valid_from=today - timedelta(days=10),
            valid_until=today + timedelta(days=10),
        )
        self.stock = Inventory.objects.create(
            organization=self.org, resource_type=self.food, total_quantity=10
        )
        self.other_stock = Inventory.objects.create(
            organization=self.other_org, resource_type=self.food, total_quantity=10
        )

    def item(self, **overrides):
        return {
            "organization": str(self.org.pk),
            "resource_code": self.food.code,
            "lot_ref": "23",
            "quantity": 4,
            "risk_level": "high",
            **overrides,
        }

    def award(self, **overrides):
        return {
            "project": {
                "external_id": "12",
                "title": "Inundación en La Plata",
                "risk_level": "high",
                "bonita_case_id": "3456",
                "municipality_ref": "1",
            },
            "items": [self.item(assignment="main")],
            **overrides,
        }

    def login_as(self, user):
        self.client.force_authenticate(user=user)

    def commit(self, data=None, key="award-12"):
        self.login_as(self.service)
        return self.client.post(API + "commitments/", data or self.award(), HTTP_IDEMPOTENCY_KEY=key)


class NationalTestCase(FixtureMixin, APITestCase):
    def setUp(self):
        self.create_fixtures()
