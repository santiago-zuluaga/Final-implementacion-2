"""Reproducible tabular training with an untouched final test partition."""
from __future__ import annotations
import hashlib, json, os, platform, subprocess, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'prestamos_entrenamiento.csv'; OUT=ROOT/'models'
TARGET='incumplimiento_90d'; SEED=42
NUM=['ingresos_mensuales_cop','obligaciones_mensuales_cop','antiguedad_laboral_meses',
     'meses_historial_crediticio','creditos_previos','atrasos_previos_30d',
     'porcentaje_pago_puntual','monto_solicitado_cop','plazo_meses','cuota_estimada_cop',
     'sin_historial','ratio_endeudamiento','cuota_ingreso']
CAT=['tipo_empleo']; FEATURES=NUM+CAT

def feature_frame(df):
    d=df.copy()
    d['sin_historial']=d['porcentaje_pago_puntual'].isna().astype(int)
    denom=d['ingresos_mensuales_cop'].replace(0,np.nan)
    d['ratio_endeudamiento']=(d['obligaciones_mensuales_cop']+d['cuota_estimada_cop'])/denom
    d['cuota_ingreso']=d['cuota_estimada_cop']/denom
    return d[FEATURES]

def pipeline(est):
    prep=ColumnTransformer([
      ('num',Pipeline([('imputer',SimpleImputer(strategy='median',add_indicator=False)),('scale',StandardScaler())]),NUM),
      ('cat',Pipeline([('imputer',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))]),CAT)])
    return Pipeline([('features',prep),('model',est)])

def metrics(y,p,threshold):
    pred=(p>=threshold).astype(int)
    return {'precision_1':float(precision_score(y,pred,zero_division=0)),
      'recall_1':float(recall_score(y,pred,zero_division=0)), 'f1_1':float(f1_score(y,pred,zero_division=0)),
      'roc_auc':float(roc_auc_score(y,p)), 'average_precision':float(average_precision_score(y,p)),
      'brier':float(brier_score_loss(y,p)), 'confusion_matrix':confusion_matrix(y,pred).tolist()}

