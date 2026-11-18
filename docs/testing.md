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
```

Con el stack activo, las APIs corren en puertos 8001–8004, Nginx en 8080, MLflow en 5000 y RabbitMQ Management en 15672. No ejecutar `down -v` al verificar persistencia.

Después de completar al menos un préstamo de demo y confirmarlo entregado, puede repetirse la prueba temporal de stock con `.venv\Scripts\python.exe scripts\acceptance_stock_race.py`. El script verifica sin stock y la carrera por la última unidad; elimina los datos que crea al finalizar.

Con el mismo fixture COMPLETADA, `.venv\Scripts\python.exe scripts\acceptance_idempotency.py` prueba reintento HTTP, conflicto por cuerpo distinto y republicación de comando/evento RabbitMQ. Limpia los préstamos, stock, producto y movimientos temporales al finalizar.

`.venv\Scripts\python.exe scripts\acceptance_price.py` verifica invalidación de cache y que el préstamo persiste el precio/versión actualizados. También requiere el fixture COMPLETADA y limpia los registros temporales.

`.venv\Scripts\python.exe scripts\acceptance_recovery.py` detiene RabbitMQ y luego el consumidor Inventario en escenarios separados; valida que outbox/cola durable recuperen ambas solicitudes. Restaura ambos servicios y limpia los datos temporales.

## Evidencia actual

El registro fechado, con cantidades y limitaciones, está en [EXECUTION_LOG.md](EXECUTION_LOG.md); los 16 casos académicos y su estado están en [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md). En la corrida local del 18-11-2026, pytest dio 11 passed, build web pasó, equivalencia fue 200/200 con error máximo `2.22e-16`, y la caché produjo una muestra miss/hit. Aún faltan pruebas automatizadas de concurrencia, caída de dependencias, retries/DLQ y flujo visual real.

Un build exitoso o un endpoint sano no equivale a pasar el caso de aceptación. Registrar los datos observados y mantener el caso como no verificado hasta cumplir el resultado esperado.
