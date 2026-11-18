# Contratos y broker

Broker: RabbitMQ con exchange durable directo `credimarket.commands` y exchange durable tipo topic `credimarket.events`. Mensajes persistentes y publisher confirms. Las colas son durables. Asume pocos comandos por minuto, un consumidor de inventario y un consumidor de eventos de préstamos; RabbitMQ encaja mejor con el trabajo punto a punto que Kafka.

La fuente durable de publicación es Outbox en la base local de cada servicio. El relay publica y marca `published_at`; un fallo entre confirmación y marca puede duplicar publicación, por lo que los consumidores deduplican por `event_id` y restricciones únicas. No se afirma entrega exactly-once.

## Enrutamiento y recuperación

| Clase | Exchange | Routing key |
|---|---|---|
| `ReservaSolicitada` | `credimarket.commands` | `reserva.solicitar` |
| `LiberarReserva` | `credimarket.commands` | `reserva.liberar` |
| `InventarioReservado` | `credimarket.events` | `inventario.reservado` |
| `InventarioInsuficiente` | `credimarket.events` | `inventario.insuficiente` |
| `ReservaLiberada` | `credimarket.events` | `inventario.liberada` |
| `ReservaVencida` | `credimarket.events` | `inventario.vencida` |
| `SalidaConfirmada` | `credimarket.events` | `inventario.salida_confirmada` |

## Ejemplo

```json
{
  "event_id": "uuid",
  "type": "ReservaSolicitada",
  "schema_version": 1,
  "occurred_at": "2026-11-18T12:00:00Z",
  "correlation_id": "loan-uuid",
  "prestamo_id": "loan-uuid",
  "payload": {"producto_id": 4, "cantidad": 1}
}
```

No se publican ingresos ni otros datos financieros. El enunciado pide retención/replay como parte de la decisión del broker: no se requiere replay de eventos porque las bases y tablas de movimientos/outbox son la auditoría. Los supuestos de retención y replay están desarrollados en `decisions.md`.

Comandos y eventos usan colas durables con DLX. Los errores de procesamiento hacen NACK sin requeue; una cola de retry aplica 5 segundos de TTL y dead-letters de vuelta a la cola original. Tras tres reintentos, el consumidor publica al DLQ correspondiente. `scripts/acceptance_retry_dlq.py` verificó el ciclo de Inventario: una violación de constraint dentro de la transacción llegó al DLQ con `attempts=3`; stock, movimientos y outbox no cambiaron, y el probe se retiró del DLQ. La recuperación de outbox ante caída de RabbitMQ/Inventario se verifica aparte con `scripts/acceptance_recovery.py`.
