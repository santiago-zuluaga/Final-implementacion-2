# Estado verificado del proyecto

Fecha de revisión: 18 de noviembre de 2026.

## Material de partida disponible

- Enunciado original copiado a `docs/Enunciado_CrediMarket.docx`.
- Histórico real del curso: 12.000 × 15; hash SHA-256 `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd`.
- Solicitudes sin etiqueta: 200 × 14. Se usa solo para inferencia, equivalencia y drift descriptivo.
- El repositorio original estaba vacío y no tenía remoto local configurado. Se inicializó Git, se enlazó el URL solicitado y se publicó el primer commit.

## Implementado y comprobado

- Entrenamiento estratificado 60/20/20, semilla 42, baseline y siete candidatas de cuatro algoritmos; pipeline de imputación/codificación/escalado dentro del estimador.
- Selección predefinida por AP de validación, desempate ROC-AUC; umbral por costos didácticos 5/1 sobre validación; test solo para la selección final.
- Dieciséis ejecuciones finalizadas en un tracking server MLflow local persistente; una corrida fallida quedó identificada como FAILED. Modelo v1 con manifiesto/hash y v2 candidata de validación; promoción v2→v1 probada.
- API FastAPI de riesgo carga un modelo promovido; equivalencia local/API en las 200 solicitudes: error absoluto máximo `2.22e-16`, dentro de `1e-9`.
- PSI de las 200 solicitudes comparado con entrenamiento; ninguna feature supera 0,2. Esto no mide capacidad predictiva porque no hay etiqueta.
- APIs en un código compartido desplegadas por separado: CRUD de Productos con Redis cache-aside y cotización directa de BD; Clientes con upsert e importación CSV; Préstamos con precio/version capturados, modelo, idempotency key, outbox, estados y timeout; Inventario con reserva atómica, movimiento, liberación, entrega, outbox y expiración.
- Frontend React/TypeScript operativo para catálogo y edición/desactivación, registro/importación de clientes, solicitud con clave retenida, seguimiento por polling, registro de existencias, entrega/cancelación y modelo.
- Compose describe PostgreSQL (cuatro bases/roles), RabbitMQ, Redis, MLflow y cuatro APIs más Nginx/React.
- `python -m compileall -q domain_service loan_service ml tests`: correcto.
- `python -m pytest -q`: 7 passed (un aviso de deprecación en Starlette/AnyIO).
- `npm ci && npm run build`: correcto en Windows y en `node:24-slim` (Debian) durante la construcción de Docker. `node:24-alpine` fallaba al procesar `react-dom/client.js`; se fijó el stage de build a Debian slim.
- `npm audit --omit=dev --audit-level=moderate`: 0 vulnerabilidades de producción.
- `docker compose config --quiet`: correcto con `.env` local. `docker compose up --build -d` construyó y levantó todos los servicios.

## Integración verificada en Docker

- Docker Desktop está activo. PostgreSQL, Redis, RabbitMQ y las cuatro APIs reportaron estado saludable; MLflow y frontend/Nginx quedaron ejecutándose.
- El flujo probado en contenedores incluyó alta de cliente, catálogo/consulta, evaluación de riesgo, evento de reserva, entrega y estado final `COMPLETADA`; el inventario disminuyó de 5 a 4 unidades disponibles.
- Equivalencia contra el endpoint del servicio de Préstamos con las 200 solicitudes: cero diferencias por encima de tolerancia (`2.22e-16` de máximo error absoluto).
- Nginx sirvió la interfaz en `http://localhost:8080` y el proxy `/api/products`.
- Se corrigió el filtro opcional de Productos: PostgreSQL rechazaba comparar un parámetro nulo sin tipo. La consulta solo añade `ILIKE` cuando se recibe `q`.

La ruta del flujo feliz está comprobada; faltan pruebas de fallos de broker para retries/DLQ, carrera de idempotencia, cancelación/expiración y dependencias no disponibles.

## Pendiente obligatorio o de alto impacto

- Reintentos limitados (3, con cola TTL de 5 segundos) y dead letter queue implementados; falta forzar errores y confirmar los reintentos con el broker real.
- Seguridad/autorización (JWT o equivalente), cuentas, sesión expirada y restricción de préstamos ajenos. La autenticación es opcional en la descripción, pero la rúbrica exige roles para aspirar al mejor nivel.
- Vistas persistentes de préstamos propias (la UI conserva solicitudes de la sesión actual); controles completos de búsqueda y detalle.
- Idempotencia HTTP bajo carreras concurrentes debe validarse con PostgreSQL; errores de API y contraejemplos de mensajes deben probarse.
- Pruebas de aceptación 1–16 y resiliencia con broker/Redis/PostgreSQL detenidos.
- MLflow en Compose, registro de V2, dashboard de promoción y rollback mediante reinicio del servicio; Drift endpoint/UI.
- Historial explícito de transiciones del préstamo en persistencia; actualmente solo se guarda el estado y el motivo vigente.
- Migraciones versionadas, CI, guía de demo con productos/stock inicial y nombres reales de los integrantes.
- La decisión sobre broker ocupa menos de las 1–2 páginas solicitadas y debe ampliarse con evidencia tras probar DLQ/retries.

## Riesgo de dependencia

`npm audit --omit=dev` reporta 0 problemas de producción. El audit completo identifica 4 alertas de severidad alta ligadas a `picomatch` dentro de la toolchain de Vite de desarrollo/build. La app desplegada es el bundle estático servido por Nginx; el issue no está en runtime del navegador. Revisar el upstream antes de actualizar.
