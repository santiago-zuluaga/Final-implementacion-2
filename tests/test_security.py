import asyncio

import pytest
import httpx

from domain_service import security


def test_password_hash_uses_unique_salts_and_verifies(monkeypatch):
    first_salt, first_hash = security.hash_password('correct-horse-battery-17')
    second_salt, second_hash = security.hash_password('correct-horse-battery-17')
    assert first_salt != second_salt
    assert first_hash != second_hash
    assert security.verify_password('correct-horse-battery-17', first_salt, first_hash)
    assert not security.verify_password('wrong-password', first_salt, first_hash)


def test_jwt_signature_claims_and_expiration(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'unit-test-jwt-secret-not-for-production-123456789')
    monkeypatch.setattr(security.time, 'time', lambda: 1000)
    token = security.issue_token('ana', 'CUSTOMER', 'C-1')
    assert security.verify_token(token)['customer_id'] == 'C-1'
    head, body, signature = token.split('.')
    with pytest.raises(ValueError):
        security.verify_token(f'{head}.{body}.invalid')
    monkeypatch.setattr(security.time, 'time', lambda: 1000 + security.JWT_TTL_SECONDS)
    with pytest.raises(ValueError, match='expired'):
        security.verify_token(token)


def test_business_endpoints_reject_anonymous_and_wrong_role(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'unit-test-jwt-secret-not-for-production-123456789')
    import domain_service.app as service
    previous = service.SERVICE
    service.SERVICE = 'products'
    try:
        async def requests():
            transport = httpx.ASGITransport(app=service.app)
            async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
                payload = {'name': 'Laptop', 'category': 'Computadores', 'price_cop': 1000}
                anonymous = await client.post('/products', json=payload)
                customer_token = security.issue_token('ana', 'CUSTOMER', 'C-1')
                wrong_role = await client.post('/products', json=payload, headers={'Authorization': f'Bearer {customer_token}'})
                malformed = await client.post('/products', json=payload, headers={'Authorization': 'Bearer broken'})
                return anonymous.status_code, wrong_role.status_code, malformed.status_code
        anonymous, wrong_role, malformed = asyncio.run(requests())
        assert anonymous == 401
        assert wrong_role == 403
        assert malformed == 401
    finally:
        service.SERVICE = previous


def test_customer_cannot_request_a_loan_for_another_customer(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'unit-test-jwt-secret-not-for-production-123456789')
    import domain_service.app as service
    previous = service.SERVICE
    service.SERVICE = 'loans'
    try:
        customer_token = security.issue_token('ana', 'CUSTOMER', 'C-1')
        async def request():
            transport = httpx.ASGITransport(app=service.app)
            async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
                return await client.post('/prestamos', json={'customer_id': 'C-2', 'product_id': 1, 'quantity': 1, 'term_months': 12}, headers={'Authorization': f'Bearer {customer_token}', 'Idempotency-Key': 'security-test-1'})
        assert asyncio.run(request()).status_code == 403
    finally:
        service.SERVICE = previous
