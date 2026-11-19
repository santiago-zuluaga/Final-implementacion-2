# Guía para la demo de CrediMarket

## Preparación

1. Copiar `.env.example` como `.env` y reemplazar todos los valores de ejemplo. No mostrar ni compartir `.env` durante la sustentación.
2. Desde la raíz ejecutar `docker compose up --build -d` y esperar a que PostgreSQL, Redis, RabbitMQ y las cuatro APIs estén healthy (`docker compose ps`).
3. Ejecutar `.venv\Scripts\python.exe scripts\seed_demo.py` (o `python scripts/seed_demo.py` en Linux/macOS). Es idempotente: crea tres productos de demostración y agrega stock solo cuando aún no existe.
4. Abrir `http://localhost:8080`. Entrar con `ADMIN_USERNAME` y `ADMIN_PASSWORD` definidos en `.env`; crear una cuenta cliente desde el formulario de registro.

## Recorrido recomendado

1. Como ADMIN, mostrar catálogo y versión del modelo; ver inventario y movimientos. La carga inicial son datos sintéticos.
2. Como CUSTOMER, completar el perfil propio y enviar una solicitud con producto, cantidad y plazo. Explicar que el importe lo calcula el backend usando la cotización vigente y que la evaluación de riesgo no equivale a aprobación.
3. Mostrar ID y estado pendiente; el polling refleja el resultado asíncrono de RabbitMQ/Inventario. Si la reserva se confirma, volver a ADMIN y confirmar entrega para ver `COMPLETADA`.
4. Mostrar historial propio al cliente; comprobar que un cliente no puede abrir otro perfil o préstamo modificando el ID en la petición (debe responder 403).
5. Como ADMIN, mostrar movimientos y métricas Redis. Para observar un miss seguido de hit sobre el producto 1, eliminar su clave con `docker compose exec redis redis-cli DEL products:v1:1`, consultar `GET /products/1` dos veces y leer `/cache/metrics`. El contador es local al proceso y se reinicia en cada despliegue.
6. Mostrar el panel de drift como cambio de distribución sin etiquetas, no como degradación del modelo. La equivalencia reproducible se ejecuta con `.venv\Scripts\python.exe ml\equivalence.py`.

## Resultados esperados

- El login responde con el rol indicado en el perfil de la interfaz. Un token vencido termina la sesión y pide iniciar de nuevo.
- La solicitud muestra su UUID, score/version y estado `PENDIENTE_INVENTARIO`. Un riesgo favorable no es aprobación final: Préstamos cambia a `APROBADA` cuando Inventario confirma la reserva; sin existencias el resultado terminal es `CANCELADA_SIN_STOCK`.
- ADMIN observa disponible/reservado y los movimientos persistidos. Tras confirmar entrega, la reserva queda `DELIVERED`, el movimiento `OUT` se registra y el préstamo termina `COMPLETADA`.
- CUSTOMER solo ve y actualiza su propio perfil y préstamos. Una consulta directa de otro perfil/préstamo debe responder 403; ADMIN puede consultar vistas administrativas.
- El modelo indica `Disponible` y una versión cuando está cargado. `Error de consulta` indica que no se pudo consultar; no equivale a un modelo descargado.

La evaluación sintética puede rechazar una solicitud o devolver alto riesgo; no alteres umbrales/datos para forzar aprobación. La disponibilidad del stock y el perfil financiero determinan los resultados.

## URLs

- Frontend: `http://localhost:8080`
- Swagger Productos/Clientes/Préstamos/Inventario: `http://localhost:8001/docs` hasta `http://localhost:8004/docs`
- MLflow: `http://localhost:5000`
- RabbitMQ Management: `http://localhost:15672`

## Recuperación básica

- Estado de contenedores: `docker compose ps`; logs: `docker compose logs --tail 100 loans inventory rabbitmq`.
- Reiniciar el stack preservando datos: `docker compose restart`. No usar `docker compose down -v` durante la preparación.
- Si ya se usaron los productos, el seeder no sobreescribe ni reinicia el stock.
- Si la interfaz no abre, revisar el servicio frontend y los logs; el acceso automatizado al navegador local quedó bloqueado por la autorización del origen en esta sesión, por lo que esa ruta visual todavía requiere demostración manual.
- Si una API no responde, revisar `docker compose ps` y consultar `docker compose logs --tail 100 <servicio>`; reintentar desde el botón Actualizar después de recuperar el servicio. Una petición que devuelve error no se debe presentar como guardada.
- Si una solicitud permanece pendiente por caída de RabbitMQ/Inventario, recuperar primero el servicio y revisar Logs/estado; el worker aplica timeout a los dos minutos y solicita liberar una reserva tardía. No reinicializar PostgreSQL ni borrar volúmenes para recuperar el flujo.
- Si no se puede registrar entrega, confirmar que la reserva esté `RESERVED` y no `DELIVERED`, `RELEASED` o `EXPIRED`; el backend rechaza la transición no válida con 409.

## Cuentas y datos

La cuenta ADMIN se configura al inicializar usando las variables de `.env`. No hay una contraseña compartida para clientes; cada cliente se registra. El CSV de entrenamiento no se importa por defecto a la base de usuarios: contiene datos de modelado y no es una lista de cuentas de acceso. Usar identidades sintéticas para la demo.

La guía permite repetir el flujo feliz, pero no sustituye los casos formales ni demuestra por sí sola retry/DLQ, expiración o concurrencia. Consultar `PRUEBAS_ACEPTACION.md` antes de afirmar cobertura.
