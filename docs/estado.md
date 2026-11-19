# Estado de CrediMarket

Revisión: 18 de noviembre de 2026. La matriz detallada es [MATRIZ_CUMPLIMIENTO.md](MATRIZ_CUMPLIMIENTO.md); pruebas y límites de los 16 casos están en [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md). El trabajo sigue en curso y no se presenta como cumplimiento del 100%.

Conteo vigente calculado desde la matriz: 57/72 requisitos `VERIFICADO` (79,2%), 15 `IMPLEMENTADO_NO_VERIFICADO`, 0 `BLOQUEADO`; entre los obligatorios, 56/71 verificados (78,9%). Aceptación: 13/16 aprobados; ACC-14–16 siguen pendientes de interfaz visual.

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
- Aceptación: stock insuficiente, carrera por última unidad, idempotencia HTTP concurrente, cancelación/evento tardío/vencimiento, importación CSV, promoción/rollback y equivalencia probados. Resultado actual: 13/16; tres requieren validación UI real.
- ML con split 60/20/20 seed 42, baseline + siete candidatas; v1 `logreg_c1` seleccionado por validación, threshold ~0.305. Equivalencia en 200 filas: mismatches 0, error máximo `2.22e-16`.
- Modalidad individual: Santiago Zuluaga Correa es el único autor y asume arquitectura, backend, frontend, ML, MLOps, infraestructura, integración, pruebas y documentación. El README y la matriz anotan que el texto genérico del enunciado habla de grupos.
- MLflow Model Registry registra v1/v2 por `run_id`; el alias `champion` sigue las promociones/rollback junto al puntero local y la API.
- Validaciones API de Préstamos probaron límites de esquema/monto y rechazo por perfil inactivo, ingreso cero y plazo inválido; el servicio interno ahora puede consultar perfil inactivo para aplicar el rechazo correcto.
- Timeout real de 2 minutos probado con RabbitMQ caído: solicitud llegó a `CANCELACION_PENDIENTE`; tras recuperarlo terminó cancelada, reserva liberada y stock restaurado.
- Redis: misses/hits, expiración, fallback con Redis detenido y recuperación probados. Benchmark y snapshots de recursos están en [`INFORME_REDIS.md`](INFORME_REDIS.md) y `artifacts/redis_benchmark.json`.
- `pytest -q`: 34 passed, 1 aviso de deprecación; filtro de pruebas frontend no FE-01: 9 passed; `npm run build` correcto. Los servicios Docker reportaron healthy y los cuatro health proxies dieron 200.
- ARQ-05: verificado técnicamente y con validación visual reportada por Santiago (ADMIN/CUSTOMER, lecturas/persistencia, préstamo/detalle, estado de modelo y riesgo dinámico). La validación visual se atribuye al usuario y no se presenta como inspección de Codex.
- PostgreSQL restart conservó el catálogo y permitió login ADMIN; RabbitMQ conservó una publicación persistente en cola durable tras restart.
- MLflow reiniciado de forma aislada conservó 17/17 IDs de corrida y 137 archivos de artefactos que ya existían. La auditoría del run seleccionado confirma métricas train/validación/test; los intentos fallidos quedan visibles en tracking.
- `scripts/acceptance_model_promotion.py` observó v2 y después v1 desde `/modelo/info` tras reiniciar Préstamos; modelo v1 queda activo. La equivalencia fue repetida tras el entrenamiento.

## Pendientes antes de completar

- Casos 14–16: validar flujo real desde la interfaz, polling de estado, formularios/errores y sesión vencida en navegador. El permiso guardado del navegador integrado rechazó `http://localhost:8080`; no se intentó otra superficie ni una vía indirecta.
- ARQ-03, IDEM-01/02, ML-08, API-02, DOC-01 y DEV-01 están verificados con evidencia registrada. Quedan 15 requisitos `IMPLEMENTADO_NO_VERIFICADO`: DRIFT-01, API-01, FE-02/03/04/05/07, QA-01/02, DEV-02, DOC-03/04 y ACC-14/15/16. No hay bloqueados.
- Los 3 casos UI pendientes requieren inspección manual o una herramienta de navegador autorizada para `http://localhost:8080`; el permiso guardado del navegador integrado denegó el origen. Se hicieron verificaciones alternativas de API/helpers/build sin confundirlas con pruebas gráficas.

## Límites

Las métricas, ejemplos, datos y umbral de riesgo son sintéticos. PSI sin etiquetas describe cambios de distribución; no permite concluir concept drift ni caída del desempeño. Los resultados de caché y Docker son muestras locales, no una garantía de producción.
