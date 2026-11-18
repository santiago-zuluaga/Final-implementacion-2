#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=products_pw="$PRODUCTS_DB_PASSWORD" \
  --set=customers_pw="$CUSTOMERS_DB_PASSWORD" \
  --set=loans_pw="$LOANS_DB_PASSWORD" \
  --set=inventory_pw="$INVENTORY_DB_PASSWORD" <<'SQL'
CREATE ROLE cm_products LOGIN PASSWORD :'products_pw';
CREATE ROLE cm_customers LOGIN PASSWORD :'customers_pw';
CREATE ROLE cm_loans LOGIN PASSWORD :'loans_pw';
CREATE ROLE cm_inventory LOGIN PASSWORD :'inventory_pw';
CREATE DATABASE cm_products OWNER cm_products;
CREATE DATABASE cm_customers OWNER cm_customers;
CREATE DATABASE cm_loans OWNER cm_loans;
CREATE DATABASE cm_inventory OWNER cm_inventory;
REVOKE CONNECT ON DATABASE cm_products FROM PUBLIC;
REVOKE CONNECT ON DATABASE cm_customers FROM PUBLIC;
REVOKE CONNECT ON DATABASE cm_loans FROM PUBLIC;
REVOKE CONNECT ON DATABASE cm_inventory FROM PUBLIC;
SQL
