# Registro de ejecución

Registro conciso de verificaciones reproducibles del stack local. No incluye credenciales, tokens ni datos identificables.

## 2026-11-18

- `docker compose ps`: PostgreSQL, Redis, RabbitMQ y cuatro APIs healthy; frontend y MLflow en ejecución.
- Aislamiento PostgreSQL: se revocó CONNECT de PUBLIC para las cuatro bases; consulta de `has_database_privilege` mostró permiso solo para cada pareja rol/base propia (12 pares cruzados denegados). Las cuatro APIs respondieron health `ok` después del cambio.
- Durabilidad: `docker compose restart postgres` preservó el producto de demo; `/products/1` y login ADMIN respondieron 200 después del reinicio. RabbitMQ/MLflow no se reiniciaron en esta prueba.
- `python -m pytest -q`: 13 passed; un `DeprecationWarning` de Starlette/AnyIO. Incluye JWT vencido en ruta protegida y token interno inválido.
- `npm --prefix frontend run build`: TypeScript y Vite exitosos.
- `python ml/equivalence.py`: 200 filas; mismatches 0; max error `2.220446049250313e-16`; modelo v1.
- `python scripts/seed_demo.py`: productos demostrativos 1–3 confirmados; no se reinició stock existente.
- Redis: se borró `products:v1:1`, se hicieron dos lecturas y se consultaron métricas: hits=1, misses=1, fallbacks=0, hit_rate=0.5, p50/p95=0.269 ms. Una ejecución breve, no benchmark ni medición de memoria/CPU.
- Redis resiliencia: al expirar una clave (TTL de prueba 1 s) hubo miss; con Redis detenido, tres lecturas devolvieron 200 desde PostgreSQL en 379.2/5.3/2.9 ms. El contador acumulado fue fallback=6 en dos corridas; p50=1.541 ms, p95=353.888 ms en la ventana del proceso. Después del reinicio de Redis, una corrida mostró miss y luego hit. No es benchmark representativo.
- Invalidación: actualización de precio en el producto de demo invalidó la clave; GET normal y cotización interna devolvieron el precio actualizado. El precio original se restauró (versión de producto pasó a 3). Falta comprobar que un préstamo posterior conserva esa cotización/version.
- Casos de negocio persistidos: la consulta administrativa mostró un préstamo `COMPLETADA` con reserva `DELIVERED` y uno `RECHAZADA` con score/umbral/model_version, sin reserva asociada. No se guardaron identificadores de clientes ni préstamos en este log.
- Importación idempotente: CSV sintético de una fila importado dos veces: primera inserted=1/updated=0/rejected=0, segunda inserted=0/updated=1/rejected=0. Se confirmó el perfil y se eliminó al final.
- Benchmark Redis: 30 misses (p50 4.303 ms, p95 6.290 ms) y 200 hits (p50 1.743 ms, p95 2.991 ms), cero fallbacks en la ventana. Snapshots de CPU/memoria de Productos/PostgreSQL/Redis y límites de esta muestra están en `docs/INFORME_REDIS.md` y `artifacts/redis_benchmark.json`.
- Idempotencia: el mismo HTTP key/body devolvió el mismo préstamo; body distinto con key reutilizada dio 409. Se volvió a publicar el mismo comando de reserva y el mismo evento de reserva: antes/después se mantuvo una fila de reserva RESERVED, un movimiento y un evento; stock 0 disponible/1 reservado. Los registros temporales se limpiaron.
- Cotización fresca: se calentó la clave del producto temporal, se actualizó a versión 2, se confirmó GET/cotización con valor nuevo y se creó un préstamo `APROBADA` que persistió precio y versión 2. Producto, stock, préstamo, reserva y movimientos temporales se limpiaron.
- Recuperación: RabbitMQ se detuvo antes de crear un préstamo; tras reiniciarlo, el outbox publicó y el préstamo avanzó de pendiente a `APROBADA`. Después se detuvo Inventario con RabbitMQ activo; el comando persistió en cola y el consumidor lo procesó al reiniciar. Un movimiento/reserva por caso; filas temporales limpiadas.
- Retry/DLQ: un probe de comando provocó una violación de constraint dentro de la transacción; alcanzó el DLQ tras tres reintentos. Stock, movimientos y outbox quedaron intactos; el probe se retiró del DLQ.
- Estados terminales: cancelar una reserva produjo `CANCELADA`, reserva `RELEASED` y stock disponible=1/reservado=0. Un evento `InventarioReservado` tardío no reactivó el préstamo. En una segunda solicitud, se adelantó `expires_at`; worker produjo reserva `EXPIRED`, préstamo `CANCELADA` y devolvió el stock. Datos temporales limpiados.
- Promoción/rollback: se promovió v2, reinició el servicio Préstamos y `/modelo/info` informó v2; se restauró v1, se reinició y la API informó v1. Puntero final: v1.
- Auditoría de secretos: `.env` ignorado, no está en el historial ni en archivos tracked; ninguno de los valores secretos locales apareció en archivos versionados.
- `git diff --check`: correcto (advertencias de conversión LF/CRLF de Git en archivos modificados).
- Navegador: la solicitud de acceso a `http://localhost:8080` fue denegada por la aprobación del origen; no se hicieron más intentos de interfaz automatizada.

## Evidencia previa conservada en el historial del proyecto

