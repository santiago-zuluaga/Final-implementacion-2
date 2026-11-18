"""Register a validated model and explicitly move the MLflow champion alias."""
import hashlib, json, os, sys
from pathlib import Path
import mlflow
from mlflow.tracking import MlflowClient
ROOT=Path(__file__).resolve().parents[1]
REGISTRY_NAME='CrediMarketRisk'
if len(sys.argv)!=2: raise SystemExit('Uso: python ml/promote.py v1')
version=sys.argv[1]; manifest=ROOT/'models'/version/'manifest.json'; artifact=ROOT/'models'/version/'pipeline.joblib'
if not manifest.is_file() or not artifact.is_file(): raise SystemExit(f'Versión incompleta: {version}')
m=json.loads(manifest.read_text(encoding='utf-8'))
if hashlib.sha256(artifact.read_bytes()).hexdigest()!=m['artifact_sha256']: raise SystemExit('Hash del artefacto no coincide')
run_id=m.get('mlflow_run_id')
if not run_id: raise SystemExit('La versión no tiene MLflow run_id; no se puede auditar su promoción')
tracking_uri=os.getenv('MLFLOW_TRACKING_URI','http://localhost:5000')
mlflow.set_tracking_uri(tracking_uri)
client=MlflowClient(tracking_uri=tracking_uri)
registered_models=client.search_registered_models(filter_string=f"name = '{REGISTRY_NAME}'")
if not registered_models:
    registered=client.create_registered_model(REGISTRY_NAME,description='CrediMarket risk pipeline; promoción enlazada a manifests locales verificados por SHA-256.')
versions=client.search_model_versions(f"name='{REGISTRY_NAME}'")
registered_version=next((v for v in versions if v.run_id==run_id),None)
if registered_version is None:
    registered_version=client.create_model_version(
        name=REGISTRY_NAME, source=f'runs:/{run_id}/pipeline', run_id=run_id,
        tags={'credimarket_model_version':version,'artifact_sha256':m['artifact_sha256']},
        description=f'CrediMarket {version}, candidate {m.get("selected_candidate", "unknown")}',
    )
client.set_registered_model_alias(REGISTRY_NAME,'champion',registered_version.version)
alias_version=client.get_model_version_by_alias(REGISTRY_NAME,'champion')
if alias_version.run_id!=run_id:
    raise RuntimeError(f'El alias champion no quedó enlazado al run {run_id}')
m['mlflow_registry_name']=REGISTRY_NAME
m['mlflow_registry_version']=int(registered_version.version)
manifest.write_text(json.dumps(m,indent=2),encoding='utf-8')
(ROOT/'models'/'active.json').write_text(json.dumps({'model_version':version,'manifest':f'{version}/manifest.json','artifact':f'{version}/pipeline.joblib'},indent=2),encoding='utf-8')
print(f'Promovido {version}; MLflow Registry {REGISTRY_NAME} version {registered_version.version}; alias champion actualizado')
