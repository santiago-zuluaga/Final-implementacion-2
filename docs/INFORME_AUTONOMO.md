# Informe de avance — CrediMarket

**Corte:** 18 de noviembre de 2026. **Fuente normativa:** [`Enunciado_CrediMarket.docx`](Enunciado_CrediMarket.docx).

## Estado

La solución implementa los cuatro dominios, su integración y los artefactos principales. Hay 72 requisitos trazados: 71 obligatorios y 1 recomendado. Están verificados 46/71 obligatorios (64,8%) y 47/72 al contar también el recomendado (65,3%). De los 16 casos de aceptación, 13 están verificados. No se presenta como cumplimiento del 100%.

| Categoría | Requeridos | Implementados | Verificados | Pendientes |
|---|---:|---:|---:|---:|
| Requisitos obligatorios | 71 | 71 | 46 | 25 sin verificación, 0 bloqueados |
| Requisito recomendado | 1 | 1 | 1 | 0 |
| Total trazado | 72 | 72 | 47 | 25 sin verificación, 0 bloqueados |

El conteo sale de las 72 filas de la matriz: 47 `VERIFICADO`, 25 `IMPLEMENTADO_NO_VERIFICADO` y 0 `BLOQUEADO`. El porcentaje obligatorio es 46/71 = 64,8%; el total que incluye el requisito recomendado es 47/72 = 65,3%. “Implementados” suma los verificados y los implementados que aún requieren evidencia. TEAM-01 refleja la modalidad individual indicada por Santiago; el texto genérico del enunciado §2 describe equipos de hasta cuatro.

## Arquitectura y operación

Productos, Clientes, Préstamos e Inventario son APIs FastAPI independientes, cada una con base y rol PostgreSQL propios. Se revocó `CONNECT` público a las cuatro bases y se verificaron denegaciones cruzadas. Préstamos consulta Clientes/Productos por APIs internas autenticadas. RabbitMQ transporta comandos/eventos persistentes; Préstamos e Inventario usan outbox y deduplicación. Redis opera cache-aside en Productos. React se sirve desde Nginx con proxy de API. MLflow conservó tracking y artefactos tras restart (17/17 IDs preexistentes); RabbitMQ conservó una publicación persistente en una cola durable después de reiniciarse.

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
- Entrenamiento repetido: 32 corridas `FINISHED` y 2 `FAILED` conservadas; auditoría del run v1 valida metadatos, métricas train/validación/test y artefactos (`artifacts/mlflow_audit.json`). Los dos fallos de esta sesión quedan identificados en el registro de ejecución.
- Promoción y rollback después del reentrenamiento: API devolvió v2 y luego v1 después de reinicios; equivalencia v1 volvió a pasar en 200 solicitudes.
- Persistencia RabbitMQ: la prueba leyó la publicación persistente antes y después del restart; eliminó la cola temporal al terminar.
- MLflow Registry: las promociones v2/v1 movieron el alias `champion` entre versiones y run_ids correspondientes; API de Préstamos y alias coincidieron tras restart.
- Validaciones integradas: se corrigió el acceso interno a perfiles inactivos, que antes impedía devolver `CLIENTE_INACTIVO`; el script comprobó 422 de esquema/monto, rechazo por cliente inactivo/ingreso cero/plazo inválido y ausencia de reservas.
- Timeout real: con RabbitMQ parado, el worker venció la solicitud pendiente a los dos minutos; al reanudarlo se liberó la reserva y el stock quedó íntegro.
- En el polling de la interfaz, un fallo de consulta ahora genera un mensaje visible y la respuesta exitosa lo limpia. El build final y la suite pasaron; los servicios Compose permanecen activos y la equivalencia v1/API se repitió en 200 filas (0 diferencias relevantes, error máximo `2.22e-16`).

## Pendientes y límites

- Aceptación 14, 15 y 16 requieren comprobar el flujo visual desde frontend, polling de estado, expiración/mensajes y errores de API. El navegador integrado rechazó `http://localhost:8080` por una configuración guardada de permisos; no se usó otro navegador ni una vía indirecta.
- TEAM-01 quedó documentado para la modalidad individual: Santiago Zuluaga Correa es el único autor/integrante y asume arquitectura, backend, frontend, ML, MLOps, infraestructura, integración, pruebas y documentación. El enunciado genérico se refiere a grupos; se conserva esa diferencia en la matriz.
- Siguen pendientes 25 requisitos implementados sin verificación completa. La auditoría detectó que los cuatro OpenAPI enumeran las mismas 27 rutas; se requiere documentar/exponer correctamente las rutas por dominio y verificar guardas. También siguen pendientes reproducción desde clon limpio y verificación visual del frontend.
- El entrenamiento completó, con avisos de compatibilidad de opciones del solver de scikit-learn y detección de núcleos físicos de joblib en Windows; no se ocultaron los avisos ni impidieron producir artefactos.

## Reproducción

Consulta [README.md](../README.md), [GUIA_DEMO.md](GUIA_DEMO.md) y [testing.md](testing.md). Para la matriz completa, criterios exactos y resultados por caso, usa [MATRIZ_CUMPLIMIENTO.md](MATRIZ_CUMPLIMIENTO.md) y [PRUEBAS_ACEPTACION.md](PRUEBAS_ACEPTACION.md).
