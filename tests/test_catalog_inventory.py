from django.db import IntegrityError, transaction

from national.models import OrganizationReference

from .base import API, NationalTestCase


class CatalogInventoryTests(NationalTestCase):
    def test_only_national_can_approve_and_contacts_cannot_change_status(self):
        self.org.status = "pending"
        self.org.save(update_fields=["status"])
        self.login_as(self.ngo)
        url = API + f"organizations/{self.org.pk}/"
        self.assertEqual(self.client.patch(url, {"status": "enabled"}).status_code, 400)
        self.assertEqual(
            self.client.post(url + "status/", {"status": "enabled", "reason": "Revisada"}).status_code, 403
        )
        self.assertEqual(self.client.patch(url, {"city": "Ensenada"}).status_code, 200)
        self.login_as(self.national)
        self.assertEqual(
            self.client.post(
                url + "status/", {"status": "enabled", "reason": "Documentación comprobada"}
            ).status_code,
            200,
        )
        self.org.refresh_from_db()
        self.assertEqual(self.org.status, "enabled")

    def test_pending_organizations_are_hidden_and_private_contacts_are_not_global(self):
        self.other_org.status = "pending"
        self.other_org.save(update_fields=["status"])
        self.login_as(self.ngo)
        result = self.client.get(API + "organizations/")
        self.assertEqual(result.data["count"], 1)
        self.assertNotIn("contact_email", result.data["results"][0])
        self.assertEqual(self.client.get(API + f"organizations/{self.other_org.pk}/").status_code, 404)
        self.login_as(self.auditor)
        self.assertEqual(self.client.get(API + "organizations/").data["count"], 2)

    def test_other_ngos_cannot_edit_inventory_or_contacts(self):
        self.login_as(self.other_ngo)
        self.assertEqual(
            self.client.patch(
                API + f"inventory/{self.stock.pk}/", {"total_quantity": 20, "version": 1}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(API + f"organizations/{self.org.pk}/", {"city": "Otra"}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                API + "inventory/",
                {"organization": str(self.org.pk), "resource_type": str(self.medics.pk), "total_quantity": 5},
            ).status_code,
            403,
        )

    def test_inventory_update_requires_current_version_and_cannot_reduce_below_reserved(self):
        self.commit()
        self.login_as(self.ngo)
        url = API + f"inventory/{self.stock.pk}/"
        self.assertEqual(self.client.patch(url, {"total_quantity": 20, "version": 1}).status_code, 409)
        self.assertEqual(self.client.patch(url, {"total_quantity": 3, "version": 2}).status_code, 409)
        result = self.client.patch(url, {"total_quantity": 20, "version": 2})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["available_quantity"], 16)
        self.assertEqual(result.data["version"], 3)
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_inventory_reserved_and_identity_fields_are_read_only(self):
        self.login_as(self.ngo)
        for field in ["reserved_quantity", "organization", "resource_type"]:
            self.assertEqual(
                self.client.patch(
                    API + f"inventory/{self.stock.pk}/", {"total_quantity": 20, "version": 1, field: 0}
                ).status_code,
                400,
            )

    def test_inventory_create_duplicates_and_global_availability(self):
        self.login_as(self.ngo)
        data = {"resource_type": str(self.medics.pk), "total_quantity": 5}
        self.assertEqual(self.client.post(API + "inventory/", data).status_code, 201)
        self.assertEqual(self.client.post(API + "inventory/", data).status_code, 409)
        result = self.client.get(API + "resources/availability/?resource_code=food-ration")
        self.assertEqual(result.data[0]["available_quantity"], 20)
        self.other_org.status = "suspended"
        self.other_org.save(update_fields=["status"])
        self.assertEqual(
            self.client.get(API + "resources/availability/?resource_code=food-ration").data[0][
                "available_quantity"
            ],
            10,
        )

    def test_references_are_scoped_to_source_and_cannot_be_self_assigned(self):
        reference = OrganizationReference.objects.create(
            source_system=self.source, external_id="2", organization=self.org
        )
        OrganizationReference.objects.create(
            source_system=self.other_source, external_id="2", organization=self.other_org
        )
        self.login_as(self.service)
        rows = self.client.get(API + "organization-references/?external_id=2").data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], reference.pk)
        self.assertEqual(self.client.post(API + "organization-references/", {}).status_code, 403)

    def test_auditor_cannot_modify_any_national_state(self):
        self.login_as(self.auditor)
        self.assertEqual(self.client.post(API + "resource-types/", {}).status_code, 403)
        self.assertEqual(self.client.post(API + "certification-types/", {}).status_code, 403)
        self.assertEqual(self.client.post(API + "inventory/", {}).status_code, 403)
        self.assertEqual(self.client.get(API + "audit-events/").status_code, 200)
        self.assertEqual(
            self.client.patch(API + f"organizations/{self.org.pk}/", {"city": "Otra"}).status_code, 403
        )
        self.login_as(self.service)
        self.assertEqual(self.client.get(API + "audit-events/").status_code, 403)

    def test_database_prevents_overallocation_and_invalid_account_scopes(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.stock.reserved_quantity = 11
            self.stock.save(update_fields=["reserved_quantity"])
        from national.models import User

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("invalid", role="ngo")

    def test_invalid_uuid_filters_and_lookups(self):
        self.login_as(self.service)
        for path in [
            "inventory/?organization=bad",
            "certifications/?organization=bad",
            "projects/?source_system=bad",
        ]:
            self.assertEqual(self.client.get(API + path).status_code, 400)
        self.assertEqual(self.client.get(API + "inventory/bad/").status_code, 404)
        self.assertEqual(self.client.get(API + "organizations/?status=bad").status_code, 400)

    def test_health_and_documentation_are_public(self):
        for path in ["/health/live/", "/health/ready/", "/api/schema/", "/api/docs/", "/api/redoc/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get(API + "projects/").status_code, 401)
