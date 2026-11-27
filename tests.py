"""All the automated tests: python tests.py"""

# Each test is a small function with plain assert statements, like the test
# cells of the course notebooks. The functions are called at the end of each
# section; if an assert fails the program stops and shows which one.

import sys

sys.dont_write_bytecode = True   # no __pycache__ folder (see main.py)

import contextlib
import csv
import io
import math
import shutil
import sqlite3
import tomllib
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import database as db
from common import (ConfigError, ImportConflictError, Product, SaleRecord,
                    cents_to_euros, euros_to_cents)
from config import check_config, load_config
from demand import estimate_means, generate_demand, history_matrix
from main import main
from policies import FixedQuantityPolicy, OrderUpToPolicy, ReplenishmentPolicy
from reporting import best_run, seed_check_summary, seed_winners
from simulation import compute_metrics, daily_rows, run_simulation
from storage import allocate, product_id_order, unit_margin_order
from validation import (parse_iso_date, parse_non_negative_int, parse_positive_money,
                        validate_inputs)
from workflow import run_seed_check

FOLDER = Path(__file__).resolve().parent   # the project folder
DATA = FOLDER / "data"                      # input files

# costs used in the examples calculated by hand (cents)
HOLDING = 10   # 0.10 EUR per unit per day
ORDER = 100    # 1.00 EUR per order


# Helpers

def must_raise(exctype, f, *args):
    # the same helper we used in the course exercises (multiset, L08)
    got_exc = None
    try:
        f(*args)
    except exctype as exc:
        got_exc = exc
    except Exception as exc:
        raise Exception(f"was expecting a {exctype.__name__}, got a {type(exc).__name__} instead") from exc
    if got_exc is None:
        raise Exception(f"No exception raised, was expecting a {exctype.__name__}")
    return got_exc


def make_product(product_id: str = "A", cost: int = 100, price: int = 200, stock: int = 5) -> Product:
    """A product for the tests (money in cents)."""
    return Product(product_id, "Product " + product_id, "Test", cost, price, stock)


def copy_project(folder) -> Path:
    """Copy storage.toml and the data folder into a temporary folder."""
    # so the tests run the real program without touching our database and outputs
    root = Path(folder)
    shutil.copy(FOLDER / "storage.toml", root / "storage.toml")
    shutil.copytree(DATA, root / "data")
    return root


def run_cli(*arguments) -> tuple:
    """Run the program like from the terminal; return (exit code, printed text)."""
    # the printed text is collected in a string instead of going to the screen
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = main(list(arguments))
    return code, output.getvalue()


def write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# Configuration (config.py)

STORAGE_TOML = FOLDER / "storage.toml"


def storage_toml() -> dict:
    """A new copy of storage.toml as a dictionary."""
    with open(STORAGE_TOML, "rb") as file:
        return tomllib.load(file)


def config_error(data: dict) -> str:
    """check_config must raise ConfigError; return its message."""
    error = must_raise(ConfigError, check_config, data, STORAGE_TOML)
    return str(error)


def test_valid_storage_config():
    config = load_config(STORAGE_TOML)
    # "data/products.csv" is relative to the folder of the TOML file, not to where we run
    assert config["products"] == DATA / "products.csv"
    assert config["holding_cost"] == 2      # 0.02 EUR = 2 cents
    assert config["order_cost"] == 100
    assert config["capacity"] == 300
    assert config["days"] == 60


def test_core_config_has_no_capacity():
    data = storage_toml()
    data["extension"]["selected"] = ""           # core only
    config = check_config(data, STORAGE_TOML)
    assert config["extension"] == ""
    assert config["capacity"] is None


def test_sample_invalid_config():
    error = must_raise(ConfigError, load_config, DATA / "invalid_config.toml")
    assert "days must be >= 1" in str(error)


def test_missing_file():
    must_raise(ConfigError, load_config, FOLDER / "does_not_exist.toml")


def test_wrong_types():
    data = storage_toml()
    data["simulation"]["days"] = "60"
    assert "days must be an integer" in config_error(data)

    data = storage_toml()
    data["simulation"]["seed"] = True
    assert "seed must be an integer" in config_error(data)


def test_policy_parameters():
    data = storage_toml()
    data["policies"]["order_up_to"]["target"] = 10   # the threshold is 20
    assert "target (10) must be >= threshold (20)" in config_error(data)

    data = storage_toml()
    data["policies"]["fixed_quantity"]["quantity"] = 0
    assert "quantity must be >= 1" in config_error(data)

    data = storage_toml()
    data["policies"]["fixed_quantity"]["threshold"] = -1
    assert "threshold must be >= 0" in config_error(data)


def test_target_equal_to_threshold_is_allowed():
    data = storage_toml()
    data["policies"]["order_up_to"]["target"] = 20
    config = check_config(data, STORAGE_TOML)
    assert config["out_target"] == 20


def test_costs():
    data = storage_toml()
    data["costs"]["holding_per_unit_per_day"] = -0.02
    assert "must not be negative" in config_error(data)

    data = storage_toml()
    data["costs"]["holding_per_unit_per_day"] = 0.005
    assert "more than two decimals" in config_error(data)


def test_missing_table_and_other_extension():
    data = storage_toml()
    del data["costs"]
    assert "missing table [costs]" in config_error(data)

    data = storage_toml()
    data["extension"]["selected"] = "promotion"   # we only implement storage
    assert "selected must be one of" in config_error(data)


