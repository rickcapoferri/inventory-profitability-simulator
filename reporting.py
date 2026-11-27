"""Write the CSV output files and the text report."""

# Every output file is REPLACED each time the command runs (the database,
# instead, keeps all the runs). Money is written in euros with two decimals,
# fulfilment rates with four decimals, and "NA" when demand was zero.

import csv
from datetime import datetime

import numpy as np

import database as db
from common import cents_to_euros
from workflow import RNG_DESCRIPTION

# Columns used for the measures in policy_comparison.csv
MEASURES = ["demand", "sold", "lost", "fill_rate", "revenue", "cogs", "gross_profit",
            "holding_cost", "ordering_cost", "operating_result", "orders_placed",
            "final_stock", "final_inventory_value", "outstanding_units", "outstanding_value"]
MONEY_MEASURES = {"revenue", "cogs", "gross_profit", "holding_cost", "ordering_cost",
                  "operating_result", "final_inventory_value", "outstanding_value"}


def format_rate(rate, missing="NA") -> str:
    """Fulfilment rate with 4 decimals, or "NA" when it is not applicable."""
    if rate is None:
        return missing
    return f"{rate:.4f}"


def write_csv(path, header: list, rows: list) -> None:
    """Write a CSV file with a header row (the file is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


def make_table(headers: list, rows: list) -> list:
    """Return the lines of a text table with aligned columns."""
    rows = [[str(value) for value in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    lines = []
    for row in [headers] + rows:
        cells = [value.ljust(widths[i]) for i, value in enumerate(row)]
        lines.append(("  " + "  ".join(cells)).rstrip())
    return lines


# CSV files

def write_historical_summary(conn, path) -> None:
    """historical_summary.csv: one row per product, then one row per category."""
    header = ["level", "key", "name", "category", "days", "units_sold", "mean_daily_units",
              "revenue", "cost_of_goods_sold", "gross_profit"]
    rows = []
    for pid, name, category, days, units, mean, revenue, cogs, gross in db.sales_by_product(conn):
        rows.append(["product", pid, name, category, days, units, f"{mean:.8f}",
                     cents_to_euros(revenue), cents_to_euros(cogs), cents_to_euros(gross)])
    for category, n_products, units, revenue in db.revenue_by_category(conn):
        rows.append(["category", category, "", category, "", units, "",
                     cents_to_euros(revenue), "", ""])
    write_csv(path, header, rows)


def write_daily_simulation(comparison: dict, path) -> None:
    """daily_simulation.csv: one row per run, day and product."""
    header = ["run_id", "scenario", "policy", "day", "product_id", "opening_stock",
              "received", "demand", "sold", "lost", "closing_stock", "ordered",
              "revenue", "cogs", "holding_cost", "ordering_cost", "operating_result"]
    rows = []
    for run in comparison["runs"]:
        r = run["result"]
        operating = r["revenue"] - r["cogs"] - r["holding_cost"] - r["ordering_cost"]
        for day in range(len(r["demand"])):
            for j, pid in enumerate(r["product_ids"]):
                rows.append([run["run_id"], run["scenario"], run["policy"].name, day + 1, pid,
                             r["opening_stock"][day, j], r["received"][day, j],
                             r["demand"][day, j], r["sold"][day, j], r["lost"][day, j],
                             r["closing_stock"][day, j], r["ordered"][day, j],
                             cents_to_euros(r["revenue"][day, j]),
                             cents_to_euros(r["cogs"][day, j]),
                             cents_to_euros(r["holding_cost"][day, j]),
                             cents_to_euros(r["ordering_cost"][day, j]),
                             cents_to_euros(operating[day, j])])
    write_csv(path, header, rows)


def measure_values(measures: dict) -> list:
    """The values of one measures dictionary, in the order of MEASURES."""
    values = []
    for name in MEASURES:
        if name == "fill_rate":
            values.append(format_rate(measures[name]))
        elif name in MONEY_MEASURES:
            values.append(cents_to_euros(measures[name]))
        else:
            values.append(measures[name])
    return values


def baseline_results(comparison: dict) -> dict:
    """{policy name: shop operating result without capacity limit}."""
    results = {}
    for run in comparison["runs"]:
        if run["scenario"] == "baseline":
            results[run["policy"].name] = run["shop"]["operating_result"]
    return results


def write_policy_comparison(config: dict, comparison: dict, path) -> None:
    """policy_comparison.csv: shop totals (level SHOP) and per-product rows of every run."""
    # operating_result_vs_baseline = operating result of a storage scenario
    # minus the same policy without capacity limit.
    header = (["run_id", "scenario", "policy", "policy_parameters", "capacity_units",
               "allocation_rule", "seed", "level"] + MEASURES + ["operating_result_vs_baseline"])
    baseline = baseline_results(comparison)
    rows = []
    for run in comparison["runs"]:
        # the baseline has no capacity and no rule: we leave those cells empty
        capacity = ""
        rule = ""
        difference = ""
        if run["scenario"] != "baseline":
            capacity = run["capacity"]
            rule = run["rule"]
            difference = cents_to_euros(run["shop"]["operating_result"]
                                        - baseline[run["policy"].name])
        start = [run["run_id"], run["scenario"], run["policy"].name, str(run["policy"]),
                 capacity, rule, config["seed"]]
        rows.append(start + ["SHOP"] + measure_values(run["shop"]) + [difference])
        for product_id, measures in run["by_product"].items():
            rows.append(start + [product_id] + measure_values(measures) + [""])
    write_csv(path, header, rows)


# Text report

def candidate_runs(runs: list, config: dict) -> list:
    """The runs we can recommend."""
    # With the storage extension the warehouse really has a limit, so we only
    # choose among the storage scenarios; otherwise among the baseline runs.
    # 'runs' can be the main runs or the runs of one seed of the seed check.
    if config["capacity"] is not None:
        return [run for run in runs if run["scenario"] != "baseline"]
    return [run for run in runs if run["scenario"] == "baseline"]


def best_run(runs: list, config: dict) -> dict:
    """The run with the highest operating result among the candidate runs."""
    # with the same result, the first one in the list is kept
    candidates = candidate_runs(runs, config)
    best = candidates[0]
    for run in candidates:
        if run["shop"]["operating_result"] > best["shop"]["operating_result"]:
            best = run
    return best


# Seed check

def seed_winners(comparison: dict, config: dict) -> dict:
    """{seed: best run of that seed}, chosen with the same rule as the recommendation."""
    winners = {}
    for seed in sorted(set(row["seed"] for row in comparison["seed_check"])):
        same_seed = [row for row in comparison["seed_check"] if row["seed"] == seed]
        winners[seed] = best_run(same_seed, config)
    return winners


def seed_check_summary(comparison: dict, config: dict) -> list:
    """One dictionary per option (scenario + policy) with its results over all the seeds."""
    # mean, min and max operating result in cents (the mean is rounded to the
    # nearest cent), mean lost units, and "wins" = in how many seeds the option
    # was the best. wins is None for an option we never recommend (the
    # baseline, when the storage extension is selected).
    winners = seed_winners(comparison, config)
    candidates = []
    for run in candidate_runs(comparison["runs"], config):
        candidates.append((run["scenario"], run["policy"].name))
    summary = []
    for run in comparison["runs"]:          # same order as the main comparison
        option = (run["scenario"], run["policy"].name)
        results = []
        lost = []
        for row in comparison["seed_check"]:
            if (row["scenario"], row["policy"].name) == option:
                results.append(row["shop"]["operating_result"])
                lost.append(row["shop"]["lost"])
        results = np.array(results)
        wins = None
        if option in candidates:
            wins = 0
            for best in winners.values():
                if (best["scenario"], best["policy"].name) == option:
                    wins += 1
        summary.append({"scenario": run["scenario"], "policy": run["policy"].name,
                        "mean": int(round(results.mean())), "min": int(results.min()),
                        "max": int(results.max()), "mean_lost": float(np.mean(lost)),
                        "wins": wins})
    return summary


def write_seed_check(comparison: dict, config: dict, path) -> None:
    """seed_check.csv: shop totals of every option for every seed of the seed check."""
    # best_of_seed = "yes" for the option with the highest operating result of
    # that seed (among the options we can recommend)
    winners = seed_winners(comparison, config)
    header = ["seed", "scenario", "policy"] + MEASURES + ["best_of_seed"]
    rows = []
    for row in comparison["seed_check"]:
        best = ""
        if row is winners[row["seed"]]:
            best = "yes"
        rows.append([row["seed"], row["scenario"], row["policy"].name]
                    + measure_values(row["shop"]) + [best])
    write_csv(path, header, rows)


def seed_check_lines(comparison: dict, config: dict, best: dict, section: int) -> list:
    """The SEED CHECK section of report.txt."""
    summary = seed_check_summary(comparison, config)
    winners = seed_winners(comparison, config)
    n = config["seeds_to_check"]
    first = config["seed"]
    lines = [
        f"{section}. SEED CHECK ({n} seeds: {first} to {first + n - 1})",
        f"  The comparison is repeated with {n} seeds; seed {first} is the one above.",
        "  In each seed every option gets the same demand array; all the other",
        "  parameters do not change. Only the totals are kept (seed_check.csv), the",
        f"  daily rows are saved in the database only for seed {first}. Money in EUR.",
    ]
    rows = []
    for option in summary:
        wins = "-"
        if option["wins"] is not None:
            wins = f"{option['wins']}/{n}"
        rows.append([option["scenario"], option["policy"], cents_to_euros(option["mean"]),
                     cents_to_euros(option["min"]), cents_to_euros(option["max"]),
                     f"{option['mean_lost']:.1f}", wins])
    lines += make_table(["scenario", "policy", "mean", "min", "max", "mean_lost", "best_in"],
                        rows)
    lines.append("  mean/min/max = operating result over the seeds; best_in = seeds in which")
    lines.append("  the option had the highest operating result (- = option not recommended)")
    lines.append("")

    # how often the recommended option, its rule and its policy were the best
    option_wins = 0
    rule_wins = 0
    policy_wins = 0
    for winner in winners.values():
        if winner["scenario"] == best["scenario"]:
            rule_wins += 1
        if winner["policy"].name == best["policy"].name:
            policy_wins += 1
        if winner["scenario"] == best["scenario"] and winner["policy"].name == best["policy"].name:
            option_wins += 1
    recommended = None
    highest = None
    for option in summary:
        if option["scenario"] == best["scenario"] and option["policy"] == best["policy"].name:
            recommended = option
        if option["wins"] is not None and (highest is None or option["mean"] > highest["mean"]):
            highest = option

    lines.append(f"  The recommended option was the best in {option_wins} of {n} seeds.")
    if best["rule"] is not None:
        lines.append(f"  Its allocation rule ({best['rule']}) was used by the best option "
                     f"in {rule_wins} of {n} seeds.")
    lines.append(f"  Its policy ({best['policy'].name}) was the best in {policy_wins} of {n} seeds.")
    lines.append(f"  From one seed to another its operating result goes from EUR "
                 f"{cents_to_euros(recommended['min'])} to EUR {cents_to_euros(recommended['max'])}.")
    if highest is recommended:
        lines.append(f"  It also has the highest mean operating result "
                     f"(EUR {cents_to_euros(recommended['mean'])}).")
    else:
        gap = highest["mean"] - recommended["mean"]
        lines.append(f"  The highest mean is {highest['policy']} in {highest['scenario']}: "
                     f"EUR {cents_to_euros(highest['mean'])}, EUR {cents_to_euros(gap)} more")
        lines.append(f"  than the recommended option (EUR {cents_to_euros(recommended['mean'])}).")
    if option_wins * 2 > n:
        lines.append("  Conclusion: the recommendation is confirmed in most seeds.")
    else:
        lines.append("  Conclusion: the recommended option is NOT the best in most seeds, so")
        lines.append("  the choice between the closest options depends on the random demand.")
    if best["rule"] is not None and rule_wins == n:
        lines.append(f"  The allocation rule {best['rule']} is the better rule in every seed.")
    lines.append("")
    return lines


def build_report(config: dict, conn, comparison: dict) -> str:
    """Return the full text of report.txt."""
    first, last = db.history_window(conn)
    run_ids = [str(run["run_id"]) for run in comparison["runs"]]
    lines = [
        "INVENTORY AND PROFITABILITY SIMULATION REPORT",
        f"Generated:      {datetime.now().isoformat(timespec='seconds')}",
        f"Configuration:  {config['config_file']}",
        f"Extension:      {config['extension'] or 'none (core only)'}",
        f"Horizon:        {config['days']} days, orders arrive the next morning",
        f"Random seed:    {config['seed']} (seed check: {config['seeds_to_check']} seeds)",
        f"Random numbers: {RNG_DESCRIPTION}, NumPy {np.__version__}",
        f"Holding cost:   EUR {cents_to_euros(config['holding_cost'])} per unit per day",
        f"Order cost:     EUR {cents_to_euros(config['order_cost'])} per product order",
        f"Saved run ids:  {', '.join(run_ids)}",
        "",
        "1. ASSUMPTIONS",
        "  - Historical sales are treated as historical demand: we assume the shop had",
        "    no stock-outs in the past, so no demand was hidden.",
        f"  - Mean daily demand of each product = average of the {comparison['history_days']}"
        f" historical days ({first} to {last}).",
        "  - Future daily demand is Poisson with that mean: whole numbers >= 0 that",
        "    vary randomly around the average.",
        "  - All policies and scenarios use the SAME demand array, so the differences",
        "    come from the policies and not from different random numbers.",
        "  - Demand that cannot be satisfied is lost (customers do not wait).",
        "  - Prices and costs are constant. Holding cost is paid on end-of-day stock;",
        "    the fixed order cost is paid once for each product ordered on a day.",
        "  - Orders placed on the last day are paid but never arrive: they are shown as",
        "    outstanding, separate from the final stock. Unsold stock is not COGS.",
        "",
        "2. HISTORICAL SALES (SQL summaries)",
    ]

    rows = []
    for pid, name, category, days, units, mean, revenue, cogs, gross in db.sales_by_product(conn):
        rows.append([pid, name, units, f"{mean:.2f}", cents_to_euros(revenue),
                     cents_to_euros(gross)])
    lines += make_table(["product", "name", "units", "mean/day", "revenue", "gross_profit"], rows)
    lines.append("")
    rows = []
    for category, n_products, units, revenue in db.revenue_by_category(conn):
        rows.append([category, n_products, units, cents_to_euros(revenue)])
    lines += make_table(["category", "products", "units", "revenue"], rows)
    lines.append("")
    lines.append(f"  Best sellers from {first} to {last}:")
    rows = []
    for pid, name, units, revenue in db.best_sellers(conn, first, last, 3):
        rows.append([pid, name, units, cents_to_euros(revenue)])
    lines += make_table(["product", "name", "units", "revenue"], rows)
    lines.append("")

    lines.append("3. POLICY COMPARISON (whole shop, money in EUR)")
    rows = []
    for run in comparison["runs"]:
        s = run["shop"]
        rows.append([run["scenario"], str(run["policy"]), s["sold"], s["lost"],
                     format_rate(s["fill_rate"], "n/a"), cents_to_euros(s["revenue"]),
                     cents_to_euros(s["gross_profit"]), cents_to_euros(s["holding_cost"]),
                     cents_to_euros(s["ordering_cost"]), cents_to_euros(s["operating_result"]),
                     s["final_stock"], s["outstanding_units"]])
    lines += make_table(["scenario", "policy", "sold", "lost", "fill", "revenue", "gross",
                         "holding", "ordering", "operating", "final_stock", "outstanding"], rows)
    lines.append(f"  final_stock = units in the shop after day {config['days']}; "
                 "outstanding = units ordered on the last day")
    lines.append("")

    section = 4
    if config["capacity"] is not None:
        initial = sum(p.initial_stock for p in comparison["products"])
        baseline = baseline_results(comparison)
        lines += [
            "4. EXTENSION B - STORAGE CAPACITY",
            f"  Capacity: {config['capacity']} units (initial stock {initial} units).",
            "  Checked before ordering: closing stock + orders <= capacity.",
            "  product_id_ascending: products are served in id order (P001 first).",
            "  unit_margin_descending: highest (price - cost) first, ties by id.",
        ]
        rows = []
        for run in comparison["runs"]:
            if run["scenario"] == "baseline":
                continue
            r = run["result"]
            morning_stock = (r["opening_stock"] + r["received"]).sum(axis=1)  # one total per day
            s = run["shop"]
            difference = s["operating_result"] - baseline[run["policy"].name]
            rows.append([run["rule"], run["policy"].name, s["lost"],
                         format_rate(s["fill_rate"], "n/a"),
                         cents_to_euros(s["operating_result"]), cents_to_euros(difference),
                         morning_stock.max()])
        lines += make_table(["rule", "policy", "lost", "fill", "operating", "vs_unlimited",
                             "peak_stock"], rows)
        lines.append("  vs_unlimited = operating result minus the same policy with no limit")
        lines.append("")
        section = 5

    best = best_run(comparison["runs"], config)
    s = best["shop"]
    choice = str(best["policy"])
    if best["rule"] is not None:
        choice += f" with allocation rule {best['rule']}"
    lines += [
        f"{section}. RECOMMENDATION",
        f"  The best option is {choice}.",
        f"  Operating result EUR {cents_to_euros(s['operating_result'])}, "
        f"fulfilment rate {format_rate(s['fill_rate'], 'n/a')}, lost units {s['lost']}.",
    ]
    for run in candidate_runs(comparison["runs"], config):   # compare like with like
        if run is not best:
            gap = s["operating_result"] - run["shop"]["operating_result"]
            lines.append(f"  Compared with {run['policy'].name} in {run['scenario']}: "
                         f"EUR {cents_to_euros(gap)} more, lost units {s['lost']} "
                         f"vs {run['shop']['lost']}.")
    lines.append(f"  This uses the demand of seed {config['seed']} ({config['days']} days); "
                 f"section {section + 1} repeats it with {config['seeds_to_check']} seeds.")
    lines.append("")
    lines.append("  Detail by product of the recommended option:")
    rows = []
    for pid, m in best["by_product"].items():
        rows.append([pid, m["demand"], m["sold"], m["lost"], format_rate(m["fill_rate"], "n/a"),
                     cents_to_euros(m["operating_result"]), m["final_stock"],
                     m["outstanding_units"]])
    lines += make_table(["product", "demand", "sold", "lost", "fill", "operating",
                         "final_stock", "outstanding"], rows)
    lines.append("")

    lines += seed_check_lines(comparison, config, best, section + 1)

    lines += [
        f"{section + 2}. LIMITATIONS",
        f"  - The seed check uses only {config['seeds_to_check']} seeds: it shows if the best",
        "    option changes, but it does not give precise confidence intervals.",
        "  - Demand is the same every day on average (no seasons, weekdays or trends)",
        "    and products are independent (no customer buys a substitute).",
        "  - If the shop had stock-outs in the past, the mean demand is underestimated.",
        "  - Lead time is always one day and the supplier never fails.",
        "  - The same thresholds are used for all products, which sell at very different rates.",
        "",
        f"{section + 3}. SAVED SIMULATION RUNS (SQL summary, most recent first)",
    ]
    rows = []
    for row in db.runs_summary(conn, 12):
        run_id, created, scenario, policy, seed, days, demand, sold, lost, revenue, operating = row
        rows.append([run_id, created, scenario, policy, seed, days, sold, lost,
                     cents_to_euros(operating)])
    lines += make_table(["run", "created", "scenario", "policy", "seed", "days", "sold", "lost",
                         "operating"], rows)
    lines.append("")
    lines.append("Output files are replaced by each command; runs are added to the database.")
    return "\n".join(lines) + "\n"


def write_report(config: dict, conn, comparison: dict, path) -> None:
    """Write report.txt (the file is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(build_report(config, conn, comparison))
