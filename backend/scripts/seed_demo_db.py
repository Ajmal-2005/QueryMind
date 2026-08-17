"""Build the demo e-commerce target database.

Produces a SQLite file the platform can connect to as a *target* database -
the thing a user would point it at. Deliberately mirrors the schema the
custom evaluation set is written against, and includes the awkward parts of a
real schema: a junction table, a self-referencing hierarchy, an abbreviated
column name, and a low-cardinality status column.

    python -m scripts.seed_demo_db
"""

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "demo_ecommerce.db"

SCHEMA = """
CREATE TABLE categories (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_id       INTEGER REFERENCES categories(id)
);

CREATE TABLE products (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    sku             TEXT NOT NULL UNIQUE,
    category_id     INTEGER NOT NULL REFERENCES categories(id),
    price           REAL NOT NULL,
    stock_quantity  INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE customers (
    id              INTEGER PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    region          TEXT NOT NULL,
    signup_date     TEXT NOT NULL
);

CREATE TABLE orders (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    status          TEXT NOT NULL,
    total_amount    REAL NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE order_items (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    product_id      INTEGER NOT NULL REFERENCES products(id),
    quantity        INTEGER NOT NULL,
    unit_price      REAL NOT NULL
);

CREATE TABLE suppliers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    country         TEXT NOT NULL
);

-- Junction table. Retrieval on its own tends to miss these, which is exactly
-- what foreign-key expansion is for.
CREATE TABLE product_suppliers (
    product_id      INTEGER NOT NULL REFERENCES products(id),
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id),
    lead_time_days  INTEGER NOT NULL,
    PRIMARY KEY (product_id, supplier_id)
);

-- Cryptic name and no foreign keys, like the audit tables real schemas carry.
CREATE TABLE cust_ref_log_v2 (
    id              INTEGER PRIMARY KEY,
    ref_code        TEXT NOT NULL,
    logged_at       TEXT NOT NULL
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_created ON orders(created_at);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_products_category ON products(category_id);
"""

REGIONS = ["North", "South", "East", "West", "Central"]
STATUSES = ["completed", "pending", "cancelled", "refunded"]
COUNTRIES = ["India", "Germany", "Vietnam", "Mexico", "Poland"]

TOP_CATEGORIES = [
    "Electronics",
    "Home & Garden",
    "Apparel",
    "Sports & Outdoors",
    "Books",
]
SUBCATEGORIES = {
    "Electronics": ["Laptops", "Headphones", "Cameras"],
    "Home & Garden": ["Outdoor Furniture", "Kitchenware", "Lighting"],
    "Apparel": ["Footwear", "Outerwear"],
    "Sports & Outdoors": ["Camping", "Cycling"],
    "Books": ["Fiction", "Technical"],
}


def seed(path: Path = DEFAULT_PATH, seed_value: int = 20260815) -> Path:
    """Create the database, replacing any existing file."""
    rng = random.Random(seed_value)  # reproducible: the demo must not drift

    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    category_ids: dict[str, int] = {}
    next_id = 1
    for top in TOP_CATEGORIES:
        conn.execute(
            "INSERT INTO categories (id, name, parent_id) VALUES (?, ?, NULL)",
            (next_id, top),
        )
        category_ids[top] = next_id
        parent = next_id
        next_id += 1
        for sub in SUBCATEGORIES[top]:
            conn.execute(
                "INSERT INTO categories (id, name, parent_id) VALUES (?, ?, ?)",
                (next_id, sub, parent),
            )
            category_ids[sub] = next_id
            next_id += 1

    leaf_ids = [category_ids[s] for subs in SUBCATEGORIES.values() for s in subs]

    for i in range(1, 121):
        conn.execute(
            "INSERT INTO products (id, name, sku, category_id, price, "
            "stock_quantity, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                i,
                f"Product {i:03d}",
                f"SKU-{i:05d}",
                rng.choice(leaf_ids),
                round(rng.uniform(5, 950), 2),
                rng.choice([0, 0, 5, 20, 75, 200]),
                1 if rng.random() > 0.1 else 0,
            ),
        )

    start = date(2024, 1, 1)
    for i in range(1, 501):
        conn.execute(
            "INSERT INTO customers (id, email, full_name, region, signup_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                i,
                f"customer{i:04d}@example.com",
                f"Customer {i:04d}",
                rng.choice(REGIONS),
                (start + timedelta(days=rng.randint(0, 600))).isoformat(),
            ),
        )

    for supplier_id, country in enumerate(COUNTRIES, start=1):
        conn.execute(
            "INSERT INTO suppliers (id, name, country) VALUES (?, ?, ?)",
            (supplier_id, f"Supplier {country}", country),
        )

    for product_id in range(1, 121):
        for supplier_id in rng.sample(range(1, 6), rng.randint(1, 2)):
            conn.execute(
                "INSERT INTO product_suppliers (product_id, supplier_id, "
                "lead_time_days) VALUES (?, ?, ?)",
                (product_id, supplier_id, rng.randint(3, 60)),
            )

    order_id = 1
    item_id = 1
    for _ in range(2000):
        created = start + timedelta(days=rng.randint(0, 700))
        items = [
            (rng.randint(1, 120), rng.randint(1, 4), round(rng.uniform(5, 950), 2))
            for _ in range(rng.randint(1, 4))
        ]
        total = round(sum(q * p for _, q, p in items), 2)

        conn.execute(
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                order_id,
                rng.randint(1, 500),
                rng.choices(STATUSES, weights=[70, 15, 10, 5])[0],
                total,
                created.isoformat(),
            ),
        )
        for product_id, quantity, unit_price in items:
            conn.execute(
                "INSERT INTO order_items (id, order_id, product_id, quantity, "
                "unit_price) VALUES (?, ?, ?, ?, ?)",
                (item_id, order_id, product_id, quantity, unit_price),
            )
            item_id += 1
        order_id += 1

    for i in range(1, 51):
        conn.execute(
            "INSERT INTO cust_ref_log_v2 (id, ref_code, logged_at) VALUES (?, ?, ?)",
            (i, f"REF-{rng.randint(1000, 9999)}", start.isoformat()),
        )

    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":
    created = seed()
    size_kb = created.stat().st_size / 1024
    print(f"Demo database written to {created} ({size_kb:.0f} KB)")
    print("\nRegister it in the app as a SQLite connection with this path:")
    print(f"  {created}")