- Flujo de préstamo favorable atravesó reserva RabbitMQ/Inventario y entrega, alcanzando `COMPLETADA` y descontando stock.
- Login ADMIN/registro CUSTOMER, ownership y denegación por rol se probaron contra APIs locales; petición ajena dio 403, token inválido 401.
- Repetición HTTP con igual clave/cuerpo devolvió el mismo préstamo; clave repetida con cuerpo distinto dio 409.

Los casos restantes se mantienen sin verificar en `PRUEBAS_ACEPTACION.md` y `MATRIZ_CUMPLIMIENTO.md`.

- `python ml/audit_data.py`: auditoría reproducible de ambos CSV; resumen de dimensiones, tipos, faltantes, duplicados y hash en `artifacts/data_audit.json`; diccionario agregado en `docs/DICCIONARIO_DATOS.md`.
- MLflow: reinicio aislado de servicio conservó 17/17 IDs de corrida y los 137 archivos de artefactos presentes; el backend SQLite está en `mlflow_data/` y los artefactos en `mlflow_artifacts/`. Tras el reentrenamiento el historial del experimento contiene 32 `FINISHED` y 2 `FAILED`.
- MLflow tracking: auditoría del run seleccionado `v1` comprobó parámetros (algoritmo, split, semilla, hash, features, commit, entorno/preprocesamiento), métricas de entrenamiento/validación/test y artefactos del pipeline, evaluación y ejemplo; resultado en `artifacts/mlflow_audit.json`. Se añadieron métricas `train_*` a `ml/train.py`.
- Entrenamiento: un primer intento falló al imprimir el emoji de MLflow con la codificación cp1252 de Windows; un intento posterior fue interrumpido por el límite de ejecución y quedó `RUNNING`. Ambos aparecen como `FAILED` en MLflow; se completó un entrenamiento nuevo con UTF-8, sin borrar esos fallos. Se observaron avisos de `OptimizeWarning` de scikit-learn y detección de núcleos físicos de joblib en Windows.
- Promoción post-entrenamiento: `scripts/acceptance_model_promotion.py` verificó `/modelo/info` para v2 tras restart y para v1 después del rollback/restart; puntero final v1 en `artifacts/model_promotion_report.json`. `ml/equivalence.py` volvió a dar 200/200, mismatch 0 y error máximo `2.220446049250313e-16`.
- Persistencia RabbitMQ: `scripts/acceptance_rabbit_persistence.py` creó una cola temporal durable, publicó y leyó un mensaje persistente, reinició RabbitMQ y leyó el mismo mensaje; eliminó la cola de prueba. Evidencia: `artifacts/rabbit_persistence_report.json`.
- Model Registry: `ml/promote.py` registra versiones por `run_id` y mueve el alias `champion`; `scripts/acceptance_model_promotion.py` observó alias v2 y luego v1 después de reiniciar Loans. El manifiesto final v1 incluye nombre/versión del Registry; el alias queda apuntando a v1.
- Validación de Préstamos: `scripts/acceptance_loan_validation.py` encontró que Clientes ocultaba al servicio interno perfiles inactivos y la API devolvía 404 al crearlos; se corrigió el filtrado por rol/token. Repetición: quantity=0, plazo 61 y monto > COP 1.000.000.000 dieron 422; cliente inactivo, ingreso cero y plazo 37 dieron `RECHAZADA` con causa; ninguna reserva. Tres filas de préstamo/clave y dos clientes/productos temporales se limpiaron.
- Timeout de solicitud pendiente: `scripts/acceptance_pending_timeout.py` detuvo RabbitMQ, creó una solicitud favorable y esperó 138,8 s. El worker cambió a `CANCELACION_PENDIENTE`; al recuperar RabbitMQ, el préstamo terminó `CANCELADA`, reserva `RELEASED`, stock disponible=1/reservado=0. Filas y producto temporales limpiados; evidencia en `artifacts/pending_timeout_report.json`. Las 21 filas preexistentes en `loans.events.dlq` no se tocaron.
- TEAM-01: enunciado §2 establece máximo cuatro estudiantes y menciona contribuciones de cuatro; por aclaración expresa de Santiago, esta entrega es individual. README identifica a Santiago Zuluaga Correa y enumera responsabilidades; Git registra un único autor (`santidevw`). TEAM-01 refleja esa modalidad, con la diferencia respecto del texto general anotada en la matriz.
- Frontend visual: se intentó abrir el URL confirmado `http://localhost:8080` con el navegador integrado; la herramienta rechazó el acceso por una configuración guardada que impide egress a localhost. No se intentó otra superficie. 14–16 siguen no verificados visualmente.
- Manejo de error del polling: la UI ahora muestra un mensaje visible si falla la consulta periódica del estado y lo limpia cuando vuelve a recibir respuesta; `npm --prefix frontend run build` pasó. Esto es evidencia de compilación/código, no una prueba visual de ACC-15/16.
- Validación final: `pytest -q` 13 passed (un aviso de deprecación de Starlette); build Vite/TypeScript correcto; equivalencia API v1 en 200 filas, cero mismatch, error máximo `2.22e-16`; auditorías de datos y MLflow aprobadas. Todos los nueve servicios Compose estaban running; servicios de negocio, DB, Redis y RabbitMQ healthy. Nginx devolvió la página y cuatro health routes 200.
- Auditoría OpenAPI: cada servicio respondió con 27 rutas y los cuatro documentos enumeran rutas de todos los dominios; API-01/ARQ-03 permanecen pendientes hasta limitar/documentar rutas por servicio y verificar el límite efectivo.
