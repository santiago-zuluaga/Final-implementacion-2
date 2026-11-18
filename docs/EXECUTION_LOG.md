# Registro de ejecución

Registro conciso de verificaciones reproducibles del stack local. No incluye credenciales, tokens ni datos identificables.

## 2026-11-18

- `docker compose ps`: PostgreSQL, Redis, RabbitMQ y cuatro APIs healthy; frontend y MLflow en ejecución.
- Aislamiento PostgreSQL: se revocó CONNECT de PUBLIC para las cuatro bases; consulta de `has_database_privilege` mostró permiso solo para cada pareja rol/base propia (12 pares cruzados denegados). Las cuatro APIs respondieron health `ok` después del cambio.
- `python -m pytest -q`: 11 passed; un `DeprecationWarning` de Starlette/AnyIO.
- `npm --prefix frontend run build`: TypeScript y Vite exitosos.
- `python ml/equivalence.py`: 200 filas; mismatches 0; max error `2.220446049250313e-16`; modelo v1.
- `python scripts/seed_demo.py`: productos demostrativos 1–3 confirmados; no se reinició stock existente.
- Redis: se borró `products:v1:1`, se hicieron dos lecturas y se consultaron métricas: hits=1, misses=1, fallbacks=0, hit_rate=0.5, p50/p95=0.269 ms. Una ejecución breve, no benchmark ni medición de memoria/CPU.
- Promoción/rollback: se promovió v2, reinició el servicio Préstamos y `/modelo/info` informó v2; se restauró v1, se reinició y la API informó v1. Puntero final: v1.
- `git diff --check`: correcto (advertencias de conversión LF/CRLF de Git en archivos modificados).
- Navegador: la solicitud de acceso a `http://localhost:8080` fue denegada por la aprobación del origen; no se hicieron más intentos de interfaz automatizada.

## Evidencia previa conservada en el historial del proyecto

- Flujo de préstamo favorable atravesó reserva RabbitMQ/Inventario y entrega, alcanzando `COMPLETADA` y descontando stock.
- Login ADMIN/registro CUSTOMER, ownership y denegación por rol se probaron contra APIs locales; petición ajena dio 403, token inválido 401.
- Repetición HTTP con igual clave/cuerpo devolvió el mismo préstamo; clave repetida con cuerpo distinto dio 409.

Los casos restantes se mantienen sin verificar en `PRUEBAS_ACEPTACION.md` y `MATRIZ_CUMPLIMIENTO.md`.
