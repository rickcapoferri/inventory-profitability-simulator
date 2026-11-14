VALIDATION EXAMPLES
Use each file independently, starting with a fresh database and the valid counterpart.
Copy a valid config into config/ and change the applicable input path to ../validation/FILE.
Do not import every CSV in this directory together.

sales_negative_quantity.csv: row 2 has -1 units; reject as invalid integer quantity.
sales_missing_day.csv: P001 on 2026-01-01 is missing; report incomplete history.
sales_duplicate_pair.csv: final row repeats P001 on 2026-01-01; report duplicate pair.
sales_unknown_product.csv: row 2 refers to P999; report unknown product (and resulting missing P001 record if completeness is checked).
products_zero_cost.csv: row 2 has zero purchase cost; reject catalogue.
invalid_config.toml: zero simulation days; reject before simulation. Its paths are valid relative to validation/.

These cases must not produce a successful simulation. Exact exception names and message wording are design choices.
Repeated import test: import data/historical_sales.csv twice without resetting the database. There must still be 720 unique historical records and unchanged totals. This is different from a duplicate pair within a single input file.
