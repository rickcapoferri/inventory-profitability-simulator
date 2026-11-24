"""Things used by every module: our exceptions, the records, money in cents."""

import math
from collections import namedtuple


# Exceptions

# main() in main.py catches these errors and prints a clear message;
# any other error is a bug and still shows the full traceback.


class InventoryError(Exception):
    """Base class for the errors of this program."""


class ConfigError(InventoryError):
    """The TOML configuration (or a policy parameter) is wrong."""


class DataNotLoadedError(InventoryError):
    """The database does not contain the data needed by a command."""


class InputValidationError(InventoryError):
    """The CSV files are invalid: the simulation must not run."""

    def __init__(self, issues: list) -> None:
        super().__init__(f"input validation failed with {len(issues)} problem(s)")
        self.issues: list = issues


class ImportConflictError(InventoryError):
    """The CSV files contradict what is already stored in the database."""

    def __init__(self, conflicts: list) -> None:
        super().__init__(f"import rejected: {len(conflicts)} conflict(s)")
        self.conflicts: list = conflicts


# Records read from the CSV files

# Like a tuple it cannot be changed (a price cannot be modified by mistake),
# but we read the fields by name: product.selling_price_cents, not product[4].

# one row of products.csv (money in integer cents)
Product = namedtuple("Product", ["product_id", "name", "category", "purchase_cost_cents",
                                 "selling_price_cents", "initial_stock"])

# one row of historical_sales.csv
SaleRecord = namedtuple("SaleRecord", ["sale_date", "product_id", "units_sold"])


# Money: stored as integer cents (2.50 EUR -> 250) so that sums are exact

# with floats 0.1 + 0.2 == 0.3 is False; with integer cents 10 + 20 == 30 is True


def euros_to_cents(value) -> int:
    """Convert euros (a number or a text like "2.50") to integer cents."""
    if type(value) == bool:  # in Python True == 1, so we refuse it explicitly
        raise ValueError("is not a number")
    amount: float = float(value)  # raises ValueError for a text like "abc"
    if not math.isfinite(amount):  # float("inf") and float("nan") do not fail
        raise ValueError("is not a finite number")
    cents: int = round(amount * 100)
    if not math.isclose(amount * 100, cents, abs_tol=0.000001):
        raise ValueError("has more than two decimals")
    return cents


def cents_to_euros(cents) -> str:
    """Format cents as euros with two decimals: 1234 -> "12.34"."""
    return f"{cents / 100:.2f}"
