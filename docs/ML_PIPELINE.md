# Reproducción del pipeline de Machine Learning

Esta guía describe cómo reproducir el entrenamiento, registrar sus experimentos, verificar artefactos y promover o revertir una versión. El modelo usa datos sintéticos para el proyecto académico; el umbral y sus resultados no son una política de crédito real.

## Requisitos y entradas

- Python 3.13 y dependencias fijadas en `requirements.txt` / `requirements-api.txt` (incluyen MLflow, pandas, NumPy, scikit-learn y joblib).
- `data/prestamos_entrenamiento.csv` con la etiqueta `incumplimiento_90d` y las columnas indicadas en `docs/DICCIONARIO_DATOS.md`.
- Docker Compose con MLflow accesible en `http://localhost:5000`, si se desea tracking remoto persistente. `docker-compose.yml` monta SQLite en `mlflow_data/` y artefactos en `mlflow_artifacts/`.

El entrenamiento lee solo `prestamos_entrenamiento.csv`, calcula un SHA-256 y usa semilla 42 con partición estratificada 60/20/20 para train/validation/test. Selecciona por Average Precision de validación, ROC-AUC como desempate y complejidad como último criterio. Calcula el umbral a partir de validation; el conjunto test se evalúa una vez después de congelar modelo y umbral. No se usa la cohorte nueva sin etiqueta para entrenar ni para medir desempeño.

## Reproducción en Windows PowerShell

Desde la raíz del repositorio:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
docker compose up -d mlflow
docker compose ps mlflow
$env:MLFLOW_TRACKING_URI = 'http://localhost:5000'
python ml/train.py
python ml/audit_mlflow.py
python ml/equivalence.py --url http://localhost:8003
```

La alternativa para Linux/macOS es `python3.13 -m venv .venv`, activar `source .venv/bin/activate` y ejecutar los mismos comandos Python. La API para equivalencia debe estar levantada y con el modelo que se quiere comparar.

`python ml/train.py` crea/actualiza `models/v1/` y `models/v2/`, `artifacts/training_report.json`, `artifacts/model_example.json` y `artifacts/splits/{train,validation,test}.csv`. MLflow registra parámetros (incluidos hash de datos, semilla, split, versión de Python y dependencias), métricas de train/validation/test y artefactos del pipeline, evaluación y ejemplo de entrada/salida. Si MLflow no está disponible, el entrenamiento local puede conservar manifiestos e informes, pero la corrida no acredita tracking remoto.

## Promoción y rollback

La promoción exige un manifiesto, un artefacto existente, hash SHA-256 coincidente y un MLflow `run_id` auditable:

```powershell
python ml/promote.py v1
docker compose restart loans
Invoke-RestMethod http://localhost:8003/modelo/info -Headers @{Authorization='Bearer <JWT_ADMIN>'}
```

Reemplaza `<JWT_ADMIN>` por el token temporal recibido de `/auth/login`; no lo guardes en archivos ni en el historial del repositorio.

Para revertir una promoción a la versión estable:

```powershell
python ml/promote.py v1
docker compose restart loans
```

La promoción valida y actualiza el alias `CrediMarketRisk@champion` y `models/active.json`. La API Préstamos carga el puntero al iniciar, verifica el SHA-256 antes de deserializar el pipeline y publica la versión en `/modelo/info`; `/ready` falla si no hay modelo cargado. El endpoint administrativo `/riesgo/predict` valida el esquema y devuelve la versión junto a la probabilidad.

Para comparar el pipeline guardado con la API, `ml/equivalence.py` prueba 200 filas, cero mismatches y error numérico máximo dentro de `1e-9`. Para auditar el registro y artefactos de una corrida seleccionada se usa `python ml/audit_mlflow.py`; el resultado se escribe en `artifacts/mlflow_audit.json`. `scripts/acceptance_model_promotion.py` cubre promoción v2, reinicio, rollback v1 y segundo reinicio contra Docker.

## Persistencia y cuidado de los datos

- No borres `mlflow_data/`, `mlflow_artifacts/`, `models/` ni los volúmenes nombrados PostgreSQL/RabbitMQ/Redis para repetir el pipeline.
- Compose monta MLflow en directorios persistentes del repositorio; se comprobó previamente que 17/17 IDs de corrida y 137/137 archivos de artefactos sobrevivieron un restart del servicio.
- Entrenar crea corridas nuevas y regenera candidatos/reportes/splits. Inspecciona antes las versiones y conserva copias si necesitas comparar modelos anteriores.
- No uses `docker compose down -v` para reiniciar. El frontend no accede a MLflow, bases de datos ni credenciales directamente.

## Evidencia y límite de reproducción

La corrida auditada seleccionada v1 figura `FINISHED`; contiene todos los parámetros, métricas y artefactos requeridos según `artifacts/mlflow_audit.json`. La equivalencia medida previamente fue 200/200, mismatch 0, error absoluto máximo `2.220446049250313e-16`. `EXECUTION_LOG.md` conserva la promoción/rollback y persistencia observados. Esta guía aún no se ha ejecutado desde un clon limpio; la matriz mantiene ese aspecto como pendiente hasta esa verificación.
