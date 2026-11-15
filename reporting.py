"""Export core simulation results using standard-library CSV and text files."""

import csv
import json
import platform
import tomllib
from pathlib import Path

import numpy as np

from database import DAILY_COLUMNS


def validation_output_directory(config_path: str | Path) -> Path:
    """Locate the report folder even when configuration validation fails.

    If the TOML cannot be read or has no usable output path, use a
    validation_results folder beside that configuration file.
    """
    path = Path(config_path).resolve()
    try:
        with path.open("rb") as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError):
        return path.parent / "validation_results"
    files = config.get("files")
    if isinstance(files, dict):
        output = files.get("output_directory")
        if isinstance(output, str) and output.strip():
            return (path.parent / output).resolve()
    return path.parent / "validation_results"


def write_validation_report(output_directory: str | Path, passed: bool, detail: str) -> None:
    """Write the latest validation outcome, including actionable input errors."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    status = "PASSED" if passed else "FAILED"
    (output / "validation_report.txt").write_text(
        f"Input validation: {status}\n{detail}\n", encoding="utf-8"
    )


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def export_results(
    output_directory: str | Path,
    config: dict,
    historical_summary: list[dict],
    category_summary: list[dict],
    simulations: list[dict],
    run_ids: list[int],
    saved_summaries: list[dict],
) -> None:
    """Replace the latest core exports; SQLite retains all saved executions."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    historical_rows = []
    for scope, summaries in (("product", historical_summary), ("category", category_summary)):
        for summary in summaries:
            row = {"scope": scope}
            row.update(summary)
            for key in ("revenue", "cost_of_goods_sold", "gross_profit"):
                if key in row:
                    row[key] = f"{row[key]:.2f}"
            if "mean_daily_units" in row:
                row["mean_daily_units"] = f"{row['mean_daily_units']:.8f}"
            historical_rows.append(row)
    _write_csv(output / "historical_summary.csv", [
        "scope", "product_id", "category", "days", "units_sold", "mean_daily_units",
        "revenue", "cost_of_goods_sold", "gross_profit",
    ], historical_rows)

    daily_rows = []
    comparison_rows = []
    shop_rows = []
    for result, run_id in zip(simulations, run_ids):
        for daily in result["daily_results"]:
            row = {"run_id": run_id, "scenario": "core"}
            row.update(daily)
            daily_rows.append(row)
        for summary in saved_summaries:
            if summary["run_id"] == run_id:
                shop_rows.append(summary)
                row = summary.copy()
                row["scope"] = "shop"
                comparison_rows.append(row)
        for summary in result["product_summary"]:
            row = {"run_id": run_id, "scenario": "core", "policy": result["policy"],
                   "days": config["simulation"]["days"], "seed": config["simulation"]["seed"],
                   "currency": config["simulation"]["currency"], "scope": "product"}
            row.update(summary)
            comparison_rows.append(row)
    _write_csv(output / "daily_simulation.csv",
               ["run_id", "scenario", "policy"] + list(DAILY_COLUMNS), daily_rows)
    _write_csv(output / "policy_comparison.csv", [
        "run_id", "scenario", "policy", "days", "seed", "currency", "scope", "product_id",
        "demand", "units_sold", "units_lost", "ordered_units", "received_units",
        "fulfilment_rate", "revenue_cents", "cost_of_goods_sold_cents", "gross_profit_cents",
        "holding_cost_cents", "ordering_cost_cents", "operating_result_cents",
        "final_stock", "outstanding_orders", "final_inventory_value_cents",
    ], comparison_rows)
    (output / "report.txt").write_text(_text_report(config, shop_rows), encoding="utf-8")


def _text_report(config: dict, shop_rows: list[dict]) -> str:
    lines = [
        "Inventory and profitability: core policy comparison",
        f"Currency: {config['simulation']['currency']}",
        f"Python: {platform.python_version()}; NumPy: {np.__version__}",
        f"RNG: default_rng(PCG64).poisson; seed: {config['simulation']['seed']}",
        "Both policies use the same demand array, starting stock, costs and horizon.",
        "",
    ]
    best = shop_rows[0]
    for row in shop_rows:
        if row["operating_result_cents"] > best["operating_result_cents"]:
            best = row
        rate = row["fulfilment_rate"]
        fulfilment = "N/A (zero demand)" if rate is None else f"{rate:.2%}"
        lines.extend([
            f"Run {row['run_id']}: {row['policy']} ({row['days']} days)",
            f"Demand: {row['demand']}; sold: {row['units_sold']}; lost: {row['units_lost']}; fulfilment: {fulfilment}",
        ])
        for key in ("revenue", "cost_of_goods_sold", "gross_profit", "holding_cost",
                    "ordering_cost", "operating_result", "final_inventory_value"):
            lines.append(f"{key}: {row[key + '_cents'] / 100:.2f}")
        lines.append(f"Final on-hand stock: {row['final_stock']}; outstanding orders: {row['outstanding_orders']}")
        lines.append("")
    winners = [row["policy"] for row in shop_rows
               if row["operating_result_cents"] == best["operating_result_cents"]]
    lines.extend([
        f"Highest operating result in this simulation: {', '.join(winners)} "
        f"({best['operating_result_cents'] / 100:.2f}).",
        "Use this result as a provisional policy choice under these inputs; a single seed does not establish a general winner.",
        "",
        "Assumptions and conventions:",
        "Historical sales equal demand: the shop had no historical shortages.",
        "Each product uses its observed historical daily mean as its Poisson parameter.",
        "Arrivals precede sales; unmet demand is permanently lost; holding cost uses closing stock.",
        "Orders arrive next morning. Final-day orders are charged and remain outstanding.",
        "Final inventory is valued separately at purchase cost; unsold units are not cost of goods sold.",
        "Money uses integer cents; unit prices and cost rates are rounded half up before multiplication.",
        "CSV financial fields ending in _cents are integer cents; fulfilment is a fraction and blank for zero demand.",
        "",
        "Limitations:",
        "Constant independent Poisson means omit seasonality, trends and correlations between products.",
        "One random demand realization gives no estimate of uncertainty in policy performance.",
        "Lead time is always one day and supplier availability is unlimited.",
        "The operating result excludes overhead, taxes and a full cash-flow model.",
        "",
        "Scenario: core. Extension experiments are not implemented.",
        "SQLite appends new runs. These exports replace the previous successful files in this folder.",
        "The validation report describes the latest attempt; after an invalid attempt other files may describe an older successful run.",
        "",
        "Requested configuration (resolved paths; extension settings, if any, are inactive):",
        json.dumps(config, default=str, indent=2, sort_keys=True),
    ])
    return "\n".join(lines) + "\n"
