"""Command-line workflow for importing data and showing historical summaries."""

import sqlite3
import sys
from pathlib import Path

from config import ConfigurationError, load_config
from validation import (
    CSVValidationError,
    products_csv_validation,
)
from database import (
    historical_sales_by_product,
    import_historical_data,
)
from simulation import generate_demand


def main(argv: list[str] | None = None) -> int:
    """Run the workflow using an optional TOML filename."""
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--help"] or argv == ["-h"]:
        print("Usage: python main.py [config.toml]")
        return 0
    if len(argv) > 1:
        print("Usage: python main.py [config.toml]", file=sys.stderr)
        return 1
    config_path = Path(__file__).resolve().parent / "config.toml"
    if argv:
        config_path = Path(argv[0])
    try:
        config = load_config(config_path)
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


if __name__ == "__main__":
    raise SystemExit(main())
