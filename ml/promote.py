"""Explicitly switch the active model pointer to a validated version."""
import hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if len(sys.argv)!=2: raise SystemExit('Uso: python ml/promote.py v1')
version=sys.argv[1]; manifest=ROOT/'models'/version/'manifest.json'; artifact=ROOT/'models'/version/'pipeline.joblib'
if not manifest.is_file() or not artifact.is_file(): raise SystemExit(f'Versión incompleta: {version}')
m=json.loads(manifest.read_text(encoding='utf-8'))
if hashlib.sha256(artifact.read_bytes()).hexdigest()!=m['artifact_sha256']: raise SystemExit('Hash del artefacto no coincide')
(ROOT/'models'/'active.json').write_text(json.dumps({'model_version':version,'manifest':f'{version}/manifest.json','artifact':f'{version}/pipeline.joblib'},indent=2),encoding='utf-8')
print(f'Promovido {version}')
