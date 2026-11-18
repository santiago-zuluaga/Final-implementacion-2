"""Create a small synthetic product/inventory catalog through the public APIs."""
import os
import requests
from dotenv import load_dotenv

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT,'.env'))

PRODUCTS=os.getenv('PRODUCTS_URL','http://localhost:8001')
INVENTORY=os.getenv('INVENTORY_URL','http://localhost:8004')
CUSTOMERS=os.getenv('CUSTOMERS_URL','http://localhost:8002')
SEED=[('Portátil de demostración','Computadores',2899000),('Teléfono de demostración','Celulares',1499000),('Audífonos de demostración','Accesorios',249000)]

def main():
    credentials={'username':os.environ['ADMIN_USERNAME'],'password':os.environ['ADMIN_PASSWORD']}
    login=requests.post(CUSTOMERS+'/auth/login',json=credentials,timeout=5); login.raise_for_status()
    admin_headers={'Authorization':f"Bearer {login.json()['access_token']}"}
    existing=requests.get(PRODUCTS+'/products',timeout=5); existing.raise_for_status()
    by_name={p['name']:p for p in existing.json()}
    for name,category,price in SEED:
      product=by_name.get(name)
      if not product:
        response=requests.post(PRODUCTS+'/products',json={'name':name,'category':category,'price_cop':price},headers=admin_headers,timeout=5); response.raise_for_status(); product=response.json()
      stock=requests.get(INVENTORY+'/inventory',headers=admin_headers,timeout=5); stock.raise_for_status()
      if not any(s['product_id']==product['id'] for s in stock.json()):
        response=requests.post(INVENTORY+'/inventory/stock',json={'product_id':product['id'],'quantity':5},headers=admin_headers,timeout=5); response.raise_for_status()
      print(f"{product['name']} (id={product['id']}) - 5 unidades iniciales si no existian")

if __name__=='__main__': main()
