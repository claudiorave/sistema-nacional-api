import logging

from django.db import IntegrityError, OperationalError
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class Conflict(APIException):
    status_code = 409
    default_detail = "La operación entra en conflicto con el estado actual."
    default_code = "conflict"


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response
    if isinstance(exc, IntegrityError):
        logger.warning("Conflicto de integridad en %s", context["view"].__class__.__name__)
        return Response({"detail": "Registro duplicado o restricción de integridad incumplida."}, status=409)
    if isinstance(exc, OperationalError):
        logger.error("Base de datos temporalmente no disponible en %s", context["view"].__class__.__name__)
        return Response(
            {
                "detail": "Base de datos ocupada o no disponible. Reintente con la misma clave de idempotencia."
            },
            status=503,
            headers={"Retry-After": "5"},
        )
    return None
