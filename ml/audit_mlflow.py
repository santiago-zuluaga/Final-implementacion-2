"""Audit the selected training run against the required MLflow metadata."""
from __future__ import annotations

import json
import os
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "models" / "v1" / "manifest.json").read_text(encoding="utf-8"))
run_id = manifest["mlflow_run_id"]
client = MlflowClient(tracking_uri=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
run = client.get_run(run_id)
params = run.data.params
metrics = run.data.metrics
required_params = {
    "algorithm", "seed", "split", "selection", "data_sha256", "features",
    "python", "code_commit", "dependencies", "preprocessing_numeric",
    "preprocessing_categorical",
}
required_metrics = {
    "average_precision", "roc_auc", "brier", "duration_seconds",
    "train_average_precision", "train_roc_auc", "train_brier",
    "test_average_precision", "test_roc_auc", "test_brier",
}
artifact_dir = ROOT / "mlflow_artifacts" / run.info.experiment_id / run_id / "artifacts"
artifact_paths = sorted(str(p.relative_to(artifact_dir)).replace("\\", "/") for p in artifact_dir.rglob("*") if p.is_file())
missing_params = sorted(required_params - params.keys())
missing_metrics = sorted(required_metrics - metrics.keys())
required_artifacts = {"pipeline/MLmodel", "confusion.json", "test_evaluation.json", "example_input_output.json"}
missing_artifacts = sorted(required_artifacts - set(artifact_paths))
result = {
    "run_id": run_id,
    "status": run.info.status,
    "algorithm": params.get("algorithm"),
    "required_params": sorted(required_params),
    "missing_params": missing_params,
    "required_metrics": sorted(required_metrics),
    "missing_metrics": missing_metrics,
    "artifacts": artifact_paths,
    "missing_artifacts": missing_artifacts,
    "passed": run.info.status == "FINISHED" and not missing_params and not missing_metrics and not missing_artifacts,
}
out = ROOT / "artifacts" / "mlflow_audit.json"
out.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
if not result["passed"]:
    raise SystemExit(1)
