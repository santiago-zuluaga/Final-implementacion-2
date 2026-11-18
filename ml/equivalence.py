"""Compare the promoted local pipeline and the running Loans API on new requests."""
import argparse, json, os
from pathlib import Path
import joblib, numpy as np, pandas as pd, requests
from dotenv import load_dotenv
from train import feature_frame
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--url',default='http://localhost:8003'); args=ap.parse_args()
    load_dotenv(ROOT/'.env')
    token=os.getenv('INTERNAL_API_TOKEN')
    if not token: raise SystemExit('INTERNAL_API_TOKEN is required to call the protected risk endpoint')
    df=pd.read_csv(ROOT/'data'/'solicitudes_nuevas.csv'); pointer=json.loads((ROOT/'models'/'active.json').read_text()); m=json.loads((ROOT/'models'/pointer['manifest']).read_text()); model=joblib.load(ROOT/'models'/pointer['artifact'])
    local=model.predict_proba(feature_frame(df))[:,1]; remote=[]
    for _,r in df.iterrows():
      body={k:(None if pd.isna(v) else v.item() if hasattr(v,'item') else v) for k,v in r.to_dict().items() if k not in ('solicitud_id','cliente_id','tasa_mensual_simulada')}
      res=requests.post(args.url+'/riesgo/predict',json=body,headers={'X-Internal-Token':token},timeout=10); res.raise_for_status(); remote.append(res.json()['probabilidad_incumplimiento'])
    delta=np.abs(local-np.array(remote)); report={'n':len(df),'model_version':m['model_version'],'max_abs_error':float(delta.max()),'mean_abs_error':float(delta.mean()),'mismatch_count':int(np.sum(delta>1e-9)),'worst_rows':[{'row':int(i),'abs_error':float(delta[i]),'local_probability':float(local[i]),'api_probability':float(remote[i])} for i in np.argsort(delta)[-5:][::-1]],'tolerance':1e-9,'equivalent':bool(delta.max()<=1e-9)}
    (ROOT/'artifacts'/'equivalence_report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
    if not report['equivalent']: raise SystemExit(1)
if __name__=='__main__': main()