def test_unknown_keys():
    data = storage_toml()
    data["simulation"]["dasy"] = 90               # typo of "days"
    assert "[simulation] unknown key 'dasy'" in config_error(data)

    data = storage_toml()
    data["policies"]["fixed_quantity"]["qty"] = 5
    assert "[policies.fixed_quantity] unknown key 'qty'" in config_error(data)

    data = storage_toml()
    data["other"] = {"x": 1}
    assert "unknown table [other]" in config_error(data)


def test_storage_settings():
    data = storage_toml()
    data["storage"]["capacity_units"] = 0
    assert "capacity_units must be >= 1" in config_error(data)

    data = storage_toml()
    data["storage"]["allocation_rules"] = ["product_id_ascending", "random"]
    assert "allocation_rules may only contain" in config_error(data)

    data = storage_toml()
    data["storage"]["allocation_rules"] = ["product_id_ascending"]
    assert "at least two" in config_error(data)


def test_database_and_output_paths_of_the_wrong_kind():
    data = storage_toml()
    data["files"]["database"] = "data"               # a folder
    assert "database is a folder" in config_error(data)

    data = storage_toml()
    data["files"]["output_directory"] = "data/products.csv"  # a file
    assert "output_directory is a file" in config_error(data)


def test_seed_check_setting():
    data = storage_toml()
    data["simulation"]["seeds_to_check"] = 0
    assert "seeds_to_check must be >= 1" in config_error(data)

    data = storage_toml()
    del data["simulation"]["seeds_to_check"]
    assert "[simulation] missing key 'seeds_to_check'" in config_error(data)

    config = load_config(STORAGE_TOML)
    assert config["seeds_to_check"] == 20


def test_all_problems_are_reported_together():
    data = storage_toml()
    data["simulation"]["days"] = 0
    data["costs"]["fixed_per_product_order"] = "one"
    message = config_error(data)
    assert "days must be >= 1" in message
    assert "fixed_per_product_order must be a number" in message


test_valid_storage_config()
test_core_config_has_no_capacity()
test_sample_invalid_config()
test_missing_file()
test_wrong_types()
test_policy_parameters()
test_target_equal_to_threshold_is_allowed()
test_costs()
test_missing_table_and_other_extension()
test_unknown_keys()
test_storage_settings()
test_database_and_output_paths_of_the_wrong_kind()
test_seed_check_setting()
test_all_problems_are_reported_together()
print("config tests passed")


# CSV validation (validation.py)

PRODUCTS_CSV = DATA / "products.csv"
SALES_CSV = DATA / "historical_sales.csv"
PRODUCT_HEADER = "product_id,name,category,purchase_cost,selling_price,initial_stock\n"


def sales_file(folder: Path, days: int) -> Path:
    """Sales of product A for 'days' consecutive days from 2026-01-01, all zero."""
    lines: list = ["date,product_id,units_sold"]
    for day in range(1, days + 1):
        if day <= 31:
            lines.append(f"2026-01-{day:02d},A,0")
        else:
            lines.append(f"2026-02-{day - 31:02d},A,0")
    return write_text(folder / "sales.csv", "\n".join(lines) + "\n")


def products_file(folder: Path, rows: str) -> Path:
    return write_text(folder / "products.csv", PRODUCT_HEADER + rows)


# single fields

def test_integers():
    assert parse_non_negative_int(" 7 ") == 7
    assert parse_non_negative_int("0") == 0
    for wrong in ["-1", "3.0", "", "abc", "+2"]:
        must_raise(ValueError, parse_non_negative_int, wrong)


def test_money():
    assert parse_positive_money("2.50") == 250
    assert parse_positive_money("1.2") == 120
    for wrong in ["0.00", "-1", "1.234", "x", "inf", "nan"]:
        must_raise(ValueError, parse_positive_money, wrong)
    must_raise(ValueError, euros_to_cents, True)


def test_dates():
    assert parse_iso_date("2026-01-31").day == 31
    for wrong in ["2026-02-30", "01/02/2026", "20260101", "2026-1-01"]:
        must_raise(ValueError, parse_iso_date, wrong)


# the files given by the teacher (data/validation_README.txt)

def test_valid_files():
    result = validate_inputs(PRODUCTS_CSV, SALES_CSV)
    assert result["issues"] == []
    assert len(result["products"]) == 8
    assert len(result["sales"]) == 720
    assert result["first_date"] == "2026-01-01"
    assert result["last_date"] == "2026-03-31"


def test_negative_quantity():
    issues = validate_inputs(PRODUCTS_CSV, DATA / "sales_negative_quantity.csv")["issues"]
    assert ("sales_negative_quantity.csv:2: units_sold = '-1' must be a "
            "non-negative integer") in issues


def test_missing_day():
    issues = validate_inputs(PRODUCTS_CSV, DATA / "sales_missing_day.csv")["issues"]
    assert issues == ["historical sales: missing record for product P001 on "
                      "2026-01-01 (zero sales must be written explicitly)"]


def test_duplicate_pair():
    issues = validate_inputs(PRODUCTS_CSV, DATA / "sales_duplicate_pair.csv")["issues"]
    assert issues == ["sales_duplicate_pair.csv:722: duplicate record for "
                      "product P001 on 2026-01-01"]


