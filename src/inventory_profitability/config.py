import tomllib
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when the project configuration is invalid."""


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load and validate a TOML configuration file."""
    path = Path(config_path)

    with path.open("rb") as file:
        config = tomllib.load(file)

    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    """Validate compulsory configuration values."""
    try:
        days = config["simulation"]["days"]
    except KeyError as error:
        raise ConfigurationError(
            "Missing required configuration: simulation.days"
        ) from error

    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ConfigurationError(
            "simulation.days must be a positive integer"
        )



