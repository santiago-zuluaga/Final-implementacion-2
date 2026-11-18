"""Four independently deployed CrediMarket APIs, selected by SERVICE."""
from __future__ import annotations
import asyncio, csv, hashlib, io, json, os, uuid
import statistics, time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import aio_pika
import httpx
import joblib
import pandas as pd
import redis
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Response
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from sqlalchemy import create_engine, text

SERVICE=os.getenv('SERVICE','products')
DB=os.getenv('DATABASE_URL','postgresql+psycopg://cm_products:dev_products@postgres:5432/credimarket')
engine=create_engine(DB,pool_pre_ping=True,pool_size=5,max_overflow=5)
REDIS_URL=os.getenv('REDIS_URL','redis://redis:6379/0')
try: cache=redis.Redis.from_url(REDIS_URL,socket_connect_timeout=.2,socket_timeout=.2,decode_responses=True)
except Exception: cache=None
RABBIT=os.getenv('RABBIT_URL','amqp://guest:guest@rabbitmq:5672/')
ROOT=Path(__file__).resolve().parents[1]
CACHE_METRICS={'hits':0,'misses':0,'fallbacks':0,'durations_ms':[]}

SCHEMAS={
'products':'''CREATE TABLE IF NOT EXISTS products(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,price_cop BIGINT NOT NULL CHECK(price_cop>0),version INT NOT NULL DEFAULT 1,active BOOLEAN NOT NULL DEFAULT TRUE,updated_at TIMESTAMPTZ NOT NULL DEFAULT now());''',
'customers':'''CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '',income BIGINT NOT NULL DEFAULT 0 CHECK(income>=0),obligations BIGINT NOT NULL DEFAULT 0 CHECK(obligations>=0),employment TEXT,tenure_months DOUBLE PRECISION,history_months DOUBLE PRECISION,prior_credits INT NOT NULL DEFAULT 0,late_payments INT NOT NULL DEFAULT 0,payment_on_time DOUBLE PRECISION,active BOOLEAN NOT NULL DEFAULT TRUE,updated_at TIMESTAMPTZ NOT NULL DEFAULT now());''',
'inventory':'''CREATE TABLE IF NOT EXISTS stock(product_id BIGINT PRIMARY KEY,available INT NOT NULL CHECK(available>=0),reserved INT NOT NULL DEFAULT 0 CHECK(reserved>=0)); CREATE TABLE IF NOT EXISTS reservations(loan_id TEXT PRIMARY KEY,product_id BIGINT NOT NULL,quantity INT NOT NULL,status TEXT NOT NULL,expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '30 minutes'); CREATE TABLE IF NOT EXISTS movements(id BIGSERIAL PRIMARY KEY,product_id BIGINT,loan_id TEXT,kind TEXT,quantity INT,created_at TIMESTAMPTZ DEFAULT now()); CREATE TABLE IF NOT EXISTS processed_messages(event_id TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY,type TEXT NOT NULL,correlation_id TEXT NOT NULL,loan_id TEXT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ DEFAULT now(),published_at TIMESTAMPTZ);''',
'loans':'''CREATE TABLE IF NOT EXISTS loans(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,product_id BIGINT NOT NULL,quantity INT NOT NULL,term_months INT NOT NULL,price_cop BIGINT NOT NULL,product_version INT NOT NULL,probability DOUBLE PRECISION NOT NULL,threshold DOUBLE PRECISION NOT NULL,model_version TEXT NOT NULL,status TEXT NOT NULL,reason TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT now()); CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY,request_hash TEXT NOT NULL,loan_id TEXT NOT NULL); CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY,type TEXT NOT NULL,correlation_id TEXT NOT NULL,loan_id TEXT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ DEFAULT now(),published_at TIMESTAMPTZ); CREATE TABLE IF NOT EXISTS processed_messages(event_id TEXT PRIMARY KEY);'''}

def init_db():
    with engine.begin() as c:
        for ddl in SCHEMAS[SERVICE].split(';'):
            if ddl.strip(): c.execute(text(ddl))

