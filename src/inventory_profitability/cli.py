"""Command-line workflow for importing data and showing historical summaries."""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from inventory_profitability.config import ConfigurationError, load_config
from inventory_profitability.csv_validation import (
    CSVValidationError,
    products_csv_validation,
)
from inventory_profitability.database import (
    historical_sales_by_product,
    import_historical_data,
)
from inventory_profitability.demand import generate_demand


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate inventory data, import it into SQLite, and show historical results."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/core.toml"),
        help="TOML configuration file (default: config/core.toml)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        products, sales = products_csv_validation(
            config["files"]["products"],
            config["files"]["historical_sales"],
        )
        database = config["files"]["database"]
        import_historical_data(database, products, sales)
        summary = historical_sales_by_product(database)
        product_ids, demand = generate_demand(
            summary, config["simulation"]["days"], config["simulation"]["seed"]
        )
    except (
        OSError,
        sqlite3.Error,
        ConfigurationError,
        CSVValidationError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Imported {len(products)} products and {len(sales)} sales rows.")
    print(f"Historical summary ({config['simulation']['currency']}):")
    print("Product | Days | Units | Mean/day | Revenue | COGS | Gross profit")
    for row in summary:
        print(
            f"{row['product_id']} | {row['days']} | {row['units_sold']} | "
            f"{row['mean_daily_units']:.2f} | {row['revenue']:.2f} | "
            f"{row['cost_of_goods_sold']:.2f} | {row['gross_profit']:.2f}"
        )
    print(f"Database: {database}")
    print(
        f"Generated demand: {demand.shape[0]} days x {len(product_ids)} products "
        f"(seed {config['simulation']['seed']})."
    )
    return 0
