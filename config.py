"""Read and check the TOML configuration file."""

# load_config() returns a dictionary with all the settings already checked
# and converted (paths as Path objects, money in cents). If something is
# wrong it raises ConfigError listing all the problems found, so the user
# can fix them in one go.

import tomllib
from pathlib import Path

from common import ConfigError, euros_to_cents
from storage import ALLOCATION_RULES

# All the keys we accept in each table. Anything else is reported, so that
# a typo such as "dasy = 60" is not silently ignored.
ALLOWED_KEYS = {
    "files": ["products", "historical_sales", "database", "output_directory"],
    "simulation": ["days", "seed", "seeds_to_check", "currency"],
    "demand": ["model", "mean_source"],
    "costs": ["holding_per_unit_per_day", "fixed_per_product_order"],
    "policies": ["fixed_quantity", "order_up_to"],
    "policies.fixed_quantity": ["threshold", "quantity"],
    "policies.order_up_to": ["threshold", "target"],
    "extension": ["selected"],
    "storage": ["capacity_units", "allocation_rules"],
}


def get_table(data: dict, name: str, errors: list) -> dict:
    """Return a table such as "costs" or "policies.order_up_to" as a dict."""
    table = data
    for part in name.split("."):
        table = table.get(part)
        if type(table) != dict:
            errors.append(f"missing table [{name}]")
            return {}
    return table


def check_unknown_keys(data: dict, errors: list) -> None:
    """Add an error for every table or key that is not in ALLOWED_KEYS."""
    tables = {}
    for name, table in data.items():
        tables[name] = table
        if name == "policies" and type(table) == dict:
            for policy_name, policy_table in table.items():
                tables["policies." + policy_name] = policy_table
    for name, table in tables.items():
        if name not in ALLOWED_KEYS:
            errors.append(f"unknown table [{name}]")
        elif type(table) == dict:
            for key in table:
                if key not in ALLOWED_KEYS[name]:
                    errors.append(f"[{name}] unknown key '{key}'")


def read_int(table: dict, name: str, key: str, errors: list, minimum: int):
    """Read an integer that must be >= minimum. Returns None if it is wrong."""
    if key not in table:
        errors.append(f"[{name}] missing key '{key}'")
        return None
    value = table[key]
    if type(value) != int:  # type(True) is bool, so true/false are refused too
        errors.append(f"[{name}] {key} must be an integer, got {value!r}")
        return None
    if value < minimum:
        errors.append(f"[{name}] {key} must be >= {minimum}, got {value}")
        return None
    return value


def read_choice(table: dict, name: str, key: str, errors: list, allowed: list):
    """Read a text value that must be one of the allowed values."""
    value = table.get(key)
    if value not in allowed:
        errors.append(f"[{name}] {key} must be one of {allowed}, got {value!r}")
        return None
    return value


def read_money(table: dict, name: str, key: str, errors: list):
    """Read a non-negative amount in euros and return it in cents."""
    value = table.get(key)
    if type(value) not in (int, float):
        errors.append(f"[{name}] {key} must be a number, got {value!r}")
        return None
    try:
        cents = euros_to_cents(value)
    except ValueError as error:
        errors.append(f"[{name}] {key} {error}")
        return None
    if cents < 0:
        errors.append(f"[{name}] {key} must not be negative")
        return None
    return cents


def check_config(data: dict, config_file: Path) -> dict:
    """Check the content of a TOML file and build the settings dictionary."""
    errors = []
    check_unknown_keys(data, errors)
    config = {"config_file": config_file, "toml": data}

    # Paths are relative to the folder that contains the TOML file.
    files = get_table(data, "files", errors)
    for key in ALLOWED_KEYS["files"]:
        value = files.get(key)
        if type(value) != str or value == "":
            errors.append(f"[files] {key} must be a non-empty path")
        else:
            config[key] = (config_file.parent / value).resolve()
    for key in ["products", "historical_sales"]:
        if key in config and not config[key].is_file():
            errors.append(f"[files] {key}: file not found: {config[key]}")
    # they may not exist yet, but if they exist they must be of the right kind
    if "database" in config and config["database"].is_dir():
        errors.append(f"[files] database is a folder, not a file: {config['database']}")
    if "output_directory" in config and config["output_directory"].is_file():
        errors.append(f"[files] output_directory is a file, not a folder: {config['output_directory']}")

    simulation = get_table(data, "simulation", errors)
    config["days"] = read_int(simulation, "simulation", "days", errors, minimum=1)
    config["seed"] = read_int(simulation, "simulation", "seed", errors, minimum=0)
    config["seeds_to_check"] = read_int(simulation, "simulation", "seeds_to_check", errors,
                                        minimum=1)
    read_choice(simulation, "simulation", "currency", errors, ["EUR"])

    demand = get_table(data, "demand", errors)
    read_choice(demand, "demand", "model", errors, ["poisson"])
    read_choice(demand, "demand", "mean_source", errors, ["historical_daily_mean"])

    costs = get_table(data, "costs", errors)
    config["holding_cost"] = read_money(costs, "costs", "holding_per_unit_per_day", errors)
    config["order_cost"] = read_money(costs, "costs", "fixed_per_product_order", errors)

    name = "policies.fixed_quantity"
    fixed = get_table(data, name, errors)
    config["fq_threshold"] = read_int(fixed, name, "threshold", errors, minimum=0)
    config["fq_quantity"] = read_int(fixed, name, "quantity", errors, minimum=1)

    name = "policies.order_up_to"
    up_to = get_table(data, name, errors)
    config["out_threshold"] = read_int(up_to, name, "threshold", errors, minimum=0)
    config["out_target"] = read_int(up_to, name, "target", errors, minimum=0)
    if config["out_threshold"] is not None and config["out_target"] is not None:
        if config["out_target"] < config["out_threshold"]:
            errors.append(f"[{name}] target ({config['out_target']}) must be "
                          f">= threshold ({config['out_threshold']})")

    # Our group implements only extension B. "" means core only.
    extension = get_table(data, "extension", errors)
    config["extension"] = read_choice(extension, "extension", "selected", errors,
                                      ["", "storage"])
    config["capacity"] = None
    config["allocation_rules"] = []
    if config["extension"] == "storage":
        storage = get_table(data, "storage", errors)
        config["capacity"] = read_int(storage, "storage", "capacity_units", errors, minimum=1)
        rules = storage.get("allocation_rules")
        if type(rules) != list or len(rules) < 2:
            errors.append("[storage] allocation_rules must be a list of at least two rules")
        else:
            known = [rule for rule in rules if type(rule) == str and rule in ALLOCATION_RULES]
            if len(known) != len(rules):
                errors.append(f"[storage] allocation_rules may only contain "
                              f"{list(ALLOCATION_RULES)}, got {rules}")
            elif len(set(rules)) != len(rules):
                errors.append("[storage] allocation_rules contains the same rule twice")
            config["allocation_rules"] = rules

    if errors:
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))
    return config


def load_config(path) -> dict:
    """Open a TOML file and return the checked settings."""
    config_file = Path(path).resolve()
    try:
        with open(config_file, "rb") as file:  # tomllib wants binary mode
            data = tomllib.load(file)
    except FileNotFoundError:
        raise ConfigError(f"configuration file not found: {config_file}")
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{config_file.name} is not valid TOML: {error}")
    return check_config(data, config_file)
