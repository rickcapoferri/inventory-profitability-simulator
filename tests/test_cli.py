from pathlib import Path

from inventory_profitability.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_imports_and_prints_historical_summary(tmp_path, capsys):
    config_path = tmp_path / "cli.toml"
    database_path = tmp_path / "nested" / "inventory.sqlite"
    config_path.write_text(
        f'''[files]
products = "{ROOT / "data" / "products.csv"}"
historical_sales = "{ROOT / "data" / "historical_sales.csv"}"
database = "{database_path}"
output_directory = "{tmp_path / "results"}"

[simulation]
days = 60
seed = 2026
currency = "EUR"

[demand]
model = "poisson"
mean_source = "historical_daily_mean"

[costs]
holding_per_unit_per_day = 0.02
fixed_per_product_order = 1.00

[policies.fixed_quantity]
threshold = 20
quantity = 40

[policies.order_up_to]
threshold = 20
target = 60

[extension]
selected = ""
''',
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Imported 8 products and 720 sales rows." in output
    assert "P001 | 90 | 733" in output
    assert "Generated demand: 60 days x 8 products (seed 2026)." in output
    assert database_path.is_file()


def test_cli_reports_invalid_config_without_traceback(tmp_path, capsys):
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("[simulation]\ndays = 0\n", encoding="utf-8")

    exit_code = main(["--config", str(config_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err
