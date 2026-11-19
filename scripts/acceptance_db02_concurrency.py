"""Run real concurrent HTTP/DB checks for DB-02 against Docker Compose."""
import json, os, subprocess, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
PORTS={'customers':8002,'products':8001,'loans':8003,'inventory':8004}

def env_values():
    values=os.environ.copy(); path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1); values.setdefault(k.strip(),v.strip().strip('"').strip("'"))
    return values

def docker_python(service,code):
    return subprocess.run(['docker','compose','exec','-T',service,'python','-c',code],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()

def db_json(service,code): return json.loads(docker_python(service,code))

def concurrent_pair(url,headers,body):
    barrier=threading.Barrier(2)
    def send():
        barrier.wait(timeout=10); started=time.perf_counter()
        response=requests.post(url,headers=headers,json=body,timeout=20)
        ended=time.perf_counter()
        try: payload=response.json()
        except ValueError: payload={'body':response.text[:300]}
        return {'status':response.status_code,'payload':payload,'started':started,'ended':ended}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(send) for _ in range(2)]
        return [f.result(timeout=30) for f in futures]

def wait_loan(session,url,headers,loan_id,terminal,timeout=45):
    deadline=time.monotonic()+timeout; latest=None
    while time.monotonic()<deadline:
        r=session.get(f'{url}/prestamos/{loan_id}',headers=headers,timeout=6); r.raise_for_status(); latest=r.json()
        if latest['status'] in terminal: return latest
        time.sleep(.2)
    raise AssertionError(f'Loan did not reach {terminal}; latest={latest}')

def snapshots(key,product_id):
    lcode=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 k={key!r}; row=c.execute(text('SELECT i.loan_id,l.status FROM idempotency i JOIN loans l ON l.id=i.loan_id WHERE i.key=:k'),{{'k':k}}).mappings().first()
 loan=row['loan_id'] if row else None
 print(json.dumps({{'loan':dict(row) if row else None,'idempotency_rows':c.execute(text('SELECT count(*) FROM idempotency WHERE key=:k'),{{'k':k}}).scalar(),'loans_for_key':c.execute(text('SELECT count(*) FROM loans l JOIN idempotency i ON i.loan_id=l.id WHERE i.key=:k'),{{'k':k}}).scalar(),'loan_commands':c.execute(text("SELECT count(*) FROM outbox WHERE loan_id=:id AND type='ReservaSolicitada'"),{{'id':loan}}).scalar() if loan else 0}}))
'''
    loan_data=db_json('loans',lcode)
    loan_id=(loan_data.get('loan') or {}).get('loan_id')
    icode=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 loan={loan_id!r}; p={product_id!r}; stock=c.execute(text('SELECT available,reserved FROM stock WHERE product_id=:p'),{{'p':p}}).mappings().first()
 def count(sql): return c.execute(text(sql),{{'id':loan}}).scalar() if loan else 0
 r={{'stock':dict(stock) if stock else None,'reservations':count('SELECT count(*) FROM reservations WHERE loan_id=:id'),'reservation_status':count('SELECT status FROM reservations WHERE loan_id=:id'),'reserve_movements':count("SELECT count(*) FROM movements WHERE loan_id=:id AND kind='RESERVE'"),'release_movements':count("SELECT count(*) FROM movements WHERE loan_id=:id AND kind='RELEASE'"),'inventory_events':count("SELECT count(*) FROM outbox WHERE loan_id=:id AND type='InventarioReservado'"),'release_events':count("SELECT count(*) FROM outbox WHERE loan_id=:id AND type='ReservaLiberada'")}}
 print(json.dumps(r,default=dict))
'''
    return loan_data,db_json('inventory',icode)

def cleanup(product_name,keys,late_ids):
    key_repr,late_repr=repr(keys),repr(late_ids)
    find_products=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c: print(json.dumps(c.execute(text('SELECT id FROM products WHERE name=:n'),{{'n':{product_name!r}}}).scalars().all()))
