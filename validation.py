"""Read and check the two CSV input files."""

# We do not stop at the first error: every problem is added to a list
# "issues" with the file name and line number, so the user can correct all
# of them at once. The header is line 1, so the first data row is line 2.
#
# CSV files (UTF-8, comma separated, one header row):
#   products.csv:          product_id,name,category,purchase_cost,selling_price,initial_stock
#   historical_sales.csv:  date,product_id,units_sold
# Money is in EUR with at most two decimals; dates are YYYY-MM-DD.

import csv
from datetime import date, timedelta

from common import Product, SaleRecord, euros_to_cents

PRODUCT_COLUMNS = ["product_id", "name", "category", "purchase_cost",
                   "selling_price", "initial_stock"]
SALES_COLUMNS = ["date", "product_id", "units_sold"]
MIN_HISTORY_DAYS = 30
MAX_LISTED_MISSING = 20  # so the report does not get thousands of lines


# Functions that read one field: they return the value or raise ValueError

def parse_non_negative_int(text: str) -> int:
    """Accept only digits, such as "0" or "42" (no sign, no decimals)."""
    text = text.strip()
    if not text.isdigit() or not text.isascii():  # isdigit() alone also accepts "²"
        raise ValueError("must be a non-negative integer")
    return int(text)


def parse_positive_money(text: str) -> int:
    """Read a positive amount in euros and return it in cents."""
    try:
        cents = euros_to_cents(text.strip())
    except ValueError:
        raise ValueError("must be a finite number with at most two decimals")
    if cents <= 0:
        raise ValueError("must be positive")
    return cents


