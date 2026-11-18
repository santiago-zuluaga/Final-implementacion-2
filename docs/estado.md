# Estado de CrediMarket

Revisión: 18 de noviembre de 2026. La matriz detallada es [MATRIZ_CUMPLIMIENTO.md](MATRIZ_CUMPLIMIENTO.md); pruebas y limitaciones por cada uno de los 16 escenarios están en [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md). Este resumen diferencia implementación de verificación y no representa una afirmación de cumplimiento total.

## Material de partida

- Enunciado del profesor conservado en `docs/Enunciado_CrediMarket.docx`.
- Histórico: 12.000 filas × 15 columnas; SHA-256 `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd`.
- Solicitudes sin etiqueta: 200 × 14, reservadas para inferencia, equivalencia y drift descriptivo.

## Implementado

- Cuatro APIs de negocio FastAPI separadas, PostgreSQL con cuatro bases/roles lógicos, Redis, RabbitMQ, MLflow, frontend React/Nginx.
- Autenticación JWT y roles `ADMIN`/`CUSTOMER`, hash de password PBKDF2, protección de rutas administrativas e internas y consulta/editado restringido al cliente dueño. Las rutas de navegador están integradas con token; la inspección visual requiere un browser aprobado.
- Catálogo con cache-aside/invalidación/cotización de fuente de verdad; importación/upsert de clientes; creación idempotente de préstamos; outbox y máquina de estados; reserva atómica, movimientos, entrega y expiración.
- ML: split estratificado 60/20/20 con semilla fija; baseline y candidatos múltiples; selección por validación; MLflow, modelos versionados, promoción/rollback, endpoint de predicción y reporte PSI sin labels.
- Pruebas unitarias/ASGI de autenticación, seguridad básica y ML; script de equivalencia; seeder de demo.

## Verificado con evidencia disponible

- Compose completo arranca; PostgreSQL, Redis, RabbitMQ y cuatro APIs healthy. Frontend y MLflow están ejecutándose.
- Flujo de negocio integrado probado previamente: riesgo favorable, reserva en RabbitMQ/Inventario y entrega produjeron estado `COMPLETADA`; disponibilidad bajó en una unidad.
- Autorización integrada comprobada previamente: login ADMIN, cliente registrado, perfil propio 200, recurso ajeno 403, acción administrativa desde CUSTOMER 403, token inválido 401. Préstamo propio 200 y ajeno 403.
- Idempotencia HTTP comprobada previamente: mismo cuerpo/clave devolvió el mismo ID; mismo key con cuerpo distinto dio 409.
- Corrida actual: 11 tests aprobados; `npm run build` correcto; equivalencia 200 filas, cero mismatches, error máximo `2.22e-16`; seeder correcto; Redis miss/hit con muestra p50/p95 de 0.269 ms. No es un benchmark representativo.

## Pendiente antes de decir “100%”

- Casos formales pendientes: rechazo y sin stock, carrera por última unidad, duplicado de evento, recuperación ante caída de RabbitMQ/consumidor, cancelación/evento tardío/expiración, caída/TTL Redis, precio actualizado de extremo a extremo, importación CSV repetida y rollback de modelo confirmado por API.
- Medir cache fallback con Redis caído, además de CPU/memoria y latencias sobre carga representativa. Métricas de caché actuales son por proceso y memoria efímera.
- Validar UI visual/polling/formularios/errores en navegador. El acceso automatizado al origen `http://localhost:8080` fue denegado por la aprobación del origen; se respetó el bloqueo y no se usaron rutas alternativas.
- Revisar grants PostgreSQL y accesos cruzados con consultas de rol; revisar persistencia tras reinicio sin borrar volúmenes; verificar la topología retry/DLQ con fallo inyectado.
- El grupo debe completar nombres reales, responsabilidades e historial/contribuciones. La información de integrantes no está en los archivos disponibles y no se inventa.
- La guía de demo, decisión del broker, informe de pruebas y matriz ya existen; algunas evidencias que documentan son parciales y deben sustituirse por datos medidos al completar los casos.

## Seguridad y limitaciones

`.env` local está ignorado por Git. No publicar credenciales, JWT ni tokens internos. Las métricas, thresholds y resultados proceden de datos sintéticos y no son política de crédito. PSI sin etiquetas solo detecta cambios descriptivos de distribución; no permite concluir concept drift ni pérdida de desempeño.
