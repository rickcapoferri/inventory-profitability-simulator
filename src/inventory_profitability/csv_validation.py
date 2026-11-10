"""Load and validate product and daily sales CSV files using the standard library."""

import csv
from datetime import date, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

PROJECT_DIRECTORY = Path(__file__).resolve().parents[2]
PRODUCTS_PATH = PROJECT_DIRECTORY / "data" / "products.csv"
HISTORICAL_SALES_PATH = PROJECT_DIRECTORY / "data" / "historical_sales.csv"

PRODUCT_COLUMNS = (
    "product_id", "name", "category", "purchase_cost", "selling_price", "initial_stock"
)
SALES_COLUMNS = ("date", "product_id", "units_sold")
ProductRow = dict[str, Any]
SalesRow = dict[str, Any]


class CSVValidationError(ValueError):
    """Invalid CSV input; messages identify offending fields and CSV rows."""


def products_csv_validation(
    products_file: str | Path = PRODUCTS_PATH,
    sales_file: str | Path = HISTORICAL_SALES_PATH,
) -> tuple[list[ProductRow], list[SalesRow]]:
    """Return validated rows; paths may come from ``load_config()['files']``."""
    products = _read_csv(products_file, PRODUCT_COLUMNS, "products")
    sales = _read_csv(sales_file, SALES_COLUMNS, "historical_sales")
    errors: list[str] = []
    checks = (
        lambda: product_identifiers_unique(products),
        lambda: costs_and_selling_prices_positive(products),
        lambda: stock_and_sales_quantities_non_negative(products, sales),
        lambda: dates_valid_iso(products, sales),
        lambda: sales_reference_existing_product(products, sales),
        lambda: product_date_pair_unique(products, sales),
    )
    for check in checks:
        try:
            check()
        except CSVValidationError as error:
            errors.append(str(error))
    if not errors:
        try:
            sales_history_complete(products, sales)
        except CSVValidationError as error:
            errors.append(str(error))
    if errors:
        raise CSVValidationError("CSV validation failed:\n- " + "\n- ".join(errors))

    for row in products:
        row["purchase_cost"] = float(row["purchase_cost"])
        row["selling_price"] = float(row["selling_price"])
        row["initial_stock"] = int(row["initial_stock"])
    for row in sales:
        row["units_sold"] = int(row["units_sold"])
    return products, sales


def _row_numbers(rows: list[dict[str, Any]], invalid: set[int]) -> str:
    numbers = [str(index + 2) for index in sorted(invalid)]
    return ", ".join(numbers[:10]) + (", ..." if len(numbers) > 10 else "")


def _read_csv(path: str | Path, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            headers = reader.fieldnames or []
            missing = set(columns) - set(headers)
            if missing:
                raise CSVValidationError(f"{label}: missing columns: {', '.join(sorted(missing))}")
            rows = list(reader)
    except CSVValidationError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise CSVValidationError(f"Cannot read {label} CSV {path}: {error}") from error
    if not rows:
        raise CSVValidationError(f"{label}: CSV must contain at least one data row.")
    for column in columns:
        blank = {i for i, row in enumerate(rows) if not (row.get(column) or "").strip()}
        if blank:
            raise CSVValidationError(
                f"{label}.{column}: missing values at CSV rows {_row_numbers(rows, blank)}."
            )
    return rows


def product_identifiers_unique(products: list[ProductRow]) -> None:
    seen: set[str] = set()
    duplicates: set[int] = set()
    for index, row in enumerate(products):
        identifier = row["product_id"]
        if identifier in seen:
            duplicates.add(index)
        seen.add(identifier)
    if duplicates:
        raise CSVValidationError(
            f"products.product_id: duplicate identifiers at CSV rows {_row_numbers(products, duplicates)}."
        )


def _validate_number(rows: list[dict[str, Any]], column: str, label: str, integer: bool) -> None:
    invalid: set[int] = set()
    for index, row in enumerate(rows):
        try:
            value = float(row[column])
            valid = isfinite(value) and (value >= 0 if integer else value > 0)
            if integer:
                valid = valid and value.is_integer()
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            invalid.add(index)
    if invalid:
        requirement = "finite non-negative integers" if integer else "finite positive numbers"
        raise CSVValidationError(
            f"{label}.{column}: expected {requirement} at CSV rows {_row_numbers(rows, invalid)}."
        )


def costs_and_selling_prices_positive(products: list[ProductRow]) -> None:
    for column in ("purchase_cost", "selling_price"):
        _validate_number(products, column, "products", integer=False)


def stock_and_sales_quantities_non_negative(
    products: list[ProductRow], sales: list[SalesRow]
) -> None:
    _validate_number(products, "initial_stock", "products", integer=True)
    _validate_number(sales, "units_sold", "historical_sales", integer=True)


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def dates_valid_iso(products: list[ProductRow], sales: list[SalesRow]) -> None:
    invalid = {i for i, row in enumerate(sales) if not _is_iso_date(row["date"])}
    if invalid:
        raise CSVValidationError(
            "historical_sales.date: expected valid YYYY-MM-DD dates at CSV rows "
            f"{_row_numbers(sales, invalid)}."
        )


def sales_reference_existing_product(products: list[ProductRow], sales: list[SalesRow]) -> None:
    product_ids = {row["product_id"] for row in products}
    invalid = {i for i, row in enumerate(sales) if row["product_id"] not in product_ids}
    if invalid:
        unknown = ", ".join(dict.fromkeys(sales[i]["product_id"] for i in sorted(invalid)))
        raise CSVValidationError(
            f"historical_sales.product_id: unknown products ({unknown}) at CSV rows "
            f"{_row_numbers(sales, invalid)}."
        )


def product_date_pair_unique(products: list[ProductRow], sales: list[SalesRow]) -> None:
    seen: set[tuple[str, str]] = set()
    duplicates: set[int] = set()
    for index, row in enumerate(sales):
        pair = (row["product_id"], row["date"])
        if pair in seen:
            duplicates.add(index)
        seen.add(pair)
    if duplicates:
        raise CSVValidationError(
            "historical_sales: duplicate product-date pairs at CSV rows "
            f"{_row_numbers(sales, duplicates)}."
        )


def sales_history_complete(products: list[ProductRow], sales: list[SalesRow]) -> None:
    dates = [date.fromisoformat(row["date"]) for row in sales]
    first_day, last_day = min(dates), max(dates)
    days = (last_day - first_day).days + 1
    if days < 30:
        raise CSVValidationError(
            f"historical_sales: at least 30 consecutive days are required; found {days}."
        )
    dates_by_product: dict[str, set[date]] = {}
    for row in sales:
        dates_by_product.setdefault(row["product_id"], set()).add(date.fromisoformat(row["date"]))
    details = []
    for product in products:
        present = dates_by_product.get(product["product_id"], set())
        if len(present) != days:
            missing = next(
                (first_day + timedelta(days=offset) for offset in range(days)
                 if first_day + timedelta(days=offset) not in present),
                None,
            )
            details.append(f"{product['product_id']}: missing {missing.isoformat() if missing else 'day'}")
    if details:
        raise CSVValidationError(
            "historical_sales: incomplete history; explicit rows (including zero sales) "
            f"are required for every product on every day from {first_day} to {last_day}. "
            + "; ".join(details[:10])
        )
