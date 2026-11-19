"""Simulate Inventory committing a message effect, losing its Rabbit ACK, and recovering by redelivery."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = 'http://localhost:8001'
CUSTOMERS = 'http://localhost:8002'
RABBIT_API = 'http://localhost:15672/api/queues/%2F/inventory.commands'


def env_values():
    env = os.environ.copy()
    for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def run(*args, check=True):
    return subprocess.run(args, cwd=ROOT, check=check, capture_output=True, text=True)


def db_json(service, code, oneoff=False):
    action = ['run', '--rm', '--no-deps', '-T', service] if oneoff else ['exec', '-T', service]
    return json.loads(run('docker', 'compose', *action, 'python', '-c', code).stdout.strip().splitlines()[-1])


def queue_state(session, auth):
    response = session.get(RABBIT_API, auth=auth, timeout=5)
    response.raise_for_status()
    return response.json()


def publish_command(event):
    code = f"""import asyncio,json,os
import aio_pika
async def main():
 conn=await aio_pika.connect_robust(os.environ['RABBIT_URL'])
 async with conn:
  ch=await conn.channel(publisher_confirms=True)
  ex=await ch.declare_exchange('credimarket.commands',aio_pika.ExchangeType.DIRECT,durable=True)
  await ex.publish(aio_pika.Message(json.dumps({event!r}).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key='reserva.solicitar',mandatory=True)
asyncio.run(main())
"""
    run('docker', 'compose', 'exec', '-T', 'loans', 'python', '-c', code)


def commit_without_ack(event_id):
    code = f"""import asyncio,json,os
import aio_pika
from domain_service.app import handle_inventory_command
async def main():
 conn=await aio_pika.connect_robust(os.environ['RABBIT_URL'])
 async with conn:
  ch=await conn.channel()
  q=await ch.declare_queue('inventory.commands',durable=True,arguments={{'x-dead-letter-exchange':'credimarket.retry'}})
  deadline=asyncio.get_running_loop().time()+15; msg=None
  while asyncio.get_running_loop().time()<deadline:
   msg=await q.get(no_ack=False,fail=False)
   if msg is not None: break
   await asyncio.sleep(.1)
  if msg is None: raise RuntimeError('message not delivered to manual consumer')
  d=json.loads(msg.body)
  if d['event_id']!={event_id!r}: raise RuntimeError('unexpected message on empty fixture queue')
  if not handle_inventory_command(d): raise RuntimeError('message was already processed before injected ACK loss')
  print(json.dumps({{'committed':True,'event_id':d['event_id'],'loan_id':d['prestamo_id']}}))
 # Channel/connection closes with delivery unacked: RabbitMQ requeues it.
asyncio.run(main())
"""
    result = run('docker', 'compose', 'run', '--rm', '--no-deps', '-T', 'inventory', 'python', '-c', code)
    return json.loads(result.stdout.strip().splitlines()[-1])


def read_effects(product_id, loan_id, event_id, oneoff=False):
    code = f"""import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 p={product_id!r}; loan={loan_id!r}; event={event_id!r}
 stock=c.execute(text('SELECT available,reserved FROM stock WHERE product_id=:p'),{{'p':p}}).mappings().one()
 r=c.execute(text('SELECT status,product_id,quantity FROM reservations WHERE loan_id=:id'),{{'id':loan}}).mappings().one()
 out={{'stock':dict(stock),'reservation':dict(r),'reserve_movements':c.execute(text(\"SELECT count(*) FROM movements WHERE loan_id=:id AND kind='RESERVE'\"),{{'id':loan}}).scalar(),
 'reserve_events':c.execute(text(\"SELECT count(*) FROM outbox WHERE loan_id=:id AND type='InventarioReservado'\"),{{'id':loan}}).scalar(),
 'processed_message_rows':c.execute(text('SELECT count(*) FROM processed_messages WHERE event_id=:e'),{{'e':event}}).scalar()}}
 print(json.dumps(out))
"""
    return db_json('inventory', code, oneoff=oneoff)


def cleanup(product_id, loan_id, event_id):
    inv = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c:
 for table in ('movements','reservations','outbox'): c.execute(text(f'DELETE FROM {{table}} WHERE loan_id=:id'),{{'id':{loan_id!r}}})
 c.execute(text('DELETE FROM processed_messages WHERE event_id=:event'),{{'event':{event_id!r}}})
 c.execute(text('DELETE FROM stock WHERE product_id=:id'),{{'id':{product_id!r}}})
"""
    prod = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':{product_id!r}}})
"""
    run('docker', 'compose', 'exec', '-T', 'inventory', 'python', '-c', inv)
    run('docker', 'compose', 'exec', '-T', 'products', 'python', '-c', prod)
    run('docker', 'compose', 'exec', '-T', 'redis', 'redis-cli', 'DEL', f'products:v1:{product_id}')


def main():
    env = env_values()
    session = requests.Session()
    auth = (env['RABBIT_USER'], env['RABBIT_PASSWORD'])
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            initial = queue_state(session, auth)
            break
        except requests.RequestException:
            time.sleep(.25)
    else:
        raise SystemExit('RabbitMQ Management API is unavailable')
    if initial['messages_ready'] or initial['messages_unacknowledged']:
        raise SystemExit('inventory.commands is not empty; refusing to touch pre-existing messages')

    login = session.post(f'{CUSTOMERS}/auth/login', json={'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=8)
    login.raise_for_status()
    headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
    tag = uuid.uuid4().hex
    product_id = loan_id = None
    event_id = str(uuid.uuid4())
    stopped = False
    published = committed = False
    try:
        created = session.post(f'{PRODUCTS}/products', headers=headers, json={
            'name': f'IDEM02 ACK-loss fixture {tag}', 'category': 'AUTOTEST', 'price_cop': 1}, timeout=8)
        created.raise_for_status()
        product_id = created.json()['id']
        loan_id = str(uuid.uuid4())
        stock = session.post('http://localhost:8004/inventory/stock', headers=headers,
                             json={'product_id': product_id, 'quantity': 5}, timeout=8)
        stock.raise_for_status()
        event = {'event_id': event_id, 'type': 'ReservaSolicitada', 'schema_version': 1,
                 'occurred_at': '2026-11-18T00:00:00+00:00', 'correlation_id': loan_id,
                 'prestamo_id': loan_id, 'payload': {'producto_id': product_id, 'cantidad': 1}}

        run('docker', 'compose', 'stop', 'inventory')
        stopped = True
        publish_command(event)
        published = True
        manual = commit_without_ack(event_id)
        committed = manual['committed']
        before_redelivery = read_effects(product_id, loan_id, event_id, oneoff=True)
        if before_redelivery != {'stock': {'available': 4, 'reserved': 1},
                                 'reservation': {'status': 'RESERVED', 'product_id': product_id, 'quantity': 1},
                                 'reserve_movements': 1, 'reserve_events': 1, 'processed_message_rows': 1}:
            raise AssertionError(f'Unexpected committed effects before redelivery: {before_redelivery}')

        run('docker', 'compose', 'start', 'inventory')
        stopped = False
        health_deadline = time.monotonic() + 30
        while time.monotonic() < health_deadline:
            try:
                if session.get('http://localhost:8004/health', timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(.25)
        else:
            raise AssertionError('Inventory did not become healthy after restart')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = queue_state(session, auth)
            after = read_effects(product_id, loan_id, event_id)
            if state['messages_ready'] == 0 and state['messages_unacknowledged'] == 0:
                break
            time.sleep(.2)
        else:
            raise AssertionError(f'Redelivered message was not acknowledged; queue={state}')
        if after != before_redelivery:
            raise AssertionError(f'Redelivery after commit duplicated business effects: {before_redelivery} -> {after}')
        print(json.dumps({'initial_queue': {'ready': initial['messages_ready'], 'unacknowledged': initial['messages_unacknowledged']},
                          'failure_window': 'transaction committed; channel closed before ACK',
                          'manual_delivery': manual, 'after_commit_before_redelivery': before_redelivery,
                          'after_real_consumer_redelivery': after, 'queue_after_recovery': {
                              'ready': state['messages_ready'], 'unacknowledged': state['messages_unacknowledged']},
                          'business_effects_duplicated': False, 'cleanup': 'completed'}, indent=2))
    finally:
        if stopped:
            run('docker', 'compose', 'start', 'inventory', check=False)
        if product_id is not None and committed and not stopped:
            # Only delete this fixture after the main queue is drained and the committed marker is present.
            current = queue_state(session, auth)
            effects = read_effects(product_id, loan_id, event_id)
            if current['messages_ready'] == 0 and current['messages_unacknowledged'] == 0 and effects['processed_message_rows'] == 1:
                cleanup(product_id, loan_id, event_id)
            else:
                print(json.dumps({'cleanup': 'skipped to preserve a pending/unprocessed fixture', 'queue': current}))


if __name__ == '__main__':
    main()
