"""Exercise deactivate/reactivate, historical visibility, role access and stock in Docker."""
import json
import os
import subprocess
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
URLS = {name: f'http://localhost:{port}' for name, port in
        (('customers', 8002), ('products', 8001), ('loans', 8003), ('inventory', 8004))}


def environment():
    result = os.environ.copy()
    for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            result.setdefault(key.strip(), value.strip())
    return result


def sql(service, query, params=None):
    # Parameters are JSON encoded and passed to a short read-only DB probe.
    code = (
        "import json,os; from sqlalchemy import create_engine,text; "
        "q=json.loads(os.environ['CM_SQL_QUERY']); p=json.loads(os.environ['CM_SQL_PARAMS']); "
        "e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); "
        "print(json.dumps([dict(x) for x in c.execute(text(q),p).mappings().all()])); c.close()"
    )
    child_env = os.environ.copy()
    child_env['CM_SQL_QUERY'] = json.dumps(query)
    child_env['CM_SQL_PARAMS'] = json.dumps(params or {})
    result = subprocess.run(['docker', 'compose', 'exec', '-T', '-e', f"CM_SQL_QUERY={child_env['CM_SQL_QUERY']}",
                             '-e', f"CM_SQL_PARAMS={child_env['CM_SQL_PARAMS']}", service, 'python', '-c', code],
                            cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def require_status(response, expected, label):
    if response.status_code != expected:
        raise AssertionError(f'{label}: HTTP {response.status_code}, expected {expected}: {response.text[:300]}')


def main():
    env = environment()
    admin_login = requests.post(f"{URLS['customers']}/auth/login", json={
        'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=8)
    admin_login.raise_for_status()
    admin = {'Authorization': f"Bearer {admin_login.json()['access_token']}"}
    product_id = int(os.getenv('CM_PRODUCT_ID', '2'))
    product_url = f"{URLS['products']}/products/{product_id}"
    original = requests.get(product_url, params={'include_inactive': 'true'}, headers=admin, timeout=8)
    original.raise_for_status()
    product = original.json()
    code = f"CM-{product_id:04d}"
    stock_before = sql('inventory', 'SELECT product_id,available,reserved FROM stock WHERE product_id=:id', {'id': product_id})
    if len(stock_before) != 1:
        raise AssertionError(f'Expected existing stock row for product {product_id}; got {stock_before}')

    # Temporary CUSTOMER fixture is used only for auth/ownership checks; it is removed in finally.
    tag = uuid.uuid4().hex[:12]
    customer_id, username, loan_key = f'FE01-{tag}', f'fe01-{tag}', f'fe01-inactive-{tag}'
    customer_created = False
    try:
        signup = requests.post(f"{URLS['customers']}/auth/register", json={
            'username': username, 'password': f'Temp-{uuid.uuid4().hex}-Aa9!',
            'customer': {'id': customer_id, 'name': 'Fixture lifecycle FE-01', 'income': 6000000,
                         'obligations': 100000, 'employment': 'dependiente', 'tenure_months': 48,
                         'history_months': 48, 'prior_credits': 3, 'late_payments': 0,
                         'payment_on_time': 100}}, timeout=8)
        signup.raise_for_status()
        customer_created = True
        customer = {'Authorization': f"Bearer {signup.json()['access_token']}"}

        # ADMIN deactivates the same existing product; it disappears from public financing options.
        deactivated = requests.post(f'{product_url}/deactivate', headers=admin, timeout=8)
        require_status(deactivated, 200, 'ADMIN deactivate')
        require_status(requests.get(URLS['products'] + '/products', timeout=8), 200, 'public active list')
        public_list = requests.get(URLS['products'] + '/products', timeout=8).json()
        if any(p['id'] == product_id for p in public_list):
            raise AssertionError('Inactive product remained in public active catalog')
        admin_list = requests.get(URLS['products'] + '/products', params={'include_inactive': 'true'}, headers=admin, timeout=8)
        admin_list.raise_for_status()
        historic = next(p for p in admin_list.json() if p['id'] == product_id)
        if historic['name'] != product['name'] or historic['active'] is not False:
            raise AssertionError('ADMIN historical product view lost original name/status')
        customer_detail = requests.get(product_url, params={'include_inactive': 'true'}, headers=customer, timeout=8)
        require_status(customer_detail, 403, 'CUSTOMER inactive detail')
        for method, url, kwargs in (
            ('post', f'{product_url}/activate', {}),
            ('post', f'{product_url}/deactivate', {}),
            ('put', product_url, {'json': {'name': product['name'], 'category': product['category'], 'price_cop': product['price_cop']}}),
        ):
            require_status(getattr(requests, method)(url, headers=customer, timeout=8, **kwargs), 403, f'CUSTOMER {method} restriction')

        # Inventory holds IDs only. Resolve the historical name through ADMIN's inactive-inclusive Products query.
        inventory_row = next(x for x in requests.get(URLS['inventory'] + '/inventory', headers=admin, timeout=8).json()
                             if x['product_id'] == product_id)
        if historic['name'] != 'Teléfono de demostración' or inventory_row['product_id'] != product_id:
            raise AssertionError('Inventory/product metadata mapping did not retain original product identity')
        quotation = requests.get(f'{product_url}/quotation', headers={'X-Internal-Token': env['INTERNAL_API_TOKEN']}, timeout=8)
        require_status(quotation, 404, 'inactive internal quotation')
        loan = requests.post(f'{URLS["loans"]}/prestamos', headers={**customer, 'Idempotency-Key': loan_key}, json={
            'customer_id': customer_id, 'product_id': product_id, 'quantity': 1, 'term_months': 12}, timeout=10)
        require_status(loan, 404, 'loan against inactive product')
        if sql('loans', 'SELECT key FROM idempotency WHERE key=:key', {'key': loan_key}):
            raise AssertionError('Inactive product request persisted an idempotency/loan effect')

        # CUSTOMER can read active catalog products but cannot mutate them.
        requests.get(URLS['products'] + '/products', headers=customer, timeout=8).raise_for_status()
        active_target = next(p for p in public_list if p['active'])
        target_url = f"{URLS['products']}/products/{active_target['id']}"
        require_status(requests.post(f'{target_url}/activate', headers=customer, timeout=8), 403, 'CUSTOMER activate')
        require_status(requests.post(f'{target_url}/deactivate', headers=customer, timeout=8), 403, 'CUSTOMER deactivate')
        require_status(requests.put(target_url, headers=customer, json={
            'name': active_target['name'], 'category': active_target['category'], 'price_cop': active_target['price_cop']}, timeout=8), 403, 'CUSTOMER edit')

        activated = requests.post(f'{product_url}/activate', headers=admin, timeout=8)
        activated.raise_for_status()
        active_detail = requests.get(product_url, timeout=8)
        active_detail.raise_for_status()
        if active_detail.json()['id'] != product_id or active_detail.json()['name'] != product['name']:
            raise AssertionError('Reactivation changed product identity or name')
        final_stock = sql('inventory', 'SELECT product_id,available,reserved FROM stock WHERE product_id=:id', {'id': product_id})
        if stock_before != final_stock:
            raise AssertionError(f'Inventory changed across deactivate/reactivate: {stock_before} -> {final_stock}')
        print(json.dumps({
            'product': {'id': product_id, 'code': code, 'name': product['name'], 'initial_active': product['active'],
                        'deactivate_http': deactivated.status_code, 'inactive_publicly_hidden': True,
                        'admin_historical_name_visible': historic['name'], 'inactive_quotation_http': quotation.status_code,
                        'inactive_loan_http': loan.status_code, 'reactivate_http': activated.status_code,
                        'reactivated_active': active_detail.json()['active']},
            'customer_access': {'active_catalog_read': '200', 'inactive_detail': customer_detail.status_code,
                                'reactivate_edit_deactivate': '403'},
            'inventory': {'before': stock_before, 'after': final_stock, 'unchanged': stock_before == final_stock},
            'temporary_customer_cleanup': 'executed in finally',
        }, ensure_ascii=False, indent=2))
    finally:
        # Leave the pre-existing demonstration product available for the owner.
        try:
            requests.post(f'{product_url}/activate', headers=admin, timeout=8).raise_for_status()
        finally:
            if customer_created:
                result = subprocess.run(['docker', 'compose', 'exec', '-T', 'customers', 'python', '-c',
                    "import os,sys; from sqlalchemy import create_engine,text; c=create_engine(os.environ['DATABASE_URL']).connect(); tx=c.begin(); "
                    "c.execute(text('DELETE FROM credentials WHERE username=:u'),{'u':sys.argv[1]}); "
                    "c.execute(text('DELETE FROM customers WHERE id=:id'),{'id':sys.argv[2]}); tx.commit(); c.close()",
                    username, customer_id], cwd=ROOT, capture_output=True, text=True)
                if result.returncode:
                    raise RuntimeError(f'Could not clean temporary customer fixture: {result.stderr[:300]}')


if __name__ == '__main__':
    main()
