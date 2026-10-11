# Desarrollo

Usar Python 3.12 y PostgreSQL; preparar `.env` según README. Instalar `requirements-dev.txt` y ejecutar los controles de la sección Verificación antes de publicar cambios. La CI exige al menos 85 % de cobertura y que `docs/openapi.yaml` coincida con el esquema generado.

Las operaciones que afectan habilitación, credenciales o inventario deben tomar el lock de la ONG correspondiente. Las operaciones de un proyecto toman primero el lock del proyecto, luego los de ONG en orden de UUID, y finalmente inventarios en orden de UUID. Mantener ese orden para evitar deadlocks. No mutar reservas ni datos operativos desde el admin ni crear rutas que eviten los servicios transaccionales.

Las ofertas y sus versiones pertenecen al backend local. Una nueva ruta de evaluación nacional debe ser consultiva y no persistir esas propuestas. Los compromisos reflejan adjudicaciones firmes y conservan su auditoría.

Al cambiar modelos, incluir las migraciones. Al cambiar contratos, regenerar el OpenAPI y actualizar ejemplos/documentación. No incorporar claves, `.env`, datos reales ni archivos generados de entornos virtuales.

`requirements.in` registra dependencias directas; `requirements.txt` fija todas las dependencias de ejecución. Actualizar en un entorno limpio, revisar la compatibilidad, regenerar el lock y ejecutar las pruebas. Las dependencias de desarrollo están fijadas en `requirements-dev.txt`.
