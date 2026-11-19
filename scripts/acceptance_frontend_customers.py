"""Exercise customer portal ownership and ADMIN CSV reporting with isolated fixtures."""
import csv
import io
import os
import subprocess
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CUSTOMERS = 'http://localhost:8002'


def env_values():
    values = os.environ.copy()
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def delete_fixtures(username, *customer_ids):
    code = f"""import os
from sqlalchemy import create_engine,text
e=create_engine(os.environ['DATABASE_URL'])
with e.begin() as c:
 c.execute(text('DELETE FROM credentials WHERE username=:u'),{{'u':{username!r}}})
 for customer_id in {list(customer_ids)!r}:
  c.execute(text('DELETE FROM customers WHERE id=:id'),{{'id':customer_id}})
"""
    subprocess.run(['docker', 'compose', 'exec', '-T', 'customers', 'python', '-c', code],
                   cwd=ROOT, check=True, capture_output=True, text=True)


def main():
    env = env_values()
    suffix = uuid.uuid4().hex
    username = f'fe02-{suffix}'
    customer_id = f'FE02-C-{suffix}'
    imported_id = f'FE02-I-{suffix}'
    session = requests.Session()
    admin = session.post(f'{CUSTOMERS}/auth/login', json={
        'username': env['ADMIN_USERNAME'], 'password': env['ADMIN_PASSWORD']}, timeout=8)
    admin.raise_for_status()
    admin_headers = {'Authorization': f"Bearer {admin.json()['access_token']}"}
    existing = session.get(f'{CUSTOMERS}/customers', headers=admin_headers, timeout=8)
    existing.raise_for_status()
    foreign_id = next((row['id'] for row in existing.json() if row['id'] != customer_id), None)
    if not foreign_id:
        raise SystemExit('An existing customer is required to verify ownership restrictions')

    password = f'Autotest-{suffix}-Pass!'
    registered = False
    result = None
    try:
        response = session.post(f'{CUSTOMERS}/auth/register', json={
            'username': username, 'password': password,
            'customer': {'id': customer_id, 'name': 'FE02 temporary', 'income': 2_000_000,
                         'obligations': 100_000, 'employment': 'dependiente'},
        }, timeout=8)
        response.raise_for_status()
        registered = True
        token = response.json()['access_token']
        user_headers = {'Authorization': f'Bearer {token}'}

        profile = session.get(f'{CUSTOMERS}/customers', headers=user_headers, timeout=8)
        profile.raise_for_status()
        assert [row['id'] for row in profile.json()] == [customer_id]
        forbidden_get = session.get(f'{CUSTOMERS}/customers/{foreign_id}', headers=user_headers, timeout=8)
        assert forbidden_get.status_code == 403
        forbidden_put = session.put(f'{CUSTOMERS}/customers/{foreign_id}', headers=user_headers,
                                    json={'id': foreign_id, 'name': 'Should not change', 'income': 1,
                                          'obligations': 0, 'employment': 'dependiente'}, timeout=8)
        assert forbidden_put.status_code == 403
        forbidden_import = session.post(f'{CUSTOMERS}/customers/import', headers=user_headers,
                                        files={'file': ('clients.csv', 'cliente_id,nombre\n', 'text/csv')}, timeout=8)
        assert forbidden_import.status_code == 403

        updated = session.put(f'{CUSTOMERS}/customers/{customer_id}', headers=user_headers, json={
            'id': customer_id, 'name': 'FE02 updated', 'income': 2_100_000,
            'obligations': 90_000, 'employment': 'independiente', 'tenure_months': None,
            'history_months': None, 'prior_credits': 0, 'late_payments': 0,
            'payment_on_time': None, 'active': True,
        }, timeout=8)
        updated.raise_for_status()
        assert updated.json()['name'] == 'FE02 updated'

        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['cliente_id', 'nombre', 'ingresos_mensuales_cop', 'obligaciones_mensuales_cop',
                         'tipo_empleo', 'antiguedad_laboral_meses', 'meses_historial_crediticio',
                         'creditos_previos', 'atrasos_previos_30d', 'porcentaje_pago_puntual'])
        writer.writerow([customer_id, 'CSV updated', 2_200_000, 80_000, 'dependiente', 12, 12, 1, 0, 97])
        writer.writerow([imported_id, 'CSV inserted', 1_500_000, 0, 'temporal', 6, 6, 0, 0, 90])
        writer.writerow([f'{imported_id}-bad', 'CSV invalid', 'not-a-number', 0, 'dependiente', '', '', 0, 0, ''])
        imported = session.post(f'{CUSTOMERS}/customers/import', headers=admin_headers,
                                files={'file': ('clients.csv', stream.getvalue(), 'text/csv')}, timeout=8)
        imported.raise_for_status()
        report = imported.json()
        assert (report['insertados'], report['actualizados'], report['rechazados']) == (1, 1, 1), report
        assert report['errores'] and report['errores'][0]['fila'] == 4, report
        result = {'own_profile_read': 200, 'own_profile_update': updated.status_code,
                  'foreign_profile_read': forbidden_get.status_code,
                  'foreign_profile_update': forbidden_put.status_code,
                  'customer_csv_import': forbidden_import.status_code,
                  'admin_csv_report': {key: report[key] for key in ('insertados', 'actualizados', 'rechazados', 'errores')}}
    finally:
        if registered:
            delete_fixtures(username, customer_id, imported_id, f'{imported_id}-bad')
    print({**result, 'secrets_or_tokens_logged': False, 'fixture_cleanup': 'completed'})


if __name__ == '__main__':
    main()
