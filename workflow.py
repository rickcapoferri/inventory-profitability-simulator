"""The main steps of the program: check and import the data, compare the policies."""

# These functions do not print anything and do not read the command line,
# so the tests can call them in the same way as main.py does.

from contextlib import closing

import numpy as np

import database as db
from demand import estimate_means, generate_demand, history_matrix
from common import ConfigError, ImportConflictError, InputValidationError
from policies import policies_from_config
from simulation import compute_metrics, daily_rows, run_simulation
from storage import check_initial_stock
from validation import validate_inputs, write_validation_report

RNG_DESCRIPTION = "numpy.random.default_rng(seed) (PCG64), Generator.poisson"


def check_inputs(config: dict) -> dict:
    """Check the CSV files and write validation_report.txt."""
    # With the storage extension the initial stock must also fit in the
    # warehouse. Raises InputValidationError with the list of all problems.
    report_path = config["output_directory"] / "validation_report.txt"
    result = validate_inputs(config["products"], config["historical_sales"])
    capacity_problems = []
    if config["capacity"] is not None:
        try:
            check_initial_stock(list(result["products"].values()), config["capacity"])
        except ConfigError as error:
            capacity_problems = [str(error)]
    write_validation_report(result, report_path, config["products"],
                            config["historical_sales"], capacity_problems)
    all_problems = result["issues"] + capacity_problems
    if all_problems:
        raise InputValidationError(all_problems)
    return result


def validate_and_import(config: dict) -> dict:
    """Check the input files, then store them in the database."""
    # Raises InputValidationError (wrong files) or ImportConflictError (the
    # files contradict the database). In both cases nothing is imported.
    # Returns the counts of inserted and unchanged records.
    result = check_inputs(config)
    with closing(db.open_database(config["database"])) as conn:
        try:
            counts = db.import_data(conn, result["products"], result["sales"])
        except ImportConflictError as error:
            report_path = config["output_directory"] / "validation_report.txt"
            write_validation_report(result, report_path, config["products"],
                                    config["historical_sales"], error.conflicts)
            raise
    return counts


def build_scenarios(config: dict) -> list:
    """List of (scenario name, capacity, allocation rule)."""
    # The first scenario has no capacity limit; with the storage extension we
    # add one scenario for each allocation rule.
    scenarios = [("baseline", None, None)]
    for rule in config["allocation_rules"]:
        scenarios.append(("storage_" + rule, config["capacity"], rule))
    return scenarios


def effective_config(config: dict, means) -> dict:
    """The settings saved with every run, so that it can be reproduced."""
    return {
        "config_file": str(config["config_file"]),
        "toml": config["toml"],
        "products_file": str(config["products"]),
        "sales_file": str(config["historical_sales"]),
        "rng": RNG_DESCRIPTION,
        "numpy_version": np.__version__,
        "demand_means": [round(float(m), 8) for m in means],
    }


def run_comparison(config: dict, conn) -> dict:
    """Generate ONE demand array and simulate every policy in every scenario on it."""
    # Using the same demand for every run means that the differences between
    # runs come from the policies and rules, not from random luck.
    products = db.load_products(conn)
    product_ids = [p.product_id for p in products]
    history = history_matrix(db.load_history_rows(conn), product_ids)
    means = estimate_means(history)
    demand = generate_demand(means, config["days"], config["seed"])
    settings = effective_config(config, means)

    runs = []
    for scenario, capacity, rule in build_scenarios(config):
        for policy in policies_from_config(config):
            result = run_simulation(products, demand, policy, config["holding_cost"],
                                    config["order_cost"], scenario, capacity, rule)
            run_id = db.save_run(conn, scenario, str(policy), config["seed"],
                                 config["days"], np.__version__, settings, daily_rows(result))
            by_product, shop = compute_metrics(result, products)
            runs.append({"run_id": run_id, "scenario": scenario, "rule": rule,
                         "capacity": capacity, "policy": policy, "result": result,
                         "by_product": by_product, "shop": shop})

    return {"products": products, "history_days": len(history), "means": means,
            "demand": demand, "runs": runs}
