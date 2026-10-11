# Despliegue y operación

## Repositorio

Esta carpeta es la raíz de un servicio independiente; los Dockerfiles, workflows y Blueprint no dependen de carpetas hermanas. `.gitignore` excluye entornos, secretos, archivos estáticos generados y bases. Los archivos `.env.example` y `.env.production.example` contienen ejemplos, no credenciales reales.

Crear un repositorio vacío en el proveedor elegido y, desde esta carpeta:

```bash
git init -b codex/etapa-3
git add .
git status --short
git commit -m "Implementa API nacional de RescueSync para etapa 3"
git remote add origin <URL_DEL_REPOSITORIO_VACIO>
git push -u origin codex/etapa-3
```

Elegir esa rama al crear el servicio de Render, o promoverla a la rama principal según la convención del equipo. La CI de GitHub corre en pushes y pull requests con PostgreSQL y Redis dedicados, sin secretos de producción. Las URLs de repositorio, API y Swagger deben completarse en `ENTREGA_3.md` cuando existan; no se incluyen URLs ficticias como evidencia de publicación.

## Configuración de producción

Usar `.env.production.example` como referencia de variables del servidor. No subir `.env`. Generar dos claves distintas con:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Ejecutar dos veces y guardar como `SECRET_KEY` y `JWT_SIGNING_KEY` en el almacén de secretos del proveedor. Cambiar la clave JWT invalida todos los tokens vigentes. El servidor rechaza producción con claves menores a 50 caracteres, claves iguales, hosts comodín, SQLite o caché compartida ausente.

| Variable | Configuración |
|---|---|
| `DEBUG` | `false` |
| `SECRET_KEY`, `JWT_SIGNING_KEY` | Secretos independientes y aleatorios |
| `ALLOWED_HOSTS` | Hostname exacto de la API, sin esquema; varias entradas separadas por comas |
| `DATABASE_URL` | PostgreSQL; `sslmode=require` para conexión externa si el proveedor lo exige |
| `CACHE_URL` | Redis/Key Value compartido; `rediss://` si requiere TLS |
| `CSRF_TRUSTED_ORIGINS` | URL HTTPS exacta para el admin, por ejemplo `https://nacional.example.org` |
| `TRUST_PROXY_HEADERS` | `true` solo si el proxy de entrada sobrescribe `X-Forwarded-Proto` |
| `NUM_PROXIES` | Cantidad confiable de proxies para calcular IP en el throttle; 0 al recibir directamente |
| `SECURE_SSL_REDIRECT` | `true` |
| `WEB_CONCURRENCY`, `GUNICORN_THREADS` | 2 y 4 inicialmente; ajustar a memoria y conexiones disponibles |
| `PORT` | Puerto que asigne el proveedor; por defecto 8000 |

Producción activa HSTS por un año, incluyendo subdominios y elegibilidad para preload. Si se aloja en un dominio con subdominios que necesitan HTTP, configurar explícitamente `SECURE_HSTS_INCLUDE_SUBDOMAINS=false` y `SECURE_HSTS_PRELOAD=false`; `check --deploy` señalará esas decisiones para su revisión. No enviar HSTS desde un host que deba seguir disponible exclusivamente por HTTP.

Las APIs usan JWT; el admin usa las sesiones y CSRF de Django. Las dependencias de Swagger/ReDoc se sirven desde `/static/`, sin requerir CDN. El proceso de build genera esos estáticos sin usar secretos de producción ni conectarse a PostgreSQL.

## Render con Docker

Se incluye `render.yaml`, validado contra el esquema JSON oficial. Define un servicio web Docker, PostgreSQL y Key Value, en la misma región y con acceso privado a los almacenes. **El Blueprint contiene planes pagos** y no se ha ejecutado: revisar costos y disponibilidad en la cuenta antes de crearlo.

1. Publicar el repositorio y crear un Blueprint desde la rama de esta entrega.
2. Revisar nombres y planes del Blueprint antes de confirmar su creación.
3. Completar `SECRET_KEY`, `JWT_SIGNING_KEY`, `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS`. Si todavía no está asignado el hostname, usar el que informa Render para el nuevo servicio y ajustar esas variables antes del arranque exitoso.
4. Render construye la imagen, ejecuta `python manage.py migrate --noinput` mediante `preDeployCommand` e inicia el `CMD` de Gunicorn. El proveedor suministra `PORT`. Los estáticos ya están dentro de la imagen.
5. Confirmar que `/health/ready/` responde 200 y abrir `/api/docs/` por HTTPS.
6. Desde la consola segura del servicio crear operador, cuenta de integración y, si hace falta, superusuario. No cargar demo en producción.
7. Probar onboarding, habilitación y un ciclo completo de validación → compromiso → finalización → cierre con datos de ensayo controlados.

