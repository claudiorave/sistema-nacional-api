"""Genera configuración local sin dependencias y sin sobrescribir un archivo existente."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = root / ".env"
password = secrets.token_hex(32)
content = f"""DEBUG=true
SECRET_KEY={secrets.token_urlsafe(64)}
JWT_SIGNING_KEY={secrets.token_urlsafe(64)}
ALLOWED_HOSTS=localhost,127.0.0.1
POSTGRES_DB=sistema_nacional
POSTGRES_USER=nacional
POSTGRES_PASSWORD={password}
DATABASE_URL=postgresql://nacional:{password}@127.0.0.1:5432/sistema_nacional
CACHE_URL=
TRUST_PROXY_HEADERS=false
NUM_PROXIES=0
"""
try:
    with target.open("x") as file:
        file.write(content)
    target.chmod(0o600)
except FileExistsError:
    raise SystemExit("Ya existe .env. Se conservó sin cambios.") from None
print(".env creado con claves independientes y contraseña aleatoria. No se imprimieron secretos.")
