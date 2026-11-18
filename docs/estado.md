# Estado de CrediMarket

Revisión: 18 de noviembre de 2026. La matriz detallada es [MATRIZ_CUMPLIMIENTO.md](MATRIZ_CUMPLIMIENTO.md); pruebas y límites de los 16 casos están en [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md). El trabajo sigue en curso y no se presenta como cumplimiento del 100%.

## Material de partida

- Enunciado del profesor: `docs/Enunciado_CrediMarket.docx`.
- Histórico: 12.000 × 15, SHA-256 `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd`.
- Solicitudes sin etiqueta: 200 × 14; reservadas para inferencia, equivalencia y análisis descriptivo de drift.
- [`DICCIONARIO_DATOS.md`](DICCIONARIO_DATOS.md) y `artifacts/data_audit.json` registran el esquema y auditoría de ambos archivos.

## Implementado y verificado

- Cuatro APIs FastAPI independientes con cuatro bases PostgreSQL y roles; pruebas confirmaron CONNECT solo a la base de cada dominio.
- Autenticación JWT/roles `ADMIN` y `CUSTOMER`, PBKDF2, ownership de perfil/préstamos, protección de rutas admin/internas, expiración token 401; `.env` ignorado y no aparece en historial.
- Productos cache-aside/invalidación/cotización vigente; Clientes import/upsert; Préstamos persistencia/idempotencia/outbox/máquina de estados; Inventario reserva atómica, movimientos, liberación, entrega y expiración.
- RabbitMQ: outbox recuperado tras broker/consumidor detenidos; duplicados HTTP/evento sin efecto repetido; fallo transaccional genera tres reintentos y DLQ, sin mutación de stock/movimientos/outbox.
- Persistencia RabbitMQ verificada con mensaje persistente en cola durable tras restart; la prueba retiró su cola temporal.
- Aceptación: stock insuficiente, carrera por última unidad, precio/versión actualizada, cancelación/evento tardío/vencimiento, importación CSV doble, promoción/rollback y modelo equivalente probados. Resultado actual: 13/16 casos aprobados.
- ML con split 60/20/20 seed 42, baseline + siete candidatas; v1 `logreg_c1` seleccionado por validación, threshold ~0.305. Equivalencia en 200 filas: mismatches 0, error máximo `2.22e-16`.
- Redis: misses/hits, expiración, fallback con Redis detenido y recuperación probados. Benchmark y snapshots de recursos están en [`INFORME_REDIS.md`](INFORME_REDIS.md) y `artifacts/redis_benchmark.json`.
- `pytest -q`: 13 passed; build frontend Vite/TypeScript correcto; servicios Docker healthy.
- PostgreSQL restart conservó el catálogo y permitió login ADMIN; la persistencia RabbitMQ tras restart aún no se probó.
- MLflow reiniciado de forma aislada conservó 17/17 IDs de corrida y 137 archivos de artefactos que ya existían. La auditoría del run seleccionado confirma métricas train/validación/test; los intentos fallidos quedan visibles en tracking.
- `scripts/acceptance_model_promotion.py` observó v2 y después v1 desde `/modelo/info` tras reiniciar Préstamos; modelo v1 queda activo. La equivalencia fue repetida tras el entrenamiento.

## Pendientes antes de completar

- Casos 14–16: validar flujo real desde la interfaz, polling de estado, formularios/errores y sesión vencida en navegador. La aprobación para abrir `http://localhost:8080` fue denegada por el gate de origen en esta sesión; no se intentó un camino alternativo.
- La matriz conserva 29 requisitos `IMPLEMENTADO_NO_VERIFICADO` y 1 `BLOQUEADO`; incluye auditoría exhaustiva de endpoints/OpenAPI, reinicio RabbitMQ con mensajes persistidos y timeout de solicitud aún pendiente.
- TEAM-01 requiere nombres, responsabilidades y aportes reales del grupo, que no estaban en los archivos recibidos y no se inventaron.

## Límites

Las métricas, ejemplos, datos y umbral de riesgo son sintéticos. PSI sin etiquetas describe cambios de distribución; no permite concluir concept drift ni caída del desempeño. Los resultados de caché y Docker son muestras locales, no una garantía de producción.
