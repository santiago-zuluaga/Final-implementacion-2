"""Verify outbox/queue recovery when RabbitMQ or Inventory is unavailable."""
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
    if (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values.setdefault(key.strip(), value.strip())
    return values


def docker(service, *args):
    return subprocess.run(['docker', 'compose', *args, service], cwd=ROOT, check=True, capture_output=True, text=True)


def service_python(service, code):
    return subprocess.run(['docker', 'compose', 'exec', '-T', service, 'python', '-c', code], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def cleanup(product_id, loan_ids):
    ids = repr(loan_ids)
    loans_code = f"""import os,uuid
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={ids}
with e.begin() as c:
 for loan_id in ids:
  events=c.execute(text(\"SELECT event_id FROM outbox WHERE loan_id=:id AND type='ReservaSolicitada'\"),{{'id':loan_id}}).scalars().all()
  for event_id in events:
   for kind in ('InventarioReservado','InventarioInsuficiente'):
    c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':str(uuid.uuid5(uuid.NAMESPACE_URL,event_id+kind))}})
  c.execute(text('DELETE FROM idempotency WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM loans WHERE id=:id'),{{'id':loan_id}})
"""
    inventory_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={ids}; pid={product_id!r}
with e.begin() as c:
 for loan_id in ids:
  for table in ('movements','reservations','outbox'):
   c.execute(text(f'DELETE FROM {{table}} WHERE loan_id=:id'),{{'id':loan_id}})
 c.execute(text('DELETE FROM movements WHERE product_id=:id'),{{'id':pid}})
 c.execute(text('DELETE FROM stock WHERE product_id=:id'),{{'id':pid}})
"""
    products_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':{product_id!r}}})
"""
    for service, code in (('loans', loans_code), ('inventory', inventory_code), ('products', products_code)):
        service_python(service, code)
    subprocess.run(['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'DEL', f'products:v1:{product_id}'], cwd=ROOT, check=True, capture_output=True)


def main():
    env = env_values()
    ports = {'customers': 8002, 'products': 8001, 'loans': 8003, 'inventory': 8004}
    urls = {name: os.environ.get(f'CREDIMARKET_{name.upper()}_URL', f'http://localhost:{port}').rstrip('/') for name, port in ports.items()}
    session = requests.Session()
    login = session.post(f"{urls['customers']}/auth/login", json={'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=5)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    loans = session.get(f"{urls['loans']}/prestamos", headers=headers, timeout=10)
    loans.raise_for_status()
    source = next((loan for loan in loans.json() if loan['status'] == 'COMPLETADA'), None)
    if not source:
        raise SystemExit('Necesita un préstamo COMPLETADA sintético como fixture de riesgo')

    product_id = None
    loan_ids = []
    rabbit_stopped = inventory_stopped = False
    try:
        created = session.post(f"{urls['products']}/products", headers=headers, json={
            'name': 'Autotest temporal ACC06', 'category': 'AUTOTEST', 'price_cop': source['price_cop'],
        }, timeout=5)
        created.raise_for_status()
        product_id = created.json()['id']
        stock = session.post(f"{urls['inventory']}/inventory/stock", headers=headers, json={
            'product_id': product_id, 'quantity': source['quantity'] * 2,
        }, timeout=5)
        stock.raise_for_status()
        body = {'customer_id': source['customer_id'], 'product_id': product_id, 'quantity': source['quantity'], 'term_months': source['term_months']}

        def submit(label):
            response = session.post(f"{urls['loans']}/prestamos", headers={**headers, 'Idempotency-Key': f'{label}-{uuid.uuid4()}'}, json=body, timeout=10)
            response.raise_for_status()
            return response.json()['id']

        def state(loan_id):
            response = session.get(f"{urls['loans']}/prestamos/{loan_id}", headers=headers, timeout=5)
            response.raise_for_status()
            return response.json()['status']

        def wait_for(loan_id, expected):
            deadline = time.monotonic() + 60
            current = state(loan_id)
            while current == 'PENDIENTE_INVENTARIO' and time.monotonic() < deadline:
                time.sleep(.25)
                current = state(loan_id)
            if current != expected:
                raise AssertionError(f'Loan recovery expected {expected}, got {current}')

        docker('rabbitmq', 'stop')
        rabbit_stopped = True
        broker_loan = submit('acc06-broker')
        loan_ids.append(broker_loan)
        time.sleep(1)
        pending_while_broker_down = state(broker_loan) == 'PENDIENTE_INVENTARIO'
        docker('rabbitmq', 'start')
        rabbit_stopped = False
        wait_for(broker_loan, 'APROBADA')

        docker('inventory', 'stop')
        inventory_stopped = True
        consumer_loan = submit('acc06-consumer')
        loan_ids.append(consumer_loan)
        time.sleep(1)
        pending_while_consumer_down = state(consumer_loan) == 'PENDIENTE_INVENTARIO'
        docker('inventory', 'start')
        inventory_stopped = False
        wait_for(consumer_loan, 'APROBADA')

        ids_literal = repr(loan_ids)
        check_code = f"""import os,json
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={ids_literal}
with e.connect() as c:
 rows=[]
 for loan_id in ids:
  rows.append({{'loan_id':loan_id,'movements':c.execute(text('SELECT count(*) FROM movements WHERE loan_id=:id'),{{'id':loan_id}}).scalar()}})
 print(json.dumps(rows))
"""
        effects = json.loads(service_python('inventory', check_code))
        if len(effects) != 2 or any(row['movements'] != 1 for row in effects):
            raise AssertionError(f'Unexpected recovered effects: {effects}')
        print(json.dumps({
            'broker_unavailable_left_pending': pending_while_broker_down,
            'broker_recovery_status': 'APROBADA',
            'consumer_unavailable_left_pending': pending_while_consumer_down,
            'consumer_recovery_status': 'APROBADA',
            'one_reserve_movement_per_loan': all(row['movements'] == 1 for row in effects),
            'temporary_rows_cleanup': 'completed',
        }, indent=2))
    finally:
        if inventory_stopped:
            docker('inventory', 'start')
        if rabbit_stopped:
            docker('rabbitmq', 'start')
        if product_id is not None:
            cleanup(product_id, loan_ids)


if __name__ == '__main__':
    main()
