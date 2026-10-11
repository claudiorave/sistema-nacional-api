import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from national.models import SourceSystem, User


class Command(BaseCommand):
    help = "Crea el sistema de origen y una cuenta JWT de servicio para Bonita."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--source-code", required=True)
        parser.add_argument("--source-name", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("El usuario ya existe. No se modificaron credenciales ni alcance.")
        source = SourceSystem(code=options["source_code"], name=options["source_name"])
        try:
            source.full_clean(validate_unique=False)
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        source, _ = SourceSystem.objects.get_or_create(code=source.code, defaults={"name": source.name})
        password = os.environ.get("SERVICE_PASSWORD") or getpass.getpass("Contraseña de integración: ")
        user = User(username=options["username"], role="service", source_system=source)
        try:
            validate_password(password, user)
            user.set_password(password)
            user.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        user.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"Cuenta {user.username} creada. Sistema de origen: {source.pk} ({source.code})."
            )
        )
