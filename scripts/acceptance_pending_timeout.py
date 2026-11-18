"""Verify the real two-minute pending-loan timeout through RabbitMQ recovery."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
URLS = {name: os.getenv(f"CREDIMARKET_{name.upper()}_URL", f"http://localhost:{port}").rstrip("/") for name, port in {"customers": 8002, "products": 8001, "loans": 8003, "inventory": 8004}.items()}
session = requests.Session()
login = session.post(f"{URLS['customers']}/auth/login", json={"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]}, timeout=5)
login.raise_for_status()
headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
listed = session.get(f"{URLS['loans']}/prestamos", headers=headers, timeout=8)
listed.raise_for_status()
source = next((loan for loan in listed.json() if loan["status"] == "COMPLETADA"), None)
if not source:
    raise SystemExit("Necesita un préstamo COMPLETADA como fixture de perfil sintético")

tag = uuid.uuid4().hex
product_id = None
loan_id = None
stopped = False
report = {}


def cleanup():
    if stopped:
        subprocess.run(["docker", "compose", "start", "rabbitmq"], cwd=ROOT, check=True, capture_output=True, text=True)
    if loan_id:
        quoted = f"'{loan_id}'"
        code = f"from sqlalchemy import create_engine,text; import os; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); c.execute(text(\"DELETE FROM outbox WHERE loan_id IN ({quoted})\")); c.execute(text(\"DELETE FROM idempotency WHERE loan_id IN ({quoted})\")); c.execute(text(\"DELETE FROM loans WHERE id IN ({quoted})\")); c.commit()"
        subprocess.run(["docker", "compose", "exec", "-T", "loans", "python", "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)
        code = f"from sqlalchemy import create_engine,text; import os; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); c.execute(text(\"DELETE FROM movements WHERE loan_id={quoted}\")); c.execute(text(\"DELETE FROM reservations WHERE loan_id={quoted}\")); c.execute(text(\"DELETE FROM stock WHERE product_id={int(product_id)}\")); c.commit()"
        subprocess.run(["docker", "compose", "exec", "-T", "inventory", "python", "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)
    if product_id:
        code = f"from sqlalchemy import create_engine,text; import os; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); c.execute(text('DELETE FROM products WHERE id={int(product_id)}')); c.commit()"
        subprocess.run(["docker", "compose", "exec", "-T", "products", "python", "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)
        subprocess.run(["docker", "compose", "exec", "-T", "redis", "redis-cli", "DEL", f"products:v1:{product_id}"], cwd=ROOT, check=True, capture_output=True, text=True)


try:
    product = session.post(f"{URLS['products']}/products", headers=headers, json={"name": f"Autotest timeout {tag}", "category": "AUTOTEST", "price_cop": source["price_cop"]}, timeout=5)
    product.raise_for_status()
    product_id = product.json()["id"]
    stock = session.post(f"{URLS['inventory']}/inventory/stock", headers=headers, json={"product_id": product_id, "quantity": source["quantity"]}, timeout=5)
    stock.raise_for_status()

    subprocess.run(["docker", "compose", "stop", "rabbitmq"], cwd=ROOT, check=True, capture_output=True, text=True)
    stopped = True
    response = session.post(f"{URLS['loans']}/prestamos", headers={**headers, "Idempotency-Key": f"timeout-{tag}"}, json={
        "customer_id": source["customer_id"], "product_id": product_id,
        "quantity": source["quantity"], "term_months": source["term_months"],
    }, timeout=10)
    response.raise_for_status()
    loan_id = response.json()["id"]
    if response.status_code != 202 or response.json()["status"] != "PENDIENTE_INVENTARIO":
        raise AssertionError(f"Expected initial pending state, got {response.status_code} {response.text}")

    created_at = time.monotonic()
    deadline = created_at + 150
    timed_out = False
    while time.monotonic() < deadline:
        current = session.get(f"{URLS['loans']}/prestamos/{loan_id}", headers=headers, timeout=5)
        current.raise_for_status()
        if current.json()["status"] == "CANCELACION_PENDIENTE":
            timed_out = True
            break
        time.sleep(2)
    if not timed_out or time.monotonic() - created_at < 120:
        raise AssertionError("Pending loan did not time out at the configured two-minute boundary")

    subprocess.run(["docker", "compose", "start", "rabbitmq"], cwd=ROOT, check=True, capture_output=True, text=True)
    stopped = False
    for _ in range(60):
        current = session.get(f"{URLS['loans']}/prestamos/{loan_id}", headers=headers, timeout=5)
        current.raise_for_status()
        if current.json()["status"] == "CANCELADA":
            break
        time.sleep(1)
    else:
        raise AssertionError(f"Loan did not converge to CANCELADA after broker recovery: {current.text}")

    reservation_list = session.get(f"{URLS['inventory']}/inventory/reservations", headers=headers, timeout=5)
    reservation_list.raise_for_status()
    reservation = next((r for r in reservation_list.json() if r["loan_id"] == loan_id), None)
    if not reservation or reservation["status"] != "RELEASED":
        raise AssertionError(f"Timed out loan reservation was not released: {reservation}")
    stock_list = session.get(f"{URLS['inventory']}/inventory", headers=headers, timeout=5)
    stock_list.raise_for_status()
    stock_row = next(r for r in stock_list.json() if r["product_id"] == product_id)
    if stock_row["available"] != source["quantity"] or stock_row["reserved"] != 0:
        raise AssertionError(f"Stock was not restored: {stock_row}")
    report = {"initial_status": "PENDIENTE_INVENTARIO", "timeout_status": "CANCELACION_PENDIENTE", "final_status": "CANCELADA", "reservation_status": reservation["status"], "available_after_release": stock_row["available"], "reserved_after_release": stock_row["reserved"], "elapsed_seconds": round(time.monotonic() - created_at, 1), "passed": True}
finally:
    cleanup()

(ROOT / "artifacts" / "pending_timeout_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
