"""Load and validate the product catalogue and complete daily sales history."""

from datetime import date
from math import isfinite
from pathlib import Path

import pandas as pd


project_directory = Path(__file__).resolve().parents[2]
products_path = project_directory / "data" / "products.csv"
historical_sales_path = project_directory / "data" / "historical_sales.csv"

PRODUCT_COLUMNS = (
    "product_id", "name", "category", "purchase_cost", "selling_price", "initial_stock"
)
SALES_COLUMNS = ("date", "product_id", "units_sold")


class CSVValidationError(ValueError):
    """Invalid CSV input; messages identify offending fields and CSV rows."""


def products_csv_validation(
    products_file: str | Path = products_path,
    sales_file: str | Path = historical_sales_path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return validated data or raise a report, without writing to the database.
    Pass the resolved paths from load_config()['files'] to use configured inputs.
    """
    products = _read_csv(products_file, PRODUCT_COLUMNS, "products")
    sales = _read_csv(sales_file, SALES_COLUMNS, "historical_sales")
    errors = []
    try:
        product_identifiers_unique(products["product_id"])
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
        dates_valid_iso(products, sales)
    except CSVValidationError as error:
        errors.append(str(error))

    try:
        sales_reference_existing_product(products, sales)
    except CSVValidationError as error:
        errors.append(str(error))

    try:
        product_date_pair_unique(products, sales)
    except CSVValidationError as error:
        errors.append(str(error))

    # Completeness depends on valid identifiers, dates, and unique pairs.
    if not errors:
        try:
            sales_history_complete(products, sales)
        except CSVValidationError as error:
            errors.append(str(error))
    if errors:
        raise CSVValidationError("CSV validation failed:\n- " + "\n- ".join(errors))
    for column in ("purchase_cost", "selling_price", "initial_stock"):
        products[column] = pd.to_numeric(products[column], errors="raise")
    sales["units_sold"] = pd.to_numeric(sales["units_sold"], errors="raise")
    return products, sales


def _row_numbers(mask: pd.Series) -> str:
    """The header is CSV row 1; cap long reports at ten row numbers."""
    rows = [str(index + 2) for index, invalid in enumerate(mask) if invalid]
    return ", ".join(rows[:10]) + (", ..." if len(rows) > 10 else "")


def _read_csv(path: str | Path, columns: tuple[str, ...], label: str) -> pd.DataFrame:
    try:
        # Preserve identifiers such as 001 and text such as the category 'NA'.
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise CSVValidationError(f"Cannot read {label} CSV {path}: {error}") from error
    missing = set(columns) - set(frame.columns)
    if missing:
        raise CSVValidationError(f"{label}: missing columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise CSVValidationError(f"{label}: CSV must contain at least one data row.")
    for column in columns:
        blank = frame[column].isna() | frame[column].str.strip().eq("")
        if blank.any():
            raise CSVValidationError(
                f"{label}.{column}: missing values at CSV rows {_row_numbers(blank)}."
            )
    return frame


def product_identifiers_unique(products: pd.Series) -> None:
    duplicates = products.duplicated(keep=False)
    if duplicates.any():
        raise CSVValidationError(
            f"products.product_id: duplicate identifiers at CSV rows {_row_numbers(duplicates)}."
        )


def _validate_number(frame: pd.DataFrame, column: str, label: str, integer: bool) -> None:
    values = pd.to_numeric(frame[column], errors="coerce")
    invalid = ~values.map(isfinite)
    if integer:
        invalid |= values.lt(0) | values.mod(1).ne(0)
        requirement = "finite non-negative integers"
    else:
        invalid |= values.le(0)
        requirement = "finite positive numbers"
    if invalid.any():
        raise CSVValidationError(
            f"{label}.{column}: expected {requirement} at CSV rows {_row_numbers(invalid)}."
        )


def costs_and_selling_prices_positive(products: pd.DataFrame) -> None:
    for column in ("purchase_cost", "selling_price"):
        _validate_number(products, column, "products", integer=False)


def stock_and_sales_quantities_non_negative(products: pd.DataFrame, sales: pd.DataFrame) -> None:
    _validate_number(products, "initial_stock", "products", integer=True)
    _validate_number(sales, "units_sold", "historical_sales", integer=True)


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def dates_valid_iso(products: pd.DataFrame, sales: pd.DataFrame) -> None:
    invalid = ~sales["date"].map(_is_iso_date)
    if invalid.any():
        raise CSVValidationError(
            f"historical_sales.date: expected valid YYYY-MM-DD dates at CSV rows {_row_numbers(invalid)}."
        )


def sales_reference_existing_product(products: pd.DataFrame, sales: pd.DataFrame) -> None:
    invalid = ~sales["product_id"].isin(products["product_id"])
    if invalid.any():
        unknown = ", ".join(sales.loc[invalid, "product_id"].unique()[:10])
        raise CSVValidationError(
            f"historical_sales.product_id: unknown products ({unknown}) at CSV rows {_row_numbers(invalid)}."
        )


def product_date_pair_unique(products: pd.DataFrame, sales: pd.DataFrame) -> None:
    duplicates = sales.duplicated(["product_id", "date"], keep=False)
    if duplicates.any():
        raise CSVValidationError(
            f"historical_sales: duplicate product-date pairs at CSV rows {_row_numbers(duplicates)}."
        )


def sales_history_complete(products: pd.DataFrame, sales: pd.DataFrame) -> None:
    dates = sales["date"].map(date.fromisoformat)
    first_day, last_day = dates.min(), dates.max()
    days = (last_day - first_day).days + 1
    if days < 30:
        raise CSVValidationError(
            f"historical_sales: at least 30 consecutive days are required; found {days}."
        )
    counts = sales.groupby("product_id").size()
    incomplete = products["product_id"].map(counts).fillna(0).ne(days)
    if incomplete.any():
        details = []
        for product_id in products.loc[incomplete, "product_id"].head(10):
            present = set(dates[sales["product_id"].eq(product_id)])
            # Find a missing date without constructing a potentially huge date grid.
            next_ordinal = first_day.toordinal()
            for day in sorted(present):
                if day.toordinal() != next_ordinal:
                    break
                next_ordinal += 1
            missing_day = date.fromordinal(next_ordinal)
            details.append(f"{product_id}: missing {missing_day.isoformat()}")
        raise CSVValidationError(
            "historical_sales: incomplete history; explicit rows (including zero sales) "
            "are required for every product on every day from "
            f"{first_day} to {last_day}. " + "; ".join(details)
        )
