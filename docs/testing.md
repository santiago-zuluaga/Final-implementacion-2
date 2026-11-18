# Verificación

- Frontend: `cd frontend && npm ci && npm run build`.
- Backend: `python -m compileall -q domain_service loan_service ml scripts tests` y `python -m pytest -q` (actualmente 6 tests).
- Entrenamiento: `python ml/train.py` (para MLflow, configurar `MLFLOW_TRACKING_URI=http://localhost:5000` y levantar Compose).
- Contrato de ejecución: `docker compose config --quiet` después de copiar `.env.example` a `.env` y completar credenciales.
- Equivalencia: `python ml/equivalence.py --url http://localhost:8003`.
- Drift de entrada no etiquetada: `python ml/drift.py`.

El Docker daemon no estuvo disponible durante esta sesión, así que aún no hay evidencia de levantamiento integrado ni pruebas de aceptación de extremo a extremo. No se deben presentar como aprobadas las 16 pruebas hasta ejecutarlas con Docker activo.
