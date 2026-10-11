from django.core.cache import cache
from django.test import override_settings
from rest_framework_simplejwt.tokens import AccessToken

from national.models import AuditEvent, Organization, User

from .base import API, PASSWORD, NationalTestCase


class AccountTests(NationalTestCase):
    def registration(self, **overrides):
        return {
            "username": "nueva",
            "password": PASSWORD,
            "email": "nueva@example.org",
            "organization_name": "Nueva ONG",
            "registration_number": "ONG-NEW",
            "city": "Quilmes",
            **overrides,
        }

    def test_onboarding_is_pending_and_password_is_hashed(self):
        response = self.client.post(API + "auth/register/", self.registration())
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="nueva")
        self.assertEqual(user.role, "ngo")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)
        self.assertEqual(user.organization.status, "pending")
        self.assertNotIn("password", response.data["user"])
        self.assertEqual(AuditEvent.objects.filter(action="organization.registered").count(), 1)

    def test_registration_rejects_privilege_fields(self):
        for field in ["role", "is_staff", "is_superuser", "status", "organization", "source_system"]:
            with self.subTest(field=field):
                response = self.client.post(API + "auth/register/", self.registration(**{field: "national"}))
                self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="nueva").exists())

    def test_weak_password_and_invalid_username(self):
        for data in [self.registration(password="123"), self.registration(username="not a username")]:
            self.assertEqual(self.client.post(API + "auth/register/", data).status_code, 400)

    def test_duplicate_registration_is_atomic(self):
        self.client.post(API + "auth/register/", self.registration())
        self.assertEqual(
            self.client.post(API + "auth/register/", self.registration(username="otra")).status_code, 400
        )
        self.assertFalse(User.objects.filter(username="otra").exists())
        self.assertEqual(Organization.objects.filter(registration_number="ONG-NEW").count(), 1)

    def test_jwt_login_exact_endpoint_and_protected_catalog(self):
        self.assertEqual(self.client.get(API + "organizations/").status_code, 401)
        response = self.client.post("/login", {"username": self.ngo.username, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        token = AccessToken(response.data["access"])
        self.assertEqual(token["iss"], "sistema-nacional")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + response.data["access"])
        self.assertEqual(self.client.get(API + "auth/me/").data["role"], "ngo")
        self.assertEqual(self.client.get(API + "resource-types/").status_code, 200)

    def test_bad_password_invalid_token_and_inactive_account(self):
        self.assertEqual(
            self.client.post("/login", {"username": self.ngo.username, "password": "incorrecta"}).status_code,
            401,
        )
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
        self.assertEqual(self.client.get(API + "auth/me/").status_code, 401)
        self.client.credentials()
        result = self.client.post("/login", {"username": self.ngo.username, "password": PASSWORD}).data
        self.ngo.is_active = False
        self.ngo.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + result["access"])
        self.assertEqual(self.client.get(API + "auth/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(
            self.client.post(API + "auth/refresh/", {"refresh": result["refresh"]}).status_code, 400
        )

    def test_refresh_rotation_logout_and_wrong_owner(self):
        tokens = self.client.post("/login", {"username": self.ngo.username, "password": PASSWORD}).data
        rotated = self.client.post(API + "auth/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(rotated.status_code, 200)
        self.assertNotEqual(rotated.data["refresh"], tokens["refresh"])
        self.assertEqual(
            self.client.post(API + "auth/refresh/", {"refresh": tokens["refresh"]}).status_code, 401
        )
        self.login_as(self.other_ngo)
        self.assertEqual(
            self.client.post(API + "auth/logout/", {"refresh": rotated.data["refresh"]}).status_code, 403
        )
        self.login_as(self.ngo)
        self.assertEqual(
            self.client.post(API + "auth/logout/", {"refresh": rotated.data["refresh"]}).status_code, 204
        )
        self.assertEqual(
            self.client.post(API + "auth/refresh/", {"refresh": rotated.data["refresh"]}).status_code, 401
        )

    def test_disabled_source_invalidates_existing_jwt(self):
        tokens = self.client.post("/login", {"username": self.service.username, "password": PASSWORD}).data
        self.source.is_active = False
        self.source.save(update_fields=["is_active"])
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access"])
        self.assertEqual(self.client.get(API + "auth/me/").status_code, 401)
        self.client.credentials()
        self.assertEqual(
            self.client.post(API + "auth/refresh/", {"refresh": tokens["refresh"]}).status_code, 400
        )

    @override_settings(REST_FRAMEWORK={"DEFAULT_THROTTLE_RATES": {"login": "2/min"}})
    def test_login_rate_limit(self):
        from unittest.mock import patch

        from rest_framework.throttling import ScopedRateThrottle

        from national.views import LoginView

        cache.clear()
        with (
            patch.object(LoginView, "throttle_classes", [ScopedRateThrottle]),
            patch.object(ScopedRateThrottle, "THROTTLE_RATES", {"login": "2/min"}),
        ):
            for _ in range(2):
                self.assertEqual(
                    self.client.post("/login", {"username": "missing", "password": "wrong"}).status_code, 401
                )
            self.assertEqual(
                self.client.post("/login", {"username": "missing", "password": "wrong"}).status_code, 429
            )
        cache.clear()
