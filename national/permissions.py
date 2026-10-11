from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import User


def is_national(user):
    return user.is_authenticated and (user.is_superuser or user.role == User.Role.NATIONAL)


class NationalWrite(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or is_national(request.user)


class NationalOnly(BasePermission):
    def has_permission(self, request, view):
        return is_national(request.user)


class ServiceOnly(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == User.Role.SERVICE


class AuditRead(BasePermission):
    def has_permission(self, request, view):
        return is_national(request.user) or getattr(request.user, "role", None) == User.Role.AUDITOR


class InventoryWrite(BasePermission):
    def has_permission(self, request, view):
        return (
            request.method in SAFE_METHODS or is_national(request.user) or request.user.role == User.Role.NGO
        )
