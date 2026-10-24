# Entrega 3 · Sistema Nacional · RescueSync

## Alcance y fuentes

Implementación del ítem «Servicios Web / API Externa (Sistema Nacional)» y del cronograma de entrega 3 de `Trabajo integrador 2026 (1).pdf`. Se revisaron el backend/frontend de etapa 2 y el proyecto Bonita `rescuesync-grupo20-etapa2-v3.bos`. El servicio está contenido íntegramente en `sistema_nacional`; las aplicaciones de etapa 2 y su BOS se conservaron.

La API nacional no almacena ofertas preliminares, no controla el timer y no decide adjudicaciones municipales. Gestiona identidades, habilitaciones, capacidades, inventario y compromisos nacionales firmes. El contrato de integración permite que Bonita consulte las ofertas locales y luego llame a este servicio.

## Trazabilidad

| Requisito obligatorio | Implementación | Evidencia |
|---|---|---|
| Django y servicio independiente | `config/`, `national/`, migración inicial | Checks y migraciones aplicadas en PostgreSQL |
| Login `/login` con JWT | Login, refresh rotatorio, blacklist, logout, usuario activo | Pruebas JWT y ensayo HTTP |
| Registro/onboarding ONG | ONG pendiente, usuario propio, validación de contraseña y datos | Pruebas de onboarding y anti-escalamiento |
| Gestión de ONGs habilitadas | Catálogo, contacto propio, habilitación/suspensión nacional | Pruebas de permisos y aislamiento |
| Consulta de certificaciones | Tipos, emisión nacional, vigencia por fechas y revocación | Pruebas de certificados vencidos/futuros/revocados y último día válido |
| Disponibilidad global | Inventario total/reservado/disponible y agregación nacional | Pruebas de catálogo, inventario y ONGs suspendidas |
| Perfiles por competencia/riesgo | Capacidades principales y de apoyo con riesgos permitidos | Pruebas de adaptación y restricciones de apoyo sanitario |
| Restricciones antes de comprometer | Validación no persistente y reevaluación dentro de la adjudicación | Pruebas de cambios de credenciales/stock entre etapas |
| PostgreSQL y locking | Transacciones, locks de ONG/inventario ordenados, constraints | Pruebas reales con conexiones concurrentes |
| Prevención de sobreasignación | Adjudicación atómica de todas las ONGs/lotes | Dos emergencias compiten por un stock; solo una reserva |
| Reintentos distribuidos | Hash canónico y clave de idempotencia por origen | Solicitudes paralelas idénticas reservan una vez |
| Liberación por ONG | Finalización idempotente, reserva liberada transaccionalmente | Doble finalización concurrente libera una vez |
| Cierre de proyecto | Confirmación de servicio/nacional tras todas las actividades | Cierre prematuro 409 y cierre/reintento 200 |
| Swagger | UI con Bearer JWT y estáticos locales, OpenAPI versionado | Generación/validación sin warnings y ensayo de archivos estáticos |
| Docker y preparación cloud | Dockerfile sin root, Compose PostgreSQL/Redis, Blueprint Render | Imagen construida, Compose saludable y ensayo HTTP en contenedores |
| Repositorio y documentación | `.gitignore`, locks de dependencias, CI, guías y ejemplos | Lint, formato, dependencias y esquema consistentes |

## Verificación realizada

Fecha: **11 de octubre de 2026**.