async def publish_outbox():
    while True:
      try:
        with engine.begin() as c:
          rows=c.execute(text("SELECT event_id,type,correlation_id,loan_id,payload FROM outbox WHERE published_at IS NULL ORDER BY created_at LIMIT 50 FOR UPDATE SKIP LOCKED")).mappings().all()
          if not rows: rows=[]
          else:
            conn=await aio_pika.connect_robust(RABBIT)
            async with conn:
              ch=await conn.channel(publisher_confirms=True)
              for r in rows:
                doc={'event_id':r['event_id'],'type':r['type'],'schema_version':1,'occurred_at':datetime.now(timezone.utc).isoformat(),'correlation_id':r['correlation_id'],'prestamo_id':r['loan_id'],'payload':r['payload']}
                if r['type'] in ('ReservaSolicitada','LiberarReserva'):
                  ex=await ch.declare_exchange('credimarket.commands',aio_pika.ExchangeType.DIRECT,durable=True); route={'ReservaSolicitada':'reserva.solicitar','LiberarReserva':'reserva.liberar'}[r['type']]
                else:
                  ex=await ch.declare_exchange('credimarket.events',aio_pika.ExchangeType.TOPIC,durable=True); route={'InventarioReservado':'inventario.reservado','InventarioInsuficiente':'inventario.insuficiente','ReservaLiberada':'inventario.liberada','ReservaVencida':'inventario.vencida','SalidaConfirmada':'inventario.salida_confirmada'}.get(r['type'],r['type'].lower())
                await ex.publish(aio_pika.Message(json.dumps(doc).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key=route,mandatory=True)
                c.execute(text('UPDATE outbox SET published_at=now() WHERE event_id=:id'),{'id':r['event_id']})
      except Exception as e: print(f'outbox retry: {e}',flush=True)
      await asyncio.sleep(1)

async def event_consumer(app):
    while True:
      try:
        conn=await aio_pika.connect_robust(RABBIT)
        async with conn:
          ch=await conn.channel(); await ch.set_qos(prefetch_count=8)
          ex=await ch.declare_exchange('credimarket.events',aio_pika.ExchangeType.TOPIC,durable=True)
          retry_ex=await ch.declare_exchange('credimarket.retry',aio_pika.ExchangeType.DIRECT,durable=True)
          dlx=await ch.declare_exchange('credimarket.dlx',aio_pika.ExchangeType.DIRECT,durable=True)
          q=await ch.declare_queue('loans.inventory-events',durable=True,arguments={'x-dead-letter-exchange':'credimarket.retry'})
          retry=await ch.declare_queue('loans.events.retry',durable=True,arguments={'x-message-ttl':5000,'x-dead-letter-exchange':'credimarket.events'})
          dlq=await ch.declare_queue('loans.events.dlq',durable=True); await dlq.bind(dlx,routing_key='loans.events.failed')
          routes=['inventario.reservado','inventario.insuficiente','inventario.liberada','inventario.vencida','inventario.salida_confirmada']
          for route in routes: await q.bind(ex,routing_key=route); await retry.bind(retry_ex,routing_key=route)
          async with q.iterator() as it:
            async for msg in it:
              async with msg.process(requeue=False):
                attempts=sum(int(entry.get('count',0)) for entry in (msg.headers or {}).get('x-death',[]) if entry.get('queue')=='loans.events.retry')
                if attempts>=3:
                  await dlx.publish(aio_pika.Message(msg.body,delivery_mode=aio_pika.DeliveryMode.PERSISTENT,headers={'failure':'retry limit exceeded'}),routing_key='loans.events.failed'); continue
                d=json.loads(msg.body); await handle_loan_event(d)
      except asyncio.CancelledError: raise
      except Exception as e: print(f'event consumer reconnect: {e}',flush=True); await asyncio.sleep(2)

async def inventory_consumer():
    while True:
      try:
        conn=await aio_pika.connect_robust(RABBIT)
        async with conn:
          ch=await conn.channel(); await ch.set_qos(prefetch_count=1)
          ex=await ch.declare_exchange('credimarket.commands',aio_pika.ExchangeType.DIRECT,durable=True)
          retry_ex=await ch.declare_exchange('credimarket.retry',aio_pika.ExchangeType.DIRECT,durable=True)
          dlx=await ch.declare_exchange('credimarket.dlx',aio_pika.ExchangeType.DIRECT,durable=True)
          q=await ch.declare_queue('inventory.commands',durable=True,arguments={'x-dead-letter-exchange':'credimarket.retry'})
          retry=await ch.declare_queue('inventory.commands.retry',durable=True,arguments={'x-message-ttl':5000,'x-dead-letter-exchange':'credimarket.commands'})
          dlq=await ch.declare_queue('inventory.commands.dlq',durable=True); await dlq.bind(dlx,routing_key='inventory.commands.failed')
          await q.bind(ex,routing_key='reserva.solicitar'); await q.bind(ex,routing_key='reserva.liberar')
          await retry.bind(retry_ex,routing_key='reserva.solicitar'); await retry.bind(retry_ex,routing_key='reserva.liberar')
          async with q.iterator() as it:
            async for msg in it:
              async with msg.process(requeue=False):
                attempts=sum(int(entry.get('count',0)) for entry in (msg.headers or {}).get('x-death',[]) if entry.get('queue')=='inventory.commands.retry')
                if attempts>=3:
                  await dlx.publish(aio_pika.Message(msg.body,delivery_mode=aio_pika.DeliveryMode.PERSISTENT,headers={'failure':'retry limit exceeded'}),routing_key='inventory.commands.failed'); continue
                d=json.loads(msg.body); payload=d['payload']; loan=d['prestamo_id']; is_release=d['type']=='LiberarReserva'; product=int(payload.get('producto_id',0)); qty=int(payload.get('cantidad',0))
                with engine.begin() as c:
                  old=c.execute(text('SELECT status FROM reservations WHERE loan_id=:id FOR UPDATE'),{'id':loan}).first()
                  if is_release:
                    if old and old[0]=='RESERVED':
                      r=c.execute(text("UPDATE reservations SET status='RELEASED' WHERE loan_id=:id RETURNING product_id,quantity"),{'id':loan}).mappings().one()
                      c.execute(text('UPDATE stock SET available=available+:q,reserved=reserved-:q WHERE product_id=:p'),{'q':r['quantity'],'p':r['product_id']}); c.execute(text("INSERT INTO movements(product_id,loan_id,kind,quantity) VALUES(:p,:id,'RELEASE',:q)"),{'p':r['product_id'],'id':loan,'q':r['quantity']})
                    elif not old:
                      c.execute(text("INSERT INTO reservations(loan_id,product_id,quantity,status) VALUES(:id,:p,:q,'RELEASED')"),{'id':loan,'p':product,'q':max(qty,1)})
                    success=True
                  elif old: success=old[0]=='RESERVED'
                  else:
                    updated=c.execute(text('UPDATE stock SET available=available-:q,reserved=reserved+:q WHERE product_id=:p AND available>=:q RETURNING product_id'),{'q':qty,'p':product}).first()
                    success=bool(updated)
                    if success:
                      c.execute(text("INSERT INTO reservations(loan_id,product_id,quantity,status) VALUES(:id,:p,:q,'RESERVED')"),{'id':loan,'p':product,'q':qty}); c.execute(text("INSERT INTO movements(product_id,loan_id,kind,quantity) VALUES(:p,:id,'RESERVE',:q)"),{'p':product,'id':loan,'q':qty})
                  kind=('ReservaLiberada' if is_release else 'InventarioReservado' if success else 'InventarioInsuficiente')
                  event_id=str(uuid.uuid5(uuid.NAMESPACE_URL,d['event_id']+kind))
                  c.execute(text('INSERT INTO outbox(event_id,type,correlation_id,loan_id,payload) VALUES(:e,:t,:c,:id,CAST(:payload AS JSONB)) ON CONFLICT(event_id) DO NOTHING'),{'e':event_id,'t':kind,'c':d['correlation_id'],'id':loan,'payload':json.dumps({'producto_id':product,'cantidad':qty})})
      except asyncio.CancelledError: raise
      except Exception as e: print(f'inventory consumer reconnect: {e}',flush=True); await asyncio.sleep(2)

async def reservation_expiry_worker():
    while True:
      try:
        with engine.begin() as c:
          rows=c.execute(text("SELECT loan_id,product_id,quantity FROM reservations WHERE status='RESERVED' AND expires_at<=now() FOR UPDATE SKIP LOCKED LIMIT 100")).mappings().all()
          for r in rows:
            c.execute(text("UPDATE reservations SET status='EXPIRED' WHERE loan_id=:id"),{'id':r['loan_id']})
            c.execute(text('UPDATE stock SET available=available+:q,reserved=reserved-:q WHERE product_id=:p'),{'q':r['quantity'],'p':r['product_id']})
            c.execute(text("INSERT INTO movements(product_id,loan_id,kind,quantity) VALUES(:p,:id,'EXPIRE',:q)"),{'p':r['product_id'],'id':r['loan_id'],'q':r['quantity']})
            eid=str(uuid.uuid5(uuid.NAMESPACE_URL,'expiry:'+r['loan_id']))
            c.execute(text("INSERT INTO outbox(event_id,type,correlation_id,loan_id,payload) VALUES(:e,'ReservaVencida',:c,:id,CAST(:payload AS JSONB)) ON CONFLICT(event_id) DO NOTHING"),{'e':eid,'c':r['loan_id'],'id':r['loan_id'],'payload':json.dumps({'producto_id':r['product_id'],'cantidad':r['quantity']})})
      except Exception as e: print(f'reservation expiry retry: {e}',flush=True)
      await asyncio.sleep(15)

async def pending_loan_timeout_worker():
    while True:
      try:
        with engine.begin() as c:
          rows=c.execute(text("UPDATE loans SET status='CANCELACION_PENDIENTE',reason='TIMEOUT_INVENTARIO' WHERE status='PENDIENTE_INVENTARIO' AND created_at<now()-interval '2 minutes' RETURNING id,product_id,quantity")).mappings().all()
          for r in rows:
            eid=str(uuid.uuid5(uuid.NAMESPACE_URL,'timeout:'+r['id']))
            c.execute(text("INSERT INTO outbox(event_id,type,correlation_id,loan_id,payload) VALUES(:e,'LiberarReserva',:c,:id,CAST(:payload AS JSONB)) ON CONFLICT(event_id) DO NOTHING"),{'e':eid,'c':r['id'],'id':r['id'],'payload':json.dumps({'producto_id':r['product_id'],'cantidad':r['quantity']})})
      except Exception as e: print(f'pending loan timeout retry: {e}',flush=True)
      await asyncio.sleep(10)

def handle_loan_event(d):
    event=d['event_id']; loan=d['prestamo_id']; typ=d['type']
    with engine.begin() as c:
      if c.execute(text('SELECT 1 FROM processed_messages WHERE event_id=:e'),{'e':event}).first(): return
      row=c.execute(text('SELECT status FROM loans WHERE id=:id FOR UPDATE'),{'id':loan}).first()
      if not row: return
      current=row[0]
      if typ=='InventarioReservado' and current=='PENDIENTE_INVENTARIO': nxt='APROBADA'
      elif typ=='InventarioInsuficiente' and current=='PENDIENTE_INVENTARIO': nxt='CANCELADA_SIN_STOCK'
      elif typ=='ReservaLiberada' and current=='CANCELACION_PENDIENTE': nxt='CANCELADA'
      elif typ=='ReservaVencida' and current=='APROBADA': nxt='CANCELADA'
      elif typ=='SalidaConfirmada' and current=='APROBADA': nxt='COMPLETADA'
      else: nxt=current
      reason='RESERVA_VENCIDA' if typ=='ReservaVencida' and nxt=='CANCELADA' else None
      c.execute(text('UPDATE loans SET status=:s,reason=COALESCE(:r,reason) WHERE id=:id'),{'s':nxt,'id':loan,'r':reason})
      c.execute(text('INSERT INTO processed_messages(event_id) VALUES(:e)'),{'e':event})

@asynccontextmanager
async def lifespan(app):
    for n in range(40):
      try: init_db(); break
      except Exception:
        if n==39: raise
        await asyncio.sleep(2)
    tasks=[]
    if SERVICE=='loans':
      ptr=ROOT/'models'/'active.json'
      if ptr.exists():
        a=json.loads(ptr.read_text()); m=json.loads((ROOT/'models'/a['manifest']).read_text()); artifact=ROOT/'models'/a['artifact']
        if hashlib.sha256(artifact.read_bytes()).hexdigest()!=m['artifact_sha256']: raise RuntimeError('Active model artifact hash mismatch')
        app.state.model=joblib.load(artifact); app.state.manifest=m
      else: app.state.model=None; app.state.manifest=None
      tasks=[asyncio.create_task(publish_outbox()),asyncio.create_task(event_consumer(app)),asyncio.create_task(pending_loan_timeout_worker())]
    if SERVICE=='inventory': tasks=[asyncio.create_task(inventory_consumer()),asyncio.create_task(publish_outbox()),asyncio.create_task(reservation_expiry_worker())]
    yield
    for t in tasks: t.cancel()

app=FastAPI(title=f'CrediMarket {SERVICE.title()}',lifespan=lifespan)
class ProductIn(BaseModel): name:str; category:str; price_cop:int=Field(gt=0)
class CustomerIn(BaseModel): id:str; name:str=''; income:int=Field(ge=0); obligations:int=Field(ge=0); employment:Literal['dependiente','independiente','temporal']|None=None; tenure_months:float|None=Field(default=None,ge=0,le=1000); history_months:float|None=Field(default=None,ge=0,le=1000); prior_credits:int=Field(default=0,ge=0,le=1000); late_payments:int=Field(default=0,ge=0,le=1000); payment_on_time:float|None=Field(default=None,ge=0,le=100); active:bool=True
class LoanIn(BaseModel): customer_id:str; product_id:int=Field(gt=0); quantity:int=Field(gt=0,le=10); term_months:int=Field(gt=0,le=60)
class RiskIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ingresos_mensuales_cop:int=Field(gt=0,le=1_000_000_000); obligaciones_mensuales_cop:int=Field(ge=0,le=1_000_000_000); tipo_empleo:Literal['dependiente','independiente','temporal']|None=None
    antiguedad_laboral_meses:float|None=Field(default=None,ge=0); meses_historial_crediticio:float|None=Field(default=None,ge=0)
    creditos_previos:int=Field(ge=0); atrasos_previos_30d:int=Field(ge=0); porcentaje_pago_puntual:float|None=Field(default=None,ge=0,le=100)
    monto_solicitado_cop:int=Field(gt=0); plazo_meses:int=Field(gt=0,le=120); cuota_estimada_cop:float=Field(gt=0)
class StockIn(BaseModel): product_id:int=Field(gt=0); quantity:int=Field(gt=0)

@app.get('/health')
def health(): return {'status':'ok','service':SERVICE}
@app.get('/ready')
def ready():
    with engine.connect() as c: c.execute(text('SELECT 1'))
    if SERVICE=='loans' and app.state.model is None: raise HTTPException(503,'No promoted model')
    return {'status':'ready'}

@app.post('/products',status_code=201)
def product_create(body:ProductIn):
    require('products')
    with engine.begin() as c: row=c.execute(text('INSERT INTO products(name,category,price_cop) VALUES(:n,:cat,:p) RETURNING *'),{'n':body.name,'cat':body.category,'p':body.price_cop}).mappings().one()
    return dict(row)
@app.get('/products')
def product_list(q:str|None=None):
    require('products')
    query='SELECT * FROM products WHERE active'
    params={}
    if q:
        query+=' AND name ILIKE :like'
        params['like']=f'%{q}%'
    with engine.connect() as c: rows=c.execute(text(query+' ORDER BY id'),params).mappings().all()
    return [dict(r) for r in rows]
def get_product(id,quotation=False):
    require('products'); key=f'products:v1:{id}'
    started=time.perf_counter()
    if not quotation:
      try:
        hit=cache.get(key) if cache else None
        if hit:
          CACHE_METRICS['hits']+=1; CACHE_METRICS['durations_ms'].append((time.perf_counter()-started)*1000); return json.loads(hit)
        CACHE_METRICS['misses']+=1
      except Exception: CACHE_METRICS['fallbacks']+=1; CACHE_METRICS['misses']+=1
    with engine.connect() as c: row=c.execute(text('SELECT * FROM products WHERE id=:id AND active'),{'id':id}).mappings().first()
    if not row: raise HTTPException(404,'Product not found')
    out=dict(row)
    if not quotation:
      try:
        if cache: cache.setex(key,300,json.dumps(out,default=str))
      except Exception: pass
      CACHE_METRICS['durations_ms'].append((time.perf_counter()-started)*1000)
    return out
@app.get('/cache/metrics')
def cache_metrics():
    require('products'); durations=CACHE_METRICS['durations_ms'][-500:]
    def percentile(p): return round(sorted(durations)[min(len(durations)-1,int((len(durations)-1)*p))] if durations else 0,3)
    total=CACHE_METRICS['hits']+CACHE_METRICS['misses']
    return {**{k:v for k,v in CACHE_METRICS.items() if k!='durations_ms'},'hit_rate':CACHE_METRICS['hits']/total if total else 0,'p50_ms':percentile(.50),'p95_ms':percentile(.95)}
@app.get('/products/{id}')
def product_get(id:int): return get_product(id)
@app.get('/products/{id}/quotation')
def quotation(id:int): return get_product(id,True)
@app.put('/products/{id}')
def product_update(id:int,body:ProductIn):
    require('products')
    with engine.begin() as c: r=c.execute(text('UPDATE products SET name=:n,category=:cat,price_cop=:p,version=version+1,updated_at=now() WHERE id=:id RETURNING *'),{'n':body.name,'cat':body.category,'p':body.price_cop,'id':id}).mappings().first()
    if not r: raise HTTPException(404,'Product not found')
    try:
      if cache: cache.delete(f'products:v1:{id}')
    except Exception: pass
    return dict(r)
@app.post('/products/{id}/deactivate')
def product_deactivate(id:int):
    require('products')
    with engine.begin() as c: r=c.execute(text('UPDATE products SET active=FALSE,version=version+1,updated_at=now() WHERE id=:id RETURNING id'),{'id':id}).first()
    if not r: raise HTTPException(404,'Product not found')
    try:
      if cache: cache.delete(f'products:v1:{id}')
    except Exception: pass
    return {'id':id,'active':False}

@app.post('/customers',status_code=201)
def customer_create(body:CustomerIn):
    require('customers')
    with engine.begin() as c:
      c.execute(text('INSERT INTO customers(id,name,income,obligations,employment,tenure_months,history_months,prior_credits,late_payments,payment_on_time,active) VALUES(:id,:name,:income,:obligations,:employment,:tenure_months,:history_months,:prior_credits,:late_payments,:payment_on_time,:active) ON CONFLICT(id) DO UPDATE SET name=excluded.name,income=excluded.income,obligations=excluded.obligations,employment=excluded.employment,tenure_months=excluded.tenure_months,history_months=excluded.history_months,prior_credits=excluded.prior_credits,late_payments=excluded.late_payments,payment_on_time=excluded.payment_on_time,active=excluded.active,updated_at=now()'),body.model_dump())
    return customer_get(body.id)
@app.get('/customers')
def customer_list():
    require('customers')
    with engine.connect() as c: return [dict(r) for r in c.execute(text('SELECT * FROM customers ORDER BY id')).mappings()]
@app.get('/customers/{id}')
def customer_get(id:str):
    require('customers')
    with engine.connect() as c: r=c.execute(text('SELECT * FROM customers WHERE id=:id AND active'),{'id':id}).mappings().first()
    if not r: raise HTTPException(404,'Customer not found')
    return dict(r)
@app.post('/customers/import')
async def customer_import(file:UploadFile=File(...)):
    require('customers'); content=(await file.read()).decode('utf-8-sig'); rows=list(csv.DictReader(io.StringIO(content))); inserted=updated=errors=0; details=[]
    for i,row in enumerate(rows,2):
      try:
        data=CustomerIn(id=row.get('cliente_id') or row.get('id'),name=row.get('nombre',''),income=int(row['ingresos_mensuales_cop']),obligations=int(row['obligaciones_mensuales_cop']),employment=row.get('tipo_empleo') or None,tenure_months=float(row['antiguedad_laboral_meses']) if row.get('antiguedad_laboral_meses') else None,history_months=float(row['meses_historial_crediticio']) if row.get('meses_historial_crediticio') else None,prior_credits=int(row.get('creditos_previos') or 0),late_payments=int(row.get('atrasos_previos_30d') or 0),payment_on_time=float(row['porcentaje_pago_puntual']) if row.get('porcentaje_pago_puntual') else None)
        with engine.begin() as c:
          exists=c.execute(text('SELECT 1 FROM customers WHERE id=:id'),{'id':data.id}).first(); customer_create_db(c,data); updated+=bool(exists); inserted+=not bool(exists)
      except Exception as e: errors+=1; details.append({'fila':i,'motivo':str(e)})
    return {'insertados':inserted,'actualizados':updated,'rechazados':errors,'errores':details}
def customer_create_db(c,d):
    c.execute(text('INSERT INTO customers(id,name,income,obligations,employment,tenure_months,history_months,prior_credits,late_payments,payment_on_time,active) VALUES(:id,:name,:income,:obligations,:employment,:tenure_months,:history_months,:prior_credits,:late_payments,:payment_on_time,:active) ON CONFLICT(id) DO UPDATE SET name=excluded.name,income=excluded.income,obligations=excluded.obligations,employment=excluded.employment,tenure_months=excluded.tenure_months,history_months=excluded.history_months,prior_credits=excluded.prior_credits,late_payments=excluded.late_payments,payment_on_time=excluded.payment_on_time,active=excluded.active,updated_at=now()'),d.model_dump())

@app.post('/inventory/stock',status_code=201)
def stock_add(body:StockIn):
    require('inventory')
    with engine.begin() as c:
      r=c.execute(text('INSERT INTO stock(product_id,available) VALUES(:id,:q) ON CONFLICT(product_id) DO UPDATE SET available=stock.available+:q RETURNING *'),{'id':body.product_id,'q':body.quantity}).mappings().one()
      c.execute(text("INSERT INTO movements(product_id,kind,quantity) VALUES(:p,'IN',:q)"),{'p':body.product_id,'q':body.quantity})
    return dict(r)
@app.get('/inventory')
def stock_list():
    require('inventory')
    with engine.connect() as c: return [dict(r) for r in c.execute(text('SELECT * FROM stock ORDER BY product_id')).mappings()]
@app.get('/inventory/reservations')
def inventory_reservations():
    require('inventory')
    with engine.connect() as c: return [dict(r) for r in c.execute(text('SELECT * FROM reservations ORDER BY expires_at DESC LIMIT 200')).mappings()]
@app.post('/inventory/reservations/{loan_id}/deliver')
def delivery(loan_id:str):
    require('inventory')
    with engine.begin() as c:
      r=c.execute(text("UPDATE reservations SET status='DELIVERED' WHERE loan_id=:id AND status='RESERVED' RETURNING product_id,quantity"),{'id':loan_id}).mappings().first()
      if not r: raise HTTPException(409,'Reservation not active')
      c.execute(text('UPDATE stock SET reserved=reserved-:q WHERE product_id=:p'),{'q':r['quantity'],'p':r['product_id']}); c.execute(text('INSERT INTO movements(product_id,loan_id,kind,quantity) VALUES(:p,:id,\'OUT\',:q)'),{'p':r['product_id'],'id':loan_id,'q':r['quantity']})
      c.execute(text("INSERT INTO outbox(event_id,type,correlation_id,loan_id,payload) VALUES(:e,'SalidaConfirmada',:c,:id,'{}'::jsonb)"),{'e':str(uuid.uuid4()),'c':loan_id,'id':loan_id})
    return {'status':'DELIVERED'}

@app.post('/prestamos/{loan_id}/cancel')
def cancel_loan(loan_id:str):
    require('loans')
    with engine.begin() as c:
      r=c.execute(text("UPDATE loans SET status='CANCELACION_PENDIENTE',reason='CANCELACION_USUARIO' WHERE id=:id AND status IN ('APROBADA','PENDIENTE_INVENTARIO') RETURNING id,product_id,quantity"),{'id':loan_id}).mappings().first()
      if not r: raise HTTPException(409,'Loan cannot be cancelled in its current state')
      c.execute(text("INSERT INTO outbox(event_id,type,correlation_id,loan_id,payload) VALUES(:e,'LiberarReserva',:c,:id,CAST(:payload AS JSONB))"),{'e':str(uuid.uuid4()),'c':loan_id,'id':loan_id,'payload':json.dumps({'producto_id':r['product_id'],'cantidad':r['quantity']})})
    return {'id':loan_id,'status':'CANCELACION_PENDIENTE'}

@app.post('/loans')
@app.post('/prestamos')
def loan_create(body:LoanIn,response:Response,idempotency_key:str=Header(alias='Idempotency-Key')):
    require('loans'); body_hash=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    with engine.connect() as c: prev=c.execute(text('SELECT request_hash,loan_id FROM idempotency WHERE key=:k'),{'k':idempotency_key}).first()
    if prev:
      if prev[0]!=body_hash: raise HTTPException(409,'Idempotency-Key reused with different request')
      return loan_get(prev[1])
    try:
      customer=httpx.get(os.getenv('CUSTOMERS_URL','http://customers:8000')+f'/customers/{body.customer_id}',timeout=3).raise_for_status().json()
      product=httpx.get(os.getenv('PRODUCTS_URL','http://products:8000')+f'/products/{body.product_id}/quotation',timeout=3).raise_for_status().json()
    except httpx.HTTPStatusError as e: raise HTTPException(e.response.status_code,e.response.text)
    except Exception as e: raise HTTPException(503,f'Dependent service unavailable: {e}')
    price=int(product['price_cop']); amount=price*body.quantity
    if amount>1_000_000_000: raise HTTPException(422,'Loan amount exceeds the supported range')
    rate=.018; n=body.term_months; payment=round(amount*rate*(1+rate)**n/((1+rate)**n-1),2)
    if app.state.model is None: raise HTTPException(503,'Model unavailable')
    features={'ingresos_mensuales_cop':customer['income'],'obligaciones_mensuales_cop':customer['obligations'],'tipo_empleo':customer['employment'],'antiguedad_laboral_meses':customer['tenure_months'],'meses_historial_crediticio':customer['history_months'],'creditos_previos':customer['prior_credits'],'atrasos_previos_30d':customer['late_payments'],'porcentaje_pago_puntual':customer['payment_on_time'],'monto_solicitado_cop':amount,'plazo_meses':n,'cuota_estimada_cop':payment}
    x=pd.DataFrame([features]); x['tipo_empleo']=x['tipo_empleo'].astype(object); x.loc[x['tipo_empleo'].isna(),'tipo_empleo']=float('nan'); x['sin_historial']=x['porcentaje_pago_puntual'].isna().astype(int); den=x['ingresos_mensuales_cop'].replace(0,float('nan')); x['ratio_endeudamiento']=(x['obligaciones_mensuales_cop']+x['cuota_estimada_cop'])/den; x['cuota_ingreso']=x['cuota_estimada_cop']/den
    p=float(app.state.model.predict_proba(x)[:,1][0]); m=app.state.manifest; risk_favorable=p<m['threshold']; accepted=customer['active'] and customer['income']>0 and risk_favorable and 6<=body.term_months<=36
    loan=str(uuid.uuid4()); status='PENDIENTE_INVENTARIO' if accepted else 'RECHAZADA'; reason=None if accepted else ('CLIENTE_INACTIVO' if not customer['active'] else 'INGRESO_INVALIDO' if customer['income']<=0 else 'RIESGO_SUPERIOR_UMBRAL' if not risk_favorable else 'PLAZO_INVALIDO')
    try:
      with engine.begin() as c:
        c.execute(text('INSERT INTO loans(id,customer_id,product_id,quantity,term_months,price_cop,product_version,probability,threshold,model_version,status,reason) VALUES(:id,:customer,:product,:q,:term,:price,:version,:p,:threshold,:model,:status,:reason)'),{'id':loan,'customer':body.customer_id,'product':body.product_id,'q':body.quantity,'term':n,'price':price,'version':product['version'],'p':p,'threshold':m['threshold'],'model':m['model_version'],'status':status,'reason':reason})
        c.execute(text('INSERT INTO idempotency(key,request_hash,loan_id) VALUES(:k,:h,:id)'),{'k':idempotency_key,'h':body_hash,'id':loan})
        if accepted: c.execute(text("INSERT INTO outbox(event_id,type,correlation_id,loan_id,payload) VALUES(:e,'ReservaSolicitada',:c,:id,CAST(:payload AS JSONB))"),{'e':str(uuid.uuid4()),'c':loan,'id':loan,'payload':json.dumps({'producto_id':body.product_id,'cantidad':body.quantity})})
    except Exception as e:
      with engine.connect() as c: prev=c.execute(text('SELECT request_hash,loan_id FROM idempotency WHERE key=:k'),{'k':idempotency_key}).first()
      if prev:
        if prev[0]!=body_hash: raise HTTPException(409,'Idempotency-Key reused with different request')
        return loan_get(prev[1])
      raise HTTPException(409,str(e))
    response.status_code=202 if accepted else 200
    return {'id':loan,'status':status,'reason':reason,'probabilidad_incumplimiento':p,'decision_riesgo':'FAVORABLE' if risk_favorable else 'DESFAVORABLE','model_version':m['model_version'],'price_cop':price,'product_version':product['version']}
@app.get('/loans/{id}')
@app.get('/prestamos/{id}')
def loan_get(id:str):
    require('loans')
    with engine.connect() as c: r=c.execute(text('SELECT * FROM loans WHERE id=:id'),{'id':id}).mappings().first()
    if not r: raise HTTPException(404,'Loan not found')
    d=dict(r); d['probabilidad_incumplimiento']=d.pop('probability'); d['decision_riesgo']='FAVORABLE' if d['probabilidad_incumplimiento']<d['threshold'] else 'DESFAVORABLE'; return d
@app.get('/modelo/info')
def model_info():
    require('loans')
    if app.state.model is None: raise HTTPException(503,'No model promoted')
    return {k:app.state.manifest[k] for k in ['model_version','run_id','features','threshold']}
@app.post('/riesgo/predict')
def risk_predict(body:RiskIn):
    require('loans')
    if app.state.model is None: raise HTTPException(503,'No model promoted')
    x=pd.DataFrame([body.model_dump()]); x['tipo_empleo']=x['tipo_empleo'].astype(object); x.loc[x['tipo_empleo'].isna(),'tipo_empleo']=float('nan'); x['sin_historial']=x['porcentaje_pago_puntual'].isna().astype(int); den=x['ingresos_mensuales_cop'].replace(0,float('nan')); x['ratio_endeudamiento']=(x['obligaciones_mensuales_cop']+x['cuota_estimada_cop'])/den; x['cuota_ingreso']=x['cuota_estimada_cop']/den
    p=float(app.state.model.predict_proba(x)[:,1][0]); m=app.state.manifest
    return {'probabilidad_incumplimiento':p,'decision_riesgo':'FAVORABLE' if p<m['threshold'] else 'DESFAVORABLE','umbral':m['threshold'],'model_version':m['model_version']}

def require(name):
    if SERVICE!=name: raise HTTPException(404,'Not found')
