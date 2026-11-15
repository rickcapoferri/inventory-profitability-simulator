"""Command-line workflow for validation, analysis, simulation and exports."""

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
    historical_revenue_by_category,
    import_historical_data,
    save_simulation_runs,
    saved_simulation_summary,
)
from reporting import export_results, validation_output_directory, write_validation_report
from simulation import (
    FixedQuantityPolicy,
    OrderUpToPolicy,
    generate_demand,
    simulate_inventory,
)


def main(argv: list[str] | None = None) -> int:
    """Run the workflow using an optional TOML filename."""
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--help"] or argv == ["-h"]:
        print("Usage: python main.py [config/core.toml]")
        return 0
    if len(argv) > 1:
        print("Usage: python main.py [config/core.toml]", file=sys.stderr)
        return 1
    config_path = Path(__file__).resolve().parent / "config" / "core.toml"
    if argv:
        config_path = Path(argv[0])
    config = None
    inputs_valid = False
    try:
        config = load_config(config_path)
        products, sales = products_csv_validation(
            config["files"]["products"],
            config["files"]["historical_sales"],
        )
        inputs_valid = True
        write_validation_report(
            config["files"]["output_directory"], True,
            f"Configuration: {config_path.resolve()}\n"
            f"Validated {len(products)} products and {len(sales)} historical sales rows.",
        )
        database = config["files"]["database"]
        import_historical_data(database, products, sales)
        summary = historical_sales_by_product(database)
        product_ids, demand = generate_demand(
            summary, config["simulation"]["days"], config["simulation"]["seed"]
        )
        fixed = config["policies"]["fixed_quantity"]
        target = config["policies"]["order_up_to"]
        policies = [
            FixedQuantityPolicy(fixed["threshold"], fixed["quantity"]),
            OrderUpToPolicy(target["threshold"], target["target"]),
        ]
        simulations = []
        for policy in policies:
            simulations.append(simulate_inventory(
                products, product_ids, demand, policy,
                config["costs"]["holding_per_unit_per_day"],
                config["costs"]["fixed_per_product_order"],
            ))
        run_ids = save_simulation_runs(database, config, products, summary, simulations)
        export_results(
            config["files"]["output_directory"], config, summary,
            historical_revenue_by_category(database), simulations, run_ids,
            saved_simulation_summary(database),
        )
    except (
        OSError,
        sqlite3.Error,
        ConfigurationError,
        CSVValidationError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        if not inputs_valid:
            output = validation_output_directory(config_path)
            try:
                write_validation_report(
                    output, False, f"Configuration: {config_path.resolve()}\n{error}"
                )
                print(f"Validation report: {output / 'validation_report.txt'}", file=sys.stderr)
            except OSError as report_error:
                print(f"Could not write validation report: {report_error}", file=sys.stderr)
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
    print("Core simulation comparison:")
    print("Policy | Sold | Lost | Fulfilment | Operating result | Final stock | Outstanding orders")
    for result in simulations:
        totals = result["shop_summary"]
        rate = totals["fulfilment_rate"]
        fulfilment = "N/A" if rate is None else f"{rate:.2%}"
        print(
            f"{result['policy']} | {totals['units_sold']} | {totals['units_lost']} | "
            f"{fulfilment} | {totals['operating_result_cents'] / 100:.2f} | "
            f"{totals['final_stock']} | {totals['outstanding_orders']}"
        )
    if config["extension"]["selected"]:
        print("The selected extension is not implemented; these are core results only.")
    print(f"Saved simulation runs: {', '.join(str(run_id) for run_id in run_ids)}")
    print(f"Reports: {config['files']['output_directory']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
