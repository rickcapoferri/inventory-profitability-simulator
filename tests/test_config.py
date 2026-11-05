from pathlib import Path

from inventory_profitability.config import load_config

import pytest

from inventory_profitability.config import (
    ConfigurationError,
    load_config,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_load_core_config() -> None:
    config_path = PROJECT_ROOT / "config" / "core.toml"

    config = load_config(config_path)

    assert config["simulation"]["days"] == 60
    assert config["simulation"]["seed"] == 2026
    assert config["simulation"]["currency"] == "EUR"


def test_rejects_zero_simulation_days() -> None:
    config_path = PROJECT_ROOT / "validation" / "invalid_config.toml"

    with pytest.raises(
        ConfigurationError,
        match="simulation.days must be a positive integer",
    ):
        load_config(config_path)