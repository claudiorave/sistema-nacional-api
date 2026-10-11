# Contrato de integración · RescueSync y Bonita

El proyecto nacional no modifica `rescuesync_back`, `rescuesync_front` ni el `.bos` de etapa 2. La API está completa y disponible para los conectores de la siguiente iteración del proceso. El `.bos` inspeccionado contiene la tarea «Validación nacional pendiente (etapa 3)» y actividades posteriores sin conectores nacionales; importar ese archivo sin cambios no ejecuta automáticamente la nueva API.

## Responsabilidades

1. La app local conserva emergencias, lotes, ofertas editables, revisiones y consorcios.
2. Bonita controla el timer y solicita las ofertas locales al vencer.
3. Bonita invoca la validación nacional; conserva en variables del proceso la evaluación estructurada y deriva la cobertura efectiva/caminos alternativos.
4. El municipio selecciona las cantidades y ONGs entre las alternativas habilitadas.
5. Bonita compromete la adjudicación en el sistema nacional; solo entonces se consideran asignados los recursos nacionales.
6. Al finalizar las actividades en la app local, se informa cada compromiso nacional. Después de la confirmación bilateral se cierra el proyecto.

La API nacional no inicia consultas al backend local, no administra el timer ni guarda ofertas preliminares. `POST validations/` procesa el JSON en memoria y responde; los proyectos y líneas se persisten recién en `POST commitments/`.

## Identificadores

Los IDs numéricos de la base local no son IDs nacionales. El servicio nacional usa UUID para ONGs, inventarios, proyectos y compromisos; los códigos de recurso son estables.

Crear la cuenta `bonita_rescuesync` con `create_service_account`. Su `source_system` identifica la instalación local. Con un JWT de operador nacional, registrar cada correspondencia:

```http
POST /api/v1/organization-references/
Authorization: Bearer <access_del_operador_nacional>
Content-Type: application/json

{
  "source_system": "<uuid_impreso_por_create_service_account>",
  "external_id": "2",
  "organization": "<uuid_nacional_de_la_ong>"
}
```

Con su propia cuenta de servicio, Bonita consulta `GET /api/v1/organization-references/?external_id=2`. Una referencia ajena a su sistema no aparece. Para revisar el UUID de su sistema, puede consultar `/api/v1/auth/me/`. Solo el operador nacional crea correspondencias; la ONG no puede vincularse a la identidad de otra organización.

La aplicación local de etapa 2 define lotes con `resource` y `unit` de texto libre. Antes de conectar adjudicaciones debe existir una correspondencia explícita por lote con `resource_code` nacional y la unidad correcta; no deducirla con coincidencias de texto. `lot_ref` conserva el ID local como cadena. El mapa debe almacenarse en la app local o variables de Bonita, no en ofertas nacionales. La etapa 2 devuelve IDs de lotes en cada oferta; los datos de los lotes se obtienen de la emergencia local/variable `emergenciaJSON`.

## Autenticación

```http
POST /login
Content-Type: application/json

{"username": "bonita_rescuesync", "password": "<secreto_del_servidor>"}
```

Respuesta: `access` de 15 minutos y `refresh` de un día. Bonita utiliza `Authorization: Bearer <access>`. Mantener credenciales en la configuración segura del servidor/conector, fuera del `.bos`, scripts versionados y logs. Renovar con `POST /api/v1/auth/refresh/` y sustituir ambos tokens: el refresh anterior queda revocado. No compartir un refresh rotatorio entre instancias concurrentes; usar tokens por instancia o coordinar su renovación. Si expira, iniciar una sesión nueva con la cuenta de servicio.

## Obtener y evaluar las ofertas

Al vencer el timer, Bonita mantiene el GET existente:

```http
GET <URL_RESCUESYNC>/api/integrations/bonita/emergencies/12/offers/
X-Bonita-Callback-Token: <secreto_de_rescuesync>
```

Esta ruta está declarada en `rescuesync_back/config/urls.py`. El contrato actual devuelve `emergency`, `case_id`, `offers`, `consortia`, `coverage` y `coverage_type=declared_not_validated`. No utilizar `fully_covered` como si fuese cobertura nacional habilitada.

Transformar **cada alternativa** a un request de validación, preservando los aportes individuales de un consorcio. Si se agrupan varias ofertas alternativas de la misma ONG/recurso, la respuesta de una sola validación aplica disponibilidad acumulada en el orden de las líneas; para comparar alternativas independientes hacer consultas separadas. La API limita cada solicitud a 200 ítems.

```http
POST /api/v1/validations/
Authorization: Bearer <access>
Content-Type: application/json

{
  "items": [{
    "organization": "<uuid_nacional>",
    "resource_code": "food-ration",
    "lot_ref": "23",
    "quantity": 100,
    "risk_level": "high"
  }]
}
```

