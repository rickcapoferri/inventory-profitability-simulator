# Small Business Inventory and Profitability Simulator

Command-line program that imports a shop's product catalogue and sales history, stores them in
SQLite, summarises past sales with SQL, simulates future demand with NumPy and compares two
replenishment policies: how do we balance the cost of keeping stock against the sales we lose
when a product is out of stock?

Group 13. Selected extension: B - storage constraint (at most 300 units in the shop, two allocation rules).

## Requirements

- Python 3.11 or later (tested with 3.13), any operating system (Windows, macOS, Linux)
- NumPy (tested with 2.5.3): `python -m pip install -r requirements.txt`
- sqlite3, csv, tomllib, argparse come with Python. Tests use plain `assert`: no extra package.

On macOS and Linux the command may be `python3` instead of `python`; on Windows also `py`.

## Files

The program is in the main folder; three folders hold the data, the outputs and the documents.

| Where | What |
|---|---|
| `main.py` | command line: run this file |
| `config.py` `validation.py` `database.py` `demand.py` `policies.py` `storage.py` `simulation.py` `reporting.py` `workflow.py` `common.py` | the program, one module per job (see `docs/design_note.md`) |
| `tests.py` | all the automated tests |
| `storage.toml` | configuration used for the submission (every key is commented) |
| `data/` | input: `products.csv`, `historical_sales.csv`; teacher's expected values `expected_historical_by_product.csv`; teacher's invalid examples (`invalid_config.toml`, `products_zero_cost.csv`, `sales_*.csv`, `validation_README.txt`) |
| `output/` | created by the program: `inventory.sqlite` and the output files (included in the submission, made with seed 2026) |
| `docs/` | `design_note.md`, `contribution_statement.md` |

## Commands

Run them from the project folder (the paths in the TOML file are relative to the TOML file, so
they also work from another folder).

```
python main.py init-db --config storage.toml --reset     # new empty database
python main.py import --config storage.toml              # check + import the CSV files
python main.py summary --config storage.toml --start 2026-03-01 --end 2026-03-31 --top 3
python main.py simulate --config storage.toml            # check + import + compare + seed check + all outputs
python main.py runs --config storage.toml                # simulation runs saved in the database
python main.py validate --config storage.toml            # only check the CSV files
python tests.py                                          # run all the tests
```

`simulate` always checks and imports the CSV files first, so invalid input is never simulated.

To reproduce the submitted outputs exactly (the database then has run ids 1 to 6):

```
python main.py init-db --config storage.toml --reset
python main.py simulate --config storage.toml
```

Exit codes: 0 = OK, 1 = invalid input files or import conflict, 2 = invalid configuration or data
not imported yet.

Invalid examples: `python main.py simulate --config data/invalid_config.toml` stops with exit code 2.
For an invalid CSV, copy `storage.toml`, put e.g. `historical_sales = "data/sales_missing_day.csv"`,
start from a new database (`init-db --reset`) and run `simulate`: it stops with exit code 1 and
lists the problems in `validation_report.txt`.

## Input files

UTF-8 CSV (files saved by Excel are accepted too), comma separated, one header row.

- `products.csv`: `product_id,name,category,purchase_cost,selling_price,initial_stock`
  (unique `product_id`; cost and price > 0 with at most 2 decimals; `initial_stock` integer >= 0)
- `historical_sales.csv`: `date,product_id,units_sold`
  (`date` as YYYY-MM-DD; known `product_id`; `units_sold` integer >= 0; each product and date
  at most once; every product needs a row for every day of the same window of at least 30
  consecutive days, zero sales written explicitly)

## Output files

Written in `output_directory` (the `output/` folder). They are replaced every time; the database
instead keeps every run (new `run_id`, with configuration, seed and NumPy version).

| File | Columns / content |
|---|---|
| `validation_report.txt` | VALID or INVALID and every problem with file and line number |
| `historical_summary.csv` | `level,key,name,category,days,units_sold,mean_daily_units,revenue,cost_of_goods_sold,gross_profit` (`level` = product or category) |
| `daily_simulation.csv` | `run_id,scenario,policy,day,product_id,opening_stock,received,demand,sold,lost,closing_stock,ordered,revenue,cogs,holding_cost,ordering_cost,operating_result` |
| `policy_comparison.csv` | `run_id,scenario,policy,policy_parameters,capacity_units,allocation_rule,seed,level,demand,sold,lost,fill_rate,revenue,cogs,gross_profit,holding_cost,ordering_cost,operating_result,orders_placed,final_stock,final_inventory_value,outstanding_units,outstanding_value,operating_result_vs_baseline` (`level` = SHOP or a product_id) |
| `report.txt` | assumptions, SQL summaries, policy comparison, storage comparison, recommendation, seed check, limitations, saved runs |
| `seed_check.csv` | `seed,scenario,policy,demand,sold,lost,fill_rate,revenue,cogs,gross_profit,holding_cost,ordering_cost,operating_result,orders_placed,final_stock,final_inventory_value,outstanding_units,outstanding_value,best_of_seed` (shop totals; `best_of_seed` = `yes` for the best option of that seed) |

## Conventions

- Money is stored as integer cents and written in EUR with 2 decimals; mean demand with 8
  decimals; fulfilment rate with 4 decimals, `NA` (CSV) or `n/a` (report) when demand is 0.
- Every day: receive yesterday's orders, sell min(demand, stock), the rest of demand is lost,
  holding cost on the stock left, the policy orders for tomorrow morning.
- Orders of the last day are paid but never arrive: reported as outstanding, not as stock.
- Import: identical records are skipped; different values, or data in the database that is not
  in the files, cancel the whole import (rollback). Use `init-db --reset` for a new dataset.
- Unknown keys in the TOML file are errors. `SHOP` cannot be a product_id (it labels the shop
  totals). Initial stock above `capacity_units` is refused before importing.
- Random numbers: `numpy.random.default_rng(seed)` and `poisson`; one read-only
  (days x products) array, shared by every policy and scenario.
- Seed check: `seeds_to_check` in `[simulation]` (20 in `storage.toml`). The whole comparison is
  repeated with the seeds `seed`, `seed + 1`, ... (2026 to 2045); in each seed every option gets
  the same demand and all the other parameters stay the same. Only the shop totals are kept
  (`seed_check.csv` and the report): the daily rows are saved in the database only for `seed`,
  so the database stays small. Means over the seeds are rounded to the nearest cent.