def test_unknown_product():
    issues = validate_inputs(PRODUCTS_CSV, DATA / "sales_unknown_product.csv")["issues"]
    assert "sales_unknown_product.csv:2: unknown product_id 'P999'" in issues


def test_zero_cost():
    issues = validate_inputs(DATA / "products_zero_cost.csv", SALES_CSV)["issues"]
    assert issues == ["products_zero_cost.csv:2: purchase_cost = '0.00' must be positive"]


# small files written by the test itself

def test_30_days_of_zero_sales_is_valid():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        result = validate_inputs(products_file(folder, "A,Thing,Cat,1.00,2.00,0\n"),
                                 sales_file(folder, 30))
        assert result["issues"] == []


def test_29_days_is_too_short():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        result = validate_inputs(products_file(folder, "A,Thing,Cat,1.00,2.00,0\n"),
                                 sales_file(folder, 29))
        assert "at least 30 consecutive days" in result["issues"][0]


def test_duplicate_product():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        products = products_file(folder, "A,Thing,Cat,1.00,2.00,0\nA,Other,Cat,1.00,2.00,0\n")
        issues = validate_inputs(products, sales_file(folder, 30))["issues"]
        assert "products.csv:3: duplicate product_id 'A'" in issues


def test_missing_column():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        products = write_text(folder / "p.csv", "product_id,name\nA,Thing\n")
        issues = validate_inputs(products, sales_file(folder, 30))["issues"]
        assert "header is missing column(s)" in issues[0]


def test_infinite_price_is_an_issue_not_a_crash():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        products = products_file(folder, "A,Thing,Cat,inf,2.00,0\n")
        issues = validate_inputs(products, sales_file(folder, 30))["issues"]
        assert ("products.csv:2: purchase_cost = 'inf' must be a finite number "
                "with at most two decimals") in issues


def test_shop_is_reserved():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        products = products_file(folder, "SHOP,Thing,Cat,1.00,2.00,0\n")
        issues = validate_inputs(products, sales_file(folder, 30))["issues"]
        assert "products.csv:2: product_id 'SHOP' is reserved" in issues


def test_file_saved_by_excel_with_bom():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        products = folder / "excel.csv"
        bom = b"\xef\xbb\xbf"   # the 3 bytes Excel puts at the start of a UTF-8 file
        products.write_bytes(bom + (PRODUCT_HEADER + "A,Thing,Cat,1.00,2.00,0\n").encode())
        result = validate_inputs(products, sales_file(folder, 30))
        assert result["issues"] == []


def test_file_that_is_not_utf8():
    with TemporaryDirectory() as folder:
        folder = Path(folder)
        products = folder / "latin1.csv"
        products.write_bytes(PRODUCT_HEADER.encode() + "A,Caffè,Cat,1.00,2.00,0\n".encode("latin-1"))
        issues = validate_inputs(products, sales_file(folder, 30))["issues"]
        assert "cannot read the file" in issues[0]


test_integers()
test_money()
test_dates()
test_valid_files()
test_negative_quantity()
test_missing_day()
test_duplicate_pair()
test_unknown_product()
test_zero_cost()
test_30_days_of_zero_sales_is_valid()
test_29_days_is_too_short()
test_duplicate_product()
test_missing_column()
test_infinite_price_is_an_issue_not_a_crash()
test_shop_is_reserved()
test_file_saved_by_excel_with_bom()
test_file_that_is_not_utf8()
print("validation tests passed")


# Database and SQL summaries (database.py)

# the valid sample files, read once for all the tests
SAMPLE = validate_inputs(DATA / "products.csv", DATA / "historical_sales.csv")
SAMPLE_PRODUCTS = SAMPLE["products"]
SAMPLE_SALES = SAMPLE["sales"]


