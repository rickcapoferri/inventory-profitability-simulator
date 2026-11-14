import tomllib
from math import isfinite
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when the project configuration is invalid."""


def load_config(config_path: str | Path) -> dict:
    """Load and validate a TOML configuration file."""
    path = Path(config_path)

    with path.open("rb") as file:
        config = tomllib.load(file)

    validate_config(config)
    config["files"] = validate_files(config, path)
    return config


def validate_config(config: dict) -> None:
    """Run the validator for each section of the configuration."""
    validate_simulation(config)
    validate_demand(config)
    validate_costs(config)
    validate_policies(config)
    validate_extension(config)


def validate_simulation(config: dict) -> None:
    simulation = _require_section(config, "simulation")
    _require_int(simulation, "days", "simulation", minimum=1)
    _require_int(simulation, "seed", "simulation", minimum=0)
    _require_string(simulation, "currency", "simulation")


def validate_demand(config: dict) -> None:
    demand = _require_section(config, "demand")
    if _require_string(demand, "model", "demand") != "poisson":
        raise ConfigurationError("demand.model must be 'poisson'")
    if _require_string(demand, "mean_source", "demand") != "historical_daily_mean":
        raise ConfigurationError(
            "demand.mean_source must be 'historical_daily_mean'"
        )


def validate_costs(config: dict) -> None:
    costs = _require_section(config, "costs")
    _require_number(costs, "holding_per_unit_per_day", "costs", minimum=0)
    _require_number(costs, "fixed_per_product_order", "costs", minimum=0)


def validate_policies(config: dict) -> None:
    policies = _require_section(config, "policies")
    fixed = _require_section(policies, "fixed_quantity", "policies")
    _require_int(fixed, "threshold", "policies.fixed_quantity", minimum=0)
    _require_int(fixed, "quantity", "policies.fixed_quantity", minimum=1)

    order_up_to = _require_section(policies, "order_up_to", "policies")
    threshold = _require_int(
        order_up_to, "threshold", "policies.order_up_to", minimum=0
    )
    target = _require_int(order_up_to, "target", "policies.order_up_to", minimum=0)
    if target < threshold:
        raise ConfigurationError(
            "policies.order_up_to.target must be at least its threshold"
        )


def validate_extension(config: dict) -> None:
    extension = _require_section(config, "extension")
    selected = _require_string(extension, "selected", "extension", allow_empty=True)
    if selected not in {"", "promotion", "storage", "policy_tuning"}:
        raise ConfigurationError(
            "extension.selected must be '', 'promotion', 'storage', or 'policy_tuning'"
        )
    if selected == "promotion":
        simulation_days = config["simulation"]["days"]
        _validate_promotion(
            _require_section(config, "promotion"), simulation_days
        )
    elif selected == "storage":
        storage = _require_section(config, "storage")
        _require_int(storage, "capacity_units", "storage", minimum=0)
        rules = storage.get("allocation_rules")
        if not isinstance(rules, list) or not rules:
            raise ConfigurationError("storage.allocation_rules must be a non-empty list of strings")
        allowed_rules = {"product_id_ascending", "unit_margin_descending"}
        for rule in rules:
            if not isinstance(rule, str) or rule not in allowed_rules:
                raise ConfigurationError(
                    f"Unsupported storage allocation rule: {rule!r}. "
                    "Use 'product_id_ascending' or 'unit_margin_descending'."
                )
    elif selected == "policy_tuning":
        _validate_policy_tuning(_require_section(config, "policy_tuning"))


def _require_section(
    values: dict, key: str, parent: str = ""
) -> dict:
    name = f"{parent}.{key}" if parent else key
    section = values.get(key)
    if section is None:
        raise ConfigurationError(f"Missing required configuration section: {name}")
    if not isinstance(section, dict):
        raise ConfigurationError(f"{name} must be a TOML section")
    return section


def _require_int(
    values: dict, key: str, section: str, minimum: int
) -> int:
    name = f"{section}.{key}"
    value = values.get(key)
    if key not in values:
        raise ConfigurationError(f"Missing required configuration: {name}")
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "positive" if minimum == 1 else "non-negative"
        raise ConfigurationError(f"{name} must be a {qualifier} integer")
    return value


def _require_number(
    values: dict, key: str, section: str, minimum: float
) -> float:
    name = f"{section}.{key}"
    value = values.get(key)
    if key not in values:
        raise ConfigurationError(f"Missing required configuration: {name}")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not isfinite(value))
        or value < minimum
    ):
        raise ConfigurationError(
            f"{name} must be a finite number greater than or equal to {minimum}"
        )
    return value


def _require_string(
    values: dict, key: str, section: str, allow_empty: bool = False
) -> str:
    name = f"{section}.{key}"
    value = values.get(key)
    if key not in values:
        raise ConfigurationError(f"Missing required configuration: {name}")
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        requirement = "non-empty string"
        if allow_empty:
            requirement = "string"
        raise ConfigurationError(f"{name} must be a {requirement}")
    return value


def _validate_promotion(
    promotion: dict, simulation_days: int
) -> None:
    product_ids = promotion.get("product_ids")
    if not isinstance(product_ids, list) or not product_ids:
        raise ConfigurationError("promotion.product_ids must be a non-empty list of strings")
    for product_id in product_ids:
        if not isinstance(product_id, str) or not product_id.strip():
            raise ConfigurationError("promotion.product_ids must contain non-empty strings")
    start = _require_int(promotion, "start_day", "promotion", minimum=1)
    end = _require_int(promotion, "end_day", "promotion", minimum=1)
    if end < start:
        raise ConfigurationError("promotion.end_day must be on or after start_day")
    if end > simulation_days:
        raise ConfigurationError(
            "promotion.end_day must not exceed simulation.days"
        )
    discount = _require_number(promotion, "discount_fraction", "promotion", minimum=0)
    if discount >= 1:
        raise ConfigurationError("promotion.discount_fraction must be less than 1")
    _require_number(promotion, "demand_multiplier", "promotion", minimum=0)


def _validate_policy_tuning(tuning: dict) -> None:
    """Validate a grid of thresholds paired with quantities or targets.

    Every threshold is combined with every quantity or target. For order-up-to
    tuning, all resulting pairs must satisfy target >= threshold.
    """
    policy = _require_string(tuning, "policy", "policy_tuning")
    if policy not in {"fixed_quantity", "order_up_to"}:
        raise ConfigurationError("policy_tuning.policy must be 'fixed_quantity' or 'order_up_to'")
    grid_key = "quantities" if policy == "fixed_quantity" else "targets"
    for key in ("thresholds", grid_key):
        if key not in tuning:
            raise ConfigurationError(f"Missing required configuration: policy_tuning.{key}")
        values = tuning.get(key)
        if not isinstance(values, list) or not values:
            raise ConfigurationError(f"policy_tuning.{key} must be a non-empty list")
        minimum = 1 if key == "quantities" else 0
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                qualifier = "non-negative"
                if minimum == 1:
                    qualifier = "positive"
                raise ConfigurationError(
                    f"policy_tuning.{key} must contain {qualifier} integers"
                )
    if policy == "order_up_to" and min(tuning["targets"]) < max(tuning["thresholds"]):
        raise ConfigurationError(
            "Every policy_tuning.targets value must be at least every threshold "
            "because all grid combinations are evaluated"
        )
    for key in ("selection_runs", "evaluation_runs"):
        _require_int(tuning, key, "policy_tuning", minimum=1)
    for key in ("selection_seed", "evaluation_seed"):
        _require_int(tuning, key, "policy_tuning", minimum=0)
    if _require_string(tuning, "objective", "policy_tuning") != "mean_operating_result":
        raise ConfigurationError("policy_tuning.objective must be 'mean_operating_result'")


def validate_files(
    config: dict,
    config_path: str | Path,
) -> dict[str, Path]:
    """Validate file settings and resolve paths relative to the TOML directory.

    Input CSV files must exist. The database and output directory may be
    created later; this function does not create any files or directories.
    """
    if "files" not in config:
        raise ConfigurationError("Missing required configuration section: files")

    files = config["files"]
    if not isinstance(files, dict):
        raise ConfigurationError("files must be a TOML section")

    config_directory = Path(config_path).resolve().parent
    required_paths = (
        "products",
        "historical_sales",
        "database",
        "output_directory",
    )
    resolved_paths: dict[str, Path] = {}

    for key in required_paths:
        if key not in files:
            raise ConfigurationError(f"Missing required configuration: files.{key}")

        value = files[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"files.{key} must be a non-empty string")

        path = Path(value)
        if not path.is_absolute():
            path = config_directory / path
        resolved_paths[key] = path.resolve()

    for key in ("products", "historical_sales"):
        if not resolved_paths[key].is_file():
            raise ConfigurationError(
                f"files.{key} must reference an existing file: {resolved_paths[key]}"
            )

    database = resolved_paths["database"]
    if database.exists() and not database.is_file():
        raise ConfigurationError("files.database must identify a file")

    output_directory = resolved_paths["output_directory"]
    if output_directory.exists() and not output_directory.is_dir():
        raise ConfigurationError("files.output_directory must identify a directory")

    return resolved_paths
