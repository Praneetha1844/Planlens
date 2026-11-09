-- Demo schema for Planlens. It deliberately has primary keys and foreign keys but NO secondary
-- indexes, so the queries in benchmark/queries/ have something to improve.
-- Usage: createdb planlens_demo && psql planlens_demo -f sql/schema.sql -f sql/load.sql

DROP TABLE IF EXISTS order_items, orders, products, customers;

CREATE TABLE customers (
    id          integer PRIMARY KEY,
    name        text        NOT NULL,
    country     text        NOT NULL,
    created_at  date        NOT NULL
);

CREATE TABLE products (
    id        integer PRIMARY KEY,
    name      text          NOT NULL,
    category  text          NOT NULL,
    price     numeric(10,2) NOT NULL CHECK (price > 0)
);

CREATE TABLE orders (
    id           integer PRIMARY KEY,
    customer_id  integer       NOT NULL REFERENCES customers (id),
    status       text          NOT NULL CHECK (status IN ('open', 'paid', 'shipped', 'cancelled')),
    created_at   date          NOT NULL,
    total        numeric(12,2) NOT NULL
);

CREATE TABLE order_items (
    id          integer PRIMARY KEY,
    order_id    integer       NOT NULL REFERENCES orders (id),
    product_id  integer       NOT NULL REFERENCES products (id),
    quantity    integer       NOT NULL CHECK (quantity > 0),
    unit_price  numeric(10,2) NOT NULL
);
