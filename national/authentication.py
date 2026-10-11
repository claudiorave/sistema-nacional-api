from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import User


class NationalJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.role == User.Role.SERVICE and not user.source_system.is_active:
            raise AuthenticationFailed("El sistema de origen está deshabilitado.")
        return user
