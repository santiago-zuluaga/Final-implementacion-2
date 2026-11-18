# Pruebas y verificación

## Regresión local

Desde la raíz del repositorio:

```powershell
python -m compileall -q domain_service loan_service ml scripts tests
python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
docker compose config --quiet
docker compose up --build -d
python ml/equivalence.py
python ml/drift.py
python ml/audit_data.py
```

Con el stack activo, las APIs corren en puertos 8001–8004, Nginx en 8080, MLflow en 5000 y RabbitMQ Management en 15672. No ejecutar `down -v` al verificar persistencia.

Después de completar al menos un préstamo de demo y confirmarlo entregado, puede repetirse la prueba temporal de stock con `.venv\Scripts\python.exe scripts\acceptance_stock_race.py`. El script verifica sin stock y la carrera por la última unidad; elimina los datos que crea al finalizar.

Con el mismo fixture COMPLETADA, `.venv\Scripts\python.exe scripts\acceptance_idempotency.py` prueba reintento HTTP, conflicto por cuerpo distinto y republicación de comando/evento RabbitMQ. Limpia los préstamos, stock, producto y movimientos temporales al finalizar.

`.venv\Scripts\python.exe scripts\acceptance_price.py` verifica invalidación de cache y que el préstamo persiste el precio/versión actualizados. También requiere el fixture COMPLETADA y limpia los registros temporales.

`.venv\Scripts\python.exe scripts\acceptance_recovery.py` detiene RabbitMQ y luego el consumidor Inventario en escenarios separados; valida que outbox/cola durable recuperen ambas solicitudes. Restaura ambos servicios y limpia los datos temporales.

`.venv\Scripts\python.exe scripts\acceptance_cancel_late.py` prueba cancelación, evento tardío y expiración de reserva. Adelanta `expires_at` para que la prueba termine en menos de un minuto; elimina los datos que crea.

Con RabbitMQ Management accesible y la DLQ `inventory.commands.dlq` vacía, `.venv\Scripts\python.exe scripts\acceptance_retry_dlq.py` provoca un rollback dentro de la transacción, espera los tres reintentos y retira del DLQ solo su mensaje de prueba. Se detiene con seguridad si la cola ya contiene fallos.

`.venv\Scripts\python.exe scripts\acceptance_model_promotion.py` promueve v2, reinicia Préstamos y consulta `/modelo/info` con ADMIN; luego revierte a v1, repite el reinicio y deja el puntero en v1.

`.venv\Scripts\python.exe ml\audit_mlflow.py` audita los parámetros, métricas de train/validación/test y artefactos del run de v1 seleccionado. El test no reinicia MLflow; la evidencia de persistencia del restart se registra en `EXECUTION_LOG.md`.

`.venv\Scripts\python.exe scripts\acceptance_rabbit_persistence.py` crea una cola de aceptación temporal, comprueba que su mensaje persistente sobrevive un restart real del broker y elimina la cola al terminar.

`.venv\Scripts\python.exe scripts\acceptance_loan_validation.py` comprueba límites de esquema/monto y rechazos por perfil inactivo, ingreso cero y plazo fuera de negocio; valida ausencia de reservas y limpia fixtures.

`.venv\Scripts\python.exe scripts\acceptance_pending_timeout.py` detiene RabbitMQ, espera el timeout real de dos minutos, recupera el broker y verifica cancelación/liberación; tarda aproximadamente 2,5 minutos y limpia sus datos temporales.

## Evidencia actual

El registro fechado, con cantidades y límites, está en [EXECUTION_LOG.md](EXECUTION_LOG.md); los 16 casos académicos y su estado están en [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md). En el corte local del 18-11-2026, pytest dio 13 passed, build web pasó, equivalencia fue 200/200 con error máximo `2.22e-16`, y las pruebas de stock, idempotencia, recuperación, expiración, retry/DLQ y CSV quedaron registradas. Permanecen sin verificación visual los casos de frontend 14–16.

Un build exitoso o un endpoint sano no equivale a pasar el caso de aceptación. Registrar los datos observados y mantener el caso como no verificado hasta cumplir el resultado esperado.
