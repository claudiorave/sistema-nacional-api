# Sistema Nacional de Gestión de Recursos y Riesgos

API independiente de **RescueSync, entrega 3**, implementada con Django 5.2 LTS, Django REST Framework y PostgreSQL. Incluye JWT, registro de ONGs, certificaciones, perfiles de competencia, disponibilidad nacional, compromiso atómico después de adjudicar y liberación/cierre. Swagger y ReDoc funcionan con archivos estáticos incluidos en la aplicación.

El código está preparado para repositorio y despliegue; las URLs públicas de la entrega se obtienen después de publicar. El alcance y la evidencia de validación están en [docs/ENTREGA_3.md](docs/ENTREGA_3.md).

## Inicio con Docker

Desde esta carpeta, con Docker Engine y Compose activos:

```bash
python3 scripts/create_local_env.py
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 api migrate
```

El primer comando genera `.env` con secretos aleatorios y se niega a sobrescribir una configuración existente. Alternativa sin Python instalado: copiar `.env.example` a `.env` y completar claves independientes y contraseña de PostgreSQL. Usar contraseñas de base con caracteres alfanuméricos para la URL interpolada de Compose; si se configura una URL manual con caracteres reservados, codificarlos.

Compose inicia PostgreSQL y Redis, ejecuta las migraciones mediante un servicio separado y luego inicia Gunicorn. La API se publica solo en loopback, puerto **8002**, para no ocupar el 8001 de RescueSync:

- Swagger: <http://localhost:8002/api/docs/>.
- ReDoc: <http://localhost:8002/api/redoc/>.
- OpenAPI: <http://localhost:8002/api/schema/> y [docs/openapi.yaml](docs/openapi.yaml).
- Salud: <http://localhost:8002/health/ready/>.

Crear las cuentas iniciales; los comandos piden contraseña y no la imprimen:

```bash
docker compose exec api python manage.py create_operator operador_nacional --email operador@example.org
docker compose exec api python manage.py create_service_account bonita_rescuesync --source-code rescuesync-grupo20 --source-name 'RescueSync Grupo 20'
```

Para la demostración, exclusivamente con `DEBUG=true`:

```bash
docker compose exec -e DEMO_PASSWORD='RescateDemo2026!' api python manage.py seed_demo
```

Usuarios ficticios: `nacional_demo`, `auditor_demo`, `ong_demo`, `bonita_demo`. La contraseña anterior es un ejemplo de prueba. `seed_demo` no cambia contraseñas, certificados existentes ni cantidades de inventario. Imprime el UUID de la ONG y del sistema de origen. Las cuentas demo no se crean al arrancar el servidor.

En Swagger ejecutar `POST /login` y luego **Authorize**, pegando el `access` JWT. Las llamadas autenticadas usan `Authorization: Bearer <access>`. El `refresh` sirve para renovar, no para autorizar peticiones operativas.

```bash
docker compose down
# Conserva el volumen de PostgreSQL. Para volver a iniciar:
docker compose up -d
```

## Desarrollo sin Docker

