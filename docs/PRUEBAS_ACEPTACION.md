# Pruebas de aceptación

Fuente de los casos: sección 12 del enunciado del profesor. El estado refleja ejecución con evidencia; una ruta existente o revisión de código no basta para marcar un caso aprobado. Fecha de evidencia: 2026-11-18.

## Comandos de regresión ejecutados

| Verificación | Resultado | Evidencia |
|---|---|---|
| Seguridad de sesión/token | Correcto | JWT vencido rechazado por ruta protegida (401); token interno incorrecto rechazado (401); tests existentes verifican rol y ownership. Auditoría confirmó `.env` fuera del historial Git y valores locales ausentes de archivos tracked. |
| Aislamiento PostgreSQL | Correcto | `has_database_privilege` comprobó CONNECT propio en cada una de las cuatro bases y denegó los 12 pares rol/base cruzados. Se revocó CONNECT de PUBLIC y se agregó al init para clústeres nuevos. |
| Persistencia PostgreSQL/RabbitMQ/MLflow | Correcto | PostgreSQL conservó catálogo/login tras restart; publicación persistente en cola durable sobrevivió restart de RabbitMQ; MLflow conservó 17/17 IDs y 137 artefactos existentes al reiniciar. |
| `python -m pytest -q` | 34 passed, 1 aviso deprecado | Unitarias/ASGI: seguridad, ownership, pipeline de riesgo, PSI, OpenAPI y rol CUSTOMER en operaciones administrativas de Inventario. |
| OpenAPI de Productos/Clientes/Préstamos/Inventario | Correcto | Compose auditado tras la activación de productos: esquema en vivo coincide con manifiesto. Respectivamente: 10/7, 10/8, 12/11 y 7/7 operaciones/paths; solo operaciones propias y health/readiness comunes. Alias de Préstamos marcados deprecated. |
| `npm --prefix frontend test` | 11 passed en la corrida completa inicial de esta continuación | Incluyó cliente HTTP, detalle/activación de producto y nuevos helpers de préstamo; esa corrida incidental incluyó tests auxiliares de producto y no se usa como evidencia adicional de FE-01. Luego de los cambios FE-02–07 se ejecutaron 9 tests dirigidos que excluyen los nombres de pruebas de producto: 9 passed. |
| `node --experimental-strip-types --test --test-name-pattern=... frontend/test/api.test.mjs` | 9 passed, 0 fallidos | Sesión/JWT, errores/red, detalle de préstamo, polling de estados y conservación de key/cuerpo idempotente; filtro omitió los tests auxiliares de producto. |
| `npm run build` | Correcto | TypeScript y Vite produjeron bundle después de los cambios de FE-02–07. |
| `python scripts/acceptance_frontend_customers.py` | Correcto | Docker real: perfil propio GET/PUT 200; cliente ajeno GET/PUT 403; import CUSTOMER 403; CSV ADMIN insertó 1, actualizó 1, rechazó 1 y devolvió error de fila 4; cleanup aislado. |
| Proxy frontend + persistencia | Correcto | Vite dev y Nginx producción sirvieron health/lecturas reales de las cuatro APIs; POST de perfil vía Vite proxy y GET posteriores por Vite y Clientes coincidieron. Fixture identificado `ARQ05-FE-PROXY-057d35449ed8`. No prueba interacción visual React. |
| `npm --prefix frontend run build` | Correcto | TypeScript y Vite produjeron bundle. |
| Manejo de error del polling frontend | Automatizado/compilado; visual pendiente | Todas las solicitudes no terminales de la lista propia se consultan con JWT cada 1,8 s; errores se muestran en aviso global y se reintentan. Prueba Node verifica qué estados son consultables; no sustituye navegador ACC-15. |
| `python ml/equivalence.py` | Correcto | 200 solicitudes, mismatch 0, error absoluto máximo `2.220446049250313e-16`, tolerancia `1e-9`, modelo `v1`. |
| `python ml/audit_data.py` | Correcto | Auditoría reproducible de histórico (12.000 × 15) y solicitudes (200 × 14), sin filas duplicadas; SHA-256 en `artifacts/data_audit.json`. |
| `python ml/audit_mlflow.py` | Correcto | Run seleccionado v1 contiene parámetros requeridos, métricas train/validación/test y artefactos esperados; evidencia en `artifacts/mlflow_audit.json`. |
| `python scripts/acceptance_model_promotion.py` | Correcto | API y alias MLflow `champion` reportaron v2/Registry v1 tras promoción y v1/Registry v2 tras rollback con reinicios; evidencia en `artifacts/model_promotion_report.json`. |
| `python scripts/acceptance_rabbit_persistence.py` | Correcto | Mensaje persistente en cola durable fue leído antes y después de reiniciar RabbitMQ; cola temporal eliminada. |
| `python scripts/acceptance_loan_validation.py` | Correcto | Límites de esquema/monto (422), cliente inactivo, ingreso cero y plazo no permitido rechazados; no hubo reserva y los fixtures temporales se limpiaron. |
| `python scripts/acceptance_pending_timeout.py` | Correcto | Con broker detenido se esperó 138,8 s; solicitud pasó a cancelación por timeout, se recuperó el broker, reserva liberada y stock restaurado. |
| `python scripts/seed_demo.py` | Correcto | Productos 1–3 disponibles; script no resetea stock existente. |
| `python scripts/acceptance_stock_race.py` | Correcto | Favorable sin stock → `CANCELADA_SIN_STOCK`; carrera por una unidad produjo exactamente una `APROBADA` y una `CANCELADA_SIN_STOCK`, available=0/reserved=1; datos temporales eliminados. Requiere que exista un préstamo `COMPLETADA` sintético para reutilizar su perfil de riesgo. |
| `python scripts/acceptance_idempotency.py` | Correcto | Mismo HTTP key/body devolvió igual ID; body cambiado dio 409; republicar comando y evento mantuvo una reserva, un movimiento y un evento. Limpieza temporal incluida; requiere préstamo `COMPLETADA` sintético. |
| `python scripts/acceptance_price.py` | Correcto | Cache caliente, actualización a versión 2, GET/cotización nueva y préstamo APROBADA con precio/versión 2 persistidos; datos temporales eliminados. Requiere préstamo `COMPLETADA` sintético. |
| `python scripts/acceptance_recovery.py` | Correcto | Broker detenido durante escritura y consumer Inventario detenido durante publicación; ambas solicitudes quedaron pendientes y luego APROBADA, una reserva por cada una, limpieza temporal. |
| `python scripts/acceptance_cancel_late.py` | Correcto | Cancelación devolvió stock y evento tardío dejó estado terminal; reserva expirada terminó EXPIRED, préstamo CANCELADA y stock liberado. |
| `python scripts/acceptance_retry_dlq.py` | Correcto | Un comando provocó fallo de constraint dentro de la transacción: tres reintentos, DLQ con `attempts=3`, sin cambio de stock/movimientos/outbox; probe retirado del DLQ. |
| Redis miss/hit en Docker | Correcto | Clave del producto 1 eliminada y consultada dos veces: hits 1, misses 1, fallbacks 0; hit rate 0.5; p50/p95 observados 0.269 ms en esa corrida. Muestra de demo, no benchmark. |
| Redis expiración, caída y recuperación | Correcto | Se expiró una clave en 1 s y la lectura volvió a PostgreSQL; en la última parada de Redis, tres lecturas dieron 200 en 379.2/5.3/2.9 ms. El contador acumulado de fallback fue 6 en dos corridas de caída. p50=1.541 ms, p95=353.888 ms en la ventana del proceso. Tras restaurar Redis, la siguiente corrida produjo miss y hit. |
| Promoción y rollback V2/V1 | Correcto | `ml/promote.py v2`, reinicio de Préstamos, `/modelo/info` devolvió v2; rollback a v1, reinicio, `/modelo/info` devolvió v1. Puntero quedó en v1. |
| `git diff --check` | Correcto | Sin errores de whitespace. |

