# Decisiones técnicas

## Mensajería: RabbitMQ

Se eligió RabbitMQ sobre Kafka para la integración entre Préstamos e Inventario. El escenario descrito es de bajo volumen (decenas de solicitudes por minuto como máximo en la demo), dos dominios con productores/consumidores conocidos y comandos que esperan una respuesta de negocio. RabbitMQ ofrece colas de trabajo, confirmación de publicación, ACK y dead lettering directamente. Kafka sería mejor si se requiriera alto caudal, retención larga, replay de muchos consumidores independientes o análisis de streams. No se estima throughput de producción a partir de esta demo.

El exchange durable `credimarket.commands` (direct) enruta `reserva.solicitar` y `reserva.liberar`; `credimarket.events` (topic) publica los resultados de Inventario para Préstamos. Los mensajes son persistentes y se usa publisher confirm. Las colas y bindings se declaran al iniciar los consumidores. Cada sobre incluye `event_id`, tipo, versión de esquema, fecha, correlación, préstamo y payload mínimo; nunca viajan datos de ingresos, obligaciones ni historial crediticio.

Préstamos e Inventario escriben cambios de dominio y su outbox en la misma transacción PostgreSQL. Un relay publica filas no enviadas y marca `published_at` después del confirm. Una caída entre el confirm y la marca puede duplicar el envío; por ello el consumidor registra `event_id` con clave única en la misma transacción que su efecto local. Esto ofrece entrega al menos una vez con efecto idempotente, no exactly-once distribuido. El consumidor ACKea el mensaje únicamente al completar su transacción. Los fallos transitorios usan una cola retry con TTL de 5 s y dead-letter de regreso a la cola original; tras tres reintentos se envía al DLQ para inspección. Una prueba con violación de constraint dentro de la transacción confirmó tres reintentos, llegada a DLQ y rollback sin cambios en stock/movimientos/outbox (`scripts/acceptance_retry_dlq.py`).

### Supuestos y respuesta a las preguntas de selección

- **Volumen:** el entorno académico y la demo suponen decenas de solicitudes por minuto, no una carga de producción. Hay un consumidor de comandos en Inventario y uno de eventos en Préstamos.
- **Retención y replay:** las colas principales mantienen comandos pendientes mientras no se confirmen; los mensajes ACKeados se eliminan. Los DLQ retienen fallos para inspección. No se requiere reproducir todo el histórico; la auditoría está en PostgreSQL (outbox y movimientos). No hay un replay masivo automatizado.
- **Orden:** RabbitMQ conserva el orden de entrada por cola; Inventario consume con prefetch 1. El flujo no depende de un orden global entre préstamos distintos. Para cada préstamo, el consumidor serializa la actualización transaccional y la máquina de estados ignora eventos tardíos que no son válidos para el estado actual.
- **Fallos y duplicados:** outbox duradero + publisher confirms cubren el corte de disponibilidad. Hay retry de 5 s, tres reintentos y DLQ; el efecto local y el registro de `event_id` son idempotentes. La semántica es al menos una vez, no exactly-once.
- **Costo y operación:** ambas opciones son software abierto y sin tarifa por mensaje en esta instalación; Kafka exige operar un log distribuido y retención/particiones, mientras que RabbitMQ cubre el patrón de cola con menos componentes para el equipo y la carga esperados. No se comparan costos de nube porque no hay despliegue cloud presupuestado.
- **Cuándo cambiar:** si mediciones bajo carga representativa muestran caudal sostenido fuera de la capacidad operativa, si varios consumidores necesitan replay independiente o si la retención analítica deja de caber en las tablas/outbox, volver a evaluar Kafka. Los umbrales numéricos deben fijarse con una prueba de carga acordada, no inferirse de la demo.

## Datos, caché y servicios

Los cuatro dominios se ejecutan en contenedores FastAPI independientes y cada uno usa una base lógica y rol PostgreSQL propios. Se comparte infraestructura PostgreSQL local para reducir recursos; ningún servicio debe consultar directamente tablas ajenas. Clientes es dueño de identidad/perfil, Productos de catálogo/cotización, Préstamos de solicitud/decisión y del artefacto ML, e Inventario de stock/reservas/movimientos. Préstamos consulta clientes y cotizaciones mediante APIs internas autenticadas.

Productos implementa cache-aside en Redis, clave `products:v1:{id}` y TTL de 300 s. Las escrituras invalidan la clave; la cotización de un préstamo consulta el endpoint de fuente de verdad y evita reutilizar un precio cacheado. Si Redis falla, la lectura puede continuar desde PostgreSQL. Las métricas `hits`, `misses`, `fallbacks`, hit rate y latencias p50/p95 se exponen en `/cache/metrics` para ADMIN. Las métricas actuales viven en memoria del proceso, por lo que se reinician al desplegar y no son un histórico de observabilidad.

## ML y política de demostración

El pipeline usa selección por Average Precision de validación con ROC-AUC para desempatar. El umbral se determina con costos didácticos 5:1 usando validación; el test se reserva para la evaluación final. v1 es el champion inicial y v2 es una candidata seleccionada con validación. La API carga el puntero de modelo al arrancar, verifica SHA-256 y expone la versión. Este umbral y los datos son sintéticos: no constituyen política de crédito real ni asesoría financiera.

## Interfaz y acceso

Nginx sirve el bundle React y proxifica las APIs. JWT distingue `ADMIN` y `CUSTOMER`; el backend verifica propiedad del perfil y de cada préstamo, no confía en el ocultamiento de controles de la UI. El secreto JWT, token interno y credenciales de administración se configuran en `.env`, que queda fuera del repositorio.
