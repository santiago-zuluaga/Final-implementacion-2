from domain_service import app as service


def test_database_guards_cover_persisted_loan_and_inventory_invariants():
    loans = service.DB_CONSTRAINTS['loans']
    inventory = service.DB_CONSTRAINTS['inventory']
    assert {'loans_quantity_positive', 'loans_term_months_valid', 'loans_price_positive',
            'loans_probability_valid', 'loans_threshold_valid', 'loans_status_valid',
            'idempotency_key_nonempty', 'idempotency_hash_sha256',
            'idempotency_loan_nonempty'} <= set(loans)
    assert {'reservations_quantity_positive', 'reservations_status_valid',
            'movements_quantity_positive', 'movements_kind_valid'} <= set(inventory)
    assert loans['loans_quantity_positive'] == ('loans', 'quantity > 0')
    assert loans['loans_probability_valid'] == ('loans', 'probability BETWEEN 0 AND 1')
    assert inventory['reservations_quantity_positive'] == ('reservations', 'quantity > 0')
    assert inventory['movements_quantity_positive'] == ('movements', 'quantity > 0')


def test_constraint_migrations_are_scoped_to_the_owning_databases():
    assert set(service.DB_CONSTRAINTS) == {'loans', 'inventory'}
    for constraints in service.DB_CONSTRAINTS.values():
        assert all(table in {'loans', 'idempotency', 'reservations', 'movements'}
                   for table, _ in constraints.values())
