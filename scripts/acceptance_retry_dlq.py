"""Inject one malformed command and verify its retry/DLQ lifecycle."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MANAGEMENT = 'http://localhost:15672'
QUEUE_PATH = '/api/queues/%2F/inventory.commands.dlq'


def env_values():
    values = os.environ.copy()
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values.setdefault(key.strip(), value.strip())
    return values


def main():
    env = env_values()
    auth = (env['RABBIT_USER'], env['RABBIT_PASSWORD'])
    session = requests.Session()
    queue = session.get(MANAGEMENT + QUEUE_PATH, auth=auth, timeout=5)
    queue.raise_for_status()
    initial = queue.json()['messages_ready']
    if initial != 0:
        raise SystemExit(f'DLQ already contains {initial} message(s); refusing to alter existing failures')

    probe = f'acc06-dlq-{uuid.uuid4()}'
    stock_code = """import os,json
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 r=c.execute(text('SELECT product_id,available,reserved FROM stock WHERE available>0 ORDER BY product_id LIMIT 1')).mappings().first()
 print(json.dumps(dict(r) if r else None))
"""
    stock_row = json.loads(subprocess.run(['docker', 'compose', 'exec', '-T', 'inventory', 'python', '-c', stock_code], cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    if not stock_row:
        raise SystemExit('No hay stock de demo disponible para forzar rollback transaccional')
    product_id = stock_row['product_id']
    movements_before = int(subprocess.run(['docker', 'compose', 'exec', '-T', 'inventory', 'python', '-c',
        f"import os; from sqlalchemy import create_engine,text; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); print(c.execute(text('SELECT count(*) FROM movements WHERE product_id=:id'),{{'id':{product_id}}}).scalar())"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip())
    doc = {
        'event_id': str(uuid.uuid4()), 'type': 'ReservaSolicitada', 'schema_version': 1,
        'occurred_at': '2026-11-18T00:00:00+00:00', 'correlation_id': probe,
        'prestamo_id': None, 'probe_id': probe,
        # Stock update succeeds provisionally; the NOT NULL reservation constraint fails inside the same transaction.
        'payload': {'producto_id': product_id, 'cantidad': 1},
    }
    code = f"""import asyncio,json,os
import aio_pika
async def run():
 conn=await aio_pika.connect_robust(os.environ['RABBIT_URL'])
 async with conn:
  ch=await conn.channel(publisher_confirms=True)
  ex=await ch.declare_exchange('credimarket.commands',aio_pika.ExchangeType.DIRECT,durable=True)
  await ex.publish(aio_pika.Message(json.dumps({doc!r}).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key='reserva.solicitar',mandatory=True)
asyncio.run(run())
"""
    subprocess.run(['docker', 'compose', 'exec', '-T', 'inventory', 'python', '-c', code], cwd=ROOT, check=True, capture_output=True, text=True)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(1)
        queue = session.get(MANAGEMENT + QUEUE_PATH, auth=auth, timeout=5)
        queue.raise_for_status()
        state = queue.json()
        if state['messages_ready'] == 1 and state['messages_unacknowledged'] == 0:
            break
    else:
        raise AssertionError('Probe did not reach the inventory DLQ')

    received = session.post(MANAGEMENT + QUEUE_PATH + '/get', auth=auth, json={
        'count': 1, 'ackmode': 'ack_requeue_false', 'encoding': 'auto', 'truncate': 50000,
    }, timeout=5)
    received.raise_for_status()
    messages = received.json()
    if len(messages) != 1:
        raise AssertionError(f'Expected one probe message in DLQ, got {len(messages)}')
    message = messages[0]
    payload = message.get('payload', '')
    headers = message.get('properties', {}).get('headers', {})
    if probe not in payload or headers.get('failure') != 'retry limit exceeded' or int(headers.get('attempts', 0)) < 3:
        raise AssertionError(f'DLQ message did not match the probe/retry expectation: {headers}')
    effects_code = f"""import os,json
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); product_id={product_id!r}; probe={probe!r}
with e.connect() as c:
 stock=c.execute(text('SELECT product_id,available,reserved FROM stock WHERE product_id=:id'),{{'id':product_id}}).mappings().one()
 result={{'stock':dict(stock),'movements':c.execute(text('SELECT count(*) FROM movements WHERE product_id=:id'),{{'id':product_id}}).scalar(),
 'outbox':c.execute(text('SELECT count(*) FROM outbox WHERE correlation_id=:probe'),{{'probe':probe}}).scalar()}}
 print(json.dumps(result))
"""
    effects = json.loads(subprocess.run(['docker', 'compose', 'exec', '-T', 'inventory', 'python', '-c', effects_code], cwd=ROOT, check=True, capture_output=True, text=True).stdout)
    if effects['stock'] != stock_row or effects['movements'] != movements_before or effects['outbox'] != 0:
        raise AssertionError(f'Failed transaction changed data: before={stock_row}/{movements_before}, after={effects}')
    print(json.dumps({
        'initial_dlq_count': initial,
        'probe_received_in_dlq': True,
        'retry_attempts': headers['attempts'],
        'failure_header': headers['failure'],
        'failed_transaction_left_no_effects': True,
        'probe_removed_from_dlq': True,
    }, indent=2))


if __name__ == '__main__':
    main()