def count_rows(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def execute_sql(conn, sql: str) -> None:
    with conn:
        conn.execute(sql)


def test_importing_twice_does_not_duplicate():
    with TemporaryDirectory() as folder:
        with closing(db.open_database(Path(folder) / "test.sqlite")) as conn:
            first = db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            total = conn.execute("SELECT SUM(units_sold) FROM historical_sales").fetchone()[0]
            second = db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            assert first["sales_inserted"] == 720
            assert second["sales_inserted"] == 0
            assert second["sales_unchanged"] == 720
            assert count_rows(conn, "historical_sales") == 720
            assert count_rows(conn, "products") == 8
            new_total = conn.execute("SELECT SUM(units_sold) FROM historical_sales").fetchone()[0]
            assert new_total == total


def test_conflict_cancels_the_whole_import():
    changed: list = list(SAMPLE_SALES)
    first = changed[0]
    changed[0] = SaleRecord(first.sale_date, first.product_id, first.units_sold + 1)
    changed.append(SaleRecord("2026-04-01", "P001", 3))  # a new row: it must not stay
    with TemporaryDirectory() as folder:
        with closing(db.open_database(Path(folder) / "test.sqlite")) as conn:
            db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            must_raise(ImportConflictError, db.import_data, conn, SAMPLE_PRODUCTS, changed)
            assert count_rows(conn, "historical_sales") == 720


def test_old_data_not_in_the_files_is_a_conflict():
    # import 90 days, then a file with only the first 60 days
    first_60_days = [s for s in SAMPLE_SALES if s.sale_date < "2026-03-02"]
    with TemporaryDirectory() as folder:
        with closing(db.open_database(Path(folder) / "test.sqlite")) as conn:
            db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            must_raise(ImportConflictError, db.import_data, conn, SAMPLE_PRODUCTS, first_60_days)
            assert count_rows(conn, "historical_sales") == 720


def test_constraints():
    with TemporaryDirectory() as folder:
        with closing(db.open_database(Path(folder) / "test.sqlite")) as conn:
            db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            # unknown product (FOREIGN KEY)
            must_raise(sqlite3.IntegrityError, execute_sql, conn,
                       "INSERT INTO historical_sales VALUES ('2026-05-01', 'P999', 1)")
            # negative units (CHECK)
            must_raise(sqlite3.IntegrityError, execute_sql, conn,
                       "INSERT INTO historical_sales VALUES ('2026-05-01', 'P001', -1)")
            # stock conservation: 5 + 0 - 2 is 3, not 4
            execute_sql(conn, "INSERT INTO simulation_runs VALUES (1, 'now', 's', 'p', 1, 1, 'np', '{}')")
            must_raise(sqlite3.IntegrityError, execute_sql, conn,
                       "INSERT INTO daily_results VALUES (1, 1, 'P001', 5, 0, 2, 2, 0, 4, 0, 500, 240, 8, 0)")


def test_summary_by_product_matches_the_teacher_checks():
    expected: dict = {}
    with open(DATA / "expected_historical_by_product.csv",
              newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            expected[row["product_id"]] = row
    with TemporaryDirectory() as folder:
        with closing(db.open_database(Path(folder) / "test.sqlite")) as conn:
            db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            rows = db.sales_by_product(conn)
    assert len(rows) == 8
    for pid, name, category, days, units, mean, revenue, cogs, gross in rows:
        assert days == int(expected[pid]["days"])
        assert units == int(expected[pid]["units_sold"])
        assert math.isclose(mean, float(expected[pid]["mean_daily_units"]), abs_tol=1e-8)
        assert cents_to_euros(revenue) == expected[pid]["revenue"]
        assert cents_to_euros(cogs) == expected[pid]["cost_of_goods_sold"]
        assert cents_to_euros(gross) == expected[pid]["gross_profit"]


def test_category_and_best_sellers():
    with TemporaryDirectory() as folder:
        with closing(db.open_database(Path(folder) / "test.sqlite")) as conn:
            db.import_data(conn, SAMPLE_PRODUCTS, SAMPLE_SALES)
            categories: dict = {}
            for category, n_products, units, revenue in db.revenue_by_category(conn):
                categories[category] = (n_products, units, revenue)
            # Stationery = P001 + P002 + P003 (numbers from the checks file)
            assert categories["Stationery"] == (3, 733 + 1383 + 856, 183250 + 110640 + 51360)
            top_two = db.best_sellers(conn, "2026-01-01", "2026-03-31", 2)
            assert [row[0] for row in top_two] == ["P002", "P003"]
            assert db.best_sellers(conn, "2030-01-01", "2030-12-31") == []


test_importing_twice_does_not_duplicate()
test_conflict_cancels_the_whole_import()
test_old_data_not_in_the_files_is_a_conflict()
test_constraints()
test_summary_by_product_matches_the_teacher_checks()
test_category_and_best_sellers()
print("database tests passed")


# Replenishment policies (policies.py)

def test_fixed_quantity_orders_only_strictly_below_threshold():
    policy = FixedQuantityPolicy(threshold=20, quantity=40)
    assert policy.order_quantity(0) == 40
    assert policy.order_quantity(19) == 40
    assert policy.order_quantity(20) == 0    # equal: no order
    assert policy.order_quantity(35) == 0


def test_order_up_to_reaches_the_target():
    policy = OrderUpToPolicy(threshold=20, target=60)
    assert policy.order_quantity(0) == 60
    assert policy.order_quantity(19) == 41
    assert policy.order_quantity(20) == 0


def test_threshold_zero_never_orders():
    assert FixedQuantityPolicy(0, 5).order_quantity(0) == 0
    assert OrderUpToPolicy(0, 0).order_quantity(0) == 0


def test_wrong_parameters():
    must_raise(ConfigError, FixedQuantityPolicy, 5, 0)     # quantity 0
    must_raise(ConfigError, OrderUpToPolicy, 10, 9)        # target below threshold
    must_raise(ConfigError, FixedQuantityPolicy, -1, 5)    # negative threshold


def test_inheritance_and_str():
    fixed = FixedQuantityPolicy(3, 4)
    up_to = OrderUpToPolicy(3, 6)
    assert isinstance(fixed, ReplenishmentPolicy)
    assert isinstance(up_to, ReplenishmentPolicy)
    assert str(fixed) == "fixed_quantity(threshold=3, quantity=4)"
    assert str(up_to) == "order_up_to(threshold=3, target=6)"
    # the base class alone does not know how much to order
    must_raise(NotImplementedError, ReplenishmentPolicy(3).order_quantity, 0)


test_fixed_quantity_orders_only_strictly_below_threshold()
test_order_up_to_reaches_the_target()
test_threshold_zero_never_orders()
test_wrong_parameters()
test_inheritance_and_str()
print("policies tests passed")


# Simulation, measures and demand (simulation.py, demand.py)

# One product: cost 1.00, price 2.00, initial stock 5.
# Holding cost 0.10 per unit per day, order cost 1.00. Demand for 4 days: 2, 4, 1, 3.
PRODUCT = make_product("A", cost=100, price=200, stock=5)
HAND_DEMAND = np.array([[2], [4], [1], [3]])

# three products and 200 days of random demand for the general checks
THREE_PRODUCTS = [make_product("A", stock=10), make_product("B", stock=0), make_product("C", stock=50)]
RANDOM_DEMAND = generate_demand(np.array([4.0, 2.5, 0.5]), days=200, seed=7)


# examples calculated by hand, day by day

def test_fixed_quantity_by_hand():
    # threshold 3, quantity 4
    # day 1: stock 5, sell 2 -> 3. 3 is not < 3: no order.       holding 30
    # day 2: stock 3, demand 4 -> sell 3, lose 1 -> 0. order 4.   holding 0, order 100
    # day 3: receive 4, sell 1 -> 3, no order.                    holding 30
    # day 4: stock 3, sell 3 -> 0, order 4 (it never arrives).    holding 0, order 100
    result = run_simulation([PRODUCT], HAND_DEMAND, FixedQuantityPolicy(3, 4), HOLDING, ORDER)
    assert list(result["sold"][:, 0]) == [2, 3, 1, 3]
    assert list(result["lost"][:, 0]) == [0, 1, 0, 0]
    assert list(result["closing_stock"][:, 0]) == [3, 0, 3, 0]
    assert list(result["ordered"][:, 0]) == [0, 4, 0, 4]
    assert list(result["received"][:, 0]) == [0, 0, 4, 0]

    by_product, shop = compute_metrics(result, [PRODUCT])
    assert shop["demand"] == 10
    assert shop["sold"] == 9
    assert shop["lost"] == 1
    assert math.isclose(shop["fill_rate"], 0.9)
    assert shop["revenue"] == 1800            # 9 x 2.00
    assert shop["cogs"] == 900                # 9 x 1.00
    assert shop["gross_profit"] == 900
    assert shop["holding_cost"] == 60
    assert shop["ordering_cost"] == 200
    assert shop["operating_result"] == 640    # 900 - 60 - 200
    assert shop["final_stock"] == 0
    assert shop["outstanding_units"] == 4     # the order of the last day
    assert shop["outstanding_value"] == 400
    assert by_product["A"] == shop            # only one product


def test_order_up_to_by_hand():
    # threshold 3, target 6
    # day 1: 5 -> sell 2 -> 3, no order                  holding 30
    # day 2: 3 -> sell 3, lose 1 -> 0, order 6           holding 0, order 100
    # day 3: receive 6 -> sell 1 -> 5                    holding 50
    # day 4: 5 -> sell 3 -> 2, order 6 - 2 = 4           holding 20, order 100
    result = run_simulation([PRODUCT], HAND_DEMAND, OrderUpToPolicy(3, 6), HOLDING, ORDER)
    assert list(result["ordered"][:, 0]) == [0, 6, 0, 4]
    assert list(result["closing_stock"][:, 0]) == [3, 0, 5, 2]
    by_product, shop = compute_metrics(result, [PRODUCT])
    assert shop["holding_cost"] == 100
    assert shop["ordering_cost"] == 200
    assert shop["operating_result"] == 600    # 900 - 100 - 200
    assert shop["final_stock"] == 2
    assert shop["final_inventory_value"] == 200
    assert shop["outstanding_units"] == 4


# general behaviour of the engine

def test_order_arrives_next_morning():
    product = make_product("A", stock=0)
    demand = np.array([[1], [1], [0]])
    result = run_simulation([product], demand, FixedQuantityPolicy(1, 5), HOLDING, ORDER)
    assert result["sold"][0, 0] == 0         # nothing to sell on day 1
    assert result["ordered"][0, 0] == 5      # ordered on the evening of day 1
    assert result["received"][0, 0] == 0     # not received the same day
    assert result["received"][1, 0] == 5     # received on day 2
    assert result["sold"][1, 0] == 1


def test_stock_is_conserved_and_never_negative():
    initial = np.array([p.initial_stock for p in THREE_PRODUCTS])
    for policy in [FixedQuantityPolicy(5, 8), OrderUpToPolicy(5, 12)]:
        r = run_simulation(THREE_PRODUCTS, RANDOM_DEMAND, policy, HOLDING, ORDER)
        # initial + received - sold = final stock
        final = initial + r["received"].sum(axis=0) - r["sold"].sum(axis=0)
        assert np.array_equal(final, r["closing_stock"][-1])
        # what we ordered either arrived or is still outstanding
        arrived_or_pending = r["received"].sum(axis=0) + r["ordered"][-1]
        assert np.array_equal(r["ordered"].sum(axis=0), arrived_or_pending)
        # every day the arrivals are the orders of the day before
        assert np.array_equal(r["received"][1:], r["ordered"][:-1])
        assert np.array_equal(r["sold"] + r["lost"], r["demand"])
        assert np.all(r["closing_stock"] >= 0)


def test_demand_array_is_not_changed():
    before = RANDOM_DEMAND.copy()
    run_simulation(THREE_PRODUCTS, RANDOM_DEMAND, FixedQuantityPolicy(5, 8), HOLDING, ORDER)
    run_simulation(THREE_PRODUCTS, RANDOM_DEMAND, OrderUpToPolicy(5, 12), HOLDING, ORDER)
    assert np.array_equal(RANDOM_DEMAND, before)


def test_zero_demand():
    product = make_product("A", stock=3)
    demand = np.zeros((5, 1), dtype=int)
    result = run_simulation([product], demand, FixedQuantityPolicy(2, 4), HOLDING, ORDER)
    by_product, shop = compute_metrics(result, [product])
    assert shop["fill_rate"] is None             # not applicable, not 0 and not 1
    assert shop["revenue"] == 0
    assert shop["ordering_cost"] == 0            # stock 3 is never < 2
    assert shop["holding_cost"] == 5 * 3 * HOLDING


def test_no_order_means_no_order_cost():
    product = make_product("A", stock=4)
    demand = np.zeros((3, 1), dtype=int)
    result = run_simulation([product], demand, OrderUpToPolicy(4, 4), HOLDING, ORDER)
    assert result["ordering_cost"].sum() == 0


def test_daily_rows():
    result = run_simulation(THREE_PRODUCTS, RANDOM_DEMAND[:3], FixedQuantityPolicy(5, 8), HOLDING, ORDER)
    rows = daily_rows(result)
    assert len(rows) == 3 * 3                    # 3 days x 3 products
    assert rows[0][:2] == (1, "A")
    assert type(rows[0][2]) == int               # normal int, not a NumPy number


# demand

def test_same_seed_gives_same_demand():
    means = np.array([8.0, 1.2, 0.0])
    first = generate_demand(means, 60, seed=2026)
    second = generate_demand(means, 60, seed=2026)
    other = generate_demand(means, 60, seed=2027)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, other)
    assert first.shape == (60, 3)
    assert np.all(first >= 0)
    assert np.all(first[:, 2] == 0)              # mean 0 -> always 0


def set_first_value(array, value):
    array[0, 0] = value


def test_demand_is_read_only():
    demand = generate_demand(np.array([3.0]), 5, seed=1)
    assert not demand.flags.writeable
    must_raise(ValueError, set_first_value, demand, 99)   # NumPy refuses to change it


def test_poisson_mean_is_the_historical_mean():
    # with many days the average of the generated demand is close to the mean we gave
    demand = generate_demand(np.array([0.5, 4.0]), 100_000, seed=123)
    assert math.isclose(demand[:, 0].mean(), 0.5, abs_tol=0.05)
    assert math.isclose(demand[:, 1].mean(), 4.0, abs_tol=0.05)


def test_history_matrix_and_means():
    rows = [("2026-01-01", "A", 1), ("2026-01-01", "B", 0),
            ("2026-01-02", "A", 3), ("2026-01-02", "B", 2)]
    history = history_matrix(rows, ["A", "B"])
    assert np.array_equal(history, np.array([[1, 0], [3, 2]]))
    assert np.allclose(estimate_means(history), np.array([2.0, 1.0]))


test_fixed_quantity_by_hand()
test_order_up_to_by_hand()
test_order_arrives_next_morning()
test_stock_is_conserved_and_never_negative()
test_demand_array_is_not_changed()
test_zero_demand()
test_no_order_means_no_order_cost()
test_daily_rows()
test_same_seed_gives_same_demand()
test_demand_is_read_only()
test_poisson_mean_is_the_historical_mean()
test_history_matrix_and_means()
print("simulation tests passed")


# Extension B: storage capacity (storage.py)

# two products with 30 units at the start, 120 days of random demand
TWO_PRODUCTS = [make_product("A", stock=20), make_product("B", stock=10)]
STORAGE_DEMAND = generate_demand(np.array([6.0, 3.0]), days=120, seed=11)


# allocation rules

def test_order_of_the_rules():
    # margins: A = 100, C = 300, B = 300 (B and C tie: B first because of the id)
    products = [make_product("A", cost=100, price=200),
                make_product("C", cost=100, price=400),
                make_product("B", cost=100, price=400)]
    assert product_id_order(products) == [0, 2, 1]    # A, B, C
    assert unit_margin_order(products) == [2, 1, 0]   # B, C, A


def test_the_last_products_get_less():
    # 8 free units, every product wants 5
    assert allocate([5, 5, 5], [0, 0, 0], 8, [0, 2, 1]) == [5, 0, 3]
    assert allocate([5, 5, 5], [0, 0, 0], 8, [2, 1, 0]) == [0, 3, 5]


def test_exact_fit_and_full_warehouse():
    # 8 - 3 = 5 free units and we want exactly 5: nothing is cut
    assert allocate([2, 3, 0], [1, 1, 1], 8, [0, 1, 2]) == [2, 3, 0]
    # warehouse already full: nothing can be ordered
    assert allocate([2, 3, 0], [4, 4, 0], 8, [0, 1, 2]) == [0, 0, 0]


def test_never_more_than_wanted():
    assert allocate([1, 2, 3], [0, 0, 0], 1000, [0, 1, 2]) == [1, 2, 3]


# capacity inside the simulation

def test_capacity_is_never_exceeded():
    for rule in ["product_id_ascending", "unit_margin_descending"]:
        for policy in [FixedQuantityPolicy(15, 30), OrderUpToPolicy(15, 40)]:
            r = run_simulation(TWO_PRODUCTS, STORAGE_DEMAND, policy, HOLDING, ORDER, "test", 40, rule)
            morning_stock = (r["opening_stock"] + r["received"]).sum(axis=1)  # one total per day
            assert morning_stock.max() <= 40
            evening = (r["closing_stock"] + r["ordered"]).sum(axis=1)
            assert evening.max() <= 40


def test_initial_stock_equal_to_capacity_is_accepted():
    r = run_simulation(TWO_PRODUCTS, STORAGE_DEMAND, FixedQuantityPolicy(15, 30), HOLDING, ORDER,
                       "test", 30, "product_id_ascending")
    assert r["opening_stock"][0].sum() == 30


def test_initial_stock_above_capacity_is_refused():
    must_raise(ConfigError, run_simulation, TWO_PRODUCTS, STORAGE_DEMAND, FixedQuantityPolicy(15, 30),
               HOLDING, ORDER, "test", 29, "product_id_ascending")


def test_order_cut_to_zero_has_no_order_cost():
    # the warehouse is full from the start: the policy wants 5 units, but nothing fits
    products = [make_product("A", stock=10)]
    demand = np.zeros((3, 1), dtype=int)
    r = run_simulation(products, demand, FixedQuantityPolicy(20, 5), HOLDING, ORDER,
                       "test", 10, "product_id_ascending")
    assert r["ordered"].sum() == 0
    assert r["ordering_cost"].sum() == 0


def test_huge_capacity_is_like_no_limit():
    policy = OrderUpToPolicy(15, 40)
    free = run_simulation(TWO_PRODUCTS, STORAGE_DEMAND, policy, HOLDING, ORDER)
    big = run_simulation(TWO_PRODUCTS, STORAGE_DEMAND, policy, HOLDING, ORDER,
                         "test", 10000, "unit_margin_descending")
    assert np.array_equal(free["ordered"], big["ordered"])
    assert np.array_equal(free["sold"], big["sold"])


test_order_of_the_rules()
test_the_last_products_get_less()
test_exact_fit_and_full_warehouse()
test_never_more_than_wanted()
test_capacity_is_never_exceeded()
test_initial_stock_equal_to_capacity_is_accepted()
test_initial_stock_above_capacity_is_refused()
test_order_cut_to_zero_has_no_order_cost()
test_huge_capacity_is_like_no_limit()
print("storage tests passed")


# Seed check (workflow.py and reporting.py)

# Two products and a small warehouse, so that the two allocation rules give
# different results: product_id_ascending serves A first, unit_margin_descending
# serves B first (margin 2.00 against 0.50).
SEED_PRODUCTS = [make_product("A", cost=100, price=150, stock=30),
                 make_product("B", cost=100, price=300, stock=30)]
SEED_MEANS = np.array([6.0, 3.0])


def seed_check_config(seeds: int) -> dict:
    """The settings of storage.toml with 30 days, capacity 80 and 'seeds' seeds."""
    data = storage_toml()
    data["simulation"]["days"] = 30
    data["simulation"]["seeds_to_check"] = seeds
    data["storage"]["capacity_units"] = 80
    return check_config(data, STORAGE_TOML)


def seed_check_comparison(seeds: int) -> dict:
    """A comparison dictionary like the one of run_comparison(), for the tests."""
    config = seed_check_config(seeds)
    rows = run_seed_check(config, SEED_PRODUCTS, SEED_MEANS)
    main_runs = [row for row in rows if row["seed"] == config["seed"]]
    return {"runs": main_runs, "seed_check": rows}


def test_seed_check_uses_one_demand_per_seed():
    config = seed_check_config(5)
    rows = run_seed_check(config, SEED_PRODUCTS, SEED_MEANS)
    assert len(rows) == 5 * 6                    # 5 seeds x 3 scenarios x 2 policies
    seeds = [row["seed"] for row in rows]
    assert sorted(set(seeds)) == [2026, 2027, 2028, 2029, 2030]
    for seed in set(seeds):
        expected = int(generate_demand(SEED_MEANS, 30, seed).sum())
        for row in rows:
            if row["seed"] == seed:
                assert row["shop"]["demand"] == expected   # same demand for every option


def test_first_seed_is_the_main_comparison():
    config = seed_check_config(3)
    rows = run_seed_check(config, SEED_PRODUCTS, SEED_MEANS)
    demand = generate_demand(SEED_MEANS, 30, 2026)
    policy = FixedQuantityPolicy(20, 40)
    result = run_simulation(SEED_PRODUCTS, demand, policy, config["holding_cost"],
                            config["order_cost"], "storage_product_id_ascending", 80,
                            "product_id_ascending")
    by_product, shop = compute_metrics(result, SEED_PRODUCTS)
    found = 0
    for row in rows:
        if (row["seed"] == 2026 and row["scenario"] == "storage_product_id_ascending"
                and row["policy"].name == "fixed_quantity"):
            assert row["shop"] == shop
            found += 1
    assert found == 1


def test_every_seed_has_one_best_option():
    comparison = seed_check_comparison(6)
    config = seed_check_config(6)
    winners = seed_winners(comparison, config)
    assert sorted(winners) == [2026, 2027, 2028, 2029, 2030, 2031]
    for seed, best in winners.items():
        assert best["scenario"] != "baseline"     # with extension B we recommend a storage scenario
        for row in comparison["seed_check"]:
            if row["seed"] == seed and row["scenario"] != "baseline":
                assert row["shop"]["operating_result"] <= best["shop"]["operating_result"]
    summary = seed_check_summary(comparison, config)
    assert len(summary) == 6
    total_wins = 0
    for option in summary:
        if option["scenario"] == "baseline":
            assert option["wins"] is None
        else:
            total_wins += option["wins"]
        assert option["min"] <= option["mean"] <= option["max"]
    assert total_wins == 6


def test_one_seed_gives_the_main_recommendation():
    # boundary: seeds_to_check = 1 means "only the main seed"
    comparison = seed_check_comparison(1)
    config = seed_check_config(1)
    assert len(comparison["seed_check"]) == 6
    winners = seed_winners(comparison, config)
    assert winners[2026] is best_run(comparison["runs"], config)
    for option in seed_check_summary(comparison, config):
        assert option["min"] == option["mean"] == option["max"]


test_seed_check_uses_one_demand_per_seed()
test_first_seed_is_the_main_comparison()
test_every_seed_has_one_best_option()
test_one_seed_gives_the_main_recommendation()
print("seed check tests passed")


# Whole program through the command line (main.py)

def read_csv(path) -> list:
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_simulate_writes_all_the_outputs():
    with TemporaryDirectory() as folder:
        root = copy_project(folder)
        code, text = run_cli("simulate", "--config", str(root / "storage.toml"))
        assert code == 0, text
        for name in ["historical_summary.csv", "daily_simulation.csv", "policy_comparison.csv",
                     "validation_report.txt", "report.txt", "seed_check.csv"]:
            assert (root / "output" / name).is_file(), name
        # 3 scenarios x 2 policies x 60 days x 8 products
        assert len(read_csv(root / "output" / "daily_simulation.csv")) == 6 * 60 * 8
        report = (root / "output" / "report.txt").read_text(encoding="utf-8")
        for title in ["ASSUMPTIONS", "POLICY COMPARISON", "STORAGE CAPACITY",
                      "RECOMMENDATION", "SEED CHECK", "LIMITATIONS"]:
            assert title in report
        # seed check: 20 seeds x 6 options; the first seed gives the same
        # operating results as the main comparison
        seed_rows = read_csv(root / "output" / "seed_check.csv")
        assert len(seed_rows) == 20 * 6
        main = {}
        for row in read_csv(root / "output" / "policy_comparison.csv"):
            if row["level"] == "SHOP":
                main[(row["scenario"], row["policy"])] = row["operating_result"]
        for row in seed_rows:
            if row["seed"] == "2026":
                assert row["operating_result"] == main[(row["scenario"], row["policy"])]


def test_same_seed_gives_same_results():
    with TemporaryDirectory() as folder:
        root = copy_project(folder)
        config = str(root / "storage.toml")
        daily_file = root / "output" / "daily_simulation.csv"
        run_cli("simulate", "--config", config)
        first = read_csv(daily_file)
        run_cli("simulate", "--config", config)
        second = read_csv(daily_file)
        for row in first + second:
            del row["run_id"]     # the run ids are different, everything else is equal
        assert first == second
        with closing(sqlite3.connect(root / "output" / "inventory.sqlite")) as conn:
            runs = conn.execute("SELECT COUNT(*) FROM simulation_runs").fetchone()[0]
            sales = conn.execute("SELECT COUNT(*) FROM historical_sales").fetchone()[0]
        assert runs == 12      # runs are added
        assert sales == 720    # historical sales are not duplicated


def test_invalid_sales_stop_the_simulation():
    with TemporaryDirectory() as folder:
        root = copy_project(folder)
        text = (root / "storage.toml").read_text(encoding="utf-8")
        text = text.replace('"data/historical_sales.csv"', '"data/sales_missing_day.csv"')
        bad_config = root / "bad.toml"
        bad_config.write_text(text, encoding="utf-8")
        code, output = run_cli("simulate", "--config", str(bad_config))
        assert code == 1
        assert "INVALID" in (root / "output" / "validation_report.txt").read_text(encoding="utf-8")
        assert not (root / "output" / "report.txt").exists()
        assert not (root / "output" / "inventory.sqlite").exists()


def test_capacity_smaller_than_initial_stock_stops_before_import():
    with TemporaryDirectory() as folder:
        root = copy_project(folder)
        text = (root / "storage.toml").read_text(encoding="utf-8")
        small = root / "small.toml"
        small.write_text(text.replace("capacity_units = 300", "capacity_units = 269"), encoding="utf-8")
        code, output = run_cli("simulate", "--config", str(small))
        assert code == 1
        assert "more than capacity_units = 269" in (root / "output" / "validation_report.txt").read_text(encoding="utf-8")
        assert not (root / "output" / "inventory.sqlite").exists()


def test_invalid_config():
    with TemporaryDirectory() as folder:
        root = copy_project(folder)
        code, output = run_cli("simulate", "--config", str(root / "data" / "invalid_config.toml"))
        assert code == 2
        assert "days must be >= 1" in output


def test_summary_needs_import_first():
    with TemporaryDirectory() as folder:
        root = copy_project(folder)
        config = str(root / "storage.toml")
        code, output = run_cli("summary", "--config", config)
        assert code == 2
        code, output = run_cli("import", "--config", config)
        assert code == 0
        code, output = run_cli("summary", "--config", config, "--start", "2026-03-01",
                               "--end", "2026-03-31", "--top", "2")
        assert code == 0, output
        assert "Best sellers from 2026-03-01 to 2026-03-31" in output


test_simulate_writes_all_the_outputs()
test_same_seed_gives_same_results()
test_invalid_sales_stop_the_simulation()
test_capacity_smaller_than_initial_stock_stops_before_import()
test_invalid_config()
test_summary_needs_import_first()
print("cli tests passed")

print("ALL TESTS PASSED")
