# Inventory profitability simulator

## Setup and execution

Use Python 3.12 or later: the pinned NumPy version requires it. Tested locally
with Python 3.14. No Pandas or graphical interface is needed.

With your Python environment activated, run from the project folder:

```bash
python -m pip install -r requirements.txt
python main.py
```

The default is `config/core.toml`. To choose another configuration:

```bash
python main.py config/promotion.toml
python main.py --help
```

Use `python3` instead if that is your system's Python command.
Paths inside TOML are resolved relative to that file, so moving the whole
project folder preserves the sample configuration.

The command validates the inputs, imports historical data into SQLite, prints
the historical summary, generates Poisson demand, and simulates both core
policies on that same demand. It prints shop totals, saves both runs in SQLite,
and exports CSV and text reports. The extension
TOMLs define example settings; the actual experiments still need implementing.
Selecting one currently runs only the core and prints a notice.

## Files

| File | Responsibility |
|---|---|
| `main.py` | Run the steps; optional TOML filename from `sys.argv` |
| `config.py` | Read TOML; validate settings and paths |
| `validation.py` | Load and validate product and sales CSV records |
| `database.py` | SQLite tables, imports, saved runs and SQL summaries |
| `simulation.py` | Demand, policy classes, daily engine and economic summaries |
| `reporting.py` | CSV exports, validation outcome and readable comparison report |
| `test_project.py` | Automated tests grouped by component |

This uses the lesson concepts: loops and collections (L01-L04), functions (L05),
plain modules (L06), classes/inheritance (L07-L08), SQL (L09), and NumPy arrays
and seeded randomness (L11). Required file formats also need standard-library
tools such as `csv`, `tomllib`, `pathlib`, and `sqlite3`. `json` stores a copy
of the configuration as text in SQLite and in the report.
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
Deliberately invalid examples are described in `validation/README.txt`.

SQLite stores unit prices in integer cents using `ROUND_HALF_UP` when necessary.
A price that rounds to zero cents is rejected. SQL aggregates cents before
returning totals in currency units. Historical revenues use the catalogue's
prices throughout the historical window.

Each import replaces the active catalogue and history in one transaction.
Repeated imports do not duplicate records; changed CSVs replace the old dataset,
including dates/products absent from the new input. A failed import rolls back
to the previous data. Saved simulations retain their own catalogue and estimated
demand means; the raw historical input datasets are not archived.

Historical sales are treated as demand under the no-stock-shortages assumption.
`generate_demand(summary, days, seed)` returns sorted product IDs and a read-only
NumPy array (rows = days, columns = products). Poisson demand uses a constant
historical daily mean per product and independent days/products. Fixed inputs,
seed, and NumPy version reproduce the array. Both policies must reuse one array.

## Daily inventory simulation

`simulate_inventory(products, product_ids, demand, policy,
holding_per_unit_per_day, fixed_per_product_order)` accepts validated catalogue
records and a NumPy demand array. Its columns must match `product_ids`.
It returns a dictionary with `policy`, `daily_results` (one row per day/product),
`product_summary` and `shop_summary`. The command saves the daily results and
prints the main shop totals; reports include both product and shop summaries.

Each day receives yesterday's orders, sells the minimum of demand and available
stock, records the rest as permanently lost sales, charges holding cost on closing
stock, and applies the policy to that closing stock. Orders arrive the next
morning. Day 1 starts with the catalogue's initial stock and no outstanding orders.
Final-day orders are recorded and charged; they remain outstanding and are not
included in final on-hand stock or its value. A positive order incurs one fixed
cost per product; a zero order incurs none.

Daily rows contain `opening_stock` (before receipts), `received_units`,
`available_stock`, `demand`, `units_sold`, `units_lost`, `closing_stock`,
`ordered_units`, and financial fields ending in `_cents`. Monetary values use
integer cents, with unit prices and cost rates rounded half up to cents before
multiplication, consistently with historical prices in SQLite. Summary financial
fields are `revenue_cents`, `cost_of_goods_sold_cents`, `gross_profit_cents`,
`holding_cost_cents`, `ordering_cost_cents`, `operating_result_cents` and
`final_inventory_value_cents`. Unsold stock is valued at purchase cost separately;
only sold units enter cost of goods sold. Summaries also include final stock,
outstanding order quantities, and fulfilment (sold / demand), using `None` for
zero demand (`N/A` in terminal output).

The implementation uses course constructs: dictionaries/lists and loops
(L01-L04), focused functions and modules (L05-L06), inherited policy behaviour
(L07-L08), and array copies, element-wise arithmetic and `np.minimum` (L11).
`Decimal` supplies the project's documented monetary rounding.

## Saved runs and reports

Every successful execution appends two runs to `simulation_runs`, one per policy,
with distinct `run_id` values. Each stores the resolved configuration as JSON,
seed, horizon, currency, NumPy version and RNG method. `simulation_products`
stores a catalogue snapshot and the historical daily mean used for each product.
`daily_simulation_results` references that snapshot using `(run_id, product_id)`;
its primary key is `(run_id, day, product_id)`. Foreign keys and checks reject
invalid quantities and inconsistent stock/financial identities. Both runs and
their daily rows are saved in one transaction: a failure rolls back the pair.
Subsequent catalogue imports do not change earlier runs.

`saved_simulation_summary(database_path)` uses SQL joins and aggregates to return
all saved shop results, including final stock value and outstanding orders.
The report uses those SQL totals for the current comparison.

With the default configuration, `python main.py` creates these files in
`results/core/`:

| File | Contents |
|---|---|
| `historical_summary.csv` | Product and category summaries, distinguished by `scope` |
| `daily_simulation.csv` | One row per run/day/product, identified by run ID, core scenario and policy |
| `policy_comparison.csv` | Product and shop totals, distinguished by `scope` |
| `validation_report.txt` | Latest attempt's validation outcome or input error with available row details |
| `report.txt` | Shop comparison, provisional recommendation, assumptions, limitations and requested configuration |

CSV files use UTF-8, comma separators and headers. Historical monetary columns
use currency units with two decimals; daily/comparison fields ending in `_cents`
contain integer cents. Historical means have eight decimal places. Fulfilment
rates are fractions, with a blank for zero demand. Unused fields (for example
`product_id` on a shop row) are blank. Stock and orders are units; days start at 1.
Scenario is always `core` until an extension is implemented.

SQLite retains previous runs; generated files are overwritten with the latest
successful execution. Invalid inputs prevent import/simulation and update only
the validation report; other existing exports still describe the earlier success.
If configuration validation fails, the program reads the output path directly
from TOML to locate the error report. If that path is unavailable or TOML is
unreadable, it uses `validation_results/` beside the selected configuration file.
Filesystem errors writing a report are shown on stderr. Database saving and file
exports are separate steps: a failed export may leave already committed runs.

The report's recommendation ranks operating results from this single demand
realization; it does not establish which policy performs best across many runs.

## Tests

```bash
python -m pytest -q test_project.py
```

Tests use temporary folders and databases. No installed project package or
`PYTHONPATH` setting is needed.

## Remaining work and delivery

Exactly one extension is still required. Catalogue/configuration cross-checks
will be connected with the selected extension. The final group design note,
contribution/AI-use statements and presentation also remain to prepare.

Deliver the root source and tests, documentation, and the `data/`, `config/`,
`checks/`, and `validation/` folders with their structure intact. Exclude
`.venv`, Git metadata, caches, and `tmp` (reference PDF renders).
The final submission also needs representative outputs, design/contribution/
AI-use notes, and slides.
