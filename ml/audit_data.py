"""Audit the supplied training and unlabeled CSVs without fitting a model."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'training': ROOT / 'data' / 'prestamos_entrenamiento.csv',
    'unlabeled': ROOT / 'data' / 'solicitudes_nuevas.csv',
}
TARGET = 'incumplimiento_90d'


def audit(path):
    raw = path.read_bytes()
    frame = pd.read_csv(path)
    columns = {}
    for name in frame.columns:
        series = frame[name]
        item = {
            'dtype': str(series.dtype),
            'missing': int(series.isna().sum()),
            'missing_rate': round(float(series.isna().mean()), 6),
            'unique_non_null': int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series):
            clean = pd.to_numeric(series, errors='coerce').dropna()
            if len(clean):
                item['range'] = {'min': float(clean.min()), 'median': float(clean.median()), 'max': float(clean.max())}
        else:
            item['top_values'] = {str(key): int(value) for key, value in series.value_counts(dropna=False).head(20).items()}
        columns[name] = item

    result = {
        'file': path.name,
        'sha256': hashlib.sha256(raw).hexdigest(),
        'rows': int(frame.shape[0]),
        'columns_count': int(frame.shape[1]),
        'exact_duplicate_rows': int(frame.duplicated().sum()),
        'columns': columns,
    }
    for identifier in ('solicitud_id', 'cliente_id'):
        if identifier in frame:
            result.setdefault('identifier_checks', {})[identifier] = {
                'unique': int(frame[identifier].nunique(dropna=True)),
                'missing': int(frame[identifier].isna().sum()),
                'duplicates': int(frame[identifier].duplicated().sum()),
            }
    if TARGET in frame:
        result['target'] = {
            'name': TARGET,
            'class_counts': {str(key): int(value) for key, value in frame[TARGET].value_counts(dropna=False).sort_index().items()},
            'positive_rate': float(frame[TARGET].mean()),
        }
    return result


def main():
    reports = {}
    for name, path in FILES.items():
        if not path.is_file():
            raise SystemExit(f'Missing required data file: {path}')
        reports[name] = audit(path)
    target = ROOT / 'artifacts' / 'data_audit.json'
    target.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(json.dumps({name: {key: report[key] for key in ('sha256', 'rows', 'columns_count', 'exact_duplicate_rows')} for name, report in reports.items()}, indent=2))
    print(f'Wrote {target.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
