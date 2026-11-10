import csv
from datetime import date, timedelta
from pathlib import Path

import pytest

from inventory_profitability.csv_validation import (
    CSVValidationError,
    products_csv_validation,
)

ROOT = Path(__file__).resolve().parents[1]


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def write_rows(path, rows, columns=None):
    columns = columns or list(rows[0]) if rows else columns
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def inputs(tmp_path):
    return (
        read_rows(ROOT / "data/products.csv"),
        read_rows(ROOT / "data/historical_sales.csv"),
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
    products = ROOT / "data/products.csv"
    sales = ROOT / "data/historical_sales.csv"
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
    products, sales = inputs(tmp_path)
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
    products, sales = inputs(tmp_path)
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
