# Registro de ejecución

Registro conciso de verificaciones reproducibles del stack local. No incluye credenciales, tokens ni datos identificables.

## 2026-11-18

- `docker compose ps`: PostgreSQL, Redis, RabbitMQ y cuatro APIs healthy; frontend y MLflow en ejecución.
- Aislamiento PostgreSQL: se revocó CONNECT de PUBLIC para las cuatro bases; consulta de `has_database_privilege` mostró permiso solo para cada pareja rol/base propia (12 pares cruzados denegados). Las cuatro APIs respondieron health `ok` después del cambio.
- Durabilidad: `docker compose restart postgres` preservó el producto de demo; `/products/1` y login ADMIN respondieron 200 después del reinicio. RabbitMQ/MLflow no se reiniciaron en esta prueba.
- `python -m pytest -q`: 11 passed; un `DeprecationWarning` de Starlette/AnyIO.
- `npm --prefix frontend run build`: TypeScript y Vite exitosos.
- `python ml/equivalence.py`: 200 filas; mismatches 0; max error `2.220446049250313e-16`; modelo v1.
- `python scripts/seed_demo.py`: productos demostrativos 1–3 confirmados; no se reinició stock existente.
- Redis: se borró `products:v1:1`, se hicieron dos lecturas y se consultaron métricas: hits=1, misses=1, fallbacks=0, hit_rate=0.5, p50/p95=0.269 ms. Una ejecución breve, no benchmark ni medición de memoria/CPU.
- Redis resiliencia: al expirar una clave (TTL de prueba 1 s) hubo miss; con Redis detenido, tres lecturas devolvieron 200 desde PostgreSQL en 379.2/5.3/2.9 ms. El contador acumulado fue fallback=6 en dos corridas; p50=1.541 ms, p95=353.888 ms en la ventana del proceso. Después del reinicio de Redis, una corrida mostró miss y luego hit. No es benchmark representativo.
- Invalidación: actualización de precio en el producto de demo invalidó la clave; GET normal y cotización interna devolvieron el precio actualizado. El precio original se restauró (versión de producto pasó a 3). Falta comprobar que un préstamo posterior conserva esa cotización/version.
- Casos de negocio persistidos: la consulta administrativa mostró un préstamo `COMPLETADA` con reserva `DELIVERED` y uno `RECHAZADA` con score/umbral/model_version, sin reserva asociada. No se guardaron identificadores de clientes ni préstamos en este log.
- Importación idempotente: CSV sintético de una fila importado dos veces: primera inserted=1/updated=0/rejected=0, segunda inserted=0/updated=1/rejected=0. Se confirmó el perfil y se eliminó al final.
- Benchmark Redis: 30 misses (p50 4.303 ms, p95 6.290 ms) y 200 hits (p50 1.743 ms, p95 2.991 ms), cero fallbacks en la ventana. Snapshots de CPU/memoria de Productos/PostgreSQL/Redis y límites de esta muestra están en `docs/INFORME_REDIS.md` y `artifacts/redis_benchmark.json`.
- Promoción/rollback: se promovió v2, reinició el servicio Préstamos y `/modelo/info` informó v2; se restauró v1, se reinició y la API informó v1. Puntero final: v1.
- `git diff --check`: correcto (advertencias de conversión LF/CRLF de Git en archivos modificados).
- Navegador: la solicitud de acceso a `http://localhost:8080` fue denegada por la aprobación del origen; no se hicieron más intentos de interfaz automatizada.

## Evidencia previa conservada en el historial del proyecto

- Flujo de préstamo favorable atravesó reserva RabbitMQ/Inventario y entrega, alcanzando `COMPLETADA` y descontando stock.
- Login ADMIN/registro CUSTOMER, ownership y denegación por rol se probaron contra APIs locales; petición ajena dio 403, token inválido 401.
- Repetición HTTP con igual clave/cuerpo devolvió el mismo préstamo; clave repetida con cuerpo distinto dio 409.

Los casos restantes se mantienen sin verificar en `PRUEBAS_ACEPTACION.md` y `MATRIZ_CUMPLIMIENTO.md`.
