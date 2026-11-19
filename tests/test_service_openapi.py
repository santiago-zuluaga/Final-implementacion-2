import asyncio

import httpx
import pytest

from domain_service import security
from domain_service import app as service


SERVICES = {'products', 'customers', 'loans', 'inventory'}


def operations(schema):
    return {
        (method.upper(), path)
        for path, path_item in schema['paths'].items()
        for method in path_item
        if method.lower() in {'get', 'post', 'put', 'patch', 'delete', 'options', 'head'}
    }


def test_every_registered_route_has_one_explicit_owner():
    registered = {
        (method, route.path)
        for route in service.app.routes
        if isinstance(route, service.APIRoute)
        for method in route.methods
    }
    assert registered == set(service.ROUTE_OWNERS)
    assert {owner for owner in service.ROUTE_OWNERS.values()} <= SERVICES | {'shared'}
    for route in service.app.routes:
        if not isinstance(route, service.APIRoute):
            continue
        owner = service.ROUTE_OWNERS[(next(iter(route.methods)), route.path)]
        if owner == 'shared':
            continue
        guarded_names = set(route.endpoint.__code__.co_names)
        guard_constants = set(route.endpoint.__code__.co_consts)
        if route.endpoint.__name__ == 'product_get':
            guarded_names.update(service.get_product.__code__.co_names)
            guard_constants.update(service.get_product.__code__.co_consts)
        assert 'require' in guarded_names, f'{route.path} has no runtime service guard'
        assert owner in guard_constants, f'{route.path} is not guarded for owner {owner}'


def test_each_service_openapi_contains_only_owned_and_shared_operations():
    for name in SERVICES:
        schema = service.build_service_openapi(name)
        expected = {
            route for route, owner in service.ROUTE_OWNERS.items()
            if owner in {'shared', name}
        }
        assert operations(schema) == expected
        assert schema['info']['title'] == f'CrediMarket {name.title()}'


def test_loan_compatibility_aliases_are_explicitly_deprecated():
    schema = service.build_service_openapi('loans')
    assert schema['paths']['/loans']['post']['deprecated'] is True
    assert schema['paths']['/loans/{id}']['get']['deprecated'] is True
    assert schema['paths']['/drift']['get']['deprecated'] is True


def test_openapi_documents_dynamic_acceptance_and_domain_errors():
    loans = service.build_service_openapi('loans')['paths']
    assert {'200', '202', '401', '403', '404', '409', '422', '503'} <= set(loans['/prestamos']['post']['responses'])
    assert '202' in loans['/loans']['post']['responses']
    assert '503' in loans['/ready']['get']['responses']
    inventory = service.build_service_openapi('inventory')['paths']
    assert '409' in inventory['/inventory/reservations/{loan_id}/deliver']['post']['responses']
    for schema, path in ((loans, '/prestamos'), (inventory, '/inventory/movements')):
        params = {item['name']: item['schema'] for item in schema[path]['get']['parameters']}
        assert params['limit']['minimum'] == 1 and params['limit']['maximum'] == 200
        assert params['offset']['minimum'] == 0


def test_auth_me_is_not_exposed_by_non_customer_service(monkeypatch):
    monkeypatch.setenv('JWT_SECRET', 'unit-test-jwt-secret-not-for-production-123456789')
    previous = service.SERVICE
    service.SERVICE = 'products'
    token = security.issue_token('ana', 'CUSTOMER', 'C-1')

    async def request():
        transport = httpx.ASGITransport(app=service.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
            return await client.get('/auth/me', headers={'Authorization': f'Bearer {token}'})

    try:
        assert asyncio.run(request()).status_code == 404
    finally:
        service.SERVICE = previous


@pytest.mark.parametrize(('deployed_service', 'foreign_path'), [
    ('products', '/customers'),
    ('customers', '/products'),
    ('loans', '/inventory'),
    ('inventory', '/prestamos'),
])
def test_foreign_domain_route_is_rejected_before_domain_access(deployed_service, foreign_path):
    previous = service.SERVICE
    service.SERVICE = deployed_service

    async def request():
        transport = httpx.ASGITransport(app=service.app)
        async with httpx.AsyncClient(transport=transport, base_url='http://service.test') as client:
            return await client.get(foreign_path)

    try:
        assert asyncio.run(request()).status_code == 404
    finally:
        service.SERVICE = previous
