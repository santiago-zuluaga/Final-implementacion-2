# API de desarrollo

Los servicios exponen Swagger en `/docs` en sus puertos locales. El frontend Nginx expone rutas bajo `/api`.

| Servicio | Puerto local | Endpoints implementados |
|---|---:|---|
| Productos | 8001 | `GET/POST /products`, `GET/PUT /products/{id}`, `GET /products/{id}/quotation`, `POST /products/{id}/deactivate`, `GET /cache/metrics` |
| Clientes | 8002 | `GET/POST /customers`, `GET /customers/{id}`, `POST /customers/import` |
| Préstamos | 8003 | `POST /prestamos`, `GET /prestamos/{id}`, `POST /prestamos/{id}/cancel`, `POST /riesgo/predict`, `GET /modelo/info`, `/health`, `/ready` |
| Inventario | 8004 | `GET /inventory`, `POST /inventory/stock`, `GET /inventory/reservations`, `POST /inventory/reservations/{loan_id}/deliver` |

Solicitud de ejemplo:

```http
POST /prestamos
Idempotency-Key: 4b2a...
Content-Type: application/json

{"customer_id":"CLI-0000001","product_id":1,"quantity":1,"term_months":12}
```

Cotización y datos de cliente los obtiene Préstamos entre servicios. El precio del request del navegador no se acepta. Si la evaluación es favorable la solicitud queda pendiente y responde 202; solo un evento de Inventario lleva a `APROBADA`.
