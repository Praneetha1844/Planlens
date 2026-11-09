"""Seeded synthetic data for the demo schema in `sql/schema.sql`.

The same `(scale, seed)` always produces the same files. Row counts at scale 1.0: 10,000
customers, 500 products, 100,000 orders and about 300,000 order items.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from random import Random

COUNTRIES = ("IN", "US", "DE", "FR", "ES", "IT", "NL", "FI")
CATEGORIES = ("books", "tools", "toys", "garden", "kitchen", "sports", "music", "office")
STATUSES = ("open", "paid", "shipped", "cancelled")
STATUS_WEIGHTS = (5, 20, 70, 5)  # most orders are finished, so "open" is selective
BASE_DATE = date(2023, 1, 1)
DAY_SPAN = 730

BASE_COUNTS = {"customers": 10_000, "products": 500, "orders": 100_000}


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def generate(out_dir: Path, *, scale: float = 1.0, seed: int = 42) -> dict[str, int]:
    """Write four CSV files into `out_dir` and return the number of rows written per table."""
    if scale <= 0:
        raise ValueError("scale must be > 0")
    n_customers = max(1, int(BASE_COUNTS["customers"] * scale))
    n_products = max(1, int(BASE_COUNTS["products"] * scale))
    n_orders = max(1, int(BASE_COUNTS["orders"] * scale))
    rng = Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    def created() -> str:
        return (BASE_DATE + timedelta(days=rng.randrange(DAY_SPAN))).isoformat()

    with (out_dir / "customers.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "name", "country", "created_at"])
        for cid in range(1, n_customers + 1):
            writer.writerow([cid, f"customer_{cid}", rng.choice(COUNTRIES), created()])

    prices: list[int] = []
    with (out_dir / "products.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "name", "category", "price"])
        for pid in range(1, n_products + 1):
            cents = rng.randrange(500, 50_000)
            prices.append(cents)
            writer.writerow([pid, f"product_{pid}", rng.choice(CATEGORIES), _money(cents)])

    item_id = 0
    n_items = 0
    with (
        (out_dir / "orders.csv").open("w", newline="", encoding="utf-8") as orders_file,
        (out_dir / "order_items.csv").open("w", newline="", encoding="utf-8") as items_file,
    ):
        orders = csv.writer(orders_file)
        items = csv.writer(items_file)
        orders.writerow(["id", "customer_id", "status", "created_at", "total"])
        items.writerow(["id", "order_id", "product_id", "quantity", "unit_price"])
        for oid in range(1, n_orders + 1):
            total = 0
            for _ in range(rng.randint(1, 5)):
                item_id += 1
                pid = rng.randint(1, n_products)
                quantity = rng.randint(1, 4)
                total += prices[pid - 1] * quantity
                items.writerow([item_id, oid, pid, quantity, _money(prices[pid - 1])])
                n_items += 1
            status = rng.choices(STATUSES, weights=STATUS_WEIGHTS)[0]
            orders.writerow([oid, rng.randint(1, n_customers), status, created(), _money(total)])

    return {
        "customers": n_customers,
        "products": n_products,
        "orders": n_orders,
        "order_items": n_items,
    }
