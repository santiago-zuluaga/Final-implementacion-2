# Pruebas de aceptación

Fuente de los casos: sección 12 del enunciado del profesor. El estado refleja ejecución con evidencia; una ruta existente o revisión de código no basta para marcar un caso aprobado. Fecha de evidencia: 2026-11-18.

## Comandos de regresión ejecutados

| Verificación | Resultado | Evidencia |
|---|---|---|
| Aislamiento PostgreSQL | Correcto | `has_database_privilege` comprobó CONNECT propio en cada una de las cuatro bases y denegó los 12 pares rol/base cruzados. Se revocó CONNECT de PUBLIC y se agregó al init para clústeres nuevos. |
| `python -m pytest -q` | 11 passed, 1 aviso deprecado | Unitarias/ASGI: hashes y JWT, autorización básica, aislamiento de solicitudes por propietario, pipeline de riesgo. |
| `npm --prefix frontend run build` | Correcto | TypeScript y Vite produjeron bundle. |
| `python ml/equivalence.py` | Correcto | 200 solicitudes, mismatch 0, error absoluto máximo `2.220446049250313e-16`, tolerancia `1e-9`, modelo `v1`. |
| `python scripts/seed_demo.py` | Correcto | Productos 1–3 disponibles; script no resetea stock existente. |
| Redis miss/hit en Docker | Correcto | Clave del producto 1 eliminada y consultada dos veces: hits 1, misses 1, fallbacks 0; hit rate 0.5; p50/p95 observados 0.269 ms en esa corrida. Muestra de demo, no benchmark. |
| Promoción y rollback V2/V1 | Correcto | `ml/promote.py v2`, reinicio de Préstamos, `/modelo/info` devolvió v2; rollback a v1, reinicio, `/modelo/info` devolvió v1. Puntero quedó en v1. |
| `git diff --check` | Correcto | Sin errores de whitespace. |

El acceso de navegador a `http://localhost:8080` fue denegado por la aprobación del origen de la herramienta; no se intentó ningún camino alternativo de navegador. La interfaz compila y el proxy API funciona, pero los criterios visuales y el flujo UI real quedan sin comprobar.

## Casos del enunciado

| # | Caso | Resultado actual | Evidencia/pendiente |
|---:|---|---|---|
| 1 | Riesgo favorable con stock y entrega | Parcialmente comprobado antes: reserva y entrega integrada finalizaron `COMPLETADA`. | Formalizar repetición como script y guardar evidencia identificada sin exponer datos personales. |
| 2 | Riesgo desfavorable sin reserva | No verificado como caso de aceptación formal. | Crear solicitud que resulte rechazada, comprobar que no se publica reserva y que el registro conserva score/modelo/motivo. |
| 3 | Riesgo favorable sin stock | No verificado. | Agotar stock y comprobar `CANCELADA_SIN_STOCK`, stock nunca negativo. |
| 4 | Dos solicitudes por última unidad | No verificado. | Prueba concurrente real contra PostgreSQL; exactamente una reserva. |
| 5 | Petición/evento repetido | HTTP idempotency comprobado manualmente: misma clave/cuerpo devuelve mismo ID y clave/cuerpo distinto 409. Dedupe de evento no verificado mediante inyección duplicada. | Automatizar persistencia y comparar movimientos/eventos. |
| 6 | Caída de consumidor/broker y recuperación | No verificado. | Detener RabbitMQ ante operación aceptada, reiniciar, comprobar outbox y efecto único. |
| 7 | Cancelación y evento tardío/expirado | No verificado. | Forzar secuencia tardía y expiración; probar que no reactiva estado terminal y se libera stock. |
| 8 | Redis vacío, expirado y caído | Miss/hit medidos; TTL 300s en código. Expiración y caída/fallback no probados. | Medir con pausa mayor a TTL y detener Redis brevemente controlando recuperación. |
| 9 | Cambio de precio invalida cache y préstamo usa nuevo precio | No verificado extremo a extremo. | Cambiar versión/precio y confirmar cache invalidada y cotización persistida. |
| 10 | Modelo exportado equivalente a API | Aprobado. | Corrida de equivalencia: 200/200, mismatch 0, max error `2.22e-16`, modelo v1. |
| 11 | Promoción/rollback de modelo | Parcial. | Se comprobó cambio de puntero antes; falta comprobar V2 en API después de reiniciar y rollback a V1 en API. |
| 12 | Importar CSV dos veces sin duplicar | No verificado esta corrida. | Comparar conteos y resumen de filas de la API tras dos importaciones. |
| 13 | Cliente no ve préstamos ajenos | Aprobado por prueba manual de API previa: dueño 200, ajeno 403; unitarias verifican solicitud ajena 403. | Conservar el resultado reproducible de integración al ejecutar la suite completa. |
| 14 | Operación del negocio desde frontend | No verificado por navegador. | La aprobación del origen local fue denegada; requiere validación manual de la interfaz en demo. |
| 15 | UI refleja transición asíncrona | Backend se probó en flujo feliz previo; UI no verificada visualmente. | Confirmar polling desde frontend contra el broker real. |
| 16 | Formularios/expiración/API caída con mensaje y recuperación | No verificado completo. | Probar expiración de JWT, formularios inválidos y API/broker desconectados desde UI. |

## Criterio para cerrar

Cada caso necesita comando/script reproducible, precondiciones, resultado esperado y resultado observado. Los escenarios destructivos de broker/Redis deben ejecutarse con datos de demo identificados y restaurar los contenedores al terminar. No afirmar “16/16” mientras los casos parciales o no verificados sigan abiertos.
