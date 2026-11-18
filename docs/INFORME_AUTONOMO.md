# Informe autónomo — CrediMarket

Fecha: 18 de noviembre de 2026.

## Resumen

Se avanzó desde un repositorio vacío hasta una primera implementación del ciclo ML, cuatro APIs de dominio independientes, interfaz React y configuración de despliegue. El enunciado original está en `docs/Enunciado_CrediMarket.docx`. El primer commit se publicó en GitHub; se publicarán avances adicionales una vez verificados.

## Arquitectura

Productos, Clientes, Préstamos e Inventario son procesos FastAPI separados, con una base PostgreSQL y un rol propio cada uno. Redis se usa en Productos. Préstamos e Inventario intercambian comandos/eventos versionados por RabbitMQ usando outbox y consumidores deduplicados. Préstamos carga el pipeline de ML promovido; MLflow usa SQLite y almacenamiento persistente de artefactos. React se sirve detrás de Nginx.

## Implementaciones completadas

- Preparación de datos reproducible, hash, división estratificada 60/20/20, baseline y siete candidatas, métricas y costos ficticios.
- Tracking de corridas en MLflow, exportación v1/v2 con manifiestos/hash y promoción explícita.
- API de riesgo en FastAPI y comparación de las 200 solicitudes sin etiqueta. Máximo error absoluto observado `2.22e-16` (tolerancia `1e-9`).
- Drift PSI descriptivo sobre las solicitudes sin etiqueta; no se registró feature por encima de 0,2.
- Cache-aside de catálogo con TTL 300 s, invalidación, cotización directa y endpoint de métricas.
- Persistencia por servicio, outbox de Préstamos/Inventario, idempotencia HTTP por clave, reserva atómica, liberación, expiración, cancelación y entrega.
- Interfaz de operaciones reales para catálogo, Clientes, solicitudes, inventario y consulta de modelo.
- Compose, Dockerfiles, README, contratos, diagramas, decisiones y guías.

## Pruebas y verificaciones

- `python -m compileall -q domain_service loan_service ml scripts tests`: correcto.
- `python -m pytest -q`: 7 pasaron. Un aviso de deprecación procede de Starlette/AnyIO.
- `npm ci && npm run build`: correcto.
- `npm audit --omit=dev --audit-level=moderate`: 0 vulnerabilidades de producción. El audit completo reporta alertas de desarrollo en la dependencia transitoria picomatch de Vite.
- `docker compose config --quiet`: correcto con `.env` local.
- Entrenamiento con MLflow Tracking server local: 16 corridas finalizadas y una corrida fallida identificada como `FAILED`.
- Equivalencia API/pipeline verificada en 200 filas para la API aislada y la ruta de inferencia del servicio de Préstamos (ASGI en proceso, sin DB); drift script ejecutado.

## Ejecución

Después de completar `.env` desde `.env.example`, la instrucción prevista es:

```powershell
docker compose up --build
```

URLs: frontend `http://localhost:8080`; APIs Swagger en `8001`–`8004`; MLflow `http://localhost:5000`; RabbitMQ Management `http://localhost:15672`.

## Pendientes y limitaciones

- Docker Engine no estaba activo/disponible, por lo que no se construyeron imágenes ni se levantó PostgreSQL, RabbitMQ, Redis, MLflow en Compose o frontend en contenedor.
- La topología RabbitMQ incluye reintentos con TTL y DLQ, pero no ha sido probada con el broker real.
- El stack compuesto de servicios no se probó con DB/broker/cache. La equivalencia de `domain_service.app` se hizo localmente sin ejecutar el startup de DB; falta repetirla dentro del contenedor Compose.
- Autenticación/autorización JWT, ownership de préstamos, sesiones y rutas administrativas protegidas pendientes.
- No hay historial de transiciones separado, migraciones versionadas ni pruebas de aceptación 1–16. Falta auditoría de idempotencia bajo concurrencia real.
- La UI mantiene las solicitudes de la sesión actual, no hay listado histórico autenticado.
- El profesor todavía debe completar los integrantes reales en README.

## ML y modelo

Dataset SHA-256 `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd`. Modelo v1: regresión logística con AP validación `0.520`, umbral `0.305` y ROC-AUC test `0.697`. Precision clase 1 test `0.345`, recall `0.909`, F1 `0.500`, AP `0.532`, Brier `0.216`. La decisión de umbral usa costos exclusivamente ficticios (5 falso aprobado, 1 falso rechazo). No es una política aplicable a crédito real.

## Próximas tareas

1. Activar Docker Engine y corregir cualquier error de build o integración.
2. Verificar flujo de préstamo, reservas concurrentes, duplicados, cancelación/evento tardío y vencimiento.
3. Proteger APIs con roles y añadir listados históricos propios.
4. Ejecutar las 16 pruebas de aceptación, caída de Redis/RabbitMQ y métricas p50/p95 reales.
5. Probar DLQ/retry, rollback cargando de nuevo Préstamos, y frontend de errores/sesión.
6. Confirmar nombres de integrantes, completar la decisión del broker a 1–2 páginas y actualizar este informe.
