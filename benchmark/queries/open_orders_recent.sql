-- planlens-index: CREATE INDEX idx_orders_status_created_at ON orders (status, created_at);
-- Expected shape: sequential scan of orders discarding most rows (equality + range filter).
SELECT id, total
FROM orders
WHERE status = 'open'
  AND created_at >= DATE '2024-06-01';