def main():
    if not DATA.exists(): raise SystemExit(f'Falta {DATA}. Copie allí el CSV de entrenamiento.')
    raw=DATA.read_bytes(); digest=hashlib.sha256(raw).hexdigest(); df=pd.read_csv(DATA)
    if TARGET not in df or df[TARGET].isna().any(): raise ValueError('Etiqueta ausente o incompleta')
    y=df[TARGET].astype(int); X=feature_frame(df)
    ids=np.arange(len(df)); dev,test=train_test_split(ids,test_size=.2,stratify=y,random_state=SEED)
    train,val=train_test_split(dev,test_size=.25,stratify=y.iloc[dev],random_state=SEED)
    splitdir=ROOT/'artifacts'/'splits'; splitdir.mkdir(parents=True,exist_ok=True)
    pd.DataFrame({'row_index':train}).to_csv(splitdir/'train.csv',index=False)
    pd.DataFrame({'row_index':val}).to_csv(splitdir/'validation.csv',index=False)
    pd.DataFrame({'row_index':test}).to_csv(splitdir/'test.csv',index=False)
    # Metric and tie-breakers are declared before candidate evaluation.
    candidates=[('dummy_prior',DummyClassifier(strategy='prior')),
      ('logreg_c1',LogisticRegression(C=1,max_iter=1500,class_weight='balanced',random_state=SEED)),
      ('logreg_c05',LogisticRegression(C=.5,max_iter=1500,class_weight='balanced',random_state=SEED)),
      ('tree_d5',DecisionTreeClassifier(max_depth=5,min_samples_leaf=20,class_weight='balanced',random_state=SEED)),
      ('tree_d8',DecisionTreeClassifier(max_depth=8,min_samples_leaf=30,class_weight='balanced',random_state=SEED)),
      ('forest_300',RandomForestClassifier(n_estimators=300,max_depth=12,min_samples_leaf=8,class_weight='balanced_subsample',n_jobs=-1,random_state=SEED)),
      ('forest_500',RandomForestClassifier(n_estimators=500,max_depth=10,min_samples_leaf=12,class_weight='balanced_subsample',n_jobs=-1,random_state=SEED)),
      ('hist_150',HistGradientBoostingClassifier(max_iter=150,max_leaf_nodes=15,random_state=SEED))]
    try:
      import mlflow
      mlflow.set_tracking_uri(os.getenv('MLFLOW_TRACKING_URI',str(ROOT/'mlruns')))
      mlflow.set_experiment('credimarket-risk')
    except ImportError: mlflow=None
    results=[]; fitted={}
    for name,est in candidates:
      start=time.time(); model=pipeline(est); model.fit(X.iloc[train],y.iloc[train]); pv=model.predict_proba(X.iloc[val])[:,1]
      m=metrics(y.iloc[val],pv,.5); results.append({'name':name,'metrics_validation':m,'duration_seconds':time.time()-start}); fitted[name]=model
      if mlflow:
        with mlflow.start_run(run_name=name):
          mlflow.log_params({'algorithm':type(est).__name__,'seed':SEED,'split':'60/20/20 stratified','selection':'AP validation, tie ROC-AUC then simplicity'})
          mlflow.log_params(est.get_params(deep=False)); mlflow.log_param('data_sha256',digest); mlflow.log_param('features',json.dumps(FEATURES)); mlflow.log_param('python',platform.python_version())
          mlflow.log_metrics({k:v for k,v in m.items() if isinstance(v,(int,float))}); mlflow.log_metric('duration_seconds',results[-1]['duration_seconds'])
          mlflow.log_dict({'confusion_matrix':m['confusion_matrix']},'confusion.json')
    # AP primary; ROC-AUC tie-breaker. Remaining ties retain the simpler earlier candidate.
    best=max(results,key=lambda r:(r['metrics_validation']['average_precision'],r['metrics_validation']['roc_auc']))
    model=fitted[best['name']]; pv=model.predict_proba(X.iloc[val])[:,1]
    # False approval: defaulting customer is approved (p < t). False rejection:
    # payer is rejected (p >= t). Costs are illustrative only: 5 and 1.
    thresholds=np.linspace(.05,.95,181); costs=[5*np.sum((pv<t)&(y.iloc[val].to_numpy()==1))+np.sum((pv>=t)&(y.iloc[val].to_numpy()==0)) for t in thresholds]
    threshold=float(thresholds[int(np.argmin(costs))])
    # Freeze threshold/model now; test is read exactly once below.
    pt=model.predict_proba(X.iloc[test])[:,1]; test_metrics=metrics(y.iloc[test],pt,threshold)
    version='v1'; dest=OUT/version; dest.mkdir(parents=True,exist_ok=True); artifact=dest/'pipeline.joblib'; joblib.dump(model,artifact)
    manifest={'model_version':version,'run_id':best['name'],'dataset_sha256':digest,'features':FEATURES,'positive_class':1,'threshold':threshold,'selection_metric':'average_precision_validation','tie_breaker':'roc_auc_validation_then_simplicity','validation_metrics':best['metrics_validation'],'test_metrics':test_metrics,'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'dependencies':{'python':platform.python_version(),'scikit_learn':__import__('sklearn').__version__},'selected_candidate':best['name']}
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (ROOT/'artifacts'/'training_report.json').write_text(json.dumps({'data_sha256':digest,'shape':df.shape,'class_rate':float(y.mean()),'missing':df.isna().sum().to_dict(),'partition_sizes':{'train':len(train),'validation':len(val),'test':len(test)},'selection_metric':'AP validation; ties ROC-AUC then simplicity','costs':{'false_approve':5,'false_reject':1},'threshold':threshold,'candidates':results,'selected':best['name'],'test_metrics':test_metrics,'mlflow_enabled':bool(mlflow)},indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2)); print(f'MLflow: {bool(mlflow)}; informe: artifacts/training_report.json')
if __name__=='__main__': main()

