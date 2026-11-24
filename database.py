"""SQLite database: tables, import, SQL summaries and saved simulation runs."""

# Every query uses ? placeholders (parameterised queries) and never builds SQL
# by joining strings, so a value can never be read as SQL code.
# Writes happen inside "with conn:" blocks. Each block is a transaction: it is
# saved (commit) if everything works, and completely cancelled (rollback) if
# an exception happens inside it.
#
# How to open the database (closing() makes sure it is always closed):
#
#     with closing(open_database(path)) as conn:
#         ...

import json
import sqlite3
from datetime import datetime

from common import DataNotLoadedError, ImportConflictError, Product

# historical_sales: one row per product and day (dates are YYYY-MM-DD text)
# simulation_runs:  one row per run, with the configuration used (as JSON)
# daily_results:    one row per run, day and product; the two last CHECKs say
#                   that every unit demanded is sold or lost, and that stock
#                   is conserved (opening + received - sold = closing)
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
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    scenario TEXT NOT NULL,
    policy_name TEXT NOT NULL,
    seed INTEGER NOT NULL,
    days INTEGER NOT NULL CHECK (days > 0),
    numpy_version TEXT NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_results (
    run_id INTEGER NOT NULL,
    day INTEGER NOT NULL CHECK (day >= 1),
    product_id TEXT NOT NULL,
    opening_stock INTEGER NOT NULL CHECK (opening_stock >= 0),
    received INTEGER NOT NULL CHECK (received >= 0),
    demand INTEGER NOT NULL CHECK (demand >= 0),
    sold INTEGER NOT NULL CHECK (sold >= 0),
    lost INTEGER NOT NULL CHECK (lost >= 0),
    closing_stock INTEGER NOT NULL CHECK (closing_stock >= 0),
    ordered INTEGER NOT NULL CHECK (ordered >= 0),
    revenue_cents INTEGER NOT NULL,
    cogs_cents INTEGER NOT NULL,
    holding_cost_cents INTEGER NOT NULL,
    ordering_cost_cents INTEGER NOT NULL,
    CHECK (sold + lost = demand),
    CHECK (opening_stock + received - sold = closing_stock),
    PRIMARY KEY (run_id, day, product_id),
    FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
"""


def open_database(db_path) -> sqlite3.Connection:
    """Open (or create) the database file and create the tables if needed."""
    # SQLite checks foreign keys only if we ask for it on every connection.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with conn:
        conn.executescript(SCHEMA)  # "IF NOT EXISTS": safe to run every time
    return conn


# Import

def import_data(conn: sqlite3.Connection, products: dict,
                sales: list) -> dict:
    """Store validated products and sales without ever duplicating a record."""
    # Conflict rule: a record that already exists with identical values is
    # skipped; a record that exists with different values (e.g. a changed
    # price or a different units_sold for the same day) is a conflict. Records
    # in the database that are not in the files (e.g. an older, longer history)
    # are also a conflict. Any conflict rejects the whole import: the
    # transaction is rolled back and the database stays exactly as it was.
    #
    # Returns counts of inserted and unchanged records.
    counts = {"products_inserted": 0, "products_unchanged": 0,
              "sales_inserted": 0, "sales_unchanged": 0}
    conflicts = []
    with conn:  # one transaction for the whole import
        for p in products.values():
            row = conn.execute(
                "SELECT name, category, purchase_cost_cents, selling_price_cents, initial_stock "
                "FROM products WHERE product_id = ?", (p.product_id,)).fetchone()
            in_file = (p.name, p.category, p.purchase_cost_cents, p.selling_price_cents,
                       p.initial_stock)
            if row is None:
                conn.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
                             (p.product_id, *in_file))
                counts["products_inserted"] += 1
            elif row == in_file:
                counts["products_unchanged"] += 1
            else:
                conflicts.append(f"product {p.product_id}: database has {row}, "
                                 f"file has {in_file}")

        for s in sales:
            row = conn.execute(
                "SELECT units_sold FROM historical_sales WHERE sale_date = ? AND product_id = ?",
                (s.sale_date, s.product_id)).fetchone()
            if row is None:
                conn.execute("INSERT INTO historical_sales VALUES (?, ?, ?)",
                             (s.sale_date, s.product_id, s.units_sold))
                counts["sales_inserted"] += 1
            elif row[0] == s.units_sold:
                counts["sales_unchanged"] += 1
            else:
                conflicts.append(f"sale {s.product_id} on {s.sale_date}: stored "
                                 f"{row[0]} units, file has {s.units_sold}")

        # The database must contain exactly the dataset in the CSV files.
        # Otherwise old products or dates would be silently simulated too.
        n_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        n_sales = conn.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0]
        if n_products != len(products) or n_sales != len(sales):
            conflicts.append(f"database holds {n_products} products and {n_sales} sales, "
                             f"the files {len(products)} and {len(sales)}; "
                             "run 'init-db --reset' to start from these files")

        if conflicts:
            raise ImportConflictError(conflicts)  # leaves the with-block -> rollback
    return counts


# Loading data back for the simulation

def load_products(conn: sqlite3.Connection) -> list:
    """All products ordered by product_id (the column order of every array)."""
    rows = conn.execute(
        "SELECT product_id, name, category, purchase_cost_cents, selling_price_cents, "
        "initial_stock FROM products ORDER BY product_id").fetchall()
    if not rows:
        raise DataNotLoadedError("no products in the database: run the 'import' command first")
    return [Product(*row) for row in rows]


def load_history_rows(conn: sqlite3.Connection) -> list:
    """Historical sales ordered by date, then product_id."""
    return conn.execute(
        "SELECT sale_date, product_id, units_sold FROM historical_sales "
        "ORDER BY sale_date, product_id").fetchall()


# Required SQL summaries (aggregation happens in SQL, not in Python)

def sales_by_product(conn: sqlite3.Connection) -> list:
    """Units sold, revenue, COGS and gross profit by product (cents)."""
    return conn.execute("""
        SELECT p.product_id, p.name, p.category,
               COUNT(*)                                  AS days,
               SUM(h.units_sold)                         AS units_sold,
               AVG(h.units_sold)                         AS mean_daily_units,
               SUM(h.units_sold * p.selling_price_cents) AS revenue_cents,
               SUM(h.units_sold * p.purchase_cost_cents) AS cogs_cents,
               SUM(h.units_sold * (p.selling_price_cents - p.purchase_cost_cents))
                                                         AS gross_profit_cents
        FROM historical_sales AS h
        JOIN products AS p ON p.product_id = h.product_id
        GROUP BY p.product_id
        ORDER BY p.product_id
    """).fetchall()


def revenue_by_category(conn: sqlite3.Connection) -> list:
    """Units sold and revenue by category, using a JOIN with products."""
    return conn.execute("""
        SELECT p.category,
               COUNT(DISTINCT p.product_id)              AS n_products,
               SUM(h.units_sold)                         AS units_sold,
               SUM(h.units_sold * p.selling_price_cents) AS revenue_cents
        FROM historical_sales AS h
        JOIN products AS p ON p.product_id = h.product_id
        GROUP BY p.category
        ORDER BY revenue_cents DESC, p.category
    """).fetchall()


def best_sellers(conn: sqlite3.Connection, start_date: str, end_date: str,
                 limit: int = 3) -> list:
    """Products with most units sold between two dates (inclusive)."""
    # ISO dates sort correctly as text, so BETWEEN works on the TEXT column.
    # Ties are broken by product_id so the result is deterministic.
    return conn.execute("""
        SELECT p.product_id, p.name,
               SUM(h.units_sold)                         AS units_sold,
               SUM(h.units_sold * p.selling_price_cents) AS revenue_cents
        FROM historical_sales AS h
        JOIN products AS p ON p.product_id = h.product_id
        WHERE h.sale_date BETWEEN ? AND ?
        GROUP BY p.product_id
        ORDER BY units_sold DESC, p.product_id
        LIMIT ?
    """, (start_date, end_date, limit)).fetchall()


def history_window(conn: sqlite3.Connection) -> tuple:
    """First and last date stored in historical_sales."""
    return conn.execute(
        "SELECT MIN(sale_date), MAX(sale_date) FROM historical_sales").fetchone()


def runs_summary(conn: sqlite3.Connection, limit: int = 50) -> list:
    """One line per saved simulation run with its totals (most recent first)."""
    return conn.execute("""
        SELECT r.run_id, r.created_at, r.scenario, r.policy_name, r.seed, r.days,
               SUM(d.demand)               AS demand,
               SUM(d.sold)                 AS sold,
               SUM(d.lost)                 AS lost,
               SUM(d.revenue_cents)        AS revenue_cents,
               SUM(d.revenue_cents - d.cogs_cents - d.holding_cost_cents
                   - d.ordering_cost_cents) AS operating_result_cents
        FROM simulation_runs AS r
        JOIN daily_results AS d ON d.run_id = r.run_id
        GROUP BY r.run_id
        ORDER BY r.run_id DESC
        LIMIT ?
    """, (limit,)).fetchall()


# Saving simulation runs

def save_run(conn: sqlite3.Connection, scenario: str, policy_name: str, seed: int,
             days: int, numpy_version: str, effective_config: dict,
             daily_rows: list) -> int:
    """Insert one run and its daily rows in a single transaction."""
    # daily_rows contains tuples in the column order of daily_results
    # without run_id. Returns the new run_id. Repeated commands append new
    # runs; earlier runs are kept so they can be compared.
    created_at = datetime.now().isoformat(timespec="seconds")
    with conn:
        cursor = conn.execute(
            "INSERT INTO simulation_runs (created_at, scenario, policy_name, seed, days, "
            "numpy_version, config_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (created_at, scenario, policy_name, seed, days, numpy_version,
             json.dumps(effective_config, sort_keys=True)))
        run_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO daily_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(run_id, *row) for row in daily_rows])
    return run_id
