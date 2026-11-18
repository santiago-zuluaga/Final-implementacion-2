from contextlib import asynccontextmanager
from pathlib import Path
import hashlib, json
import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parents[1]
class RiskInput(BaseModel):
    ingresos_mensuales_cop: int=Field(gt=0,le=1_000_000_000)
    obligaciones_mensuales_cop: int=Field(ge=0,le=1_000_000_000)
    tipo_empleo: str
    antiguedad_laboral_meses: float|None=Field(default=None,ge=0,le=1000)
    meses_historial_crediticio: float|None=Field(default=None,ge=0,le=1000)
    creditos_previos: int=Field(ge=0,le=1000)
    atrasos_previos_30d: int=Field(ge=0,le=1000)
    porcentaje_pago_puntual: float|None=Field(default=None,ge=0,le=100)
    monto_solicitado_cop: int=Field(gt=0,le=1_000_000_000)
    plazo_meses: int=Field(gt=0,le=120)
    cuota_estimada_cop: float=Field(gt=0,le=1_000_000_000)

def features(d):
    d=d.copy(); d['sin_historial']=d['porcentaje_pago_puntual'].isna().astype(int)
    den=d['ingresos_mensuales_cop'].replace(0,float('nan'))
    d['ratio_endeudamiento']=(d['obligaciones_mensuales_cop']+d['cuota_estimada_cop'])/den
    d['cuota_ingreso']=d['cuota_estimada_cop']/den
    return d

@asynccontextmanager
async def lifespan(app):
    pointer=ROOT/'models'/'active.json'
    if pointer.exists():
        active=json.loads(pointer.read_text(encoding='utf-8')); base=ROOT/'models'
        manifest=json.loads((base/active['manifest']).read_text(encoding='utf-8'))
        artifact=base/active['artifact']
        if hashlib.sha256(artifact.read_bytes()).hexdigest()!=manifest['artifact_sha256']:
            raise RuntimeError('Hash del modelo activo inválido')
        app.state.model=joblib.load(artifact); app.state.manifest=manifest
    else: app.state.model=None; app.state.manifest=None
    yield
app=FastAPI(title='CrediMarket Préstamos',lifespan=lifespan)
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/ready')
def ready():
    if app.state.model is None: raise HTTPException(503,'No hay modelo promovido')
    return {'status':'ready','model_version':app.state.manifest['model_version']}
@app.get('/modelo/info')
def model_info():
    if app.state.model is None: raise HTTPException(503,'No hay modelo promovido')
    m=app.state.manifest
    return {k:m[k] for k in ('model_version','run_id','features','threshold')}
@app.post('/riesgo/predict')
def predict(body:RiskInput):
    if app.state.model is None: raise HTTPException(503,'No hay modelo promovido')
    x=features(pd.DataFrame([body.model_dump()]))
    p=float(app.state.model.predict_proba(x)[:,1][0]); m=app.state.manifest; threshold=m['threshold']
    return {'probabilidad_incumplimiento':p,'decision_riesgo':'FAVORABLE' if p<threshold else 'DESFAVORABLE','umbral':threshold,'model_version':m['model_version']}