'''
    product_ids=db_json('products',find_products)
    find_loans=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c:
 result=[]
 for key in {keys!r}:
  loan_id=c.execute(text('SELECT loan_id FROM idempotency WHERE key=:k'),{{'k':key}}).scalar()
  if loan_id: result.append(loan_id)
 print(json.dumps(result))
'''
    loan_ids=db_json('loans',find_loans) if keys else []
    for loan_id in loan_ids:
        ids_code=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c: print(json.dumps(c.execute(text('SELECT event_id FROM outbox WHERE loan_id=:id'),{{'id':{loan_id!r}}}).scalars().all()))
'''
        for event_id in db_json('inventory',ids_code):
            docker_python('loans',f'''import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c: c.execute(text('DELETE FROM processed_messages WHERE event_id=:id'),{{'id':{event_id!r}}})
''')
    loans_cleanup=f'''import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ks={keys!r}; late={late_ids!r}
with e.begin() as c:
 ids=[]
 for key in ks:
  loan_id=c.execute(text('SELECT loan_id FROM idempotency WHERE key=:k'),{{'k':key}}).scalar()
  if loan_id: ids.append(loan_id)
 for loan_id in ids:
  c.execute(text('DELETE FROM idempotency WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM outbox WHERE loan_id=:id'),{{'id':loan_id}})
  c.execute(text('DELETE FROM loans WHERE id=:id'),{{'id':loan_id}})
 for event_id in late: c.execute(text('DELETE FROM processed_messages WHERE event_id=:id'),{{'id':event_id}})
'''
    docker_python('loans',loans_cleanup)
    inv_cleanup=f'''import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); loans={loan_ids!r}; products={product_ids!r}
with e.begin() as c:
 for loan_id in loans:
  for table in ('movements','reservations','outbox'): c.execute(text(f'DELETE FROM {{table}} WHERE loan_id=:id'),{{'id':loan_id}})
 for product_id in products:
  c.execute(text('DELETE FROM movements WHERE product_id=:id'),{{'id':product_id}})
  c.execute(text('DELETE FROM stock WHERE product_id=:id'),{{'id':product_id}})
'''
    docker_python('inventory',inv_cleanup)
    if product_ids:
        docker_python('products',f'''import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ids={product_ids!r}
with e.begin() as c:
 for product_id in ids: c.execute(text('DELETE FROM products WHERE id=:id'),{{'id':product_id}})
''')
        for pid in product_ids: subprocess.run(['docker','compose','exec','-T','redis','redis-cli','DEL',f'products:v1:{pid}'],cwd=ROOT,check=True,capture_output=True)
    verify=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); ks={keys!r}; ids={loan_ids!r}
with e.connect() as c:
 remaining=sum(c.execute(text('SELECT count(*) FROM idempotency WHERE key=:k'),{{'k':key}}).scalar() for key in ks)
 loan_rows=sum(c.execute(text('SELECT count(*) FROM loans WHERE id=:id'),{{'id':loan_id}}).scalar() for loan_id in ids)
 print(json.dumps({{'idempotency_rows':remaining,'loan_rows':loan_rows}}))
'''
    remaining=db_json('loans',verify)
    product_verify=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c: print(json.dumps({{'products':c.execute(text('SELECT count(*) FROM products WHERE name=:n'),{{'n':{product_name!r}}}).scalar()}}))
'''
    products_left=db_json('products',product_verify)
    inventory_verify=f'''import json,os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL']); loans={loan_ids!r}; products={product_ids!r}
with e.connect() as c:
 result={{}}
 for table in ('reservations','movements','outbox'):
  result[table+'_loan_rows']=sum(c.execute(text(f'SELECT count(*) FROM {{table}} WHERE loan_id=:id'),{{'id':loan_id}}).scalar() for loan_id in loans)
 result['stock_rows']=sum(c.execute(text('SELECT count(*) FROM stock WHERE product_id=:id'),{{'id':pid}}).scalar() for pid in products)
 result['movement_product_rows']=sum(c.execute(text('SELECT count(*) FROM movements WHERE product_id=:id'),{{'id':pid}}).scalar() for pid in products)
 print(json.dumps(result))
