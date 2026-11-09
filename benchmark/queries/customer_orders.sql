-- planlens-index: CREATE INDEX idx_orders_customer_id ON orders (customer_id);
-- Expected shape: sequential scan of orders on a selective equality filter.
SELECT id, status, total
FROM orders
WHERE customer_id = 4242;
