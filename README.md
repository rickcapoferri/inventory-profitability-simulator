# Inventory profitability simulator

Advanced Python coursework. The Python modules, TOML configurations, sample CSV
files, and tests are in the project folder, with no nested source package.

## Setup and execution

Use Python 3.12 or later: the pinned NumPy version requires it. Tested locally
with Python 3.14. No Pandas or graphical interface is needed.

With your Python environment activated, run from the project folder:

```bash
python -m pip install -r requirements.txt
python main.py
```

The default is `config.toml` beside `main.py`. To choose another configuration:

```bash
python main.py promotion.toml
python main.py --help
```

Use `python3` instead if that is your system's Python command.
Paths inside TOML are resolved relative to that file, so moving the whole
project folder preserves the sample configuration.

The command validates the inputs, imports historical data into SQLite, prints
the historical summary, and generates Poisson demand. It does not yet run an
inventory simulation. The extension TOMLs define example settings; the actual
experiments still need implementing.

## Files

| File | Responsibility |
|---|---|
| `main.py` | Run the steps; optional TOML filename from `sys.argv` |
| `config.py` | Read TOML; validate settings and paths |
| `validation.py` | Load and validate product and sales CSV records |
| `database.py` | SQLite tables, imports, and historical SQL queries |
| `simulation.py` | Demand generation and the base policy/two subclasses |
| `test_project.py` | Automated tests grouped by component |

This uses the lesson concepts: loops and collections (L01-L04), functions (L05),
plain modules (L06), classes/inheritance (L07-L08), SQL (L09), and NumPy arrays
and seeded randomness (L11). Required file formats also need standard-library
tools such as `csv`, `tomllib`, `pathlib`, and `sqlite3`.
`Decimal` is used only for reliable conversion of money to cents.

## Data and import rules

Product columns:
`product_id,name,category,purchase_cost,selling_price,initial_stock`.
Sales columns: `date,product_id,units_sold`.

Validation checks columns and missing values, unique product IDs, finite positive
prices, non-negative integer quantities, ISO dates (`YYYY-MM-DD`), valid product
references, unique product/date pairs, and the same complete history of at least
30 consecutive days for every product. Zero sales require explicit rows.
Quantity fields use integer notation (`10`, not `10.0`).
Deliberately invalid examples are described in `validation_examples.txt`.

SQLite stores unit prices in integer cents using `ROUND_HALF_UP` when necessary.
A price that rounds to zero cents is rejected. SQL aggregates cents before
returning totals in currency units. Historical revenues use the catalogue's
prices throughout the historical window.

Each import replaces the active catalogue and history in one transaction.
Repeated imports do not duplicate records; changed CSVs replace the old dataset,
including dates/products absent from the new input. A failed import rolls back
to the previous data. There is no archive of past input datasets yet.

Historical sales are treated as demand under the no-stock-shortages assumption.
`generate_demand(summary, days, seed)` returns sorted product IDs and a read-only
NumPy array (rows = days, columns = products). Poisson demand uses a constant
historical daily mean per product and independent days/products. Fixed inputs,
seed, and NumPy version reproduce the array. Both policies must reuse one array.

## Tests

```bash
python -m pytest -q test_project.py
```

Tests use temporary folders and databases. No installed project package or
`PYTHONPATH` setting is needed.

## Remaining work and delivery

The daily simulation engine, comparisons, simulation-result storage, report
exports (including `validation_report.txt`), and exactly one extension are still
required. Catalogue/configuration cross-checks will be connected with the
selected extension.

Deliver the root source, tests, inputs, settings, and documentation. Exclude
`.venv`, Git metadata, caches, and `tmp` (reference PDF renders).
The final submission also needs representative outputs, design/contribution/
AI-use notes, and slides.
