# inventory-profitability-simulator
Python inventory and profitability simulator developed for an Advanced Python Programming course. Uses NumPy and SQLite to analyse historical sales, simulate demand, and compare replenishment policies and their impact on profitability.

## Run the data import and historical summary

From the repository root, run:

```bash
PYTHONPATH=src python -m inventory_profitability
```

To select a different TOML file:

```bash
PYTHONPATH=src python -m inventory_profitability --config config/core.toml
```

The command loads and validates the TOML configuration, validates both CSV
files, imports their rows into the configured SQLite database, and prints the
historical sales summary by product. Re-running the command updates matching
product and date/product rows instead of duplicating them.

## CSV validation

Validation checks required columns and values, unique product identifiers,
finite positive prices, non-negative integer quantities, ISO dates, known
products, unique product-date pairs, and a complete shared history of at least
30 consecutive days. Missing sales records must be supplied explicitly,
including zero-sales rows. Invalid input raises `CSVValidationError` with an
error report. Validation does not write to the database.

`products_csv_validation(products_file, sales_file)` returns validated product
and sales rows as lists of dictionaries, with numeric columns converted to
numbers. Omitting the arguments uses the sample files in `data/`.
