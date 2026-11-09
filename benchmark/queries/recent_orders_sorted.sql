-- planlens-index: CREATE INDEX idx_orders_created_at_desc ON orders (created_at DESC);
-- Expected shape: a large sort that may spill to disk when work_mem is small.
SELECT id, created_at
FROM orders
ORDER BY created_at DESC
LIMIT 50000;