El acceso del navegador integrado a `http://localhost:8080` fue rechazado por una configuración guardada de permisos; no se intentó otro navegador ni una vía indirecta. La interfaz compila y el proxy API funciona, pero los criterios visuales y el flujo UI real quedan sin comprobar.

## Casos del enunciado

| # | Caso | Resultado actual | Evidencia/pendiente |
|---:|---|---|---|
| 1 | Riesgo favorable con stock y entrega | Aprobado. | API muestra un préstamo `COMPLETADA` y la reserva asociada `DELIVERED` después del flujo integrado por RabbitMQ. La UI queda para casos 14–15. |
| 2 | Riesgo desfavorable sin reserva | Aprobado. | Préstamo `RECHAZADA` persistido contiene score, threshold y model_version; no hay reserva asociada en Inventario. |
| 3 | Riesgo favorable sin stock | Aprobado. | `scripts/acceptance_stock_race.py`: producto temporal sin fila de stock terminó `CANCELADA_SIN_STOCK`; sin stock negativo. |
| 4 | Dos solicitudes por última unidad | Aprobado. | Dos POST concurrentes contra PostgreSQL con una unidad: una `APROBADA`, otra `CANCELADA_SIN_STOCK`; available=0, reserved=1. |
| 5 | Petición/evento repetido | Aprobado. | `acceptance_idempotency.py` repitió petición HTTP y volvió a publicar el comando y el evento con el mismo event_id. Mismo préstamo, 409 ante cuerpo distinto y efectos de inventario permanecieron en una reserva/movimiento/evento. |
| 6 | Caída de consumidor/broker y recuperación | Aprobado. | `acceptance_recovery.py` detuvo RabbitMQ al escribir el préstamo y luego detuvo Inventario tras publicar el comando; tras restaurar ambos casos avanzaron de pendiente a aprobado con un efecto por préstamo. |
| 7 | Cancelación y evento tardío/expirado | Aprobado. | `acceptance_cancel_late.py`: liberación por cancelación, evento tardío sin reactivación y expiración con estado CANCELADA/EXPIRED y stock devuelto. `acceptance_pending_timeout.py`: worker venció solicitud tras 138,8 s y al reanudar el broker finalizó `CANCELADA` con reserva liberada y stock restaurado. |
| 8 | Redis vacío, expirado y caído | Aprobado. | Clave vaciada y miss/hit; TTL expirado; Redis detenido con tres respuestas 200 vía DB y fallbacks=3; Redis restaurado y caché retomó miss/hit. El TTL configurado es 300s; la prueba de expiración acortó el TTL de la clave a 1s. |
| 9 | Cambio de precio invalida cache y préstamo usa nuevo precio | Aprobado. | `acceptance_price.py`: clave caliente, PUT a versión 2, GET y cotización interna nuevos; préstamo aprobado guardó el precio y la versión 2. Limpieza automática. |
| 10 | Modelo exportado equivalente a API | Aprobado. | Corrida de equivalencia: 200/200, mismatch 0, max error `2.22e-16`, modelo v1. |
| 11 | Promoción/rollback de modelo | Aprobado. | Se promovió v2, reinició Préstamos y `/modelo/info` informó v2; alias MLflow `champion` apuntó al run de v2. Rollback a v1, reinicio y API/alias informaron v1. Puntero final v1. |
| 12 | Importar CSV dos veces sin duplicar | Aprobado. | CSV sintético de una fila: primera importación inserted=1/updated=0/rejected=0; segunda inserted=0/updated=1/rejected=0; se confirmó un solo perfil y se eliminó tras la prueba. |
| 13 | Cliente no ve préstamos ajenos | Aprobado por prueba manual de API previa: dueño 200, ajeno 403; unitarias verifican solicitud ajena 403. | Conservar el resultado reproducible de integración al ejecutar la suite completa. |
| 14 | Operación del negocio desde frontend | No verificado por navegador. | Proxy y endpoints reales pasan; flujo completo React sigue pendiente de inspección visual/interacción real. |
| 15 | UI refleja transición asíncrona | Backend se probó en flujo feliz previo; polling ampliado y compilado, UI no verificada visualmente. | Confirmar que solicitudes propias pendientes cambien en la tabla React tras evento RabbitMQ. |
| 16 | Formularios/expiración/API caída con mensaje y recuperación | No verificado completo. | Helpers de sesión/red pasan pruebas automáticas; probar errores de formulario, expiración y caída/recuperación desde UI. |

## Criterio para cerrar

Cada caso necesita comando/script reproducible, precondiciones, resultado esperado y resultado observado. Los escenarios destructivos de broker/Redis deben ejecutarse con datos de demo identificados y restaurar los contenedores al terminar. No afirmar “16/16” mientras los casos parciales o no verificados sigan abiertos.
