"""Verify cancellation, late events and reservation expiry over RabbitMQ."""
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
    return subprocess.run(['docker', 'compose', 'exec', '-T', service, 'python', '-c', code], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def cleanup(product_ids, loan_ids, late_event_id):
    pids, lids, late = repr(product_ids), repr(loan_ids), repr(late_event_id)
    loans_code = f"""import os,uuid
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={lids}; late={late}
with e.begin() as c:
 for loan_id in ids:
  events=c.execute(text('SELECT event_id,type FROM outbox WHERE loan_id=:id'),{{'id':loan_id}}).all()
  for event_id,typ in events:
   kinds=('InventarioReservado','InventarioInsuficiente') if typ=='ReservaSolicitada' else ('ReservaLiberada',)
   for kind in kinds:
    c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':str(uuid.uuid5(uuid.NAMESPACE_URL,event_id+kind))}})
  expiry=str(uuid.uuid5(uuid.NAMESPACE_URL,'expiry:'+loan_id))
  c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':expiry}})
  c.execute(text('DELETE FROM idempotency WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM loans WHERE id=:id'),{{'id':loan_id}})
 if late: c.execute(text('DELETE FROM processed_messages WHERE event_id=:id'),{{'id':late}})
"""
    inventory_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={lids}; pids={pids}
with e.begin() as c:
 for loan_id in ids:
  for table in ('movements','reservations','outbox'):
   c.execute(text(f'DELETE FROM {{table}} WHERE loan_id=:id'),{{'id':loan_id}})
 for product_id in pids:
  c.execute(text('DELETE FROM movements WHERE product_id=:id'),{{'id':product_id}})
  c.execute(text('DELETE FROM stock WHERE product_id=:id'),{{'id':product_id}})
"""
    products_code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={pids}
with e.begin() as c:
 for product_id in ids: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':product_id}})
"""
    for service, code in (('loans', loans_code), ('inventory', inventory_code), ('products', products_code)):
        docker_python(service, code)
    for product_id in product_ids:
        subprocess.run(['docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'DEL', f'products:v1:{product_id}'], cwd=ROOT, check=True, capture_output=True)


def main():
    env = env_values()
    ports = {'customers': 8002, 'products': 8001, 'loans': 8003, 'inventory': 8004}
    urls = {name: os.environ.get(f'CREDIMARKET_{name.upper()}_URL', f'http://localhost:{port}').rstrip('/') for name, port in ports.items()}
    session = requests.Session()
    login = session.post(f"{urls['customers']}/auth/login", json={'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=5)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    listed = session.get(f"{urls['loans']}/prestamos", headers=headers, timeout=10)
    listed.raise_for_status()
    source = next((loan for loan in listed.json() if loan['status'] == 'COMPLETADA'), None)
    if not source:
        raise SystemExit('Necesita un préstamo COMPLETADA sintético como fixture de riesgo')

    product_ids = []
    loan_ids = []
    late_event_id = None
    try:
        body = None
        for label in ('cancel', 'expiry'):
            created = session.post(f"{urls['products']}/products", headers=headers, json={
                'name': f'Autotest temporal ACC07 {label}', 'category': 'AUTOTEST', 'price_cop': source['price_cop'],
            }, timeout=5)
            created.raise_for_status()
            product_id = created.json()['id']
            product_ids.append(product_id)
            stock = session.post(f"{urls['inventory']}/inventory/stock", headers=headers, json={'product_id': product_id, 'quantity': source['quantity']}, timeout=5)
            stock.raise_for_status()
            body = {'customer_id': source['customer_id'], 'product_id': product_id, 'quantity': source['quantity'], 'term_months': source['term_months']}
            loan = session.post(f"{urls['loans']}/prestamos", headers={**headers, 'Idempotency-Key': f'acc07-{label}-{uuid.uuid4()}'}, json=body, timeout=10)
            loan.raise_for_status()
            loan_id = loan.json()['id']
            loan_ids.append(loan_id)

            def get_loan():
                response = session.get(f"{urls['loans']}/prestamos/{loan_id}", headers=headers, timeout=5)
                response.raise_for_status()
                return response.json()

            deadline = time.monotonic() + 30
            current = get_loan()
            while current['status'] == 'PENDIENTE_INVENTARIO' and time.monotonic() < deadline:
                time.sleep(.2)
                current = get_loan()
            if current['status'] != 'APROBADA':
                raise AssertionError(f"Expected APROBADA before {label}, got {current['status']}")

            if label == 'cancel':
                cancelled = session.post(f"{urls['loans']}/prestamos/{loan_id}/cancel", headers=headers, timeout=5)
                cancelled.raise_for_status()
                deadline = time.monotonic() + 30
                current = get_loan()
                while current['status'] == 'CANCELACION_PENDIENTE' and time.monotonic() < deadline:
                    time.sleep(.2)
                    current = get_loan()
                if current['status'] != 'CANCELADA':
                    raise AssertionError(f"Cancellation ended in {current['status']}")

                late_event_id = str(uuid.uuid4())
                late_doc = {
                    'event_id': late_event_id, 'type': 'InventarioReservado', 'schema_version': 1,
                    'occurred_at': '2026-11-18T00:00:00+00:00', 'correlation_id': loan_id,
                    'prestamo_id': loan_id, 'payload': {'producto_id': product_id, 'cantidad': source['quantity']},
                }
                publish_code = f"""import asyncio,json,os
import aio_pika
async def run():
 conn=await aio_pika.connect_robust(os.environ['RABBIT_URL'])
 async with conn:
  ch=await conn.channel(publisher_confirms=True)
  ex=await ch.declare_exchange('credimarket.events',aio_pika.ExchangeType.TOPIC,durable=True)
  await ex.publish(aio_pika.Message(json.dumps({late_doc!r}).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key='inventario.reservado',mandatory=True)
asyncio.run(run())
"""
                docker_python('loans', publish_code)
                time.sleep(1)
                current = get_loan()
                inv = session.get(f"{urls['inventory']}/inventory", headers=headers, timeout=5)
                inv.raise_for_status()
                row = next(x for x in inv.json() if x['product_id'] == product_id)
                reservations = session.get(f"{urls['inventory']}/inventory/reservations", headers=headers, timeout=5).json()
                reservation = next(x for x in reservations if x['loan_id'] == loan_id)
                if current['status'] != 'CANCELADA' or row['available'] != source['quantity'] or row['reserved'] != 0 or reservation['status'] != 'RELEASED':
                    raise AssertionError('Late event reactivated loan or failed to release stock')
                cancel_result = {'status_after_late_event': current['status'], 'reservation': reservation['status'], 'available': row['available'], 'reserved': row['reserved']}
            else:
                expire = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c: c.execute(text('UPDATE reservations SET expires_at=now()-make_interval(secs=>1) WHERE loan_id=:id'),{{'id':{loan_id!r}}})
"""
                docker_python('inventory', expire)
                deadline = time.monotonic() + 60
                current = get_loan()
                while current['status'] == 'APROBADA' and time.monotonic() < deadline:
                    time.sleep(.5)
                    current = get_loan()
                if current['status'] != 'CANCELADA':
                    raise AssertionError(f"Expired reservation ended in loan state {current['status']}")
                inv = session.get(f"{urls['inventory']}/inventory", headers=headers, timeout=5)
                inv.raise_for_status()
                row = next(x for x in inv.json() if x['product_id'] == product_id)
                reservations = session.get(f"{urls['inventory']}/inventory/reservations", headers=headers, timeout=5).json()
                reservation = next(x for x in reservations if x['loan_id'] == loan_id)
                if row['available'] != source['quantity'] or row['reserved'] != 0 or reservation['status'] != 'EXPIRED':
                    raise AssertionError('Expiry did not release stock coherently')
                expiry_result = {'status': current['status'], 'reservation': reservation['status'], 'available': row['available'], 'reserved': row['reserved']}

        print(json.dumps({'cancel_and_late_event': cancel_result, 'reservation_expiry': expiry_result, 'temporary_rows_cleanup': 'completed'}, indent=2))
    finally:
        if product_ids:
            cleanup(product_ids, loan_ids, late_event_id)


if __name__ == '__main__':
    main()