'''
    inventory_left=db_json('inventory',inventory_verify)
    if remaining['idempotency_rows'] or remaining['loan_rows'] or products_left['products'] or any(inventory_left.values()):
        raise AssertionError(f'Fixture cleanup incomplete: {remaining}, {products_left}, {inventory_left}')
    print(json.dumps({'fixture_cleanup':'verified','products_removed':len(product_ids),'loan_keys_removed':len(keys),'remaining_rows':{'loans':remaining,'products':products_left,'inventory':inventory_left}}))

def main():
    env=env_values(); urls={n:os.environ.get(f'CREDIMARKET_{n.upper()}_URL',f'http://localhost:{p}').rstrip('/') for n,p in PORTS.items()}
    session=requests.Session(); login=session.post(f"{urls['customers']}/auth/login",json={'username':env['ADMIN_USERNAME'],'password':env['ADMIN_PASSWORD']},timeout=8); login.raise_for_status()
    headers={'Authorization':f"Bearer {login.json()['access_token']}"}
    customers=session.get(f"{urls['customers']}/customers",headers=headers,timeout=8); customers.raise_for_status()
    mi=session.get(f"{urls['loans']}/modelo/info",headers=headers,timeout=8); mi.raise_for_status(); threshold=float(mi.json()['threshold'])
    chosen=None
    for customer in sorted(customers.json(),key=lambda r:(r['income'],-r['obligations']),reverse=True):
        if not customer['active'] or customer['income']<=0: continue
        risk={'ingresos_mensuales_cop':customer['income'],'obligaciones_mensuales_cop':customer['obligations'],'tipo_empleo':customer['employment'],'antiguedad_laboral_meses':customer['tenure_months'],'meses_historial_crediticio':customer['history_months'],'creditos_previos':customer['prior_credits'],'atrasos_previos_30d':customer['late_payments'],'porcentaje_pago_puntual':customer['payment_on_time'],'monto_solicitado_cop':1,'plazo_meses':6,'cuota_estimada_cop':.18}
        result=session.post(f"{urls['loans']}/riesgo/predict",headers=headers,json=risk,timeout=8); result.raise_for_status()
        if result.json()['probabilidad_incumplimiento']<threshold: chosen=customer; break
    if chosen is None: raise SystemExit('No active customer has favorable risk at the minimal valid quote; no fixtures were created.')

    product_name=f'DB02 concurrency {uuid.uuid4()}'
    keys=[]; late_ids=[]
    try:
        product=session.post(f"{urls['products']}/products",headers=headers,json={'name':product_name,'category':'DB02_TEST','price_cop':1},timeout=8); product.raise_for_status(); pid=int(product.json()['id'])
        stock=session.post(f"{urls['inventory']}/inventory/stock",headers=headers,json={'product_id':pid,'quantity':5},timeout=8); stock.raise_for_status()
        body={'customer_id':chosen['id'],'product_id':pid,'quantity':1,'term_months':6}

        idem_key=f'db02-idem-{uuid.uuid4()}'; keys.append(idem_key)
        pair=concurrent_pair(f"{urls['loans']}/prestamos",{**headers,'Idempotency-Key':idem_key},body)
        if any(x['status'] not in (200,202) for x in pair): raise AssertionError(f'POST status codes: {[x["status"] for x in pair]}')
        loan_ids={x['payload'].get('id') for x in pair}
        if len(loan_ids)!=1 or None in loan_ids: raise AssertionError(f'POSTs returned different IDs: {loan_ids}')
        loan_id=next(iter(loan_ids)); loan=wait_loan(session,urls['loans'],headers,loan_id,{'APROBADA','RECHAZADA','CANCELADA_SIN_STOCK'})
        if loan['status']!='APROBADA': raise AssertionError(f'Idempotency loan did not reserve: {loan["status"]}')
        conflict=session.post(f"{urls['loans']}/prestamos",headers={**headers,'Idempotency-Key':idem_key},json={**body,'term_months':12},timeout=8)
        if conflict.status_code!=409: raise AssertionError(f'Changed body status={conflict.status_code}, expected 409')
        idem_db,idem_inv=snapshots(idem_key,pid)
        if (idem_db['idempotency_rows'],idem_db['loans_for_key'],idem_db['loan_commands'])!=(1,1,1) or (idem_inv['reservations'],idem_inv['reserve_movements'],idem_inv['inventory_events'],idem_inv['stock'])!=(1,1,1,{'available':4,'reserved':1}):
            raise AssertionError(f'Idempotency/inventory mismatch: {idem_db} {idem_inv}')

        cancel_key=f'db02-cancel-{uuid.uuid4()}'; keys.append(cancel_key)
        created=session.post(f"{urls['loans']}/prestamos",headers={**headers,'Idempotency-Key':cancel_key},json=body,timeout=10); created.raise_for_status(); cancel_id=created.json()['id']
        cancel_loan=wait_loan(session,urls['loans'],headers,cancel_id,{'APROBADA','RECHAZADA','CANCELADA_SIN_STOCK'})
        if cancel_loan['status']!='APROBADA': raise AssertionError(f'Cancellation test needs APROBADA reservation, got {cancel_loan["status"]}')
        before_db,before_inv=snapshots(cancel_key,pid)
        if before_inv['stock']!={'available':3,'reserved':2}: raise AssertionError(f'Unexpected stock before cancellation: {before_inv}')
        cancel_pair=concurrent_pair(f"{urls['loans']}/prestamos/{cancel_id}/cancel",headers,None)
        codes=sorted(r['status'] for r in cancel_pair)
        if codes!=[200,409]: raise AssertionError(f'Expected concurrent cancel 200 and 409; got {codes}')
        final=wait_loan(session,urls['loans'],headers,cancel_id,{'CANCELADA','APROBADA'})
        if final['status']!='CANCELADA': raise AssertionError(f'Cancel race ended in {final["status"]}')
        after_db,after_inv=snapshots(cancel_key,pid)
        if (after_inv['stock'],after_inv['reservation_status'],after_inv['reservations'],after_inv['reserve_movements'],after_inv['release_movements'],after_inv['release_events'])!=({'available':4,'reserved':1},'RELEASED',1,1,1,1):
            raise AssertionError(f'Cancel race duplicated/missed effects: {after_db} {after_inv}')

        late_id=str(uuid.uuid4()); late_ids.append(late_id)
        event={'event_id':late_id,'type':'InventarioReservado','schema_version':1,'occurred_at':datetime.now(timezone.utc).isoformat(),'correlation_id':cancel_id,'prestamo_id':cancel_id,'payload':{'producto_id':pid,'cantidad':1}}
        publisher=f'''import asyncio,json,os
