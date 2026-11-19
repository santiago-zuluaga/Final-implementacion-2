# Auditoría ARQ-03: propiedad de rutas y separación de servicios

## Hallazgo inicial

Los contenedores `products`, `customers`, `inventory` y `loans` ejecutan el mismo módulo `domain_service.app:app` con distinto `SERVICE`. Antes de la corrección, los decoradores registraban todas las rutas en las cuatro instancias y por ello cada `/openapi.json` exponía los mismos 27 paths. Casi todas las operaciones de negocio llamaban `require(<dominio>)` y respondían 404 al llegar al servicio equivocado; `GET /auth/me` no tenía esa guarda. La tabla de propiedad faltaba en el registro de rutas.

El contenedor loans usa `docker/loan.Dockerfile`, que también arranca `domain_service.app:app`. `loan_service/app.py` es una implementación anterior y no es el entrypoint de Compose.

## Inventario de rutas antes de la corrección

Hay 32 operaciones (método/path) sobre 27 paths únicos. `/health` y `/ready` son comunes. La columna dependencias describe las lecturas/escrituras relevantes de cada handler.

| Método y path | Handler | Propietario | Dependencias |
|---|---|---|---|
| `GET /health` | `health` | Común | Solo estado del proceso y nombre del servicio. |
| `GET /ready` | `ready` | Común | Comprueba la base configurada; Préstamos también verifica que el modelo esté cargado. |
| `POST /auth/register` | `auth_register` | Clientes | Inserta credencial y perfil en PostgreSQL de Clientes. |
| `POST /auth/login` | `auth_login` | Clientes | Lee credencial y estado del perfil en PostgreSQL de Clientes. |
| `GET /auth/me` | `auth_me` | Clientes | Valida JWT; no consulta otra base. Ahora tiene guarda `require('customers')`. |
| `POST /products` | `product_create` | Productos | Inserta catálogo en PostgreSQL de Productos. |
| `GET /products` | `product_list` | Productos | Lee catálogo en PostgreSQL de Productos. |
| `GET /cache/metrics` | `cache_metrics` | Productos | Lee métricas locales del proceso. |
| `GET /products/{id}` | `product_get` | Productos | Redis cache-aside; miss/fallo consulta PostgreSQL de Productos. |
| `GET /products/{id}/quotation` | `quotation` | Productos | Invocado por Préstamos vía HTTP interno; consulta precio/version desde Productos. |
| `PUT /products/{id}` | `product_update` | Productos | Actualiza Productos e invalida su clave Redis. |
| `POST /products/{id}/deactivate` | `product_deactivate` | Productos | Actualiza Productos e invalida su clave Redis. |
| `POST /customers` | `customer_create` | Clientes | Inserta/actualiza perfil en PostgreSQL de Clientes. |
| `GET /customers` | `customer_list` | Clientes | Lee perfiles propios o lista admin desde PostgreSQL de Clientes. |
| `GET /customers/{id}` | `customer_get` | Clientes | Lee perfil en Clientes; Préstamos usa el acceso interno autenticado. |
| `PUT /customers/{id}` | `customer_update` | Clientes | Actualiza perfil en PostgreSQL de Clientes. |
| `POST /customers/import` | `customer_import` | Clientes | Importa/upsert CSV en PostgreSQL de Clientes. |
| `POST /inventory/stock` | `stock_add` | Inventario | Actualiza stock e inserta movimiento en PostgreSQL de Inventario. |
| `GET /inventory` | `stock_list` | Inventario | Lee stock desde PostgreSQL de Inventario. |
| `GET /inventory/reservations` | `inventory_reservations` | Inventario | Lee reservas de PostgreSQL de Inventario. |
| `GET /inventory/movements` | `inventory_movements` | Inventario | Lee movimientos de PostgreSQL de Inventario. |
| `POST /inventory/reservations/{loan_id}/deliver` | `delivery` | Inventario | Actualiza reserva/stock y emite `SalidaConfirmada` por outbox/RabbitMQ. |
| `POST /prestamos` | `loan_create` | Préstamos | Lee/escribe PostgreSQL de Préstamos; HTTP interno a Clientes y Productos; publica comando por outbox/RabbitMQ. |
| `POST /loans` | `loan_create` | Préstamos | Alias compatible de `POST /prestamos`; mismas dependencias. |
| `GET /prestamos` | `loan_list` | Préstamos | Lee préstamos desde PostgreSQL de Préstamos. |
| `GET /prestamos/{id}` | `loan_get` | Préstamos | Lee préstamo desde PostgreSQL de Préstamos y valida propiedad. |
| `GET /loans/{id}` | `loan_get` | Préstamos | Alias compatible de `GET /prestamos/{id}`. |
| `POST /prestamos/{loan_id}/cancel` | `cancel_loan` | Préstamos | Actualiza préstamo/outbox; Inventario procesa la liberación por RabbitMQ. |
| `GET /modelo/info` | `model_info` | Préstamos | Lee manifiesto/modelo cargado localmente. |
| `POST /riesgo/predict` | `risk_predict` | Préstamos | Ejecuta el modelo cargado; sin acceso a DB ajena. |
| `GET /monitoring/drift` | `drift_report` | Préstamos | Lee reporte de drift local, generado offline. |
| `GET /drift` | `drift_report` | Préstamos | Alias compatible de `GET /monitoring/drift`. |

## Comunicación y bases de datos

- Préstamos consulta Clientes y la cotización de Productos mediante HTTP interno con `X-Internal-Token`.
- Préstamos publica `ReservaSolicitada`/`LiberarReserva` mediante outbox y RabbitMQ. Inventario consume comandos y emite eventos mediante su outbox; Préstamos consume esos eventos y actualiza su propia base.
- Productos usa Redis solo como caché de su catálogo.
- Cada contenedor recibe una `DATABASE_URL` y un rol PostgreSQL propios (`cm_products`, `cm_customers`, `cm_loans`, `cm_inventory`). La inspección de SQL no encontró handlers que consulten tablas ajenas.

## Decisión

Se conserva el módulo compartido para evitar una refactorización de controladores que no es necesaria para separar los contratos desplegados. `ROUTE_OWNERS` asigna explícitamente cada operación; el generador OpenAPI incluye únicamente operaciones propias más `/health` y `/ready`, y falla cerrado si hay una ruta sin propietario. Los tres aliases de Préstamos siguen disponibles por compatibilidad y están marcados como obsoletos en OpenAPI; se documentan como tales en `docs/api.md`. La guarda de `/auth/me` asegura que Clientes sea también su único propietario en ejecución.

## Evidencia después de la corrección

`tests/test_service_openapi.py` comprueba que todas las rutas registradas aparecen una sola vez en el manifiesto, que cada esquema contiene exactamente las operaciones asignadas, que los aliases están marcados como obsoletos y que las rutas de otros dominios (incluido `/auth/me`) responden 404. La verificación del Compose reconstruido y los resultados por servicio se registran en `docs/EXECUTION_LOG.md`.
