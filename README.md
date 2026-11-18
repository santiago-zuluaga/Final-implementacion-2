# CrediMarket

Plataforma académica de financiación con evaluación de riesgo sintética. La fuente normativa es el enunciado del profesor en [docs/Enunciado_CrediMarket.docx](docs/Enunciado_CrediMarket.docx). Ninguna métrica o umbral aquí descrito representa una recomendación de crédito real.

## Estado de implementación

Hay cuatro APIs FastAPI independientes (cada contenedor se ejecuta con rol y base PostgreSQL separados), una interfaz React, Redis cache-aside, RabbitMQ, outbox en Préstamos e Inventario, entrenamiento reproducible, MLflow configurable y scripts de equivalencia/drift. Consulta [docs/estado.md](docs/estado.md) para distinguir lo implementado de lo pendiente: seguridad por roles, retry/DLQ, acciones administrativas completas y pruebas de aceptación aún requieren trabajo.

## Requisitos locales

- Docker Desktop con el motor Linux activo y Docker Compose v2.
- Git.
- Para entrenar fuera de Docker: Python 3.13; para compilar la interfaz: Node 22.

## Arranque integrado

```powershell
Copy-Item .env.example .env
# Cambia las contraseñas placeholder dentro de .env
docker compose up --build
```

La primera inicialización de PostgreSQL crea cuatro bases: `cm_products`, `cm_customers`, `cm_loans` y `cm_inventory`, con credenciales distintas. MLflow conserva su tracking en SQLite y artefactos en `mlflow_data/` y `mlflow_artifacts/`. **No borres datos o volúmenes que quieras conservar.**

## URLs de desarrollo

- Frontend: http://localhost:8080
- Productos Swagger: http://localhost:8001/docs
- Clientes Swagger: http://localhost:8002/docs
- Préstamos Swagger: http://localhost:8003/docs
- Inventario Swagger: http://localhost:8004/docs
- MLflow: http://localhost:5000
- RabbitMQ Management: http://localhost:15672

Los puertos y la URL del enlace a MLflow se pueden cambiar en `.env` (`VITE_MLFLOW_URL` se aplica al hacer build del frontend).

## Entrenamiento

Los CSV se guardan en `data/`. Para crear entorno con las versiones fijadas:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
New-Item -ItemType Directory -Force mlflow_data,mlflow_artifacts | Out-Null
Start-Process .\.venv\Scripts\mlflow.exe -ArgumentList 'server --host 0.0.0.0 --port 5000 --backend-store-uri sqlite:///mlflow_data/mlflow.db --default-artifact-root ./mlflow_artifacts --serve-artifacts' -WindowStyle Hidden
$env:MLFLOW_TRACKING_URI = 'http://localhost:5000'
python ml/train.py
python ml/promote.py v1
```

Si MLflow no está disponible, el script conserva el experimento localmente con los manifiestos e informe, pero el criterio de Tracking no se considera satisfecho hasta registrar las corridas en el servidor. `models/active.json` apunta a una versión por nombre; la API carga esa versión al iniciar y verifica el SHA-256 del artefacto. `v2` es otro candidato seleccionado exclusivamente con validación; no se usa el test para seleccionarlo.

## Scripts de verificación

```powershell
python -m compileall -q domain_service loan_service ml
python ml/drift.py
python ml/equivalence.py --url http://localhost:8003
cd frontend; npm ci; npm run build; npm audit --omit=dev
```

La importación de clientes requiere un CSV con columnas del histórico. La API hace upsert por `cliente_id`; repetir el mismo archivo no crea duplicados.

## Demo básica

1. Levanta Compose y abre el frontend.
2. Ejecuta `python scripts/seed_demo.py` para crear productos y existencias sintéticas mediante las APIs.
3. Importa `data/prestamos_entrenamiento.csv` desde Clientes.
4. Selecciona un cliente y producto, envía una solicitud y observa el estado pendiente hasta la respuesta del broker.
5. Verifica el préstamo y la reserva; desde Inventario registra la entrega. Desde Préstamos puedes solicitar la cancelación antes de la entrega.
6. Consulta Redis en `/cache/metrics`, los experimentos en MLflow y RabbitMQ en su consola.

Para seguimiento de pendientes y limitaciones reales, usa [docs/estado.md](docs/estado.md), [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/events.md](docs/events.md), [docs/testing.md](docs/testing.md) y [docs/decisions.md](docs/decisions.md).

## Integrantes

| Integrante | Responsabilidades |
|---|---|
| Por definir | Por definir |
