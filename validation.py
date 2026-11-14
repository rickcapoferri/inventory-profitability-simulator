"""Load and validate product and daily sales CSV files using the standard library."""

import csv
from datetime import date, timedelta
from math import isfinite
from pathlib import Path

PROJECT_DIRECTORY = Path(__file__).resolve().parent
PRODUCTS_PATH = PROJECT_DIRECTORY / "data" / "products.csv"
HISTORICAL_SALES_PATH = PROJECT_DIRECTORY / "data" / "historical_sales.csv"

PRODUCT_COLUMNS = (
    "product_id", "name", "category", "purchase_cost", "selling_price", "initial_stock"
)
SALES_COLUMNS = ("date", "product_id", "units_sold")


class CSVValidationError(ValueError):
    """Invalid CSV input; messages identify offending fields and CSV rows."""


def products_csv_validation(
    products_file: str | Path = PRODUCTS_PATH,
    sales_file: str | Path = HISTORICAL_SALES_PATH,
) -> tuple[list[dict], list[dict]]:
    """Return validated rows; paths may come from ``load_config()['files']``."""
    products = _read_csv(products_file, PRODUCT_COLUMNS, "products")
    sales = _read_csv(sales_file, SALES_COLUMNS, "historical_sales")
    errors: list[str] = []
    # Each call is written out so the validation order is easy to follow.
    try:
        product_identifiers_unique(products)
    except CSVValidationError as error:
        errors.append(str(error))
    try:
        costs_and_selling_prices_positive(products)
    except CSVValidationError as error:
        errors.append(str(error))
    try:
        stock_and_sales_quantities_non_negative(products, sales)
    except CSVValidationError as error:
        errors.append(str(error))
    try:
        dates_valid_iso(sales)
    except CSVValidationError as error:
        errors.append(str(error))
    try:
        sales_reference_existing_product(products, sales)
    except CSVValidationError as error:
        errors.append(str(error))
    try:
        product_date_pair_unique(sales)
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


def _row_numbers(invalid: set[int]) -> str:
    numbers = [str(index + 2) for index in sorted(invalid)]
    return ", ".join(numbers[:10]) + (", ..." if len(numbers) > 10 else "")


def _read_csv(path: str | Path, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, strict=True)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                raise CSVValidationError(f"{label}: duplicate column names.")
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
    for index, row in enumerate(rows):
        if None in row:
            raise CSVValidationError(f"{label}: extra fields at CSV rows {index + 2}.")
    for column in columns:
        blank = set()
        for index, row in enumerate(rows):
            if not (row.get(column) or "").strip():
                blank.add(index)
        if blank:
            raise CSVValidationError(
                f"{label}.{column}: missing values at CSV rows {_row_numbers(blank)}."
            )
    return rows


def product_identifiers_unique(products: list[dict]) -> None:
    seen: set[str] = set()
    duplicates: set[int] = set()
    for index, row in enumerate(products):
        identifier = row["product_id"]
        if identifier in seen:
            duplicates.add(index)
        seen.add(identifier)
    if duplicates:
        raise CSVValidationError(
            f"products.product_id: duplicate identifiers at CSV rows {_row_numbers(duplicates)}."
        )


def _validate_number(rows: list[dict], column: str, label: str, integer: bool) -> None:
    invalid: set[int] = set()
    for index, row in enumerate(rows):
        try:
            if integer:
                # Validate using the same conversion used for the returned rows.
                value = int(row[column])
                valid = value >= 0
            else:
                value = float(row[column])
                valid = isfinite(value) and value > 0
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            invalid.add(index)
    if invalid:
        requirement = "finite non-negative integers" if integer else "finite positive numbers"
        raise CSVValidationError(
            f"{label}.{column}: expected {requirement} at CSV rows {_row_numbers(invalid)}."
        )


def costs_and_selling_prices_positive(products: list[dict]) -> None:
    for column in ("purchase_cost", "selling_price"):
        _validate_number(products, column, "products", integer=False)


def stock_and_sales_quantities_non_negative(
    products: list[dict], sales: list[dict]
) -> None:
    _validate_number(products, "initial_stock", "products", integer=True)
    _validate_number(sales, "units_sold", "historical_sales", integer=True)


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def dates_valid_iso(sales: list[dict]) -> None:
    invalid = {i for i, row in enumerate(sales) if not _is_iso_date(row["date"])}
    if invalid:
        raise CSVValidationError(
            "historical_sales.date: expected valid YYYY-MM-DD dates at CSV rows "
            f"{_row_numbers(invalid)}."
        )


def sales_reference_existing_product(products: list[dict], sales: list[dict]) -> None:
    product_ids = {row["product_id"] for row in products}
    invalid = {i for i, row in enumerate(sales) if row["product_id"] not in product_ids}
    if invalid:
        unknown = set()
        for index in invalid:
            unknown.add(sales[index]["product_id"])
        raise CSVValidationError(
            f"historical_sales.product_id: unknown products ({', '.join(sorted(unknown))}) at CSV rows "
            f"{_row_numbers(invalid)}."
        )


def product_date_pair_unique(sales: list[dict]) -> None:
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
            f"{_row_numbers(duplicates)}."
        )


def sales_history_complete(products: list[dict], sales: list[dict]) -> None:
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
            missing_day = first_day
            for day in sorted(present):
                if day != missing_day:
                    break
                missing_day += timedelta(days=1)
            details.append(f"{product['product_id']}: missing {missing_day.isoformat()}")
    if details:
        raise CSVValidationError(
            "historical_sales: incomplete history; explicit rows (including zero sales) "
            f"are required for every product on every day from {first_day} to {last_day}. "
            + "; ".join(details[:10])
        )
