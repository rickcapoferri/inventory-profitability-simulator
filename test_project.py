"""Tests for configuration, CSV validation, SQLite, demand, policies, and CLI."""

import csv
import json
from copy import deepcopy
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from config import ConfigurationError, load_config, validate_config
from validation import CSVValidationError, products_csv_validation
from database import (
    best_selling_products,
    historical_revenue_by_category,
    historical_sales_by_product,
    import_historical_data,
    save_simulation_runs,
    saved_simulation_summary,
)
from simulation import FixedQuantityPolicy, OrderUpToPolicy, generate_demand, simulate_inventory
from main import main

ROOT = Path(__file__).resolve().parent


# config


def test_load_core_config() -> None:
    config_path = ROOT / "config" / "core.toml"

    config = load_config(config_path)

    assert config["simulation"]["days"] == 60
    assert config["simulation"]["seed"] == 2026
    assert config["simulation"]["currency"] == "EUR"


def test_rejects_zero_simulation_days() -> None:
    config_path = ROOT / "validation" / "invalid_config.toml"

    with pytest.raises(
        ConfigurationError,
        match="simulation.days must be a positive integer",
    ):
        load_config(config_path)


def test_rejects_promotion_ending_after_simulation() -> None:
    config = load_config(ROOT / "config" / "promotion.toml")
    config["simulation"]["days"] = 20

    with pytest.raises(
        ConfigurationError,
        match="promotion.end_day must not exceed simulation.days",
    ):
        validate_config(config)

# csv validation


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_rows(path, rows, columns=None):
    if columns is None:
        columns = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def sample_rows():
    return (
        read_rows(ROOT / "data" / "products.csv"),
        read_rows(ROOT / "data" / "historical_sales.csv"),
    )


def test_valid_inputs_from_another_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    products, sales = products_csv_validation()
    assert len(sales) == 720
    assert len({row["product_id"] for row in products}) == len(products)
    assert isinstance(products[0]["purchase_cost"], float)
    assert isinstance(sales[0]["units_sold"], int)


@pytest.mark.parametrize("filename,expected", [
    ("products_zero_cost.csv", "purchase_cost"),
    ("sales_negative_quantity.csv", "units_sold"),
    ("sales_missing_day.csv", "incomplete history"),
    ("sales_duplicate_pair.csv", "duplicate product-date"),
    ("sales_unknown_product.csv", "unknown products"),
])
def test_supplied_invalid_examples(filename, expected):
    products = ROOT / "data" / "products.csv"
    sales = ROOT / "data" / "historical_sales.csv"
    invalid = ROOT / "validation" / filename
    if filename.startswith("products"):
        products = invalid
    else:
        sales = invalid
    with pytest.raises(CSVValidationError, match=expected):
        products_csv_validation(products, sales)


@pytest.mark.parametrize("table,column,value,expected", [
    ("products", "purchase_cost", "0", "purchase_cost"),
    ("products", "selling_price", "-1", "selling_price"),
    ("products", "purchase_cost", "inf", "finite positive"),
    ("products", "purchase_cost", "NaN", "finite positive"),
    ("products", "selling_price", "abc", "finite positive"),
    ("products", "initial_stock", "1.5", "non-negative integers"),
    ("products", "initial_stock", "1.0", "non-negative integers"),
    ("sales", "units_sold", "1e3", "non-negative integers"),
    ("products", "initial_stock", "-1", "non-negative integers"),
    ("sales", "units_sold", "1.5", "non-negative integers"),
    ("sales", "units_sold", "inf", "non-negative integers"),
    ("sales", "date", "2026-02-30", "YYYY-MM-DD"),
    ("sales", "date", "2026-1-01", "YYYY-MM-DD"),
    ("sales", "date", "20260101", "YYYY-MM-DD"),
    ("sales", "date", "2026-01-01T00:00:00", "YYYY-MM-DD"),
    ("products", "product_id", "", "missing values"),
    ("products", "name", "  ", "missing values"),
])
def test_invalid_values_report_rows(tmp_path, table, column, value, expected):
    products, sales = sample_rows()
    rows = products if table == "products" else sales
    rows[0][column] = value
    write_rows(tmp_path / "products.csv", products)
    write_rows(tmp_path / "sales.csv", sales)
    with pytest.raises(CSVValidationError, match=expected) as error:
        products_csv_validation(tmp_path / "products.csv", tmp_path / "sales.csv")
    assert "CSV rows 2" in str(error.value)