El hook de predespliegue se usa porque las migraciones son una tarea de release, separada del arranque de cada réplica. Si se elige un plan o proveedor sin ese hook, ejecutar una tarea única de migración antes de habilitar la nueva versión. No convertir cada worker en un ejecutor de migraciones.

Referencias oficiales consultadas: [Blueprint de Render](https://render.com/docs/blueprint-spec), [predespliegue](https://render.com/docs/deploys#pre-deploy-command), [Django en Render](https://render.com/docs/deploy-django).

## Servidor propio con contenedores

Configurar `.env` con los campos de `.env.production.example` y también `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` para el PostgreSQL interno de Compose. El archivo base de Compose reemplaza `DATABASE_URL` y `CACHE_URL` por sus servicios internos; para usar bases gestionadas, quitar ese override en la configuración de despliegue o ejecutar la imagen con las variables del proveedor directamente.

```bash
docker compose up --build -d
docker compose exec api python manage.py check --deploy --fail-level WARNING
docker compose exec api python manage.py create_operator operador_nacional
docker compose exec api python manage.py create_service_account bonita_rescuesync --source-code rescuesync-grupo20 --source-name 'RescueSync Grupo 20'
docker compose exec api python manage.py createsuperuser
```

Gunicorn se expone en `127.0.0.1:8002`. Instalar un proxy HTTPS en el host, con el dominio y certificado reales. Hay una plantilla en [deploy/nginx.conf](../deploy/nginx.conf). El proxy sobrescribe las cabeceras de protocolo/IP y transmite `/static/` a WhiteNoise. No exponer PostgreSQL ni Redis al exterior. Si el proxy también corre en Docker, conectarlo a la red interna y usar `api:8000` como upstream.

En producción el `seed_demo` devuelve error. `create_operator` y `create_service_account` piden contraseña sin eco; para tareas no interactivas aceptan `NATIONAL_PASSWORD` o `SERVICE_PASSWORD` del entorno del proceso. Estos comandos se niegan a reemplazar usuarios existentes. Rotar cuentas mediante `changepassword`; la cuenta de servicio no es superusuario ni operador nacional.

## Salud, errores y mantenimiento

- `/health/live/`: comprueba que el proceso responde.
- `/health/ready/`: comprueba conexión a PostgreSQL y Redis; devuelve 503 sin detalles internos si una dependencia falla. Las rutas de salud están excluidas del redirect HTTPS para las sondas internas, pero siguen respetando `ALLOWED_HOSTS`.
- HTTP 400: datos inválidos; 401: JWT inválido/inactivo; 403: operación sin permiso; 404: registro inexistente o fuera del ámbito; 409: estado incompatible/stock/versión/idempotencia; 429: límite de peticiones; 503: base ocupada/no disponible.

Configurar monitor de disponibilidad sobre `/health/ready/`, conservar logs de Gunicorn y eventos de auditoría. El throttle DRF es una mitigación básica con Redis; no garantiza un contador exacto ante múltiples peticiones simultáneas. Para controlar abuso desde Internet, aplicar también límites en el proxy/proveedor. No registrar cabeceras Authorization, contraseñas ni refresh tokens.

La app establece timeout de locks de 10 segundos y de consultas de 30 segundos. Ante 503 o timeout incierto de un compromiso, conservar la clave de idempotencia y reconciliar/reintentar con el mismo payload. No liberar reservas directamente con SQL para resolver un error operativo.

Ejecutar diariamente `python manage.py flushexpiredtokens` para limpiar tokens JWT expirados. Es un comando estándar de SimpleJWT; programarlo en el proveedor. Los access tokens ya emitidos duran como máximo 15 minutos y no se revocan individualmente por logout; deshabilitar el usuario invalida su uso inmediatamente porque cada petición consulta su estado. El logout revoca el refresh enviado.

Mantener backups y ensayar restauración de PostgreSQL: allí viven reservas, proyectos, auditoría e idempotencia. Redis solo mantiene límites/caché, no la verdad de las reservas. No usar `docker compose down -v` para reiniciar normalmente porque elimina los datos del volumen.

Antes de promover una versión, ejecutar migraciones y checks sobre el entorno real, comprobar salud y realizar una operación controlada. El checklist oficial de referencia es [Deployment checklist de Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