Requiere Python 3.12 y una base PostgreSQL dedicada. SQLite se rechaza explícitamente porque no garantiza los locks exigidos por la consigna. Crear `.env`, configurar `DATABASE_URL` y habilitar `DEBUG=true`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py create_operator operador_nacional
python manage.py create_service_account bonita_rescuesync --source-code rescuesync-grupo20 --source-name 'RescueSync Grupo 20'
python manage.py runserver 127.0.0.1:8002
```

Si `CACHE_URL` está vacío, desarrollo usa una caché en memoria. En producción se exige Redis para compartir los límites entre workers. La base indicada en `.env.example` debe existir y sus credenciales deben corresponder a una cuenta real. El PostgreSQL incluido en Compose no publica su puerto al host.

## Servicios

Todos los endpoints operativos están bajo `/api/v1/`; el alias `/login` responde directamente a POST, sin redirección.

| Servicio | Endpoint | Uso |
|---|---|---|
| Login JWT | `POST /login` o `/api/v1/auth/login/` | Devuelve access y refresh |
| Onboarding | `POST /api/v1/auth/register/` | Crea ONG pendiente y representante |
| Cuenta | `GET /api/v1/auth/me/` | Identidad y ámbito autenticados |
| Renovar / salir | `POST /api/v1/auth/refresh/`, `auth/logout/` | Rotación y revocación de refresh |
| ONGs | `GET organizations/`, `GET/PATCH organizations/{uuid}/` | Catálogo y contacto propio |
| Habilitación | `POST organizations/{uuid}/status/` | Solo operador nacional, con motivo |
| Competencia | `GET organizations/{uuid}/competence/` | Capacidades vigentes y riesgo permitido |
| Identidades locales | `GET/POST organization-references/` | Relaciona IDs locales y UUID nacionales |
| Tipos | `GET/POST resource-types/`, `certification-types/` | Catálogos creados por operador nacional |
| Certificaciones | `GET/POST certifications/`, `POST certifications/{uuid}/revoke/` | Credenciales emitidas por autoridad nacional |
| Inventario | `GET/POST inventory/`, `GET/PUT/PATCH inventory/{uuid}/` | Cantidades propias y edición versionada |
| Disponibilidad global | `GET resources/availability/` | Totales de ONGs habilitadas, por recurso |
| Restricciones | `POST validations/` | Evalúa competencia y stock sin guardar ofertas |
| Adjudicación | `POST commitments/` | Bonita compromete todas las líneas atómicamente |
| Seguimiento | `GET projects/`, `GET commitments/` y detalles | Scope por sistema de origen/ONG |
| Finalizar actividad | `POST commitments/{uuid}/complete/` | Libera los recursos de esa ONG |
| Cierre bilateral | `POST projects/{uuid}/close/` | Bonita confirma cierre tras todas las actividades |
| Auditoría | `GET audit-events/` | Operador nacional y auditor |

Las listas paginadas devuelven `count`, `next`, `previous`, `results`, con 50 filas por página. Filtros: `organizations/?status=enabled`, `organization-references/?external_id=2&source_system=<uuid>`, `inventory/?organization=<uuid>&resource_code=food-ration`, `certifications/?organization=<uuid>`, `resources/availability/?resource_code=food-ration`, `projects/?external_id=12&source_system=<uuid>`, `commitments/?project=<uuid>&organization=<uuid>`.

## Permisos y reglas operativas

| Perfil | Permisos |
|---|---|
| ONG | Registro propio, contacto/inventario propios, consulta de catálogos, validación propia, consulta y finalización de su participación |
| Operador nacional | Habilitación/suspensión, catálogos, emisión/revocación de credenciales, inventarios, consulta, liberación/cierre administrativo y auditoría |
| Servicio Bonita | Consulta/validación, compromiso posterior a adjudicar, liberación/cierre y consulta de proyectos de su sistema de origen |
| Auditor | Lectura de catálogos, perfiles, inventarios, proyectos y auditoría; puede consultar validación sin mutar |

La ONG se registra `pending`; no puede habilitarse ni emitirse certificados. Solo las ONGs `enabled` contribuyen a la disponibilidad nacional y pueden comprometer recursos. Suspender una ONG no impide liberar compromisos ya existentes. Los contactos privados se devuelven a su ONG y a perfiles nacionales; no forman parte del catálogo global.

Los certificados tienen fecha inicial, vencimiento, emisor, número de credencial y revocación. Se consideran vigentes durante todo su último día UTC. El perfil reúne las capacidades de todas las credenciales vigentes y el mayor riesgo autorizado para cada capacidad. Los niveles son `low`, `medium`, `high`, `critical`, en ese orden.

El catálogo define si un recurso admite apoyo secundario y con qué riesgo máximo. Sin certificado principal, una ONG puede recibir tareas de apoyo permitidas. **Una propuesta de apoyo en una emergencia de riesgo alto no habilita automáticamente trabajo de riesgo alto:** se debe adaptar la actividad concreta a un riesgo permitido. Un recurso sanitario del catálogo demo no admite apoyo médico sin habilitación.

Los tipos de recursos y certificaciones son inmutables para evitar modificar retroactivamente el significado de una habilitación. Para renovaciones se emite otra credencial; para cambios de catálogo se crea un tipo con otro código. No se borran proyectos, compromisos, auditoría ni credenciales por la API. Un inventario sin recursos se representa con total cero si no tiene reservas.

Las cantidades son enteros JSON, positivos en las adjudicaciones; no se aceptan booleanos, decimales ni cadenas. Cada código tiene una unidad nacional única. Para recursos fraccionables, usar una unidad base entera.

## Compromiso, concurrencia y cierre

Una consulta de validación es una fotografía orientativa; nunca reserva ni garantiza stock futuro. Al adjudicar, `POST commitments/` vuelve a verificar las credenciales, habilitación, riesgo y disponibilidad dentro de `transaction.atomic()`, con `SELECT FOR UPDATE` sobre ONGs e inventarios. Todos los locks se toman en un orden estable. Certificación, suspensión y actualización de inventarios respetan el mismo lock de ONG. La base impone además `reserved_quantity <= total_quantity`.

La solicitud acepta varias ONGs y lotes, incluidas adjudicaciones de consorcios; agrupa el compromiso por ONG y conserva cada línea. Si una línea falla, revierte **todos** los compromisos del lote de adjudicación. No acumular ofertas alternativas en esta operación: enviar únicamente las cantidades efectivamente seleccionadas por el municipio.

Enviar `Idempotency-Key` estable por adjudicación. La primera solicitud devuelve 201; un reintento equivalente devuelve 200 y el proyecto actual sin volver a reservar. Cambiar el contenido con la misma clave devuelve 409. La clave está aislada por sistema de origen. Para una emergencia ya adjudicada, una clave nueva tampoco crea otra adjudicación. El orden de los ítems no cambia la identidad de la solicitud. Un fallo transaccional revierte también el registro de idempotencia.

El riesgo de cada actividad no puede superar el riesgo general del proyecto. La finalización por ONG libera únicamente sus recursos, de forma idempotente. El proyecto sigue activo hasta que Bonita confirma `close`; el cierre devuelve 409 mientras quede cualquier actividad activa. Un reintento de una adjudicación ya terminada informa el estado actual y no reabre ni vuelve a reservar.

El inventario usa `version`: tanto las reservas como las liberaciones la incrementan. Para editar, enviar `total_quantity` y la versión consultada; una versión vieja o un total menor que lo reservado devuelve 409.

## Integración y despliegue

- [Integración con el backend y Bonita](docs/INTEGRACION_BONITA.md): correspondencias de IDs, contratos y orden del proceso.
- [Despliegue en Render o servidor](docs/DESPLIEGUE.md): secretos, HTTPS, migraciones, operación y publicación del repositorio.
- [Validación y trazabilidad de entrega 3](docs/ENTREGA_3.md).
- [Recorrido de prueba con Postman](docs/postman/README.md): colección y entornos para ejecutar el ciclo completo contra la API desplegada o local.
- [Ejemplo de validación](docs/examples/validation.json) y [adjudicación](docs/examples/commitment.json): reemplazar el UUID ilustrativo por el UUID nacional real.

## Verificación

Ejecutar con PostgreSQL de desarrollo/pruebas. Django crea y destruye una base `test_<nombre>`; el usuario requiere `CREATEDB`. No ejecutar las pruebas con credenciales de producción.

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
ruff format --check .
coverage run manage.py test tests --settings=config.test_settings --noinput
coverage report
python manage.py spectacular --file /tmp/openapi.yaml --validate --fail-on-warn
diff -u docs/openapi.yaml /tmp/openapi.yaml
pip check
```

Las pruebas de concurrencia utilizan conexiones PostgreSQL independientes y comprueban adjudicaciones simultáneas, reintentos, reducción de inventario y liberación repetida. La integración continua reproduce los controles, verifica el esquema versionado y construye la imagen Docker.

También se incluye `scripts/smoke_test.py` para una instalación demo ya cargada. Con Gunicorn/API iniciada, `DEMO_PASSWORD='RescateDemo2026!' BASE_URL=http://127.0.0.1:8002 python scripts/smoke_test.py` ejecuta el ciclo HTTP y deja la adjudicación de prueba finalizada, sin reservas. No ejecutar ese script contra producción.
