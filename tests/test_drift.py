import json
import asyncio

import httpx
import numpy as np

from ml.drift import psi
from domain_service import app as service
from domain_service.security import issue_token


def call(path, token):
    async def request():
        transport = httpx.ASGITransport(app=service.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
            return await client.get(path, headers={'Authorization': f'Bearer {token}'})
    return asyncio.run(request())


def test_psi_detects_shift_from_constant_reference_and_keeps_outlier_mass():
    assert psi([5, 5, 5], [5, 5, 5]) == 0
    assert psi([5, 5, 5], [9, 9, 9]) > 0.2
    baseline = np.arange(100)
    shifted = np.arange(90, 190)
    assert psi(baseline, shifted) > 0.2
    assert psi([None, float('nan')], [1, 2]) is None


def test_drift_endpoint_reports_data_drift_limit_and_admin_ownership(monkeypatch, tmp_path):
    monkeypatch.setenv('JWT_SECRET', 'unit-test-jwt-secret-not-for-production-123456789')
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    (tmp_path / 'artifacts').mkdir()
    report = {'baseline': 'reference', 'comparison': 'unlabeled', 'features': {'income': 0.31},
              'threshold': 0.2, 'drifted': ['income']}
    (tmp_path / 'artifacts' / 'drift_report.json').write_text(json.dumps(report), encoding='utf-8')
    previous_service = service.SERVICE
    service.SERVICE = 'loans'
    admin = issue_token('admin', 'ADMIN')
    customer = issue_token('customer', 'CUSTOMER', 'C-1')
    try:
        response = call('/monitoring/drift', admin)
        forbidden = call('/monitoring/drift', customer)
        assert response.status_code == 200
        assert response.json()['data_drift_only'] is True
        assert response.json()['performance_degradation_assessed'] is False
        assert 'no tiene etiquetas' in response.json()['limitation']
        assert forbidden.status_code == 403
    finally:
        service.SERVICE = previous_service


def test_drift_endpoint_reports_missing_report_as_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('JWT_SECRET', 'unit-test-jwt-secret-not-for-production-123456789')
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    previous_service = service.SERVICE
    service.SERVICE = 'loans'
    admin = issue_token('admin', 'ADMIN')
    try:
        response = call('/monitoring/drift', admin)
        assert response.status_code == 503
    finally:
        service.SERVICE = previous_service
