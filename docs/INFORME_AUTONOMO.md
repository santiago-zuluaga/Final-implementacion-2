# Informe de avance — CrediMarket

**Corte:** 18 de noviembre de 2026. **Fuente normativa:** [`Enunciado_CrediMarket.docx`](Enunciado_CrediMarket.docx).

## Estado

La solución implementa los cuatro dominios, su integración y los artefactos principales. La verificación actual cubre 41 de 72 requisitos trazados y 13 de 16 casos de aceptación; no se presenta como un cumplimiento del 100%. La [matriz de cumplimiento](MATRIZ_CUMPLIMIENTO.md) y el [registro de pruebas](PRUEBAS_ACEPTACION.md) muestran cada requisito y su evidencia.

## Arquitectura y operación

Productos, Clientes, Préstamos e Inventario son APIs FastAPI independientes, cada una con base y rol PostgreSQL propios. Se revocó `CONNECT` público a las cuatro bases y se verificaron denegaciones cruzadas. Préstamos consulta Clientes/Productos por APIs internas autenticadas. RabbitMQ transporta comandos/eventos persistentes; Préstamos e Inventario usan outbox y deduplicación. Redis opera cache-aside en Productos. React se sirve desde Nginx con proxy de API; MLflow está configurado con volúmenes persistentes; la supervivencia de tracking y artefactos tras reinicio sigue pendiente de prueba.

JWT protege operaciones administrativas e internas con roles `ADMIN` y `CUSTOMER`, y las consultas de perfil/préstamos comprueban propiedad. Los valores secretos viven en `.env`; auditoría verificó que el archivo y los secretos locales no están en Git.

## Datos y modelo

El histórico contiene 12.000 filas × 15 columnas y SHA-256 `c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd`; las solicitudes nuevas tienen 200 × 14 y no incluyen etiqueta. La auditoría reproducible y el [diccionario de datos](DICCIONARIO_DATOS.md) documentan tipos, rangos, faltantes, duplicados, clase, unidades, IDs y exclusiones.

El pipeline usa partición estratificada 60/20/20 con semilla 42, imputación/codificación/escalado dentro del estimador, baseline y siete candidatas. Selección por Average Precision de validación, desempate por ROC-AUC; el umbral de demostración usa costos ficticios 5:1 en validación. Champion v1 es `logreg_c1`, umbral aproximado 0,305, ROC-AUC test 0,697, AP test 0,532 y Brier test 0,216. La prueba no se usa para seleccionar la segunda versión. v2 se promocionó y se hizo rollback a v1; `/modelo/info` confirmó ambas versiones después de reinicios.

La equivalencia local/API en las 200 solicitudes tuvo cero mismatches y error absoluto máximo `2.22e-16` (tolerancia `1e-9`). PSI descriptivo no superó 0,2 en ninguna feature; al no tener etiquetas, no se concluye concept drift ni degradación predictiva. Estos datos y umbrales son sintéticos y no representan política de crédito real.

## Verificaciones recientes

- `pytest -q`: 13 aprobados; incluye roles, ownership, JWT vencido y rechazo de token interno incorrecto.
- Build frontend TypeScript/Vite correcto.
- Compose completo healthy; reinicio de PostgreSQL conservó el catálogo y el login ADMIN.
- Caché: 30 misses p50/p95 4,303/6,290 ms y 200 hits 1,743/2,991 ms. Prueba separada de caída mantuvo respuestas desde PostgreSQL y recuperación miss/hit; snapshots CPU/memoria y límites están en [INFORME_REDIS.md](INFORME_REDIS.md).
- Casos de aceptación con scripts: sin stock, carrera por la última unidad, idempotencia HTTP/eventos, cotización actualizada, recuperación por caída de broker/consumidor, cancelación/evento tardío/expiración y retry/DLQ.
- Importación del mismo CSV sintético dos veces: primera inserción, segunda actualización, sin duplicar perfil.

## Pendientes y límites

- Aceptación 14, 15 y 16 requieren comprobar el flujo visual desde frontend, polling de estado, expiración/mensajes y errores de API. El acceso del navegador a `http://localhost:8080` fue denegado por la autorización del origen en esta sesión; se respetó el bloqueo y no se usó una vía alternativa.
- El grupo debe aportar nombres reales y contribuciones para completar la tabla académica; esos datos no estaban en los archivos disponibles y no se inventaron.
- Siguen pendientes 30 requisitos de la matriz con implementación sin verificación completa y uno bloqueado. Entre ellos hay persistencia MLflow tras reinicio, validación exhaustiva de errores/API y timeout de una solicitud que permanezca pendiente.

## Reproducción

Consulta [README.md](../README.md), [GUIA_DEMO.md](GUIA_DEMO.md) y [testing.md](testing.md). Para la matriz completa, criterios exactos y resultados por caso, usa [MATRIZ_CUMPLIMIENTO.md](MATRIZ_CUMPLIMIENTO.md) y [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md).
