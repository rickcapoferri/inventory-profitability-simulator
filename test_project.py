"""Tests for configuration, CSV validation, SQLite, demand, policies, and CLI."""

import csv
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
)
from simulation import FixedQuantityPolicy, OrderUpToPolicy, generate_demand
from main import main

ROOT = Path(__file__).resolve().parent


# config


def test_load_core_config() -> None:
    config_path = ROOT / "config.toml"

    config = load_config(config_path)

    assert config["simulation"]["days"] == 60
    assert config["simulation"]["seed"] == 2026
    assert config["simulation"]["currency"] == "EUR"


def test_rejects_zero_simulation_days() -> None:
    config_path = ROOT / "invalid_config.toml"

    with pytest.raises(
        ConfigurationError,
        match="simulation.days must be a positive integer",
    ):
        load_config(config_path)


def test_rejects_promotion_ending_after_simulation() -> None:
    config = load_config(ROOT / "promotion.toml")
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
        read_rows(ROOT / "products.csv"),
        read_rows(ROOT / "historical_sales.csv"),
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
    products = ROOT / "products.csv"
    sales = ROOT / "historical_sales.csv"
    invalid = ROOT / filename
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
        ROOT / "products.csv",
        ROOT / "historical_sales.csv",
    )


def test_imports_data_and_matches_expected_product_summary(tmp_path):
    database = tmp_path / "nested" / "inventory.sqlite"
    products, sales = load_sample_data()

    import_historical_data(database, products, sales)
    actual = historical_sales_by_product(database)

    with (ROOT / "expected_historical_by_product.csv").open(
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
products = "{(ROOT / "products.csv").as_posix()}"
historical_sales = "{(ROOT / "historical_sales.csv").as_posix()}"
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
    assert database_path.is_file()


def test_cli_reports_invalid_config_without_traceback(tmp_path, capsys):
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("[simulation]\ndays = 0\n", encoding="utf-8")

    exit_code = main([str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err


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
    with (ROOT / "products.csv").open(newline="", encoding="utf-8") as file:
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
        products_csv_validation(path, ROOT / "historical_sales.csv")