@pytest.mark.parametrize("case,expected", [
    ("duplicate_product", "duplicate identifiers"),
    ("missing_column", "missing columns"),
    ("empty_catalogue", "at least one data row"),
    ("short_history", "at least 30 consecutive"),
    ("missing_product", "incomplete history"),
    ("missing_entire_day", "incomplete history"),
])
def test_invalid_structure(tmp_path, case, expected):
    products, sales = sample_rows()
    if case == "duplicate_product":
        products.append(products[0].copy())
    elif case == "missing_column":
        for row in products:
            row.pop("purchase_cost")
    elif case == "empty_catalogue":
        products = []
    elif case == "short_history":
        first = min(date.fromisoformat(row["date"]) for row in sales)
        sales = [row for row in sales if date.fromisoformat(row["date"]) < first + timedelta(days=29)]
    elif case == "missing_product":
        sales = [row for row in sales if row["product_id"] != products[0]["product_id"]]
    elif case == "missing_entire_day":
        missing = sorted({row["date"] for row in sales})[1]
        sales = [row for row in sales if row["date"] != missing]
    product_columns = list(products[0]) if products else [
        "product_id", "name", "category", "purchase_cost", "selling_price", "initial_stock"
    ]
    write_rows(tmp_path / "products.csv", products, product_columns)
    write_rows(tmp_path / "sales.csv", sales)
    with pytest.raises(CSVValidationError, match=expected):
        products_csv_validation(tmp_path / "products.csv", tmp_path / "sales.csv")


def test_preserves_identifiers_and_accepts_zero_sales(tmp_path):
    products = [{
        "product_id": "001", "name": "NA", "category": "NA",
        "purchase_cost": "0.20", "selling_price": "0.50", "initial_stock": "0",
    }]
    start = date(2026, 1, 1)
    sales = [{"date": (start + timedelta(days=i)).isoformat(), "product_id": "001", "units_sold": "0"} for i in range(30)]
    write_rows(tmp_path / "products.csv", products)
    write_rows(tmp_path / "sales.csv", sales)
    catalogue, history = products_csv_validation(tmp_path / "products.csv", tmp_path / "sales.csv")
    assert catalogue[0]["product_id"] == "001"
    assert catalogue[0]["name"] == "NA"
    assert all(row["units_sold"] == 0 for row in history)

# database


def load_sample_data():
    return products_csv_validation(
        ROOT / "data" / "products.csv",
        ROOT / "data" / "historical_sales.csv",
    )


def test_imports_data_and_matches_expected_product_summary(tmp_path):
    database = tmp_path / "nested" / "inventory.sqlite"
    products, sales = load_sample_data()

    import_historical_data(database, products, sales)
    actual = historical_sales_by_product(database)

    with (ROOT / "checks" / "expected_historical_by_product.csv").open(
        encoding="utf-8", newline=""
    ) as file:
        expected = list(csv.DictReader(file))
    assert [row["product_id"] for row in actual] == [row["product_id"] for row in expected]
    for result, reference in zip(actual, expected):
        assert result["days"] == int(reference["days"])
        assert result["units_sold"] == int(reference["units_sold"])
        assert result["revenue"] == pytest.approx(float(reference["revenue"]))
        assert result["cost_of_goods_sold"] == pytest.approx(
            float(reference["cost_of_goods_sold"])
        )
        assert result["gross_profit"] == pytest.approx(float(reference["gross_profit"]))


