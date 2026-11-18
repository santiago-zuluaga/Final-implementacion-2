"""Exercise no-stock and last-unit concurrency against the local Compose stack."""
import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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


def cleanup(product_id, loan_ids):
    ids = repr(loan_ids)
    loans_code = f"""import os,uuid
from sqlalchemy import create_engine,text
engine=create_engine(os.environ['DATABASE_URL'])
ids={ids}
with engine.begin() as c:
 for loan_id in ids:
  command_ids=c.execute(text(\"SELECT event_id FROM outbox WHERE loan_id=:id AND type='ReservaSolicitada'\"),{{'id':loan_id}}).scalars().all()
  for event_id in command_ids:
   for kind in ('InventarioReservado','InventarioInsuficiente'):
    processed=str(uuid.uuid5(uuid.NAMESPACE_URL,event_id+kind))
    c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':processed}})
  c.execute(text('DELETE FROM idempotency WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM loans WHERE id=:id'),{{'id':loan_id}})
"""
    inventory_code = f"""import os
from sqlalchemy import create_engine,text
engine=create_engine(os.environ['DATABASE_URL'])
ids={ids}; product_id={product_id!r}
with engine.begin() as c:
 for loan_id in ids:
  c.execute(text('DELETE FROM reservations WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM movements WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':loan_id}})
 c.execute(text('DELETE FROM movements WHERE product_id=:id'),{{'id':product_id}})
 c.execute(text('DELETE FROM stock WHERE product_id=:id'),{{'id':product_id}})
"""
    products_code = f"""import os
from sqlalchemy import create_engine,text
engine=create_engine(os.environ['DATABASE_URL'])
with engine.begin() as c: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':{product_id!r}}})
"""
    for service, code in (('loans', loans_code), ('inventory', inventory_code), ('products', products_code)):
        subprocess.run(['docker', 'compose', 'exec', '-T', service, 'python', '-c', code], cwd=ROOT, check=True, capture_output=True, text=True)


def main():
    env = env_values()
    session = requests.Session()
    customers_url = os.environ.get('CREDIMARKET_CUSTOMERS_URL', 'http://localhost:8002').rstrip('/')
    products_url = os.environ.get('CREDIMARKET_PRODUCTS_URL', 'http://localhost:8001').rstrip('/')
    loans_url = os.environ.get('CREDIMARKET_LOANS_URL', 'http://localhost:8003').rstrip('/')
    inventory_url = os.environ.get('CREDIMARKET_INVENTORY_URL', 'http://localhost:8004').rstrip('/')
    login = session.post(f'{customers_url}/auth/login', json={'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=5)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    listed = session.get(f'{loans_url}/prestamos', headers=headers, timeout=10)
    listed.raise_for_status()
    source = next((loan for loan in listed.json() if loan['status'] == 'COMPLETADA'), None)
    if not source:
        raise SystemExit('Necesita al menos un préstamo COMPLETADA existente como fixture sintético')

    product_id = None
    loan_ids = []
    try:
        product = session.post(f'{products_url}/products', headers=headers, json={
            'name': 'Autotest temporal ACC03 ACC04', 'category': 'AUTOTEST', 'price_cop': source['price_cop'],
        }, timeout=5)
        product.raise_for_status()
        product_id = product.json()['id']
        request_body = {
            'customer_id': source['customer_id'], 'product_id': product_id,
            'quantity': source['quantity'], 'term_months': source['term_months'],
        }

        def submit(key):
            response = requests.post(f'{loans_url}/prestamos', headers={**headers, 'Idempotency-Key': key}, json=request_body, timeout=10)
            response.raise_for_status()
            return response.json()['id']

        no_stock_id = submit(f'acc03-{uuid.uuid4()}')
        loan_ids.append(no_stock_id)

        def state(loan_id):
            response = session.get(f'{loans_url}/prestamos/{loan_id}', headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()

        deadline = time.monotonic() + 30
        no_stock = state(no_stock_id)
        while no_stock['status'] == 'PENDIENTE_INVENTARIO' and time.monotonic() < deadline:
            time.sleep(.2)
            no_stock = state(no_stock_id)
        if no_stock['status'] != 'CANCELADA_SIN_STOCK':
            raise AssertionError(f"No-stock case ended in {no_stock['status']}")

        stock = session.post(f'{inventory_url}/inventory/stock', headers=headers, json={'product_id': product_id, 'quantity': 1}, timeout=5)
        stock.raise_for_status()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, f'acc04-{uuid.uuid4()}') for _ in range(2)]
            concurrent_ids = [future.result() for future in futures]
        loan_ids.extend(concurrent_ids)

        deadline = time.monotonic() + 30
        concurrent = [state(loan_id) for loan_id in concurrent_ids]
        while any(loan['status'] == 'PENDIENTE_INVENTARIO' for loan in concurrent) and time.monotonic() < deadline:
            time.sleep(.2)
            concurrent = [state(loan_id) for loan_id in concurrent_ids]
        statuses = sorted(loan['status'] for loan in concurrent)
        inventory = session.get(f'{inventory_url}/inventory', headers=headers, timeout=5)
        inventory.raise_for_status()
        stock_row = next((row for row in inventory.json() if row['product_id'] == product_id), None)
        expected = ['APROBADA', 'CANCELADA_SIN_STOCK']
        if statuses != expected or not stock_row or stock_row['available'] != 0 or stock_row['reserved'] != 1:
            raise AssertionError(f'Last-unit case mismatch: statuses={statuses}, stock={stock_row}')
        print(json.dumps({
            'no_stock_status': no_stock['status'],
            'last_unit_statuses': statuses,
            'available_after_race': stock_row['available'],
            'reserved_after_race': stock_row['reserved'],
            'temporary_rows_cleanup': 'completed',
        }, indent=2))
    finally:
        if product_id is not None:
            cleanup(product_id, loan_ids)


if __name__ == '__main__':
    main()
