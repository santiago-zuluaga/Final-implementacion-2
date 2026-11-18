"""Verify cache invalidation and price/version snapshot in a loan."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def env_values():
    values = os.environ.copy()
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values.setdefault(key.strip(), value.strip())
    return values


def run_python(service, code):
    return subprocess.run(['docker', 'compose', 'exec', '-T', service, 'python', '-c', code], cwd=ROOT, check=True, capture_output=True, text=True)


def cleanup(product_id, loan_id):
    pid, lid = repr(product_id), repr(loan_id)
    if loan_id:
        loan_code = f"""import os,uuid
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c:
 events=c.execute(text(\"SELECT event_id FROM outbox WHERE loan_id=:id AND type='ReservaSolicitada'\"),{{'id':{lid}}}).scalars().all()
 for event_id in events:
  for kind in ('InventarioReservado','InventarioInsuficiente'):
   c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':str(uuid.uuid5(uuid.NAMESPACE_URL,event_id+kind))}})
 c.execute(text('DELETE FROM idempotency WHERE loan_id=:id'),{{'id':{lid}}})
 c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':{lid}}})
 c.execute(text('DELETE FROM loans WHERE id=:id'),{{'id':{lid}}})
"""
        run_python('loans', loan_code)
    inventory_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c:
 if {lid} is not None:
  for table in ('movements','reservations','outbox'):
   c.execute(text(f'DELETE FROM {{table}} WHERE loan_id=:id'),{{'id':{lid}}})
 c.execute(text('DELETE FROM movements WHERE product_id=:id'),{{'id':{pid}}})
 c.execute(text('DELETE FROM stock WHERE product_id=:id'),{{'id':{pid}}})
"""
    product_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':{pid}}})
"""
    run_python('inventory', inventory_code)
    run_python('products', product_code)
    subprocess.run(['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'DEL', f'products:v1:{product_id}'], cwd=ROOT, check=True, capture_output=True)


def main():
    env = env_values()
    urls = {name: os.environ.get(f'CREDIMARKET_{name.upper()}_URL', f'http://localhost:{port}').rstrip('/') for name, port in (('customers', 8002), ('products', 8001), ('loans', 8003), ('inventory', 8004))}
    session = requests.Session()
    login = session.post(f"{urls['customers']}/auth/login", json={'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=5)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    listed = session.get(f"{urls['loans']}/prestamos", headers=headers, timeout=10)
    listed.raise_for_status()
    source = next((loan for loan in listed.json() if loan['status'] == 'COMPLETADA'), None)
    if not source:
        raise SystemExit('Necesita un préstamo COMPLETADA sintético como fixture de riesgo')

    product_id = loan_id = None
    try:
        created = session.post(f"{urls['products']}/products", headers=headers, json={
            'name': 'Autotest temporal ACC09', 'category': 'AUTOTEST', 'price_cop': source['price_cop'],
        }, timeout=5)
        created.raise_for_status()
        product_id = created.json()['id']
        product_url = f"{urls['products']}/products/{product_id}"
        session.get(product_url, timeout=5).raise_for_status()  # warm the initial cache value
        new_price = source['price_cop'] + 1
        updated = session.put(product_url, headers=headers, json={
            'name': 'Autotest temporal ACC09', 'category': 'AUTOTEST', 'price_cop': new_price,
        }, timeout=5)
        updated.raise_for_status()
        cached_read = session.get(product_url, timeout=5)
        cached_read.raise_for_status()
        if cached_read.json()['price_cop'] != new_price or cached_read.json()['version'] != 2:
            raise AssertionError('Product cache was not invalidated after price update')

        internal = {'X-Internal-Token': env['INTERNAL_API_TOKEN']}
        quotation = session.get(f'{product_url}/quotation', headers=internal, timeout=5)
        quotation.raise_for_status()
        if quotation.json()['price_cop'] != new_price or quotation.json()['version'] != 2:
            raise AssertionError('Authoritative quotation did not return the updated price/version')

        stock = session.post(f"{urls['inventory']}/inventory/stock", headers=headers, json={'product_id': product_id, 'quantity': source['quantity']}, timeout=5)
        stock.raise_for_status()
        body = {'customer_id': source['customer_id'], 'product_id': product_id, 'quantity': source['quantity'], 'term_months': source['term_months']}
        loan = session.post(f"{urls['loans']}/prestamos", headers={**headers, 'Idempotency-Key': f'acc09-{uuid.uuid4()}'}, json=body, timeout=10)
        loan.raise_for_status()
        loan_id = loan.json()['id']
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = session.get(f"{urls['loans']}/prestamos/{loan_id}", headers=headers, timeout=5)
            result.raise_for_status()
            result = result.json()
            if result['status'] != 'PENDIENTE_INVENTARIO':
                break
            time.sleep(.2)
        if result['status'] != 'APROBADA':
            raise AssertionError(f"Expected APROBADA, got {result['status']}")
        if result['price_cop'] != new_price or result['product_version'] != 2:
            raise AssertionError('Loan did not persist the current product price/version')
        print(json.dumps({
            'cache_invalidated': True,
            'quotation_version': quotation.json()['version'],
            'loan_status': result['status'],
            'loan_used_current_price': result['price_cop'] == new_price,
            'loan_used_current_product_version': result['product_version'] == 2,
            'temporary_rows_cleanup': 'completed',
        }, indent=2))
    finally:
        if product_id is not None:
            cleanup(product_id, loan_id)


if __name__ == '__main__':
    main()
