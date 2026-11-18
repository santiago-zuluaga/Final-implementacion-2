"""Create a small synthetic product/inventory catalog through the public APIs."""
import os
import requests

PRODUCTS=os.getenv('PRODUCTS_URL','http://localhost:8001')
INVENTORY=os.getenv('INVENTORY_URL','http://localhost:8004')
SEED=[('Portátil de demostración','Computadores',2899000),('Teléfono de demostración','Celulares',1499000),('Audífonos de demostración','Accesorios',249000)]

def main():
    existing=requests.get(PRODUCTS+'/products',timeout=5); existing.raise_for_status()
    by_name={p['name']:p for p in existing.json()}
    for name,category,price in SEED:
      product=by_name.get(name)
      if not product:
        response=requests.post(PRODUCTS+'/products',json={'name':name,'category':category,'price_cop':price},timeout=5); response.raise_for_status(); product=response.json()
      stock=requests.get(INVENTORY+'/inventory',timeout=5); stock.raise_for_status()
      if not any(s['product_id']==product['id'] for s in stock.json()):
        response=requests.post(INVENTORY+'/inventory/stock',json={'product_id':product['id'],'quantity':5},timeout=5); response.raise_for_status()
      print(f"{product['name']} (id={product['id']}) → 5 unidades iniciales si no existían")

if __name__=='__main__': main()
