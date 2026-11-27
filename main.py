"""Command line of the simulator: python main.py COMMAND --config storage.toml"""

# Commands:
#   init-db   create the database (with --reset the old database is deleted first)
#   validate  check the CSV files and write validation_report.txt
#   import    check the CSV files and store them in the database
#   summary   print the SQL summaries and write historical_summary.csv
#             (--start, --end and --top choose the best sellers to show)
#   simulate  check + import, compare the policies, repeat the comparison with
#             other seeds (seed check) and write all outputs
#   runs      print the simulation runs saved in the database
#
# This file only reads the command line and prints messages; all the
# calculations are in the other modules.
# Exit codes: 0 = OK, 1 = wrong input files, 2 = wrong configuration or missing data.

import sys

# Python would save compiled copies of our modules in a __pycache__ folder:
# we do not need it, so we keep the project folder clean.
sys.dont_write_bytecode = True

import argparse
from contextlib import closing

import database as db
from config import load_config
from common import (ConfigError, DataNotLoadedError, ImportConflictError,
                    InputValidationError, cents_to_euros)
from reporting import (make_table, write_daily_simulation, write_historical_summary,
                        write_policy_comparison, write_report, write_seed_check)
from validation import parse_iso_date
from workflow import check_inputs, run_comparison, validate_and_import


def read_arguments(argv) -> argparse.Namespace:
    """Read the command and the options typed by the user."""
    parser = argparse.ArgumentParser(prog="python main.py",
                                     description="Small business inventory simulator")
    parser.add_argument("command", choices=list(COMMANDS))
    parser.add_argument("--config", required=True, help="path of the TOML configuration file")
    parser.add_argument("--reset", action="store_true", help="init-db: delete the old database")
    parser.add_argument("--start", help="summary: first date for best sellers (YYYY-MM-DD)")
    parser.add_argument("--end", help="summary: last date for best sellers (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=3, help="summary: how many best sellers")
    parser.add_argument("--limit", type=int, default=20, help="runs: how many runs to show")
    return parser.parse_args(argv)


# One function for each command

def cmd_init_db(args, config):
    """Create the database; with --reset delete the old one first."""
    database = config["database"]
    if args.reset and database.exists():
        database.unlink()
        print(f"Deleted {database}")
    with closing(db.open_database(database)):
        pass  # opening the database is enough to create the tables
    print(f"Database ready: {database}")


def cmd_validate(args, config):
    """Only check the input files and write the validation report."""
    result = check_inputs(config)  # raises InputValidationError if something is wrong
    print(f"Input is valid: {len(result['products'])} products, "
          f"{len(result['sales'])} sales records.")
    print(f"Report written to {config['output_directory'] / 'validation_report.txt'}")


def cmd_import(args, config):
    """Check the input files and store them in the database."""
    counts = validate_and_import(config)
    print(f"Import complete: {counts}")


def cmd_summary(args, config):
    """Print the SQL summaries and write historical_summary.csv."""
    with closing(db.open_database(config["database"])) as conn:
        first, last = db.history_window(conn)
        if first is None:
            raise DataNotLoadedError("no historical sales in the database: run 'import' first")
        start = args.start or first
        end = args.end or last
        try:
            parse_iso_date(start)
            parse_iso_date(end)
        except ValueError as error:
            raise ConfigError(f"--start/--end: {error}")

        print("Units sold and revenue by product (EUR):")
        rows = []
        for row in db.sales_by_product(conn):
            pid, name, category, days, units, mean, revenue, cogs, gross = row
            rows.append([pid, name, units, f"{mean:.4f}", cents_to_euros(revenue),
                         cents_to_euros(cogs), cents_to_euros(gross)])
        print("\n".join(make_table(["product", "name", "units", "mean/day", "revenue",
                                    "cogs", "gross"], rows)))

        print("\nRevenue by category (EUR):")
        rows = []
        for category, n_products, units, revenue in db.revenue_by_category(conn):
            rows.append([category, n_products, units, cents_to_euros(revenue)])
        print("\n".join(make_table(["category", "products", "units", "revenue"], rows)))

        print(f"\nBest sellers from {start} to {end}:")
        rows = []
        for pid, name, units, revenue in db.best_sellers(conn, start, end, args.top):
            rows.append([pid, name, units, cents_to_euros(revenue)])
        print("\n".join(make_table(["product", "name", "units", "revenue"], rows)))

        path = config["output_directory"] / "historical_summary.csv"
        write_historical_summary(conn, path)
    print(f"\nWritten {path}")


def cmd_simulate(args, config):
    """Check + import, compare the policies and write all the outputs."""
    counts = validate_and_import(config)
    print(f"Input valid. Import: {counts}")
    folder = config["output_directory"]
    with closing(db.open_database(config["database"])) as conn:
        comparison = run_comparison(config, conn)
        write_historical_summary(conn, folder / "historical_summary.csv")
        write_daily_simulation(comparison, folder / "daily_simulation.csv")
        write_policy_comparison(config, comparison, folder / "policy_comparison.csv")
        write_seed_check(comparison, config, folder / "seed_check.csv")
        write_report(config, conn, comparison, folder / "report.txt")
    for run in comparison["runs"]:
        shop = run["shop"]
        print(f"  run {run['run_id']:>3}  {run['scenario']:<32} {run['policy'].name:<15}"
              f" operating result EUR {cents_to_euros(shop['operating_result']):>8},"
              f" lost units {shop['lost']}")
    n = config["seeds_to_check"]
    print(f"Seed check: {n} seeds ({config['seed']} to {config['seed'] + n - 1}), see report.txt")
    print(f"Outputs written to {folder}")


def cmd_runs(args, config):
    """Print the simulation runs saved in the database."""
    with closing(db.open_database(config["database"])) as conn:
        saved = db.runs_summary(conn, args.limit)
    if len(saved) == 0:
        print("No simulation runs saved yet.")
        return
    rows = []
    for row in saved:
        run_id, created, scenario, policy, seed, days, demand, sold, lost, revenue, operating = row
        rows.append([run_id, created, scenario, policy, seed, days, sold, lost,
                     cents_to_euros(revenue), cents_to_euros(operating)])
    print("\n".join(make_table(["run", "created", "scenario", "policy", "seed", "days",
                                "sold", "lost", "revenue", "operating"], rows)))


# Dictionary: command name -> function that runs it
COMMANDS = {
    "init-db": cmd_init_db,
    "validate": cmd_validate,
    "import": cmd_import,
    "summary": cmd_summary,
    "simulate": cmd_simulate,
    "runs": cmd_runs,
}


def main(argv=None) -> int:
    """Run one command and return the exit code."""
    args = read_arguments(argv)
    try:
        config = load_config(args.config)
        COMMANDS[args.command](args, config)
    except ConfigError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except DataNotLoadedError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except InputValidationError as error:
        print(f"ERROR: {error}. Simulation not run.", file=sys.stderr)
        for issue in error.issues[:10]:
            print(f"  - {issue}", file=sys.stderr)
        print("  The full list is in validation_report.txt", file=sys.stderr)
        return 1
    except ImportConflictError as error:
        print(f"ERROR: {error}. The database was not changed.", file=sys.stderr)
        for conflict in error.conflicts[:10]:
            print(f"  - {conflict}", file=sys.stderr)
        return 1
    return 0


# this part runs only when we start the program with "python main.py ...",
# not when another file (for example tests.py) imports main
if __name__ == "__main__":
    sys.exit(main())
