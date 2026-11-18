"""Check HTTP and Rabbit command idempotency with temporary demo records."""
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


def docker_python(service, code):
    result = subprocess.run(['docker', 'compose', 'exec', '-T', service, 'python', '-c', code], cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def db_row(service, query, params):
    query_literal = repr(query)
    params_literal = repr(params)
    code = f"""import os,json
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 r=c.execute(text({query_literal}),{params_literal}).mappings().first()
 print(json.dumps(dict(r),default=str) if r else 'null')
"""
    value = docker_python(service, code)
    return json.loads(value) if value != 'null' else None


def counts(loan_id, product_id):
    ids = repr(loan_id)
    query_code = f"""import os,json
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 d={{'loan_id':{ids},'product_id':{product_id!r}}}
 r={{'movements':c.execute(text('SELECT count(*) FROM movements WHERE loan_id=:loan_id'),d).scalar(),
 'reservations':c.execute(text('SELECT count(*) FROM reservations WHERE loan_id=:loan_id'),d).scalar(),
 'reservation_status':c.execute(text('SELECT status FROM reservations WHERE loan_id=:loan_id'),d).scalar(),
 'inventory_events':c.execute(text(\"SELECT count(*) FROM outbox WHERE loan_id=:loan_id AND type='InventarioReservado'\"),d).scalar(),
 'stock':c.execute(text('SELECT available,reserved FROM stock WHERE product_id=:product_id'),d).mappings().first()}}
 print(json.dumps(r,default=dict))
"""
    return json.loads(docker_python('inventory', query_code))


def publish_duplicate(service, exchange_name, exchange_type, route, doc):
    code = f"""import asyncio,json,os
import aio_pika
async def run():
 conn=await aio_pika.connect_robust(os.environ['RABBIT_URL'])
 async with conn:
  ch=await conn.channel(publisher_confirms=True)
  ex=await ch.declare_exchange({exchange_name!r},aio_pika.ExchangeType.{exchange_type},durable=True)
  await ex.publish(aio_pika.Message(json.dumps({doc!r},default=str).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key={route!r},mandatory=True)
asyncio.run(run())
"""
    docker_python(service, code)


def cleanup(product_id, loan_id):
    lid, pid = repr(loan_id), repr(product_id)
    loan_code = f"""import os,uuid
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c:
 events=c.execute(text(\"SELECT event_id FROM outbox WHERE loan_id=:id AND type='ReservaSolicitada'\"),{{'id':{lid}}}).scalars().all()
 for event_id in events:
  for kind in ('InventarioReservado','InventarioInsuficiente'):
   processed=str(uuid.uuid5(uuid.NAMESPACE_URL,event_id+kind))
   c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':processed}})
 c.execute(text('DELETE FROM idempotency WHERE loan_id=:id'),{{'id':{lid}}})
 c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':{lid}}})
 c.execute(text('DELETE FROM loans WHERE id=:id'),{{'id':{lid}}})
"""
    inventory_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c:
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
    for service, code in (('loans', loan_code), ('inventory', inventory_code), ('products', product_code)):
        docker_python(service, code)
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
        product = session.post(f"{urls['products']}/products", headers=headers, json={
            'name': 'Autotest temporal ACC05', 'category': 'AUTOTEST', 'price_cop': source['price_cop'],
        }, timeout=5)
        product.raise_for_status()
        product_id = product.json()['id']
        stock = session.post(f"{urls['inventory']}/inventory/stock", headers=headers, json={'product_id': product_id, 'quantity': source['quantity']}, timeout=5)
        stock.raise_for_status()

        body = {'customer_id': source['customer_id'], 'product_id': product_id, 'quantity': source['quantity'], 'term_months': source['term_months']}
        key = f'acc05-{uuid.uuid4()}'
        first = session.post(f"{urls['loans']}/prestamos", headers={**headers, 'Idempotency-Key': key}, json=body, timeout=10)
        first.raise_for_status()
        loan_id = first.json()['id']
        repeated = session.post(f"{urls['loans']}/prestamos", headers={**headers, 'Idempotency-Key': key}, json=body, timeout=10)
        repeated.raise_for_status()
        changed = {**body, 'term_months': body['term_months'] + 1 if body['term_months'] < 36 else body['term_months'] - 1}
        conflict = session.post(f"{urls['loans']}/prestamos", headers={**headers, 'Idempotency-Key': key}, json=changed, timeout=10)
        if first.json()['id'] != repeated.json()['id'] or conflict.status_code != 409:
            raise AssertionError('HTTP idempotency behavior mismatch')

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = session.get(f"{urls['loans']}/prestamos/{loan_id}", headers=headers, timeout=5)
            current.raise_for_status()
            if current.json()['status'] == 'APROBADA':
                break
            time.sleep(.2)
        else:
            raise AssertionError('Loan did not reach APROBADA')

        command = db_row('loans', "SELECT event_id,type,created_at,correlation_id,loan_id,payload FROM outbox WHERE loan_id=:id AND type='ReservaSolicitada'", {'id': loan_id})
        if not command:
            raise AssertionError('Reservation command is absent from outbox')
        command_doc = {
            'event_id': command['event_id'], 'type': command['type'], 'schema_version': 1,
            'occurred_at': command['created_at'], 'correlation_id': command['correlation_id'],
            'prestamo_id': command['loan_id'], 'payload': command['payload'],
        }
        initial = counts(loan_id, product_id)
        publish_duplicate('inventory', 'credimarket.commands', 'DIRECT', 'reserva.solicitar', command_doc)
        time.sleep(1)
        after_command = counts(loan_id, product_id)

        event = db_row('inventory', "SELECT event_id,type,correlation_id,loan_id,payload,created_at FROM outbox WHERE loan_id=:id AND type='InventarioReservado'", {'id': loan_id})
        event_doc = {
            'event_id': event['event_id'], 'type': event['type'], 'schema_version': 1,
            'occurred_at': event['created_at'], 'correlation_id': event['correlation_id'],
            'prestamo_id': event['loan_id'], 'payload': event['payload'],
        }
        publish_duplicate('loans', 'credimarket.events', 'TOPIC', 'inventario.reservado', event_doc)
        time.sleep(1)
        final = counts(loan_id, product_id)
        if initial != after_command or initial != final:
            raise AssertionError(f'Duplicate event changed inventory effects: {initial} -> {after_command} -> {final}')
        if initial['movements'] != 1 or initial['reservations'] != 1 or initial['inventory_events'] != 1 or initial['reservation_status'] != 'RESERVED':
            raise AssertionError(f'Unexpected initial reservation effects: {initial}')
        print(json.dumps({
            'same_key_same_body_same_loan': first.json()['id'] == repeated.json()['id'],
            'same_key_changed_body_status': conflict.status_code,
            'initial_effects': initial,
            'effects_after_duplicate_command': after_command,
            'effects_after_duplicate_event': final,
            'temporary_rows_cleanup': 'completed',
        }, indent=2))
    finally:
        if product_id is not None:
            if loan_id:
                cleanup(product_id, loan_id)
            else:
                code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':{product_id!r}}})
"""
                docker_python('products', code)
                subprocess.run(['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'DEL', f'products:v1:{product_id}'], cwd=ROOT, check=True, capture_output=True)


if __name__ == '__main__':
    main()
