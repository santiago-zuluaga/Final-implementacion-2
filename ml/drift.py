"""Label-free PSI drift check using only the supplied unlabeled requests."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from train import NUM, feature_frame
ROOT=Path(__file__).resolve().parents[1]
def psi(reference,current,bins=10):
    ref=pd.to_numeric(reference,errors='coerce').dropna().to_numpy(); cur=pd.to_numeric(current,errors='coerce').dropna().to_numpy()
    if not len(ref) or not len(cur): return None
    edges=np.unique(np.quantile(ref,np.linspace(0,1,bins+1)))
    if len(edges)<3: return 0.0
    edges[0]-=1e-9; edges[-1]+=1e-9
    a=np.histogram(ref,bins=edges)[0]/len(ref); b=np.histogram(cur,bins=edges)[0]/len(cur)
    a=np.clip(a,1e-6,1); b=np.clip(b,1e-6,1)
    return float(np.sum((b-a)*np.log(b/a)))
def main():
    ref=feature_frame(pd.read_csv(ROOT/'data'/'prestamos_entrenamiento.csv')); new=feature_frame(pd.read_csv(ROOT/'data'/'solicitudes_nuevas.csv'))
    scores={c:psi(ref[c],new[c]) for c in NUM}; report={'baseline':'prestamos_entrenamiento.csv','comparison':'solicitudes_nuevas.csv (unlabeled; no performance metric)','features':scores,'threshold':0.2,'drifted':[k for k,v in scores.items() if v is not None and v>=.2]}
    (ROOT/'artifacts'/'drift_report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