def test_reimport_updates_existing_keys_without_duplicating_rows(tmp_path):
    database = tmp_path / "inventory.sqlite"
    products, sales = load_sample_data()
    import_historical_data(database, products, sales)
    products[0]["selling_price"] = 2.75
    sales[0]["units_sold"] = 10
    import_historical_data(database, products, sales)

    with sqlite3.connect(database) as connection:
        product_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        sales_count = connection.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0]
        updated_price = connection.execute(
            "SELECT selling_price_cents FROM products WHERE product_id = ?", ("P001",)
        ).fetchone()[0]
        updated_sales = connection.execute(
            "SELECT units_sold FROM historical_sales WHERE sale_date = ? AND product_id = ?",
            ("2026-01-01", "P001"),
        ).fetchone()[0]

    assert product_count == len(products)
    assert sales_count == len(sales)
    assert updated_price == 275
    assert updated_sales == 10


def test_category_summary_and_parameterized_date_range(tmp_path):
    database = tmp_path / "inventory.sqlite"
    products, sales = load_sample_data()
    import_historical_data(database, products, sales)

    categories = historical_revenue_by_category(database)
    by_category = {row["category"]: row for row in categories}
    assert set(by_category) == {product["category"] for product in products}
    assert by_category["Stationery"]["revenue"] == pytest.approx(
        sum(row["revenue"] for row in historical_sales_by_product(database)[:3])
    )

    ranked = best_selling_products(database, "2026-01-01", "2026-01-01")
    assert ranked[0]["product_id"] == "P002"
    assert ranked[0]["units_sold"] == 16


def test_foreign_key_failure_rolls_back_import(tmp_path):
    database = tmp_path / "inventory.sqlite"
    products, sales = load_sample_data()
    bad_sales = sales + [{"date": "2026-01-01", "product_id": "UNKNOWN", "units_sold": 1}]

    with pytest.raises(sqlite3.IntegrityError):
        import_historical_data(database, products, bad_sales)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0] == 0

# demand


SUMMARY = [
    {"product_id": "P002", "mean_daily_units": 4.0},
    {"product_id": "P001", "mean_daily_units": 0.0},
]


def test_reproducible_demand_with_stable_columns_and_zero_mean():
    product_ids, demand = generate_demand(SUMMARY, days=60, seed=2026)
    _, repeated = generate_demand(list(reversed(SUMMARY)), days=60, seed=2026)

    assert product_ids == ["P001", "P002"]
    assert demand.shape == (60, 2)
    assert np.issubdtype(demand.dtype, np.integer)
    assert (demand >= 0).all()
    assert (demand[:, 0] == 0).all()
    assert np.array_equal(demand, repeated)
    assert not demand.flags.writeable


def test_poisson_sample_mean_is_close_to_historical_mean():
    _, demand = generate_demand(SUMMARY, days=100_000, seed=123)
    assert demand[:, 1].mean() == pytest.approx(4.0, abs=0.05)


@pytest.mark.parametrize("mean", [-1, float("nan"), float("inf"), True, "4"])
def test_rejects_unusable_historical_means(mean):
    with pytest.raises(ValueError, match="Historical mean"):
        generate_demand([{"product_id": "P001", "mean_daily_units": mean}], 10, 1)


@pytest.mark.parametrize("days,seed", [(0, 1), (True, 1), (1, -1), (1, True)])
def test_rejects_invalid_days_or_seed(days, seed):
    with pytest.raises(ValueError):
        generate_demand(SUMMARY, days, seed)

# policies


@pytest.mark.parametrize("stock,fixed_order,target_order", [
    (0, 40, 60),
    (15, 40, 45),
    (19, 40, 41),
    (20, 0, 0),
    (25, 0, 0),
    (70, 0, 0),
])
def test_policy_rules_below_at_and_above_threshold(stock, fixed_order, target_order):
    fixed = FixedQuantityPolicy(threshold=20, quantity=40)
    order_up_to = OrderUpToPolicy(threshold=20, target=60)

    assert fixed.order_quantity(stock) == fixed_order
    assert order_up_to.order_quantity(stock) == target_order
    assert fixed.policy_name == "fixed_quantity"
    assert order_up_to.policy_name == "order_up_to"