Cada resultado contiene `main_allowed_risk_levels`, `support_allowed_risk_levels`, `recommended_assignment`, disponibilidad y un perfil de capacidades. Un resultado `support` con riesgo permitido `low` implica asignar tareas de apoyo de riesgo bajo; no autoriza usar recursos sin habilitación en funciones principales peligrosas. Conservar la cobertura principal y la secundaria por separado. Si la principal es insuficiente, Bonita debe volver al coordinador para evaluar reapertura/reformulación/cobertura parcial, según la guía.

No hay reservas en esta fase; enviar la adjudicación más tarde puede devolver 409 aunque esta consulta hubiese mostrado stock suficiente.

## Comprometer únicamente lo adjudicado

Después de la selección municipal:

```http
POST /api/v1/commitments/
Authorization: Bearer <access>
Idempotency-Key: rescuesync:12:adjudicacion:1
Content-Type: application/json

{
  "project": {
    "external_id": "12",
    "title": "Inundación en La Plata",
    "bonita_case_id": "3456",
    "municipality_ref": "1",
    "risk_level": "high"
  },
  "items": [{
    "organization": "<uuid_nacional>",
    "resource_code": "food-ration",
    "lot_ref": "23",
    "quantity": 100,
    "risk_level": "high",
    "assignment": "main"
  }]
}
```

Enviar todas las ONGs seleccionadas, incluidas las de consorcios, en la misma adjudicación. La respuesta 201 incluye el UUID del proyecto y `commitments` con UUID por ONG, más las líneas e instantáneas de competencia. Guardar esos IDs en Bonita y/o la app local para la liberación. La cantidad puede ser menor que la oferta inicial si el municipio adjudica parcialmente. `external_id` es único dentro del `source_system`; dos instalaciones pueden usar la emergencia local `12` sin colisionar.

Timeout/503: reintentar con **la misma clave y el mismo payload**. Un reintento confirmado devuelve 200 sin doble reserva. HTTP 409 por disponibilidad/competencia exige reevaluar y adaptar la adjudicación; no repetir indefinidamente ni notificar asignación firme antes del compromiso exitoso. El fallo no deja reservas parciales. Se puede consultar `GET projects/?external_id=12` para reconciliar, sin inventar otra clave.

Esta versión modela una adjudicación única por emergencia. Ampliaciones o reemplazos posteriores de adjudicación requieren un contrato adicional; no modificar el inventario reservado ni crear duplicados para simularlos.

## Finalizar y cerrar

Cuando una ONG marque su actividad terminada en la app local, Bonita o un representante autenticado de esa ONG invoca:

```http
POST /api/v1/commitments/<uuid_compromiso>/complete/
Authorization: Bearer <access>
Content-Type: application/json

{"notes": "Entrega y actividades finalizadas"}
```

La reserva nacional de esa ONG se libera en la misma transacción que registra la finalización. Repetir no libera dos veces. La primera nota y fecha permanecen. Otra ONG no puede finalizarla. La cuenta de servicio solo puede operar sobre proyectos de su `source_system`.

Tras todas las actividades y la confirmación bilateral del flujo:

```http
POST /api/v1/projects/<uuid_proyecto>/close/
Authorization: Bearer <access>
Content-Type: application/json

{}
```

Devuelve 200 con `status=completed`; 409 si aún existe una actividad activa. El municipio/coordinador confirma el cierre en la app/Bonita; la API recibe la llamada de servicio autorizada, no administra interfaces ni notificaciones municipales. El cierre es idempotente.

## Conectores y ensayo del BOS

En la copia de etapa 3 del proyecto Bonita:

1. Sustituir la tarea de espera nacional por servicio/conector REST de validación, conservando el GET local iniciado por Bonita.
2. Agregar variables para las correspondencias nacionales, los perfiles devueltos, la adjudicación seleccionada, la clave de idempotencia, el UUID del proyecto y los compromisos por ONG.
3. Adaptar el camino alternativo de cobertura a los recursos habilitados efectivamente, antes de la selección municipal.
4. Conectar «Registrar compromiso en sistema nacional» a `POST commitments/` después de adjudicar. Configurar recuperación de 409/503 y no avanzar al despliegue de recursos ante un fallo.
5. Conectar finalización y cierre con `complete/` y `close/`, preservando cierre bilateral y notificaciones del BPM.
6. Usar HTTPS y configurar timeout del conector superior al timeout de base (30 segundos), con reintentos acotados de la misma operación.
7. Ensayar dos emergencias competidoras, una oferta de apoyo, una credencial vencida y un reintento después de timeout.

El esquema Swagger refleja los requests nacionales completos. El contrato nacional quedó validado mediante pruebas HTTP; la ejecución de esos conectores en el motor Bonita requiere modificar/importar/desplegar el proceso, y no se presenta aquí como ya realizada.
