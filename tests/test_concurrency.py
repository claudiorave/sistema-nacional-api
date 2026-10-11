from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from national.models import Commitment, Inventory, Project

from .base import API, FixtureMixin


class PostgreSQLConcurrencyTests(FixtureMixin, TransactionTestCase):
    """Cada worker utiliza una conexión real distinta; no hay mocks del locking."""

    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.create_fixtures()

    def parallel_requests(self, requests):
        barrier = Barrier(len(requests))

        def execute(spec):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(spec["actor"])
                barrier.wait(timeout=10)
                if spec.get("method") == "patch":
                    response = client.patch(spec["path"], spec["data"])
                else:
                    response = client.post(spec["path"], spec["data"], **spec.get("headers", {}))
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            return list(executor.map(execute, requests))

    def award_request(self, external_id="12", key="award-12", quantity=7):
        data = self.award(items=[self.item(assignment="main", quantity=quantity)])
        data["project"]["external_id"] = external_id
        return {
            "actor": self.service,
            "path": API + "commitments/",
            "data": data,
            "headers": {"HTTP_IDEMPOTENCY_KEY": key},
        }

    def test_parallel_emergencies_cannot_overallocate(self):
        results = self.parallel_requests([self.award_request(), self.award_request("13", "award-13")])
        self.assertEqual(sorted(results), [201, 409])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 7)
        self.assertEqual(Project.objects.count(), 1)

    def test_identical_parallel_retries_reserve_once(self):
        results = self.parallel_requests([self.award_request(), self.award_request()])
        self.assertEqual(sorted(results), [200, 201])
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 7)
        self.assertEqual(Project.objects.count(), 1)

    def test_parallel_inventory_reduction_and_award_are_consistent(self):
        results = self.parallel_requests(
            [
                self.award_request(quantity=7),
                {
                    "actor": self.ngo,
                    "path": API + f"inventory/{self.stock.pk}/",
                    "method": "patch",
                    "data": {"total_quantity": 5, "version": 1},
                },
            ]
        )
        self.assertIn(sorted(results), [[201, 409], [200, 409]])
        self.stock.refresh_from_db()
        self.assertLessEqual(self.stock.reserved_quantity, self.stock.total_quantity)
        self.assertIn((self.stock.total_quantity, self.stock.reserved_quantity), [(10, 7), (5, 0)])

    def test_parallel_completion_releases_once(self):
        client = APIClient()
        client.force_authenticate(self.service)
        response = client.post(API + "commitments/", self.award(), HTTP_IDEMPOTENCY_KEY="award-12")
        self.assertEqual(response.status_code, 201)
        target = Commitment.objects.get()
        request = {"actor": self.ngo, "path": API + f"commitments/{target.pk}/complete/", "data": {}}
        self.assertEqual(self.parallel_requests([request, request]), [200, 200])
        self.assertEqual(Inventory.objects.get(pk=self.stock.pk).reserved_quantity, 0)

    def test_distinct_parallel_keys_for_same_project_create_once(self):
        results = self.parallel_requests([self.award_request(), self.award_request(key="other-key")])
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(Project.objects.count(), 1)

    def test_reverse_ngo_order_in_batches_does_not_deadlock(self):
        first = self.award_request(quantity=7)
        first["data"]["items"].append(
            self.item(organization=str(self.other_org.pk), quantity=7, risk_level="low", assignment="support")
        )
        second = self.award_request("13", "award-13", quantity=7)
        second["data"]["items"] = list(reversed(first["data"]["items"]))
        results = self.parallel_requests([first, second])
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(Project.objects.count(), 1)

    def test_parallel_revocation_and_award_use_same_organization_lock(self):
        results = self.parallel_requests(
            [
                self.award_request(),
                {
                    "actor": self.national,
                    "path": API + f"certifications/{self.certificate.pk}/revoke/",
                    "data": {"reason": "Habilitación retirada"},
                },
            ]
        )
        self.assertIn(results, [[201, 200], [409, 200]])
        self.certificate.refresh_from_db()
        self.assertIsNotNone(self.certificate.revoked_at)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 7 if results[0] == 201 else 0)