import aio_pika
async def main():
 conn=await aio_pika.connect_robust(os.environ['RABBIT_URL'])
 async with conn:
  ch=await conn.channel(publisher_confirms=True); ex=await ch.declare_exchange('credimarket.events',aio_pika.ExchangeType.TOPIC,durable=True)
  await ex.publish(aio_pika.Message(json.dumps({event!r}).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key='inventario.reservado',mandatory=True)
asyncio.run(main())
'''
        docker_python('loans',publisher)
        deadline=time.monotonic()+15; seen=False
        while time.monotonic()<deadline:
            seen=docker_python('loans',f'''import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.connect() as c: print(bool(c.execute(text('SELECT 1 FROM processed_messages WHERE event_id=:id'),{{'id':{late_id!r}}}).first()))
''')=='True'
            if seen: break
            time.sleep(.2)
        if not seen: raise AssertionError('Late event was not consumed')
        final_loan=wait_loan(session,urls['loans'],headers,cancel_id,{'CANCELADA'}); _,late_inv=snapshots(cancel_key,pid)
        if final_loan['status']!='CANCELADA' or late_inv!=after_inv: raise AssertionError(f'Late event changed state/inventory: {late_inv}')

        print(json.dumps({'concurrent_idempotency':{'http_statuses':sorted(x['status'] for x in pair),'same_loan_id':True,'barrier_start_skew_ms':round(abs(pair[0]['started']-pair[1]['started'])*1000,3),'same_key_changed_body_http':conflict.status_code,'database':idem_db,'inventory_after':idem_inv},'concurrent_cancellation':{'initial_state':cancel_loan['status'],'http_statuses':codes,'final_state':final['status'],'inventory_before':before_inv,'inventory_after':after_inv,'database':after_db},'late_event':{'consumed':seen,'loan_state':final_loan['status'],'inventory_unchanged':late_inv==after_inv}},indent=2))
    finally:
        cleanup(product_name,keys,late_ids)

if __name__=='__main__': main()
