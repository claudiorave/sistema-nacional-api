from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import override_settings
from redis.exceptions import ConnectionError as RedisConnectionError

from national.models import Inventory, SourceSystem, User

from .base import NationalTestCase

COMMAND_PASSWORD = "Delta92!RioClaroCumbre"


class ManagementHealthTests(NationalTestCase):
    def test_create_operator_is_scoped_and_does_not_reset_existing_user(self):
        with patch.dict("os.environ", {"NATIONAL_PASSWORD": COMMAND_PASSWORD}):
            call_command("create_operator", "operador_nuevo", stdout=StringIO())
            user = User.objects.get(username="operador_nuevo")
            self.assertEqual(user.role, "national")
            self.assertTrue(user.check_password(COMMAND_PASSWORD))
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
            with self.assertRaises(CommandError):
                call_command("create_operator", "operador_nuevo", stdout=StringIO())

    def test_create_operator_rejects_weak_password_and_invalid_username(self):
        with patch.dict("os.environ", {"NATIONAL_PASSWORD": "123"}):
            with self.assertRaises(CommandError):
                call_command("create_operator", "new_operator", stdout=StringIO())
        with patch.dict("os.environ", {"NATIONAL_PASSWORD": COMMAND_PASSWORD}):
            with self.assertRaises(CommandError):
                call_command("create_operator", "invalid user name", stdout=StringIO())
        self.assertFalse(User.objects.filter(username="new_operator").exists())

    def test_service_account_uses_source_and_rolls_back_weak_onboarding(self):
        with patch.dict("os.environ", {"SERVICE_PASSWORD": COMMAND_PASSWORD}):
            call_command(
                "create_service_account",
                "new_integration",
                source_code="new-local",
                source_name="Nueva instalación",
                stdout=StringIO(),
            )
        user = User.objects.get(username="new_integration")
        self.assertEqual(user.role, "service")
        self.assertEqual(user.source_system.code, "new-local")
        self.assertFalse(user.is_superuser)
        with patch.dict("os.environ", {"SERVICE_PASSWORD": "123"}):
            with self.assertRaises(CommandError):
                call_command(
                    "create_service_account",
                    "weak_integration",
                    source_code="weak-local",
                    source_name="Fallida",
                    stdout=StringIO(),
                )
        self.assertFalse(SourceSystem.objects.filter(code="weak-local").exists())

    @override_settings(DEBUG=False)
    def test_seed_demo_is_disabled_in_production(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_seed_demo_is_idempotent_without_resetting_inventory_or_credentials(self):
        with patch.dict("os.environ", {"DEMO_PASSWORD": COMMAND_PASSWORD}):
            call_command("seed_demo", stdout=StringIO())
        user = User.objects.get(username="ong_demo")
        original_hash = user.password
        stock = Inventory.objects.get(organization=user.organization, resource_type__code="food-ration")
        stock.total_quantity = 123
        stock.save(update_fields=["total_quantity"])
        with patch.dict("os.environ", {"DEMO_PASSWORD": "Otra93!ClaveSeguraRoca"}):
            call_command("seed_demo", stdout=StringIO())
        stock.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(stock.total_quantity, 123)
        self.assertEqual(user.password, original_hash)

    def test_readiness_handles_unavailable_database_and_cache(self):
        with patch("national.views.connection.cursor", side_effect=OperationalError("private db error")):
            response = self.client.get("/health/ready/")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.data, {"status": "unavailable"})
        with patch("national.views.cache.set", side_effect=RedisConnectionError("private redis error")):
            response = self.client.get("/health/ready/")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("redis", str(response.data))

    def test_root_redirects_to_swagger(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/api/docs/")

    def test_operational_database_failure_is_retryable_without_internal_details(self):
        with patch(
            "national.views.services.commit_resources",
            side_effect=OperationalError("private connection string"),
        ):
            response = self.commit()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "5")
        self.assertNotIn("private", str(response.data))
