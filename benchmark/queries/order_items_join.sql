-- planlens-index: CREATE INDEX idx_order_items_order_id ON order_items (order_id);
-- Expected shape: the planner may join order_items without an index on order_id; whether it
-- picks a nested loop depends on statistics, so check the plan with EXPLAIN first.
SELECT o.id, i.quantity, i.unit_price
FROM orders AS o
JOIN order_items AS i ON i.order_id = o.id
WHERE o.customer_id = 4242;