def test_order_up_to_target_can_equal_threshold():
    policy = OrderUpToPolicy(threshold=20, target=20)

    assert policy.order_quantity(15) == 5
    assert policy.order_quantity(20) == 0


def test_zero_threshold_places_no_order_for_non_negative_stock():
    policies = [
        FixedQuantityPolicy(threshold=0, quantity=40),
        OrderUpToPolicy(threshold=0, target=60),
    ]
    for policy in policies:
        assert policy.order_quantity(0) == 0

# cli


def test_cli_imports_and_prints_historical_summary(tmp_path, capsys):
    config_path = tmp_path / "cli.toml"
    database_path = tmp_path / "nested" / "inventory.sqlite"
    config_path.write_text(
        f'''[files]
products = "{(ROOT / "data" / "products.csv").as_posix()}"
historical_sales = "{(ROOT / "data" / "historical_sales.csv").as_posix()}"
database = "{database_path.as_posix()}"
output_directory = "{(tmp_path / "results").as_posix()}"

[simulation]
days = 60
seed = 2026
currency = "EUR"

[demand]
model = "poisson"
mean_source = "historical_daily_mean"

[costs]
holding_per_unit_per_day = 0.02
fixed_per_product_order = 1.00

[policies.fixed_quantity]
threshold = 20
quantity = 40

[policies.order_up_to]
threshold = 20
target = 60

[extension]
selected = ""
''',
        encoding="utf-8",
    )

    exit_code = main([str(config_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Imported 8 products and 720 sales rows." in output
    assert "P001 | 90 | 733" in output
    assert "Generated demand: 60 days x 8 products (seed 2026)." in output
    assert "Core simulation comparison:" in output
    assert "fixed_quantity |" in output
    assert "order_up_to |" in output
    assert database_path.is_file()


def test_cli_reports_invalid_config_without_traceback(tmp_path, capsys):
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("[simulation]\ndays = 0\n", encoding="utf-8")

    exit_code = main([str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err
    assert "FAILED" in (tmp_path / "validation_results" / "validation_report.txt").read_text()


def test_replacing_history_removes_old_dates(tmp_path):
    products, sales = sample_rows()
    database = tmp_path / "inventory.sqlite"
    import_historical_data(database, products, sales)
    dates = sorted({row["date"] for row in sales})[:30]
    shorter_history = []
    for row in sales:
        if row["date"] in dates:
            shorter_history.append(row)
    import_historical_data(database, products, shorter_history)

    for row in historical_sales_by_product(database):
        assert row["days"] == 30


def test_failed_replacement_preserves_previous_data(tmp_path):
    products, sales = load_sample_data()
    database = tmp_path / "inventory.sqlite"
    import_historical_data(database, products, sales)
    previous = historical_sales_by_product(database)

    with pytest.raises(sqlite3.IntegrityError):
        import_historical_data(database, products, [
            {"date": "2026-01-01", "product_id": "UNKNOWN", "units_sold": 1}
        ])
    assert historical_sales_by_product(database) == previous


@pytest.mark.parametrize("case,expected", [
    ("extra_field", "extra fields"),
    ("duplicate_header", "duplicate column"),
])
def test_malformed_csv_structure(tmp_path, case, expected):
    with (ROOT / "data" / "products.csv").open(newline="", encoding="utf-8") as file:
        rows = list(csv.reader(file))
    if case == "extra_field":
        rows[1].append("unexpected value")
    else:
        rows[0].append("product_id")
        for row in rows[1:]:
            row.append(row[0])
    path = tmp_path / "products.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerows(rows)

    with pytest.raises(CSVValidationError, match=expected):
        products_csv_validation(path, ROOT / "data" / "historical_sales.csv")


# daily simulation: independently calculated examples


def simulation_product():
    return {"product_id": "A", "initial_stock": 3,
            "purchase_cost": 1.20, "selling_price": 2.50}


def test_daily_arrivals_lost_sales_and_finances():
    product = simulation_product()
    demand = np.array([[5], [1], [0]])
    original = demand.copy()
    result = simulate_inventory(
        [product], ["A"], demand, FixedQuantityPolicy(2, 4), 0.02, 1.00
    )
    first, second, third = result["daily_results"]
    assert (first["received_units"], first["units_sold"], first["units_lost"]) == (0, 3, 2)
    assert (first["closing_stock"], first["ordered_units"]) == (0, 4)
    assert (second["received_units"], second["units_sold"], second["closing_stock"]) == (4, 1, 3)
    assert third["units_sold"] == 0  # Yesterday's lost demand is never backlogged.
    totals = result["shop_summary"]
    assert totals["revenue_cents"] == 1000
    assert totals["cost_of_goods_sold_cents"] == 480
    assert totals["gross_profit_cents"] == 520
    assert totals["holding_cost_cents"] == 12
    assert totals["ordering_cost_cents"] == 100
    assert totals["operating_result_cents"] == 408
    assert totals["fulfilment_rate"] == pytest.approx(4 / 6)
    assert totals["final_stock"] == 3
    assert totals["final_inventory_value_cents"] == 360
    assert totals["outstanding_orders"] == 0
    assert np.array_equal(demand, original)
    assert product == simulation_product()


def test_final_day_orders_are_charged_but_not_received():
    result = simulate_inventory(
        [simulation_product()], ["A"], np.array([[5], [4]]),
        FixedQuantityPolicy(2, 4), 0.02, 1.00,
    )
    totals = result["shop_summary"]
    assert totals["ordered_units"] == 8
    assert totals["received_units"] == 4
    assert totals["outstanding_orders"] == 4
    assert totals["final_stock"] == 0
    assert totals["final_inventory_value_cents"] == 0
    assert totals["ordering_cost_cents"] == 200
    assert totals["operating_result_cents"] == 710


@pytest.mark.parametrize("policy", [FixedQuantityPolicy(2, 4), OrderUpToPolicy(2, 6)])
def test_multi_product_stock_conservation_and_shared_demand(policy):
    products = [simulation_product(), {
        "product_id": "B", "initial_stock": 1,
        "purchase_cost": 0.30, "selling_price": 0.80,
    }]
    # Columns intentionally differ from catalogue order.
    demand = np.array([[2, 5], [10, 2], [0, 0]])
    demand.setflags(write=False)
    result = simulate_inventory(products, ["B", "A"], demand, policy, 0.02, 1.00)
    previous_stock = {"A": 3, "B": 1}
    previous_orders = {"A": 0, "B": 0}
    for row in result["daily_results"]:
        pid = row["product_id"]
        assert row["opening_stock"] == previous_stock[pid]
        assert row["received_units"] == previous_orders[pid]
        assert row["available_stock"] == row["opening_stock"] + row["received_units"]
        assert row["closing_stock"] == row["available_stock"] - row["units_sold"]
        assert row["closing_stock"] >= 0
        assert row["demand"] == row["units_sold"] + row["units_lost"]
        previous_stock[pid] = row["closing_stock"]
        previous_orders[pid] = row["ordered_units"]
    assert result["daily_results"][0]["units_sold"] == 1
    assert result["daily_results"][1]["units_sold"] == 3
    assert result["daily_results"][0]["ordering_cost_cents"] == 100
    assert result["daily_results"][1]["ordering_cost_cents"] == 100
    totals = result["shop_summary"]
    assert 4 + totals["received_units"] == totals["units_sold"] + totals["final_stock"]
    assert totals["ordered_units"] == totals["received_units"] + totals["outstanding_orders"]
    for key in ("revenue_cents", "operating_result_cents", "final_inventory_value_cents"):
        assert totals[key] == sum(row[key] for row in result["product_summary"])
    assert result == simulate_inventory(products, ["B", "A"], demand, policy, 0.02, 1.00)


def test_zero_demand_and_zero_order_have_no_fulfilment_rate_or_ordering_cost():
    result = simulate_inventory(
        [simulation_product()], ["A"], np.zeros((2, 1), dtype=int),
        FixedQuantityPolicy(0, 4), 0.02, 1.00,
    )
    totals = result["shop_summary"]
    assert totals["fulfilment_rate"] is None
    assert result["product_summary"][0]["fulfilment_rate"] is None
    assert totals["ordering_cost_cents"] == 0
    assert totals["ordered_units"] == 0
    assert totals["operating_result_cents"] == -12


def test_simulation_money_rounds_unit_rates_half_up():
    product = simulation_product()
    product.update(purchase_cost=1.205, selling_price=2.505)
    result = simulate_inventory(
        [product], ["A"], np.array([[1]]), FixedQuantityPolicy(0, 4), 0.025, 0,
    )
    totals = result["shop_summary"]
    assert totals["revenue_cents"] == 251
    assert totals["cost_of_goods_sold_cents"] == 121
    assert totals["holding_cost_cents"] == 6
    assert totals["final_inventory_value_cents"] == 242


@pytest.mark.parametrize("demand", [
    np.array([1]), np.array([[1, 2]]), np.array([[-1]]),
    np.array([[1.5]]), np.empty((0, 1), dtype=int), np.array([[True]]),
])
def test_simulation_rejects_invalid_demand(demand):
    with pytest.raises(ValueError, match="day-by-product"):
        simulate_inventory([simulation_product()], ["A"], demand,
                           FixedQuantityPolicy(2, 4), 0.02, 1)


# persistence and output files


def temporary_core_config(tmp_path):
    text = (ROOT / "config" / "core.toml").read_text()
    replacements = {
        "../data/products.csv": str(ROOT / "data" / "products.csv"),
        "../data/historical_sales.csv": str(ROOT / "data" / "historical_sales.csv"),
        "../working/inventory.sqlite": str(tmp_path / "inventory.sqlite"),
        "../results/core": str(tmp_path / "results"),
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    path = tmp_path / "core.toml"
    path.write_text(text)
    return path


def test_saved_runs_and_exports_match_simulation_and_append(tmp_path):
    path = temporary_core_config(tmp_path)
    assert main([str(path)]) == 0
    database = tmp_path / "inventory.sqlite"
    summaries = saved_simulation_summary(database)
    assert len(summaries) == 2
    config = load_config(path)
    products, sales = load_sample_data()
    historical = historical_sales_by_product(database)
    ids, demand = generate_demand(historical, 60, 2026)
    policies = [FixedQuantityPolicy(20, 40), OrderUpToPolicy(20, 60)]
    for stored, policy in zip(summaries, policies):
        expected = simulate_inventory(products, ids, demand, policy, 0.02, 1)["shop_summary"]
        for key, value in expected.items():
            assert stored[key] == value
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_simulation_results").fetchone()[0] == 960
        metadata = connection.execute(
            "SELECT config_json, numpy_version, rng_method FROM simulation_runs LIMIT 1"
        ).fetchone()
        assert json.loads(metadata[0])["simulation"] == config["simulation"]
        assert metadata[1] == np.__version__
        assert "PCG64" in metadata[2]
    output = tmp_path / "results"
    daily = read_rows(output / "daily_simulation.csv")
    comparison = read_rows(output / "policy_comparison.csv")
    assert len(daily) == 960
    assert len(comparison) == 18  # 2 shop totals + 2 x 8 products
    for row, expected in zip([r for r in comparison if r["scope"] == "shop"], summaries):
        assert int(row["operating_result_cents"]) == expected["operating_result_cents"]
        assert int(row["outstanding_orders"]) == expected["outstanding_orders"]
    historical_rows = read_rows(output / "historical_summary.csv")
    assert len(historical_rows) == 11  # 8 products and 3 categories
    assert historical_rows[0]["revenue"] == "1832.50"
    report = (output / "report.txt").read_text()
    assert "2764.20" in report
    assert "Limitations:" in report
    assert "fixed_quantity" in report
    assert "PASSED" in (output / "validation_report.txt").read_text()
    assert main([str(path)]) == 0
    assert len(saved_simulation_summary(database)) == 4
    assert {row["run_id"] for row in read_rows(output / "daily_simulation.csv")} == {"3", "4"}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0] == 720


def test_saved_runs_survive_catalogue_replacement(tmp_path):
    assert main([str(temporary_core_config(tmp_path))]) == 0
    database = tmp_path / "inventory.sqlite"
    previous = saved_simulation_summary(database)
    products, sales = load_sample_data()
    removed = products.pop(0)["product_id"]
    products[0]["purchase_cost"] = 99
    sales = [row for row in sales if row["product_id"] != removed]
    import_historical_data(database, products, sales)
    assert saved_simulation_summary(database) == previous
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM simulation_products").fetchone()[0] == 16


def test_failed_comparison_save_rolls_back_all_new_runs(tmp_path):
    path = temporary_core_config(tmp_path)
    assert main([str(path)]) == 0
    database = tmp_path / "inventory.sqlite"
    previous = saved_simulation_summary(database)
    config = load_config(path)
    products, _ = load_sample_data()
    historical = historical_sales_by_product(database)
    ids, demand = generate_demand(historical, 60, 2026)
    result = simulate_inventory(products, ids, demand, FixedQuantityPolicy(20, 40), 0.02, 1)
    bad = deepcopy(result)
    bad["daily_results"][0]["product_id"] = "UNKNOWN"
    with pytest.raises(sqlite3.IntegrityError):
        save_simulation_runs(database, config, products, historical, [result, bad])
    assert saved_simulation_summary(database) == previous
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM simulation_runs").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM daily_simulation_results").fetchone()[0] == 960


@pytest.mark.parametrize("filename", [
    "products_zero_cost.csv", "sales_negative_quantity.csv", "sales_missing_day.csv",
    "sales_duplicate_pair.csv", "sales_unknown_product.csv", "invalid_config.toml",
])
def test_invalid_inputs_report_failure_without_changing_saved_runs(tmp_path, filename):
    path = temporary_core_config(tmp_path)
    assert main([str(path)]) == 0
    database = tmp_path / "inventory.sqlite"
    previous = saved_simulation_summary(database)
    old_export = (tmp_path / "results" / "daily_simulation.csv").read_bytes()
    text = path.read_text()
    if filename == "invalid_config.toml":
        text = text.replace("days = 60", "days = 0")
    else:
        valid_name = "products.csv" if filename.startswith("products") else "historical_sales.csv"
        text = text.replace(str(ROOT / "data" / valid_name), str(ROOT / "validation" / filename))
    path.write_text(text)
    assert main([str(path)]) == 1
    assert "FAILED" in (tmp_path / "results" / "validation_report.txt").read_text()
    assert saved_simulation_summary(database) == previous
    assert (tmp_path / "results" / "daily_simulation.csv").read_bytes() == old_export


def test_zero_demand_is_null_in_sql_and_blank_in_export(tmp_path):
    path = temporary_core_config(tmp_path)
    _, sales = sample_rows()
    for row in sales:
        row["units_sold"] = "0"
    sales_path = tmp_path / "zero_sales.csv"
    write_rows(sales_path, sales)
    path.write_text(path.read_text().replace(str(ROOT / "data" / "historical_sales.csv"), str(sales_path)))
    assert main([str(path)]) == 0
    assert all(row["fulfilment_rate"] is None for row in saved_simulation_summary(tmp_path / "inventory.sqlite"))
    comparison = read_rows(tmp_path / "results" / "policy_comparison.csv")
    assert all(row["fulfilment_rate"] == "" for row in comparison)
    assert "N/A (zero demand)" in (tmp_path / "results" / "report.txt").read_text()
