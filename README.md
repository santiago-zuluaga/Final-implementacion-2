# CrediMarket

Plataforma académica de financiación con evaluación de riesgo sintética. La fuente normativa es el enunciado del profesor en [docs/Enunciado_CrediMarket.docx](docs/Enunciado_CrediMarket.docx). Ninguna métrica o umbral aquí descrito representa una recomendación de crédito real.

## Estado de implementación

Hay cuatro APIs FastAPI independientes (cada contenedor se ejecuta con rol y base PostgreSQL separados), una interfaz React, Redis cache-aside, RabbitMQ, outbox en Préstamos e Inventario, entrenamiento reproducible, MLflow configurable y scripts de equivalencia/drift. El sistema tiene autenticación JWT y roles `ADMIN`/`CUSTOMER`; ver [docs/estado.md](docs/estado.md) y la [matriz contra el enunciado](docs/MATRIZ_CUMPLIMIENTO.md) para el estado comprobado y los pendientes.

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

`.env` contiene credenciales locales y secretos de firma. Sustituye los placeholders de `.env.example` antes de usarlo; no publiques `.env`. El usuario definido por `ADMIN_USERNAME`/`ADMIN_PASSWORD` se crea al iniciar. Los clientes se registran desde la pantalla de acceso; las operaciones administrativas requieren rol `ADMIN`.

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

## Demo

Sigue [docs/GUIA_DEMO.md](docs/GUIA_DEMO.md) para preparar datos y recorrer la interfaz con cuentas administrativas y de cliente. La guía distingue una demo operativa de las pruebas formales de aceptación que siguen pendientes.

Para seguimiento de pendientes y limitaciones reales, usa [docs/estado.md](docs/estado.md), [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/events.md](docs/events.md), [docs/testing.md](docs/testing.md) y [docs/decisions.md](docs/decisions.md).

## Integrantes

| Integrante | Responsabilidades |
|---|---|
| Por definir | Por definir |
