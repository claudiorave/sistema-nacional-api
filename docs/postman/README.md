# Recorrido de prueba con Postman

La colección `sistema-nacional.postman_collection.json` recorre la API de punta a punta, en el orden en que la usa RescueSync: login JWT, alta de una ONG, certificación, inventario, validación por competencia, compromiso con locking, liberación y cierre. Cada pedido trae tests que verifican el código de respuesta y los datos devueltos. Con el Runner se ve el resultado de todos de una vez.

## Archivos

| Archivo | Contenido |
|---|---|
| `sistema-nacional.postman_collection.json` | 54 pedidos agrupados en 11 carpetas, con 94 verificaciones |
| `produccion.postman_environment.json` | URL de la API desplegada y nombres de las cuentas, **sin contraseñas** |
| `local.postman_environment.json` | Igual, para la API levantada con `docker compose` en `http://localhost:8002` |

## Cómo ejecutarla

1. En Postman: **Import** → seleccionar los tres archivos.
2. Elegir el entorno `Sistema Nacional - produccion` (arriba a la derecha) y completar `contrasenaOperador` y `contrasenaBonita`. El entorno ya trae las cuentas de evaluación `evaluacion_g20_nacional` y `evaluacion_g20_servicio`; sus contraseñas no están en el repositorio y figuran en el documento de entrega.
3. Sobre la colección: **Run collection** → **Run**. Los pedidos tienen que ejecutarse en orden, porque cada uno guarda en variables lo que usan los siguientes (tokens, UUID de la ONG, del proyecto y del compromiso).

También se puede recorrer a mano, pedido por pedido, empezando siempre por **0. Preparación**. La descripción de cada pedido explica qué demuestra.

Desde la terminal, con Newman:

```bash
npx newman run docs/postman/sistema-nacional.postman_collection.json \
  -e docs/postman/produccion.postman_environment.json \
  --env-var "contrasenaOperador=..." --env-var "contrasenaBonita=..."
```

## Qué muestra cada carpeta

| Carpeta | Requisito del enunciado | Qué se comprueba |
|---|---|---|
| 0. Preparación | — | La API y su base responden. Genera datos únicos para la corrida |
| 1. Autenticación JWT | Login `/login` con JWT | Tokens del operador y de Bonita, vencimiento de 15 minutos, contraseña incorrecta (401), refresh rotatorio y revocación del refresh ya usado |
| 2. Protección de los endpoints | JWT | Sin token o con token adulterado: 401. Rol sin permiso: 403 |
| 3. Catálogo nacional | Catálogo | Tipo de recurso y de certificación de prueba (se reutilizan si ya existen) |
| 4. Registro y habilitación de ONGs | Registro/onboarding de ONGs | La ONG se registra sola y queda `pending`. Duplicado: 400. Solo el operador la habilita. Mapeo del ID local de la app al UUID nacional |
| 5. Certificaciones, inventario y consultas | Consulta de certificaciones, ONGs habilitadas y disponibilidad global | La ONG no puede certificarse a sí misma. Carga de inventario. Perfil de competencia con niveles de riesgo |
| 6. Validación por competencia | Niveles de competencia sin rechazo binario | Principal, apoyo adaptando el riesgo y máximo asignable. Validar no reserva nada |
| 7. Compromiso con locking e idempotencia | Bloqueo transaccional y locking en PostgreSQL | Reserva atómica, reintento con la misma `Idempotency-Key` (200, no reserva dos veces), misma clave con otro contenido (409), sobreasignación rechazada sin reservas parciales (409), stock no editable por debajo de lo comprometido, cierre prematuro (409) |
| 8. Liberación y cierre | Liberación y cierre | La ONG finaliza su actividad y se liberan sus recursos; finalización y cierre son idempotentes; auditoría del proyecto |
| 9. Revocación de certificación | Competencia no binaria | Sin certificación vigente, la ONG pasa a apoyo en lugar de quedar descartada |
| 10. Limpieza y cierre de sesión | JWT | Suspende la ONG de prueba. Logout: el refresh queda revocado |

## Concurrencia

Postman envía los pedidos de a uno, así que no puede provocar una carrera real. La concurrencia está probada en la suite automática, con conexiones PostgreSQL independientes que compiten por el mismo stock (`tests/test_concurrency.py`): dos emergencias por el mismo inventario, reintentos simultáneos con la misma clave, edición de stock durante una adjudicación y finalizaciones duplicadas. Se ejecutan en la CI de cada push.

## Tener en cuenta

- **Cada corrida crea datos de prueba** en la API: una ONG (que queda suspendida al final), su certificación (revocada), su inventario y un proyecto ya cerrado. Los nombres empiezan con `ONG de prueba Postman` y los códigos con `postman-`.
- **Límites de frecuencia** de la API: 10 logins por minuto y 5 registros de ONG por hora por IP. Cada corrida usa 7 y 2. Si se ejecuta varias veces seguidas, esperar un minuto entre corridas; a partir de la tercera corrida en la misma hora, el registro responde 429.
- El access token dura 15 minutos. Si se recorre a mano y pasa más tiempo, volver a ejecutar los logins de la carpeta 1.
