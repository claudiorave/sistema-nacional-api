from datetime import timedelta

from django.utils import timezone

from national.models import Certification, IdempotencyRecord, Project

from .base import API, NationalTestCase


class CompetenceTests(NationalTestCase):
    def validate(self, *items):
        self.login_as(self.service)
        return self.client.post(API + "validations/", {"items": list(items) or [self.item()]})

    def test_current_certification_returns_risk_profile_without_reserving(self):
        response = self.validate()
        self.assertEqual(response.status_code, 200)
        result = response.data["items"][0]
        self.assertEqual(result["recommended_assignment"], "main")
        self.assertEqual(result["main_allowed_risk_levels"], ["low", "medium", "high"])
        self.assertEqual(result["support_allowed_risk_levels"], ["low"])
        self.assertFalse(response.data["reserves_resources"])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(Project.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_expired_revoked_and_future_certifications_allow_safe_support(self):
        today = timezone.now().date()
        for changes in [
            {"valid_until": today - timedelta(days=1)},
            {"revoked_at": timezone.now()},
            {"valid_from": today + timedelta(days=1)},
        ]:
            with self.subTest(changes=changes):
                Certification.objects.filter(pk=self.certificate.pk).update(
                    valid_from=today - timedelta(days=10),
                    valid_until=today + timedelta(days=10),
                    revoked_at=None,
                )
                Certification.objects.filter(pk=self.certificate.pk).update(**changes)
                response = self.validate()
                self.assertEqual(response.status_code, 200)
                item = response.data["items"][0]
                self.assertEqual(item["recommended_assignment"], "support")
                self.assertEqual(item["main_allowed_risk_levels"], [])
                self.assertIn("adapt_to_support_at_a_permitted_risk_level", item["observations"])

    def test_certification_valid_through_last_day(self):
        today = timezone.now().date()
        Certification.objects.filter(pk=self.certificate.pk).update(valid_from=today, valid_until=today)
        self.assertEqual(self.validate().data["items"][0]["recommended_assignment"], "main")

    def test_missing_medical_credential_does_not_authorize_medical_support(self):
        response = self.validate(self.item(resource_code=self.medics.code))
        self.assertEqual(response.status_code, 200)
        item = response.data["items"][0]
        self.assertEqual(item["recommended_assignment"], "none")
        self.assertEqual(item["support_allowed_risk_levels"], [])

    def test_suspended_organization_has_no_capacities(self):
        self.org.status = "suspended"
        self.org.save(update_fields=["status"])
        item = self.validate().data["items"][0]
        self.assertEqual(item["recommended_assignment"], "none")
        self.assertEqual(item["competence"]["capabilities"], [])

    def test_matching_capability_uses_highest_current_level(self):
        from national.models import CertificationType

        kind = CertificationType.objects.create(
            code="food-critical",
            name="Distribución crítica",
            capability_code="food-distribution",
            max_risk_level="critical",
        )
        Certification.objects.create(
            organization=self.org,
            certification_type=kind,
            credential_number="SECOND",
            issuer="Nación",
            valid_from=self.certificate.valid_from,
            valid_until=self.certificate.valid_until,
        )
        item = self.validate(self.item(risk_level="critical")).data["items"][0]
        self.assertEqual(item["recommended_assignment"], "main")
        self.assertEqual(len(item["competence"]["capabilities"][0]["certification_ids"]), 2)

    def test_quantities_are_aggregated_across_lots(self):
        response = self.validate(self.item(quantity=7), self.item(quantity=7, lot_ref="24"))
        self.assertEqual([i["max_assignable_quantity"] for i in response.data["items"]], [7, 3])

    def test_input_validation_unknown_org_unknown_resource_duplicates(self):
        import uuid

        for items in [
            [self.item(organization=str(uuid.uuid4()))],
            [self.item(resource_code="missing")],
            [self.item(), self.item()],
        ]:
            self.assertEqual(self.validate(*items).status_code, 400)

    def test_strict_positive_integer_quantities_and_risk(self):
        for value in [0, -1, True, 1.2, 1.0, "4", 2147483648]:
            with self.subTest(value=value):
                self.assertEqual(self.validate(self.item(quantity=value)).status_code, 400)
        self.assertEqual(self.validate(self.item(risk_level="unknown")).status_code, 400)

    def test_ngo_can_only_validate_its_own_resources(self):
        self.login_as(self.ngo)
        self.assertEqual(self.client.post(API + "validations/", {"items": [self.item()]}).status_code, 200)
        self.assertEqual(
            self.client.post(
                API + "validations/", {"items": [self.item(organization=str(self.other_org.pk))]}
            ).status_code,
            403,
        )

    def test_certification_type_is_immutable_and_ngo_cannot_issue_or_revoke(self):
        self.login_as(self.ngo)
        self.assertEqual(self.client.post(API + "certifications/", {}).status_code, 403)
        self.assertEqual(
            self.client.post(
                API + f"certifications/{self.certificate.pk}/revoke/", {"reason": "Fraude"}
            ).status_code,
            403,
        )
        self.login_as(self.national)
        self.assertEqual(
            self.client.patch(
                API + f"certification-types/{self.food_cert.pk}/", {"max_risk_level": "critical"}
            ).status_code,
            405,
        )

    def test_national_can_issue_and_revoke_certificates(self):
        self.login_as(self.national)
        response = self.client.post(
            API + "certifications/",
            {
                "organization": str(self.other_org.pk),
                "certification_type": str(self.food_cert.pk),
                "credential_number": "OTHER",
                "issuer": "Nación",
                "valid_from": str(self.certificate.valid_from),
                "valid_until": str(self.certificate.valid_until),
            },
        )
        self.assertEqual(response.status_code, 201)
        revoked = self.client.post(
            API + f"certifications/{response.data['id']}/revoke/", {"reason": "Retirada por la autoridad"}
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertFalse(revoked.data["is_current"])
