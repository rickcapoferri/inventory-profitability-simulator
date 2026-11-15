"""SQLite storage and SQL summaries for products and historical sales."""

import sqlite3
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np


DAILY_COLUMNS = (
    "day", "product_id", "opening_stock", "received_units", "available_stock",
    "demand", "units_sold", "units_lost", "closing_stock", "ordered_units",
    "revenue_cents", "cost_of_goods_sold_cents", "gross_profit_cents",
    "holding_cost_cents", "ordering_cost_cents", "operating_result_cents",
)


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

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id INTEGER PRIMARY KEY,
    scenario TEXT NOT NULL,
    policy TEXT NOT NULL,
    days INTEGER NOT NULL CHECK (days > 0),
    seed INTEGER NOT NULL CHECK (seed >= 0),
    currency TEXT NOT NULL,
    config_json TEXT NOT NULL,
    numpy_version TEXT NOT NULL,
    rng_method TEXT NOT NULL
);

-- Snapshots keep saved runs valid when the active catalogue is replaced.
CREATE TABLE IF NOT EXISTS simulation_products (
    run_id INTEGER NOT NULL REFERENCES simulation_runs(run_id),
    product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    initial_stock INTEGER NOT NULL CHECK (initial_stock >= 0),
    purchase_cost_cents INTEGER NOT NULL CHECK (purchase_cost_cents > 0),
    selling_price_cents INTEGER NOT NULL CHECK (selling_price_cents > 0),
    mean_daily_units REAL NOT NULL CHECK (mean_daily_units >= 0),
    PRIMARY KEY (run_id, product_id)
);

CREATE TABLE IF NOT EXISTS daily_simulation_results (
    run_id INTEGER NOT NULL,
    day INTEGER NOT NULL CHECK (day > 0),
    product_id TEXT NOT NULL,
    opening_stock INTEGER NOT NULL CHECK (opening_stock >= 0),
    received_units INTEGER NOT NULL CHECK (received_units >= 0),
    available_stock INTEGER NOT NULL CHECK (available_stock = opening_stock + received_units),
    demand INTEGER NOT NULL CHECK (demand >= 0),
    units_sold INTEGER NOT NULL CHECK (units_sold >= 0 AND units_sold <= available_stock),
    units_lost INTEGER NOT NULL CHECK (units_lost >= 0 AND demand = units_sold + units_lost),
    closing_stock INTEGER NOT NULL CHECK (closing_stock >= 0 AND closing_stock = available_stock - units_sold),
    ordered_units INTEGER NOT NULL CHECK (ordered_units >= 0),
    revenue_cents INTEGER NOT NULL CHECK (revenue_cents >= 0),
    cost_of_goods_sold_cents INTEGER NOT NULL CHECK (cost_of_goods_sold_cents >= 0),
    gross_profit_cents INTEGER NOT NULL,
    holding_cost_cents INTEGER NOT NULL CHECK (holding_cost_cents >= 0),
    ordering_cost_cents INTEGER NOT NULL CHECK (ordering_cost_cents >= 0),
    operating_result_cents INTEGER NOT NULL,
    PRIMARY KEY (run_id, day, product_id),
    FOREIGN KEY (run_id, product_id) REFERENCES simulation_products(run_id, product_id),
    CHECK (gross_profit_cents = revenue_cents - cost_of_goods_sold_cents),
    CHECK (operating_result_cents = gross_profit_cents - holding_cost_cents - ordering_cost_cents)
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


def save_simulation_runs(
    database_path: str | Path,
    config: dict,
    products: list[dict],
    historical_summary: list[dict],
    simulations: list[dict],
) -> list[int]:
    """Append a policy comparison atomically, including input snapshots.

    Both policies belong to the core scenario. Extension settings are retained
    as requested configuration but are not claimed as implemented experiments.
    """
    initialize_database(database_path)
    means = {}
    for row in historical_summary:
        means[row["product_id"]] = row["mean_daily_units"]
    config_json = json.dumps(config, default=str, sort_keys=True)
    run_ids = []
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            for result in simulations:
                cursor = connection.execute(
                    """INSERT INTO simulation_runs
                    (scenario, policy, days, seed, currency, config_json, numpy_version, rng_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("core", result["policy"], config["simulation"]["days"],
                     config["simulation"]["seed"], config["simulation"]["currency"],
                     config_json, np.__version__, "default_rng(PCG64).poisson"),
                )
                run_id = cursor.lastrowid
                run_ids.append(run_id)
                for product in products:
                    connection.execute(
                        """INSERT INTO simulation_products
                        (run_id, product_id, name, category, initial_stock,
                         purchase_cost_cents, selling_price_cents, mean_daily_units)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, product["product_id"], product["name"], product["category"],
                         product["initial_stock"], _to_cents(product["purchase_cost"]),
                         _to_cents(product["selling_price"]), means[product["product_id"]]),
                    )
                values = []
                for row in result["daily_results"]:
                    values.append((run_id,) + tuple(row[key] for key in DAILY_COLUMNS))
                # Column names come from our constant; all data use placeholders.
                columns = ", ".join(DAILY_COLUMNS)
                placeholders = ", ".join(["?"] * (len(DAILY_COLUMNS) + 1))
                connection.executemany(
                    f"INSERT INTO daily_simulation_results (run_id, {columns}) VALUES ({placeholders})",
                    values,
                )
    finally:
        connection.close()
    return run_ids


def saved_simulation_summary(database_path: str | Path) -> list[dict]:
    """Aggregate saved runs in SQL, including final stock and pending orders."""
    return _fetch_all(database_path, """
        SELECT r.run_id, r.scenario, r.policy, r.days, r.seed, r.currency,
               SUM(d.demand) AS demand,
               SUM(d.units_sold) AS units_sold,
               SUM(d.units_lost) AS units_lost,
               SUM(d.ordered_units) AS ordered_units,
               SUM(d.received_units) AS received_units,
               1.0 * SUM(d.units_sold) / NULLIF(SUM(d.demand), 0) AS fulfilment_rate,
               SUM(d.revenue_cents) AS revenue_cents,
               SUM(d.cost_of_goods_sold_cents) AS cost_of_goods_sold_cents,
               SUM(d.gross_profit_cents) AS gross_profit_cents,
               SUM(d.holding_cost_cents) AS holding_cost_cents,
               SUM(d.ordering_cost_cents) AS ordering_cost_cents,
               SUM(d.operating_result_cents) AS operating_result_cents,
               SUM(CASE WHEN d.day = r.days THEN d.closing_stock ELSE 0 END) AS final_stock,
               SUM(CASE WHEN d.day = r.days THEN d.ordered_units ELSE 0 END) AS outstanding_orders,
               SUM(CASE WHEN d.day = r.days
                   THEN d.closing_stock * p.purchase_cost_cents ELSE 0 END) AS final_inventory_value_cents
        FROM simulation_runs AS r
        JOIN daily_simulation_results AS d ON d.run_id = r.run_id
        JOIN simulation_products AS p ON p.run_id = d.run_id AND p.product_id = d.product_id
        GROUP BY r.run_id
        ORDER BY r.run_id
    """)


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
