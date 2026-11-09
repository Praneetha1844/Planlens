-- Loads the CSV files written by `planlens gen --out data`. Run from the repository root with psql.
\copy customers   FROM 'data/customers.csv'   WITH (FORMAT csv, HEADER true)
\copy products    FROM 'data/products.csv'    WITH (FORMAT csv, HEADER true)
\copy orders      FROM 'data/orders.csv'      WITH (FORMAT csv, HEADER true)
\copy order_items FROM 'data/order_items.csv' WITH (FORMAT csv, HEADER true)

ANALYZE;
