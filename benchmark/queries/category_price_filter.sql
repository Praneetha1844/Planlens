-- planlens-index: CREATE INDEX idx_products_category_price ON products (category, price);
-- Expected shape: sequential scan with equality + range filter. products is small, so a scan
-- may be the better plan; this case shows that an index is not always an improvement.
SELECT id, name
FROM products
WHERE category = 'tools'
  AND price > 100;
