import csv
import sqlite3
from pathlib import Path

import pytest

from inventory_profitability.csv_validation import products_csv_validation
from inventory_profitability.database import (
    best_selling_products,
    historical_revenue_by_category,
    historical_sales_by_product,
    import_historical_data,
)

ROOT = Path(__file__).resolve().parents[1]


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
