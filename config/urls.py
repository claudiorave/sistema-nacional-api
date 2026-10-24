from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from national import views

router = DefaultRouter()
router.register("organizations", views.OrganizationViewSet, basename="organization")
router.register("organization-references", views.ReferenceViewSet, basename="organization-reference")
router.register("resource-types", views.ResourceTypeViewSet, basename="resource-type")
router.register("certification-types", views.CertificationTypeViewSet, basename="certification-type")
router.register("certifications", views.CertificationViewSet, basename="certification")
router.register("inventory", views.InventoryViewSet, basename="inventory")
router.register("projects", views.ProjectViewSet, basename="project")
router.register("commitments", views.CommitmentViewSet, basename="commitment")
router.register("audit-events", views.AuditViewSet, basename="audit-event")

urlpatterns = [
    # La raíz no tiene contenido propio: lleva a la documentación interactiva.
    path("", RedirectView.as_view(pattern_name="swagger-ui", permanent=False), name="root"),
    path("admin/", admin.site.urls),
    # Alias exacto solicitado en el enunciado. El contrato canónico está versionado.
    path("login", views.LoginView.as_view(), name="login-exact"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("api/v1/auth/login/", views.LoginView.as_view(), name="auth-login"),
    path("api/v1/auth/refresh/", views.RefreshView.as_view(), name="auth-refresh"),
    path("api/v1/auth/logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("api/v1/auth/register/", views.RegisterView.as_view(), name="auth-register"),
    path("api/v1/auth/me/", views.MeView.as_view(), name="auth-me"),
    path("api/v1/resources/availability/", views.AvailabilityView.as_view(), name="availability"),
    path("api/v1/validations/", views.ValidationView.as_view(), name="validation"),
    path("api/v1/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("health/live/", views.LiveView.as_view(), name="health-live"),
    path("health/ready/", views.ReadyView.as_view(), name="health-ready"),
]
