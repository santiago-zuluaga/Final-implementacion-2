# API de desarrollo

Los servicios exponen Swagger en `/docs` en sus puertos locales. El frontend Nginx expone rutas bajo `/api`.

| Servicio | Puerto local | Operaciones propias documentadas |
|---|---:|---|
| Productos | 8001 | `GET/POST /products`, `GET/PUT /products/{id}`, `GET /products/{id}/quotation`, `POST /products/{id}/deactivate`, `POST /products/{id}/activate`, `GET /cache/metrics` |
| Clientes | 8002 | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `GET/POST /customers`, `GET/PUT /customers/{id}`, `POST /customers/import` |
| Préstamos | 8003 | `POST /prestamos`, `GET /prestamos`, `GET /prestamos/{id}`, `POST /prestamos/{loan_id}/cancel`, `POST /riesgo/predict`, `GET /modelo/info`, `GET /monitoring/drift` |
| Inventario | 8004 | `GET /inventory`, `POST /inventory/stock`, `GET /inventory/reservations`, `GET /inventory/movements`, `POST /inventory/reservations/{loan_id}/deliver` |

Los cuatro servicios comparten únicamente `GET /health` y `GET /ready`. Cada documento `/openapi.json` contiene solo sus operaciones propias y las dos rutas operativas comunes. Préstamos conserva aliases históricos (`/loans`, `/loans/{id}`, `/drift`) y los marca `deprecated` en OpenAPI; las rutas canónicas son `/prestamos`, `/prestamos/{id}` y `/monitoring/drift`.

## Status HTTP y validación

| Servicio/operación | Éxito | Errores relevantes |
|---|---|---|
| Todos: `GET /health` | 200 liveness | — |
| Todos: `GET /ready` | 200 si DB disponible (y modelo cargado en Préstamos) | 503 DB/modelo no disponible |
| Productos: listar/consultar | 200 | 401/403 para parámetros que incluyen inactivos; 404 para ID inexistente o inactivo en consulta activa |
| Productos: crear | 201 | 401/403, 422 validación |
| Productos: actualizar/activar/desactivar | 200 | 401/403, 404, 422 |
| Productos: cotización interna | 200 | 401 token interno, 404 producto inactivo/inexistente |
| Clientes: registrar/importar | 201/200 | 401/403; registro duplicado 409; 422 validación |
| Clientes: consultar/actualizar | 200 | 401/403; 404 perfil inexistente; 422 validación |
| Préstamos: `POST /prestamos` | 202 favorable pendiente de inventario; 200 decisión de riesgo rechazada o respuesta idempotente | 401/403, 404 cliente/producto, 409 misma clave con cuerpo distinto, 422 validación, 503 dependencia no disponible |
| Préstamos: listar/detalle/cancelar | 200 | 401/403; detalle inexistente 404; cancelación fuera de estado válido (o ID inexistente) 409 |
| Préstamos: riesgo/modelo/drift | 200 | 401/403; 422 riesgo inválido; 503 modelo/reporte no disponible |
| Inventario: listar/entrada/entrega | 200/201 | 401/403; 409 entrega no activa; 422 validación |

Las operaciones con cuerpo usan los modelos Pydantic expuestos en OpenAPI; sus errores de esquema/rango responden 422. Los errores de dominio usan JSON `{"detail":"…"}`. Los contratos OpenAPI declaran 202 para la aceptación asíncrona de Préstamos y las respuestas 401/403/404/409/503 que aplican por ruta. No toda excepción de infraestructura se puede resolver por retry automático del cliente.

`POST /prestamos` recibe `customer_id`, `product_id > 0`, `quantity` de 1 a 10, `term_months` de 1 a 60 y `Idempotency-Key`. Su JSON de respuesta incluye `id`, `status`, `reason`, `probabilidad_incumplimiento`, `decision_riesgo`, `model_version`, `price_cop` y `product_version`. Un plazo fuera de la política de aprobación (6 a 36 meses) se registra como decisión `RECHAZADA` con HTTP 200; no es un error de esquema. `GET /prestamos` y `/inventory/movements` aceptan `limit` de 1 a 200 y `offset >= 0`, documentados como límites de query en OpenAPI.

## Timeouts, reintentos y exposición

Préstamos consulta Clientes y Productos con timeout HTTP de 3 s y responde 503 si una dependencia no responde; no reintenta en el request síncrono. Un retry de cliente conserva exactamente la misma `Idempotency-Key` y cuerpo. Productos limita cada operación Redis a 350 ms y cae a PostgreSQL; tras un fallo abre un circuito de 5 s. Outbox reintenta publicación periódicamente y las colas RabbitMQ aplican TTL de retry de 5 s, hasta tres intentos y DLQ.

El navegador usa rutas same-origin `/api/*` atendidas por Nginx (Compose) o Vite (desarrollo); por eso no se requiere CORS entre navegador y microservicios y no se habilitan orígenes arbitrarios. Las variables `VITE_*_API_URL` configuran los upstreams del proxy Vite de desarrollo. En Compose, Nginx usa DNS interno de servicios y el bundle React solo conoce las rutas `/api/*`; no recibe URL de DB, Redis, RabbitMQ, artefactos ML ni `INTERNAL_API_TOKEN`. PostgreSQL y Redis no publican puertos al host; RabbitMQ Management sí publica el puerto de administración local 15672 para observabilidad, pero no lo utiliza el frontend.

Las rutas administrativas requieren `Authorization: Bearer <JWT>` de rol ADMIN. Un JWT CUSTOMER solo puede leer/editar su perfil y consultar sus propios préstamos; crear un préstamo para otro cliente se rechaza. Los endpoints internos entre servicios validan `X-Internal-Token`. Login/registro son públicos; no enviar secretos de servicio al navegador. El frontend adjunta el JWT y elimina la sesión al recibir 401.

Productos activos se consultan con `GET /products` y son visibles para los roles CUSTOMER y ADMIN. `GET /products?include_inactive=true` agrega los inactivos y exige JWT ADMIN. El detalle normal `GET /products/{id}` solo devuelve productos activos; el detalle histórico `GET /products/{id}?include_inactive=true` exige ADMIN. ADMIN puede reactivar el registro existente con `POST /products/{id}/activate`; responde `{ "id": 2, "active": true, "version": 5 }` (la versión corresponde al producto). La operación es idempotente para un producto ya activo. El endpoint de cotización interno sigue filtrando inactivos, por lo que no pueden usarse en préstamos ni nuevas reservas.

Solicitud de ejemplo:

```http
POST /prestamos
Idempotency-Key: 4b2a...
Content-Type: application/json

{"customer_id":"CLI-0000001","product_id":1,"quantity":1,"term_months":12}
```

Cotización y datos de cliente los obtiene Préstamos entre servicios. El precio del request del navegador no se acepta. Si la evaluación es favorable la solicitud queda pendiente y responde 202; solo un evento de Inventario lleva a `APROBADA`.

Las APIs tienen OpenAPI en `/docs`. No se documentan aquí secretos de demo ni tokens vigentes. Para preparación, roles y recorrido ver `GUIA_DEMO.md`.