- **62 pruebas aprobadas**, incluidas 7 pruebas PostgreSQL concurrentes, sin mocks de los locks.
- **97 % de cobertura** del código de aplicación medido por `coverage`; migraciones, comandos de administración y admin se excluyen de esa métrica. Los comandos de creación de cuentas y demo se prueban por separado dentro de la suite.
- Suite aprobada con PostgreSQL **18** en un cluster aislado y también con PostgreSQL **17** dentro de Docker, la versión utilizada por Compose y CI.
- `manage.py check`, migraciones y `makemigrations --check --dry-run`: correctos.
- OpenAPI generado con `spectacular --validate --fail-on-warn`, sin diferencias con `docs/openapi.yaml`.
- `ruff check`, `ruff format --check` y `pip check`: correctos.
- `manage.py check --deploy --fail-level WARNING` con `DEBUG=false`, claves distintas y configuración de producción: sin advertencias.
- Gunicorn real con **2 workers y 4 threads**, PostgreSQL y Redis **7**: ensayo HTTP de login, validación, compromiso, reintento, liberación y cierre completo. El ensayo local del ciclo usa HTTP sin redirect para poder ejecutarse sin certificado.
- Segundo arranque con redirect HTTPS y confianza en proxy: salud interna 200, Swagger 200 al recibir protocolo HTTPS desde el proxy y cabecera HSTS activa.
- Swagger/ReDoc y sus recursos JS/CSS respondieron 200 con estáticos recopilados y `DEBUG=false`.
- `render.yaml` validado contra `https://render.com/schema/render.yaml.json`; Compose parseado y revisado para esperar la migración antes del arranque.
- Docker Desktop **29.8.0** y Compose **5.5.1**: `docker compose build` y `docker compose up -d --wait` completados correctamente. PostgreSQL, Redis y API quedaron saludables; el servicio de migración finalizó con código cero antes de iniciar Gunicorn.
- La imagen corre como usuario `national`, UID **10001**, sin root. Las 62 pruebas se ejecutaron también usando la imagen construida y un montaje de solo lectura de la suite sobre `/app/tests`, con una base de pruebas separada del catálogo demo.
- Ensayo HTTP contra la API de Docker publicada en `127.0.0.1:8002`: JWT, validación, adjudicación, reintento, finalización y cierre aprobados. La adjudicación de ensayo quedó completada y sin reservas pendientes.

Las pruebas concurrentes cubren emergencias competidoras, reintentos idénticos, edición simultánea de inventario, finalizaciones duplicadas, claves distintas sobre una misma emergencia, orden inverso de ONGs y revocación de credenciales durante una adjudicación.

## Despliegue

La API está desplegada con Docker Compose (API con Gunicorn, PostgreSQL 17 y Redis 7) en un servidor propio del equipo, detrás de un proxy con HTTPS. En producción `DEBUG=false` y no existen las cuentas demo: `seed_demo` se niega a ejecutarse fuera de desarrollo. Las cuentas operativas son `operador_nacional` (operador nacional) y `bonita_rescuesync` (cuenta de servicio de Bonita). Para la corrección hay cuentas separadas, `evaluacion_g20_nacional`, `evaluacion_g20_servicio` y `evaluacion_g20_ong`, con datos precargados propios; sus contraseñas figuran en el documento de entrega y no en el repositorio.

| Artefacto solicitado | Ubicación |
|---|---|
| Swagger | https://sistema-nacional.claudioraverta.site/api/docs/ |
| ReDoc | https://sistema-nacional.claudioraverta.site/api/redoc/ |
| OpenAPI | https://sistema-nacional.claudioraverta.site/api/schema/ (versionado en `docs/openapi.yaml`) |
| Base de la API | https://sistema-nacional.claudioraverta.site/api/v1/ (login también en `/login`) |
| Salud | https://sistema-nacional.claudioraverta.site/health/ready/ |
| Repositorio | https://github.com/claudiorave/sistema-nacional-api |
| Dockerfile | https://github.com/claudiorave/sistema-nacional-api/blob/main/Dockerfile |
| Recorrido de prueba | [`docs/postman/`](postman/README.md): colección de Postman con 54 pedidos y 94 verificaciones |
| Guía de despliegue | `docs/DESPLIEGUE.md` |

La raíz del dominio redirige al Swagger.

## Recorrido con Postman

La colección de `docs/postman/` ejecuta el ciclo completo contra la API: JWT y revocación de refresh, protección por rol, onboarding y habilitación de una ONG, certificación, inventario, perfil de competencia, validación sin reserva, compromiso con `Idempotency-Key`, sobreasignación rechazada sin reservas parciales, liberación, cierre bilateral y revocación de la certificación. La concurrencia real se demuestra con la suite automática (`tests/test_concurrency.py`), no con Postman, que envía los pedidos de a uno.

## Fuera del alcance de esta entrega

La conexión del proceso de Bonita con esta API (validación, compromiso, liberación y cierre desde tareas automáticas) corresponde a la integración final. El contrato está documentado en `INTEGRACION_BONITA.md`.
