import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from national.models import User


class Command(BaseCommand):
    help = "Crea un operador nacional o auditor sin acceso administrativo de superusuario."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--role", choices=["national", "auditor"], default="national")
        parser.add_argument("--email", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("El usuario ya existe. No se modificó su contraseña ni su rol.")
        password = os.environ.get("NATIONAL_PASSWORD") or getpass.getpass("Contraseña del operador: ")
        user = User(username=options["username"], role=options["role"], email=options["email"])
        try:
            validate_password(password, user)
            user.set_password(password)
            user.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Usuario {user.username} creado con rol {user.role}."))
