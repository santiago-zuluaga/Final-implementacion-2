"""Exercise loan schema and business validation against the real Docker APIs."""
import json
import os
import subprocess
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CUSTOMERS = os.getenv("CREDIMARKET_CUSTOMERS_URL", "http://localhost:8002").rstrip("/")
PRODUCTS = os.getenv("CREDIMARKET_PRODUCTS_URL", "http://localhost:8001").rstrip("/")
LOANS = os.getenv("CREDIMARKET_LOANS_URL", "http://localhost:8003").rstrip("/")
INVENTORY = os.getenv("CREDIMARKET_INVENTORY_URL", "http://localhost:8004").rstrip("/")
session = requests.Session()
login = session.post(f"{CUSTOMERS}/auth/login", json={"username": os.environ["ADMIN_USERNAME"], "password": os.environ["ADMIN_PASSWORD"]}, timeout=5)
login.raise_for_status()
headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
tag = uuid.uuid4().hex
customer_ids = [f"validation-{tag}-{n}" for n in range(3)]
loan_ids: list[str] = []
product_ids: list[int] = []
checks = {}


def create_product(name, price):
    response = session.post(f"{PRODUCTS}/products", headers=headers, json={"name": name, "category": "AUTOTEST", "price_cop": price}, timeout=5)
    response.raise_for_status()
    product_id = response.json()["id"]
    product_ids.append(product_id)
    return product_id


def create_customer(index, *, income, active, employment="dependiente"):
    body = {
        "id": customer_ids[index], "name": "Autotest temporal", "income": income,
        "obligations": 0, "employment": employment, "tenure_months": 120,
        "history_months": 180, "prior_credits": 2, "late_payments": 0,
        "payment_on_time": 100, "active": active,
    }
    response = session.post(f"{CUSTOMERS}/customers", headers=headers, json=body, timeout=5)
    response.raise_for_status()


def submit(customer_id, product_id, quantity, term):
    response = session.post(f"{LOANS}/prestamos", headers={**headers, "Idempotency-Key": f"validation-{uuid.uuid4()}"}, json={
        "customer_id": customer_id, "product_id": product_id, "quantity": quantity, "term_months": term,
    }, timeout=8)
    if response.status_code in (200, 202):
        loan_ids.append(response.json()["id"])
    return response


try:
    small = create_product(f"Autotest validación {tag}", 1000)
    large = create_product(f"Autotest monto límite {tag}", 600_000_000)
    create_customer(0, income=30_000_000, active=False)
    create_customer(1, income=0, active=True)
    create_customer(2, income=100_000_000, active=True)

    bad_quantity = submit(customer_ids[2], small, 0, 12)
    bad_term = submit(customer_ids[2], small, 1, 61)
    checks["quantity_zero_422"] = bad_quantity.status_code == 422
    checks["term_over_schema_limit_422"] = bad_term.status_code == 422
    if not all((checks["quantity_zero_422"], checks["term_over_schema_limit_422"])):
        raise AssertionError(f"Schema validation failed: {bad_quantity.status_code}, {bad_term.status_code}")

    too_large = submit(customer_ids[2], large, 2, 12)
    checks["amount_over_limit_422"] = too_large.status_code == 422 and "amount" in too_large.text.lower()
    if not checks["amount_over_limit_422"]:
        raise AssertionError(f"Amount bound failed: {too_large.status_code} {too_large.text}")

    inactive = submit(customer_ids[0], small, 1, 12)
    zero_income = submit(customer_ids[1], small, 1, 12)
    checks["inactive_customer_rejected"] = inactive.status_code == 200 and inactive.json().get("reason") == "CLIENTE_INACTIVO"
    checks["zero_income_rejected"] = zero_income.status_code == 200 and zero_income.json().get("reason") == "INGRESO_INVALIDO"
    if not checks["inactive_customer_rejected"] or not checks["zero_income_rejected"]:
        raise AssertionError(f"Business validation failed: {inactive.text}; {zero_income.text}")

    term = submit(customer_ids[2], small, 1, 37)
    checks["term_37_business_rejection"] = term.status_code == 200 and term.json().get("reason") == "PLAZO_INVALIDO"
    if not checks["term_37_business_rejection"]:
        raise AssertionError(f"Business term validation failed: {term.status_code} {term.text}")

    reservations = session.get(f"{INVENTORY}/inventory/reservations", headers=headers, timeout=5)
    reservations.raise_for_status()
    loans_with_reservations = {row["loan_id"] for row in reservations.json()}
    checks["rejections_created_no_reservation"] = all(loan_id not in loans_with_reservations for loan_id in loan_ids)
    if not checks["rejections_created_no_reservation"]:
        raise AssertionError("A rejected validation probe created an inventory reservation")
    report = {"cases": checks, "statuses": {"inactive": inactive.json()["status"], "zero_income": zero_income.json()["status"], "term_37": term.json()["status"]}, "loans_created": len(loan_ids), "passed": all(checks.values())}
finally:
    loan_values = ",".join("'" + value.replace("'", "''") + "'" for value in loan_ids) or "'__none__'"
    cleanup_sql = f"from sqlalchemy import create_engine,text; e=create_engine(__import__('os').environ['DATABASE_URL']);\nwith e.begin() as c:\n c.execute(text(\"DELETE FROM outbox WHERE loan_id IN ({loan_values})\")); c.execute(text(\"DELETE FROM idempotency WHERE loan_id IN ({loan_values})\")); c.execute(text(\"DELETE FROM loans WHERE id IN ({loan_values})\"))"
    subprocess.run(["docker", "compose", "exec", "-T", "loans", "python", "-c", cleanup_sql], cwd=ROOT, check=True, capture_output=True, text=True)
    customer_values = ",".join("'" + value.replace("'", "''") + "'" for value in customer_ids)
    customer_sql = f"from sqlalchemy import create_engine,text; e=create_engine(__import__('os').environ['DATABASE_URL']);\nwith e.begin() as c: c.execute(text(\"DELETE FROM customers WHERE id IN ({customer_values})\"))"
    subprocess.run(["docker", "compose", "exec", "-T", "customers", "python", "-c", customer_sql], cwd=ROOT, check=True, capture_output=True, text=True)
    for product_id in product_ids:
        product_sql = f"from sqlalchemy import create_engine,text; import redis,os; e=create_engine(os.environ['DATABASE_URL']);\nwith e.begin() as c: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':{int(product_id)}}})"
        subprocess.run(["docker", "compose", "exec", "-T", "products", "python", "-c", product_sql], cwd=ROOT, check=True, capture_output=True, text=True)
        subprocess.run(["docker", "compose", "exec", "-T", "redis", "redis-cli", "DEL", f"products:v1:{product_id}"], cwd=ROOT, check=True, capture_output=True, text=True)

(ROOT / "artifacts" / "loan_validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
if not report["passed"]:
    raise SystemExit(1)
