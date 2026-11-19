# Auditoría ARQ-05: frontend y microservicios

## Auditoría inicial

No se encontraron mocks ni respuestas simuladas de negocio en React. Las listas y tarjetas proceden de las APIs; las operaciones mutadoras esperan respuesta HTTP exitosa antes de anunciar éxito y luego vuelven a consultar datos. El JWT se conserva en `localStorage` y el helper `api.ts` lo añade a peticiones protegidas.

| Pantalla/componente | Operación | Endpoint | API propietaria | Estado inicial / final | Observación |
|---|---|---|---|---|---|
| `Access.tsx` | Iniciar sesión / registro | `POST /auth/login`, `POST /auth/register` | Clientes | Integrada y funcional | Inicialmente usaba `fetch` aparte; ahora reutiliza `api.ts`. |
| Sesión | Validar identidad | `GET /auth/me` | Clientes | Integrada y funcional | El helper adjunta JWT; 401 limpia la sesión y emite evento. |
| Resumen | Catálogo/clientes/préstamos | `GET /products`, `/customers`, `/prestamos` | Productos, Clientes, Préstamos | Integrada y funcional | Sin fixtures de negocio; se añadió estado de carga. |
| Resumen admin | Stock/modelo | `GET /inventory`, `/modelo/info` | Inventario, Préstamos | Integrada y funcional | El badge de modelo ahora refleja disponibilidad de respuesta. |
| Catálogo | Lista, búsqueda y precio | `GET /products` | Productos | Integrada y funcional | Usa datos de lista; no llama a `GET /products/{id}` por separado. |
| Catálogo admin | Crear/editar/desactivar | `POST /products`, `PUT /products/{id}`, `POST /products/{id}/deactivate` | Productos | Integrada y funcional | Espera confirmación y luego refresca. |
| Clientes admin | Consultar/crear/actualizar/importar | `GET/POST /customers`, `PUT /customers/{id}`, `POST /customers/import` | Clientes | Integrada y funcional | Resumen de importación y errores proceden de la respuesta API. |
| Perfil cliente | Consultar/editar propio | `GET /customers`, `PUT /customers/{id}` | Clientes | Integrada y funcional | Backend aplica ownership y devuelve errores HTTP. |
| Solicitudes | Crear/listar | `POST /prestamos`, `GET /prestamos` | Préstamos | Integrada y funcional | Envía JWT e `Idempotency-Key`; la evaluación y reserva son backend real. |
| Seguimiento | Consultar estado/cancelar | `GET /prestamos/{id}`, `POST /prestamos/{id}/cancel` | Préstamos | Integrada y funcional | Poll cada 1,8 s; muestra error de consulta y refleja estados terminales. |
| Inventario admin | Stock/reservas/movimientos | `GET /inventory`, `/inventory/reservations`, `/inventory/movements` | Inventario | Integrada y funcional | Lecturas de servicio; se corrigió texto que calificaba como simulada la entrega. |
| Inventario admin | Entrada/entrega | `POST /inventory/stock`, `POST /inventory/reservations/{loan_id}/deliver` | Inventario | Integrada y funcional | Espera confirmación y refresca stock, reservas y movimientos. |
| Modelo admin | Versión y monitoreo | `GET /modelo/info`, `GET /monitoring/drift` | Préstamos | Integrada y funcional | Se cambió del alias obsoleto `/drift` a la ruta canónica. |
| Operación del navegador | Todas las vistas | UI React | — | No verificable en esta sesión | Las comprobaciones fueron HTTP vía Vite/Nginx; no se consideran prueba visual de interacción React. |

## Hallazgo y cambios

El frontend Docker ya tenía un proxy Nginx, pero `vite.config.ts` no tenía proxy de desarrollo, por lo que `npm run dev` no podía resolver las rutas relativas `/api/...`. El proxy de Vite ahora usa las mismas rutas y puertos publicados de Compose; los upstreams se pueden configurar con `VITE_PRODUCTS_API_URL`, `VITE_CUSTOMERS_API_URL`, `VITE_LOANS_API_URL` y `VITE_INVENTORY_API_URL`. Nginx conserva el proxy de producción y añade la ruta canónica `/api/monitoring/drift`.

El helper HTTP es ahora compartido también por login/registro, normaliza errores de HTTP y red, maneja respuestas vacías y conserva JSON válido. Se agregaron carga visible, atributos accesibles de estado/error y mensajes/etiquetas que no muestran un modelo activo inexistente ni describen como simulada la entrega real.

## Pruebas ejecutadas

- `npm --prefix frontend test`: 6 pruebas del cliente HTTP aprobadas (JWT, 401/sesión vencida, HTML 502, caída de red, respuesta 204 y JSON string).
- `npm --prefix frontend run build`: TypeScript y Vite correctos.
- Proxy Vite: login real, health de cuatro APIs y GET de Productos, Clientes, Préstamos, Inventario, modelo y drift pasaron.
- Persistencia mediante el proxy Vite: se creó el perfil de prueba `ARQ05-FE-PROXY-057d35449ed8`, y lecturas posteriores por Vite y por la API de Clientes coincidieron. Se deja ese fixture identificado en la base para no borrar datos.
- Proxy Nginx: página, login, health y las mismas rutas de lectura pasaron; drift canónico respondió por Préstamos. Una validación HTTP 422 del upstream siguió siendo JSON por el proxy.
- La caída de red se simuló en el test unitario del cliente HTTP. No se detuvo una API del stack.

Estas pruebas técnicas acreditaban cliente, proxy, endpoints y persistencia en PostgreSQL, pero inicialmente no acreditaban que una persona completara el flujo visual en React. La sección siguiente registra la confirmación manual recibida después; con ambas evidencias, ARQ-05 queda cerrado en la matriz.

## Evidencia manual posterior reportada por Santiago

Santiago confirmó el recorrido visual de ADMIN y CUSTOMER: inicio de sesión, lecturas de productos/clientes, persistencia tras recarga, creación de solicitudes desde React, consulta de detalle de préstamo por UUID completo y estado del modelo visible para ambos roles. También confirmó que al cambiar condiciones salariales del cliente cambió la evaluación de riesgo. No se indicó fecha ni se adjuntaron capturas. Esta confirmación cierra la brecha de interacción visual señalada arriba al combinarse con las pruebas técnicas existentes; la matriz marca ARQ-05 como `VERIFICADO`.
