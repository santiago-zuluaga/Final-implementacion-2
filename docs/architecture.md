# Arquitectura actual

## Servicios

`domain_service/app.py` se despliega como cuatro procesos/contenedores independientes con `SERVICE=products|customers|loans|inventory`. Cada despliegue usa su propia base de datos PostgreSQL y rol restringido. Los servicios solo se comunican por HTTP o RabbitMQ; no consultan bases de datos ajenas.

```mermaid
flowchart LR
  W[React / Nginx] --> P[Productos]
  W --> C[Clientes]
  W --> L[Préstamos + modelo]
  W --> I[Inventario]
  P --> R[(Redis)]
  L -->|HTTP cliente + cotización vigente| C
  L -->|HTTP| P
  L -->|outbox / comando| Q[(RabbitMQ)]
  Q --> I
  I -->|outbox / evento| Q
  Q --> L
  P --> DB1[(Postgres cm_products)]
  C --> DB2[(Postgres cm_customers)]
  L --> DB3[(Postgres cm_loans)]
  I --> DB4[(Postgres cm_inventory)]
  M[MLflow] --> DB5[(SQLite persistente + artefactos)]
```

## Flujo y estados

1. Préstamos obtiene cliente y cotización directamente de sus APIs. Calcula cuota francesa con 1,8 % mensual, construye las mismas features del entrenamiento y ejecuta el pipeline cargado al iniciar.
2. Una evaluación desfavorable se persiste en `RECHAZADA`; una favorable se persiste en `PENDIENTE_INVENTARIO` junto a `ReservaSolicitada` en outbox, antes de contestar 202.
3. El consumidor de Inventario reserva mediante un `UPDATE ... WHERE available >= quantity` dentro de una transacción. Reserva por `loan_id` único evita el doble efecto.
4. Inventario deja `InventarioReservado`/`InventarioInsuficiente` en su outbox. Préstamos deduplica por `event_id` y actualiza el estado en la misma transacción local.
5. Préstamos vence pendientes a los 2 minutos, el inventario vence reservas a los 30 minutos. Cancelar genera un comando de liberación; la confirmación tardía no modifica estados terminales.

Estados principales: `RECHAZADA`, `PENDIENTE_INVENTARIO`, `APROBADA`, `CANCELADA_SIN_STOCK`, `CANCELACION_PENDIENTE`, `CANCELADA`, `COMPLETADA`. La reserva es la fuente de verdad para aprobar y entregar.

## Redis

Productos usa `productos:v1:{id}`, TTL de 300 segundos. Un hit se responde desde Redis; miss consulta PostgreSQL y llena el caché. Actualizar/desactivar confirma primero PostgreSQL y luego invalida. Fallo de Redis cae a la BD con timeout de socket de 200 ms. `/cache/metrics` publica hits, misses, fallback, tasa de aciertos, p50 y p95 del proceso actual. `/products/{id}/quotation` lee siempre la BD.

## Límites que siguen pendientes

No hay login ni autorización por usuario; los roles administrativos aún no están protegidos por JWT. La entrega/cancelación carece de autorización de administrador. RabbitMQ tiene publisher confirms, outbox, colas durables y consumidores idempotentes; aún falta configurar reintentos limitados y DLQ con evidencia. No hay migraciones versionadas; las tablas se crean al iniciar. La UI es real pero todavía no presenta controles para crear producto, registrar stock, entregar o cancelar. Estos puntos están también en `estado.md`.
