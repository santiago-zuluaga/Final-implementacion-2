import hashlib, json
from pathlib import Path
import joblib, pandas as pd
from ml.train import DATA, TARGET, FEATURES, feature_frame, metrics

ROOT=Path(__file__).resolve().parents[1]

def test_training_dataset_hash_and_shape():
    raw=DATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='c6cdc437c3aecc9116bc8b978df421d5a7600634c1ad7d6f82e58222a2446ecd'
    df=pd.read_csv(DATA)
    assert df.shape==(12000,15)
    assert df[TARGET].isin([0,1]).all()
    assert df['cliente_id'].is_unique

def test_request_data_is_unlabeled_and_identifiers_are_not_features():
    df=pd.read_csv(ROOT/'data'/'solicitudes_nuevas.csv')
    assert df.shape==(200,14)
    assert TARGET not in df
    X=feature_frame(df)
    assert list(X.columns)==FEATURES
    assert not {'solicitud_id','cliente_id',TARGET}.intersection(X.columns)
    assert X['sin_historial'].sum()==df['porcentaje_pago_puntual'].isna().sum()

def test_active_export_and_manifest_are_consistent():
    pointer=json.loads((ROOT/'models'/'active.json').read_text())
    manifest=json.loads((ROOT/'models'/pointer['manifest']).read_text())
    artifact=ROOT/'models'/pointer['artifact']
    assert manifest['model_version']==pointer['model_version']=='v1'
    assert hashlib.sha256(artifact.read_bytes()).hexdigest()==manifest['artifact_sha256']
    assert abs(manifest['threshold']-0.305)<1e-9
    model=joblib.load(artifact)
    pred=model.predict_proba(feature_frame(pd.read_csv(ROOT/'data'/'solicitudes_nuevas.csv').head(20)))
    assert pred.shape==(20,2)
    assert ((pred>=0)&(pred<=1)).all()

def test_metric_report_has_expected_class_one_metrics():
    report=json.loads((ROOT/'artifacts'/'training_report.json').read_text())
    assert len(report['candidates'])>=7
    assert report['partition_sizes']=={'train':7200,'validation':2400,'test':2400}
    assert {'precision_1','recall_1','f1_1','roc_auc','average_precision','brier','confusion_matrix'} <= set(report['test_metrics'])

def test_risk_api_matches_pipeline_with_missing_employment():
    from fastapi.testclient import TestClient
    from loan_service.app import app
    row=pd.read_csv(ROOT/'data'/'solicitudes_nuevas.csv').iloc[46].to_dict()
    body={k:(None if pd.isna(v) else v.item() if hasattr(v,'item') else v) for k,v in row.items() if k not in ('solicitud_id','cliente_id','tasa_mensual_simulada')}
    with TestClient(app) as client:
        response=client.post('/riesgo/predict',json=body)
    assert response.status_code==200
    assert 0<=response.json()['probabilidad_incumplimiento']<=1
    assert response.json()['model_version']=='v1'

def test_domain_openapi_exposes_required_routes():
    from domain_service.app import app
    paths=app.openapi()['paths']
    for path in ['/products','/products/{id}/quotation','/customers/import','/inventory','/inventory/stock','/prestamos','/prestamos/{id}','/riesgo/predict','/modelo/info','/health','/ready']:
        assert path in paths
