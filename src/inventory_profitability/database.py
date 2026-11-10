"""SQLite storage and SQL summaries for products and historical sales."""

import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ProductRow = dict[str, Any]
SalesRow = dict[str, Any]

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    purchase_cost_cents INTEGER NOT NULL CHECK (purchase_cost_cents > 0),
    selling_price_cents INTEGER NOT NULL CHECK (selling_price_cents > 0),
    initial_stock INTEGER NOT NULL CHECK (initial_stock >= 0)
);

CREATE TABLE IF NOT EXISTS historical_sales (
    sale_date TEXT NOT NULL,
    product_id TEXT NOT NULL,
    units_sold INTEGER NOT NULL CHECK (units_sold >= 0),
    PRIMARY KEY (sale_date, product_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
"""


def initialize_database(database_path: str | Path) -> None:
    """Create the database folder and required tables if they do not exist."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)


def import_historical_data(
    database_path: str | Path,
    products: list[ProductRow],
    sales: list[SalesRow],
) -> None:
    """Save validated data atomically, storing money as integer cents.

    Re-importing the same keys updates their values, so rows are not duplicated.
    If a row conflicts with existing data, the new CSV value replaces it.
    Values with more than two decimal places are rounded to cents using
    ROUND_HALF_UP.
    Any failure rolls back the whole import.
    """
    initialize_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executemany(
                """
                INSERT INTO products (
                    product_id, name, category, purchase_cost_cents,
                    selling_price_cents, initial_stock
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    purchase_cost_cents = excluded.purchase_cost_cents,
                    selling_price_cents = excluded.selling_price_cents,
                    initial_stock = excluded.initial_stock
                """,
                [
                    (
                        row["product_id"], row["name"], row["category"],
                        _to_cents(row["purchase_cost"]),
                        _to_cents(row["selling_price"]),
                        row["initial_stock"],
                    )
                    for row in products
                ],
            )
            connection.executemany(
                """
                INSERT INTO historical_sales (sale_date, product_id, units_sold)
                VALUES (?, ?, ?)
                ON CONFLICT(sale_date, product_id) DO UPDATE SET
                    units_sold = excluded.units_sold
                """,
                [
                    (row["date"], row["product_id"], row["units_sold"])
                    for row in sales
                ],
            )


def historical_sales_by_product(database_path: str | Path) -> list[dict[str, Any]]:
    """Return units, revenue, cost of goods sold, and gross profit per product."""
    query = """
        SELECT p.product_id,
               COUNT(DISTINCT s.sale_date) AS days,
               SUM(s.units_sold) AS units_sold,
               AVG(s.units_sold) AS mean_daily_units,
               SUM(s.units_sold * p.selling_price_cents) / 100.0 AS revenue,
               SUM(s.units_sold * p.purchase_cost_cents) / 100.0 AS cost_of_goods_sold,
               SUM(s.units_sold * (p.selling_price_cents - p.purchase_cost_cents)) / 100.0 AS gross_profit
        FROM products AS p
        JOIN historical_sales AS s ON s.product_id = p.product_id
        GROUP BY p.product_id
        ORDER BY p.product_id
    """
    return _fetch_all(database_path, query)


def historical_revenue_by_category(database_path: str | Path) -> list[dict[str, Any]]:
    """Return historical sales units and revenue grouped by product category."""
    query = """
        SELECT p.category,
               SUM(s.units_sold) AS units_sold,
               SUM(s.units_sold * p.selling_price_cents) / 100.0 AS revenue
        FROM historical_sales AS s
        JOIN products AS p ON p.product_id = s.product_id
        GROUP BY p.category
        ORDER BY p.category
    """
    return _fetch_all(database_path, query)


def best_selling_products(
    database_path: str | Path,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Return products ranked by units sold in an inclusive ISO date range."""
    query = """
        SELECT p.product_id,
               p.name,
               SUM(s.units_sold) AS units_sold
        FROM historical_sales AS s
        JOIN products AS p ON p.product_id = s.product_id
        WHERE s.sale_date BETWEEN ? AND ?
        GROUP BY p.product_id, p.name
        ORDER BY units_sold DESC, p.product_id
    """
    return _fetch_all(database_path, query, (start_date, end_date))


def _fetch_all(
    database_path: str | Path,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    """Execute a read-only parameterized query and return named rows."""
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


def _to_cents(value: Any) -> int:
    """Convert a decimal currency amount to integer cents with half-up rounding."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)
