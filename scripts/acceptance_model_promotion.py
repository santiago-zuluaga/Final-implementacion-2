"""Verify the promoted model version loaded by Loans after each restart."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
BASE = os.getenv("CUSTOMERS_URL", "http://localhost:8002")
LOANS = os.getenv("LOANS_URL", "http://localhost:8003")
session = requests.Session()
login = session.post(f"{BASE}/auth/login", json={"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]}, timeout=5)
login.raise_for_status()
session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"


def restart_and_read(expected):
    subprocess.run(["docker", "compose", "restart", "loans"], cwd=ROOT, check=True, capture_output=True, text=True)
    last = None
    for _ in range(30):
        try:
            ready = requests.get(f"{LOANS}/ready", timeout=2)
            ready.raise_for_status()
            observed = session.get(f"{LOANS}/modelo/info", timeout=3)
            observed.raise_for_status()
            info = observed.json()
            if ready.json().get("status") != "ready" or info["model_version"] != expected:
                raise AssertionError(f"Expected {expected}, got ready={ready.json()} info={info}")
            return info
        except (requests.RequestException, AssertionError) as exc:
            last = exc
            time.sleep(1)
    raise RuntimeError(f"Loans did not load {expected} after restart: {last}")


results = {}
try:
    for version in ("v2", "v1"):
        subprocess.run([sys.executable, str(ROOT / "ml" / "promote.py"), version], cwd=ROOT, check=True, capture_output=True, text=True)
        results[version] = restart_and_read(version)
finally:
    subprocess.run([sys.executable, str(ROOT / "ml" / "promote.py"), "v1"], cwd=ROOT, check=True, capture_output=True, text=True)
    if results.get("v1", {}).get("model_version") != "v1":
        restart_and_read("v1")

report = {"v2_after_restart": results["v2"], "v1_after_rollback_restart": results["v1"], "final_active": json.loads((ROOT / "models" / "active.json").read_text(encoding="utf-8"))["model_version"], "passed": results["v2"]["model_version"] == "v2" and results["v1"]["model_version"] == "v1"}
(ROOT / "artifacts" / "model_promotion_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
if not report["passed"] or report["final_active"] != "v1":
    raise SystemExit(1)
