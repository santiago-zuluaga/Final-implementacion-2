import asyncio

import httpx
import numpy as np
import pytest

from domain_service import security


SECRET = 'unit-test-jwt-secret-not-for-production-123456789'
LOAN_ID = '124d5d25-183d-44d0-85f0-160f8d936878'


def call_api(service, method, path, token=None):
    async def request():
        transport = httpx.ASGITransport(app=service.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
            headers = {'Authorization': f'Bearer {token}'} if token else {}
            return await client.request(method, path, headers=headers)
    return asyncio.run(request())


@pytest.fixture
def loans_service(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', SECRET)
    import domain_service.app as service
    previous_service = service.SERVICE
    previous_model = getattr(service.app.state, 'model', None)
    previous_manifest = getattr(service.app.state, 'manifest', {})
    service.SERVICE = 'loans'
    yield service
    service.SERVICE = previous_service
    service.app.state.model = previous_model
    service.app.state.manifest = previous_manifest


def test_customer_reads_own_loan_with_full_uuid_but_not_another_customer(loans_service, monkeypatch):
    row = {'id': LOAN_ID, 'customer_id': 'C-1', 'product_id': 7, 'quantity': 2,
           'term_months': 18, 'price_cop': 400000, 'probability': .12,
           'threshold': .3, 'model_version': 'v1', 'status': 'APROBADA', 'reason': None}
    def lookup(loan_id):
        assert loan_id == LOAN_ID
        return loans_service.loan_dict(row)
    monkeypatch.setattr(loans_service, 'loan_result', lookup)
    own = security.issue_token('customer-1', 'CUSTOMER', 'C-1')
    other = security.issue_token('customer-2', 'CUSTOMER', 'C-2')
    assert call_api(loans_service, 'GET', f'/prestamos/{LOAN_ID}', own).status_code == 200
    assert call_api(loans_service, 'GET', f'/prestamos/{LOAN_ID}', other).status_code == 403


def test_model_info_is_safe_for_customer_and_detailed_for_admin(loans_service):
    loans_service.app.state.model = object()
    loans_service.app.state.manifest = {'model_version': 'v1', 'run_id': 'private-run',
                                        'features': ['private-feature'], 'threshold': .3}
    admin = security.issue_token('admin', 'ADMIN')
    customer = security.issue_token('customer', 'CUSTOMER', 'C-1')
    admin_response = call_api(loans_service, 'GET', '/modelo/info', admin)
    customer_response = call_api(loans_service, 'GET', '/modelo/info', customer)
    assert admin_response.status_code == 200
    assert admin_response.json()['available'] is True
    assert admin_response.json()['run_id'] == 'private-run'
    assert customer_response.status_code == 200
    assert customer_response.json() == {'available': True, 'model_version': 'v1'}


def test_missing_model_is_reported_as_unavailable_and_readiness_fails(loans_service, monkeypatch):
    loans_service.app.state.model = None
    loans_service.app.state.manifest = {}
    customer = security.issue_token('customer', 'CUSTOMER', 'C-1')
    response = call_api(loans_service, 'GET', '/modelo/info', customer)
    assert response.status_code == 200
    assert response.json() == {'available': False, 'model_version': None}

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, *_): return None
    class Engine:
        def connect(self): return Connection()
    monkeypatch.setattr(loans_service, 'engine', Engine())
    ready = call_api(loans_service, 'GET', '/ready')
    assert ready.status_code == 503


def test_loaded_model_prediction_validates_input_and_reports_version(loans_service):
    class Model:
        def predict_proba(self, frame):
            return np.array([[0.8, 0.2]])

    loans_service.app.state.model = Model()
    loans_service.app.state.manifest = {'model_version': 'v-test', 'threshold': .3}
    token = security.issue_token('admin', 'ADMIN')
    body = {
        'ingresos_mensuales_cop': 5_000_000, 'obligaciones_mensuales_cop': 400_000,
        'tipo_empleo': 'dependiente', 'antiguedad_laboral_meses': 36,
        'meses_historial_crediticio': 24, 'creditos_previos': 2,
        'atrasos_previos_30d': 0, 'porcentaje_pago_puntual': 100,
        'monto_solicitado_cop': 1_000_000, 'plazo_meses': 12,
        'cuota_estimada_cop': 100_000,
    }

    async def request(payload):
        transport = httpx.ASGITransport(app=loans_service.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
            return await client.post('/riesgo/predict', json=payload,
                                     headers={'Authorization': f'Bearer {token}'})

    response = asyncio.run(request(body))
    assert response.status_code == 200
    assert response.json() == {'probabilidad_incumplimiento': .2, 'decision_riesgo': 'FAVORABLE',
                               'umbral': .3, 'model_version': 'v-test'}
    assert asyncio.run(request({**body, 'ingresos_mensuales_cop': 0})).status_code == 422
    assert asyncio.run(request({**body, 'extra': True})).status_code == 422


def test_prediction_returns_unavailable_when_model_is_not_loaded(loans_service):
    loans_service.app.state.model = None
    loans_service.app.state.manifest = {}
    token = security.issue_token('admin', 'ADMIN')
    body = {
        'ingresos_mensuales_cop': 5_000_000, 'obligaciones_mensuales_cop': 400_000,
        'tipo_empleo': None, 'antiguedad_laboral_meses': None,
        'meses_historial_crediticio': None, 'creditos_previos': 0,
        'atrasos_previos_30d': 0, 'porcentaje_pago_puntual': None,
        'monto_solicitado_cop': 1_000_000, 'plazo_meses': 12,
        'cuota_estimada_cop': 100_000,
    }

    async def request():
        transport = httpx.ASGITransport(app=loans_service.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
            return await client.post('/riesgo/predict', json=body,
                                     headers={'Authorization': f'Bearer {token}'})

    assert asyncio.run(request()).status_code == 503


def test_readiness_returns_service_unavailable_when_database_is_down(loans_service, monkeypatch):
    class Engine:
        def connect(self):
            raise OSError('database unavailable')

    monkeypatch.setattr(loans_service, 'engine', Engine())
    response = call_api(loans_service, 'GET', '/ready')
    assert response.status_code == 503
