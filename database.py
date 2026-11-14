"""SQLite storage and SQL summaries for products and historical sales."""

import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


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
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
    finally:
        connection.close()


def import_historical_data(
    database_path: str | Path,
    products: list[dict],
    sales: list[dict],
) -> None:
    """Save validated data atomically, storing money as integer cents.

    Each import replaces the active product catalogue and sales history.
    Repeated imports do not duplicate rows, and old dates or products cannot
    affect the analysis of the new CSV files.
    Values with more than two decimal places are rounded to cents using
    ROUND_HALF_UP.
    Any failure rolls back the whole import.
    """
    initialize_database(database_path)
    product_values = []
    for row in products:
        product_values.append((
            row["product_id"], row["name"], row["category"],
            _to_cents(row["purchase_cost"]), _to_cents(row["selling_price"]),
            row["initial_stock"],
        ))
    sales_values = []
    for row in sales:
        sales_values.append((row["date"], row["product_id"], row["units_sold"]))

    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        # The transaction restores the previous dataset if any insert fails.
        with connection:
            connection.execute("DELETE FROM historical_sales")
            connection.execute("DELETE FROM products")
            connection.executemany(
                """
                INSERT INTO products (
                    product_id, name, category, purchase_cost_cents,
                    selling_price_cents, initial_stock
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                product_values,
            )
            connection.executemany(
                """
                INSERT INTO historical_sales (sale_date, product_id, units_sold)
                VALUES (?, ?, ?)
                """,
                sales_values,
            )
    finally:
        connection.close()


def historical_sales_by_product(database_path: str | Path) -> list[dict]:
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


def historical_revenue_by_category(database_path: str | Path) -> list[dict]:
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
) -> list[dict]:
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
    parameters: tuple = (),
) -> list[dict]:
    """Execute a read-only parameterized query and return named rows."""
    connection = sqlite3.connect(database_path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        rows = connection.execute(query, parameters).fetchall()
        results = []
        for row in rows:
            results.append(dict(row))
        return results
    finally:
        connection.close()


def _to_cents(value) -> int:
    """Convert a decimal currency amount to integer cents with half-up rounding."""
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValueError(f"Price {value} must remain positive after rounding to cents")
    return int(amount * 100)