def parse_iso_date(text: str) -> date:
    """Accept only YYYY-MM-DD and refuse impossible dates like 2026-02-30."""
    text = text.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ValueError("must be a date written as YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError("is not a valid calendar date")


# Reading the files

def read_rows(path, columns: list, issues: list) -> list:
    """Return a list of (line_number, row) for the data rows of a CSV file."""
    # Each row is a dictionary {column name: text}. If the file cannot be read
    # (not found, not UTF-8, broken quotes) or the header is wrong, we add an
    # issue and return what we could read.
    rows = []
    try:
        # "utf-8-sig" also reads files saved by Excel, which start with a BOM mark
        with open(path, newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file, strict=True)
            header = reader.fieldnames or []
            missing = [c for c in columns if c not in header]
            if missing:
                issues.append(f"{path.name}: header is missing column(s) {missing}; "
                              f"expected {columns}")
                return rows
            for row in reader:
                # reader.line_num is the line just read (the header is line 1)
                if None in row or None in row.values():
                    issues.append(f"{path.name}:{reader.line_num}: wrong number of fields")
                else:
                    rows.append((reader.line_num, row))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        issues.append(f"{path.name}: cannot read the file: {error}")
    return rows


def read_products(path, issues: list) -> tuple:
    """Read the catalogue. Wrong rows are reported and skipped."""
    # Returns (products, seen_ids): products is a dictionary {product_id: Product}
    # with the valid rows; seen_ids is the set of ALL ids in the file, also the
    # ones of wrong rows, so that their sales are not reported as "unknown" 90 times.
    products = {}
    seen_ids = set()
    for line, row in read_rows(path, PRODUCT_COLUMNS, issues):
        where = f"{path.name}:{line}"
        row_ok = True
        product_id = row["product_id"].strip()
        if product_id == "":
            issues.append(f"{where}: product_id is empty")
            row_ok = False
        elif product_id == "SHOP":  # "SHOP" is the label of the shop totals in the outputs
            issues.append(f"{where}: product_id 'SHOP' is reserved")
            row_ok = False
        elif product_id in seen_ids:
            issues.append(f"{where}: duplicate product_id {product_id!r}")
            row_ok = False
        for field in ["name", "category"]:
            if row[field].strip() == "":
                issues.append(f"{where}: {field} is empty")
                row_ok = False

        try:
            cost = parse_positive_money(row["purchase_cost"])
        except ValueError as error:
            issues.append(f"{where}: purchase_cost = {row['purchase_cost']!r} {error}")
            row_ok = False
        try:
            price = parse_positive_money(row["selling_price"])
        except ValueError as error:
            issues.append(f"{where}: selling_price = {row['selling_price']!r} {error}")
            row_ok = False
        try:
            stock = parse_non_negative_int(row["initial_stock"])
        except ValueError as error:
            issues.append(f"{where}: initial_stock = {row['initial_stock']!r} {error}")
            row_ok = False

        seen_ids.add(product_id)
        if row_ok:
            products[product_id] = Product(product_id, row["name"].strip(),
                                           row["category"].strip(), cost, price, stock)
    if len(products) == 0 and len(issues) == 0:
        issues.append(f"{path.name}: the catalogue contains no products")
    return products, seen_ids


def read_sales(path, known_ids: set, issues: list) -> list:
    """Read the sales; check the product ids and the duplicate (date, product) pairs."""
    sales = []
    seen_pairs = set()  # a set, because we only need to know "did we see it already?"
    for line, row in read_rows(path, SALES_COLUMNS, issues):
        where = f"{path.name}:{line}"
        row_ok = True
        day = None
        try:
            day = parse_iso_date(row["date"]).isoformat()
        except ValueError as error:
            issues.append(f"{where}: date = {row['date']!r} {error}")
            row_ok = False
        product_id = row["product_id"].strip()
        if product_id not in known_ids:
            issues.append(f"{where}: unknown product_id {product_id!r}")
            row_ok = False
        try:
            units = parse_non_negative_int(row["units_sold"])
        except ValueError as error:
            issues.append(f"{where}: units_sold = {row['units_sold']!r} {error}")
            row_ok = False
        if day is not None:
            if (day, product_id) in seen_pairs:
                issues.append(f"{where}: duplicate record for product {product_id} on {day}")
                row_ok = False
            seen_pairs.add((day, product_id))
        if row_ok:
            sales.append(SaleRecord(day, product_id, units))
    return sales


def check_completeness(sales: list, product_ids: set, issues: list) -> tuple:
    """Every product needs one row for every day of the same date window."""
    # The window goes from the first to the last date of the file and must be
    # at least MIN_HISTORY_DAYS long. Returns (first_date, last_date).
    if len(sales) == 0:
        issues.append("historical sales: no valid sales records")
        return None, None
    dates = sorted(set(s.sale_date for s in sales))
    first = date.fromisoformat(dates[0])
    last = date.fromisoformat(dates[-1])
    n_days = (last - first).days + 1
    if n_days < MIN_HISTORY_DAYS:
        issues.append(f"historical sales: window {first} to {last} has {n_days} days; "
                      f"at least {MIN_HISTORY_DAYS} consecutive days are required")

    present = set((s.sale_date, s.product_id) for s in sales)
    missing = []
    for product_id in sorted(product_ids):
        for i in range(n_days):
            day = (first + timedelta(days=i)).isoformat()
            if (day, product_id) not in present:
                missing.append((day, product_id))
    for day, product_id in missing[:MAX_LISTED_MISSING]:
        issues.append(f"historical sales: missing record for product {product_id} on {day} "
                      f"(zero sales must be written explicitly)")
    if len(missing) > MAX_LISTED_MISSING:
        issues.append(f"historical sales: ... and {len(missing) - MAX_LISTED_MISSING} "
                      f"more missing product-date pairs")
    return first.isoformat(), last.isoformat()


def validate_inputs(products_path, sales_path) -> dict:
    """Check both files. Returns a dictionary with what was read and the issues."""
    # The input is valid when result["issues"] is an empty list.
    issues = []
    products, seen_ids = read_products(products_path, issues)
    sales = read_sales(sales_path, seen_ids, issues)
    first_date, last_date = check_completeness(sales, seen_ids, issues)
    return {"products": products, "sales": sales, "issues": issues,
            "first_date": first_date, "last_date": last_date}


def write_validation_report(result: dict, report_path, products_path, sales_path,
                            extra_problems=None) -> None:
    """Write validation_report.txt (the file is replaced every time)."""
    # extra_problems are problems found after reading the files, for example
    # a storage capacity that is too small or a conflict with the database.
    problems = result["issues"]
    if extra_problems:
        problems = problems + extra_problems
    if problems:
        outcome = "INVALID - simulation blocked"
    else:
        outcome = "VALID - simulation allowed"
    lines = [
        "VALIDATION REPORT",
        f"Products file: {products_path}",
        f"Sales file:    {sales_path}",
        f"Valid products read: {len(result['products'])}",
        f"Valid sales records read: {len(result['sales'])}",
        f"History window: {result['first_date']} to {result['last_date']}",
        "",
        f"OUTCOME: {outcome}",
        "",
    ]
    if problems:
        lines.append(f"Problems found ({len(problems)}):")
        for problem in problems:
            lines.append(f"  - {problem}")
    else:
        lines.append("No problems found.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
