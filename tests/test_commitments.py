from datetime import timedelta

from django.utils import timezone

from national.models import AuditEvent, Commitment, CommitmentItem, IdempotencyRecord, Project

from .base import API, NationalTestCase


class CommitmentTests(NationalTestCase):
    def test_atomic_award_reserves_and_stores_competence_snapshot(self):
        response = self.commit()
        self.assertEqual(response.status_code, 201, response.data)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 4)
        self.assertEqual(self.stock.available_quantity, 6)
        self.assertEqual(self.stock.version, 2)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(Commitment.objects.count(), 1)
        self.assertEqual(CommitmentItem.objects.count(), 1)
        self.assertEqual(len(CommitmentItem.objects.get().competence_snapshot["capabilities"]), 1)

    def test_idempotency_prevents_duplicate_reservations(self):
        first = self.commit()
        second = self.commit()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 4)
        self.assertEqual(AuditEvent.objects.filter(action="project.committed").count(), 1)

    def test_key_mismatch_and_same_project_different_key_conflict(self):
        self.commit()
        data = self.award(items=[self.item(assignment="main", quantity=3)])
        self.assertEqual(self.commit(data).status_code, 409)
        self.assertEqual(self.commit(key="different").status_code, 409)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 4)

    def test_idempotency_is_order_independent_for_multiple_lots(self):
        data = self.award(
            items=[
                self.item(assignment="main", quantity=2),
                self.item(assignment="main", quantity=2, lot_ref="24"),
            ]
        )
        first = self.commit(data)
        data["items"].reverse()
        self.assertEqual(self.commit(data).status_code, 200)
        self.assertEqual(first.status_code, 201)

    def test_missing_header_and_unawarded_roles_are_rejected(self):
        self.login_as(self.service)
        self.assertEqual(self.client.post(API + "commitments/", self.award()).status_code, 400)
        for key in ["bad key", "x" * 129]:
            self.assertEqual(self.commit(key=key).status_code, 400)
        for user in [self.ngo, self.national, self.auditor]:
            self.login_as(user)
            self.assertEqual(
                self.client.post(API + "commitments/", self.award(), HTTP_IDEMPOTENCY_KEY="x").status_code,
                403,
            )

    def test_failed_batch_rolls_back_every_ngo_and_idempotency_record(self):
        data = self.award(
            items=[
                self.item(assignment="main"),
                self.item(
                    organization=str(self.other_org.pk), assignment="support", risk_level="low", quantity=11
                ),
            ]
        )
        result = self.commit(data)
        self.assertEqual(result.status_code, 409)
        self.stock.refresh_from_db()
        self.other_stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(self.other_stock.reserved_quantity, 0)
        self.assertEqual(Project.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(CommitmentItem.objects.count(), 0)

    def test_multiple_lots_cannot_overallocate_same_resource(self):
        result = self.commit(
            self.award(
                items=[
                    self.item(assignment="main", quantity=6),
                    self.item(assignment="main", quantity=6, lot_ref="24"),
                ]
            )
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(Project.objects.count(), 0)

    def test_revalidates_credentials_and_organization_at_award_time(self):
        self.login_as(self.service)
        self.assertEqual(self.client.post(API + "validations/", {"items": [self.item()]}).status_code, 200)
        self.certificate.valid_until = timezone.now().date() - timedelta(days=1)
        self.certificate.save(update_fields=["valid_until"])
        self.assertEqual(self.commit().status_code, 409)
        self.org.status = "suspended"
        self.org.save(update_fields=["status"])
        self.assertEqual(
            self.commit(self.award(items=[self.item(assignment="support", risk_level="low")])).status_code,
            409,
        )

    def test_safe_support_can_be_committed_without_primary_credentials(self):
        result = self.commit(
            self.award(
                items=[self.item(organization=str(self.other_org.pk), assignment="support", risk_level="low")]
            )
        )
        self.assertEqual(result.status_code, 201)
        self.assertEqual(CommitmentItem.objects.get().assignment, "support")

    def test_support_does_not_authorize_high_risk_or_unqualified_medical_work(self):
        self.assertEqual(
            self.commit(
                self.award(items=[self.item(organization=str(self.other_org.pk), assignment="support")])
            ).status_code,
            409,
        )
        self.assertEqual(
            self.commit(
                self.award(
                    items=[self.item(resource_code=self.medics.code, assignment="support", risk_level="low")]
                )
            ).status_code,
            409,
        )

    def test_activity_risk_cannot_exceed_project_risk(self):
        data = self.award()
        data["project"]["risk_level"] = "low"
        self.assertEqual(self.commit(data).status_code, 400)
        self.assertEqual(Project.objects.count(), 0)

    def test_ngo_finishes_only_its_activities_and_bilateral_close_waits(self):
        data = self.award(
            items=[
                self.item(assignment="main"),
                self.item(organization=str(self.other_org.pk), assignment="support", risk_level="low"),
            ]
        )
        response = self.commit(data)
        project = Project.objects.get(pk=response.data["id"])
        mine = Commitment.objects.get(organization=self.org)
        other = Commitment.objects.get(organization=self.other_org)
        self.assertEqual(self.client.post(API + f"projects/{project.pk}/close/", {}).status_code, 409)
        self.login_as(self.ngo)
        self.assertEqual(self.client.post(API + f"commitments/{other.pk}/complete/", {}).status_code, 404)
        self.assertEqual(
            self.client.post(
                API + f"commitments/{mine.pk}/complete/", {"notes": "Entrega finalizada"}
            ).status_code,
            200,
        )
        self.stock.refresh_from_db()
        self.other_stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(self.other_stock.reserved_quantity, 4)
        self.assertEqual(self.client.post(API + f"projects/{project.pk}/close/", {}).status_code, 403)
        self.login_as(self.other_ngo)
        self.assertEqual(self.client.post(API + f"commitments/{other.pk}/complete/", {}).status_code, 200)
        self.login_as(self.service)
        self.assertEqual(self.client.post(API + f"projects/{project.pk}/close/", {}).status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.status, "completed")
        self.assertIsNotNone(project.completed_at)

    def test_completion_and_close_are_idempotent_and_do_not_reopen(self):
        project_id = self.commit().data["id"]
        target = Commitment.objects.get()
        path = API + f"commitments/{target.pk}/complete/"
        self.assertEqual(self.client.post(path, {"notes": "Primera confirmación"}).status_code, 200)
        self.assertEqual(self.client.post(path, {"notes": "Reintento"}).status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.completion_notes, "Primera confirmación")
        self.assertEqual(self.client.post(API + f"projects/{project_id}/close/", {}).status_code, 200)
        self.assertEqual(self.client.post(API + f"projects/{project_id}/close/", {}).status_code, 200)
        replay = self.commit()
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data["status"], "completed")
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(AuditEvent.objects.filter(action="commitment.completed").count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="project.closed").count(), 1)

    def test_suspension_does_not_prevent_releasing_previous_commitments(self):
        self.commit()
        target = Commitment.objects.get()
        self.org.status = "suspended"
        self.org.save(update_fields=["status"])
        self.login_as(self.ngo)
        self.assertEqual(self.client.post(API + f"commitments/{target.pk}/complete/", {}).status_code, 200)

    def test_service_scoping_and_ngo_response_do_not_leak_other_commitments(self):
        response = self.commit(
            self.award(
                items=[
                    self.item(assignment="main"),
                    self.item(organization=str(self.other_org.pk), assignment="support", risk_level="low"),
                ]
            )
        )
        project_id = response.data["id"]
        self.login_as(self.other_service)
        self.assertEqual(self.client.get(API + f"projects/{project_id}/").status_code, 404)
        self.assertEqual(self.client.get(API + "projects/").data["count"], 0)
        self.assertEqual(self.client.post(API + f"projects/{project_id}/close/", {}).status_code, 404)
        self.login_as(self.ngo)
        result = self.client.get(API + f"projects/{project_id}/")
        self.assertEqual(len(result.data["commitments"]), 1)
        self.assertEqual(str(result.data["commitments"][0]["organization"]), str(self.org.pk))

    def test_same_external_ids_are_scoped_to_source_system(self):
        first = self.commit()
        self.login_as(self.other_service)
        second = self.client.post(API + "commitments/", self.award(), HTTP_IDEMPOTENCY_KEY="award-12")
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.data["id"], second.data["id"])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 8)
