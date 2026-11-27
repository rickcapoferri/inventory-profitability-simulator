# Design note

## 1. Architecture

The program files are in the main folder (no packages) and we run it with `python main.py`;
three folders hold the input data (`data/`), the files the program writes (`output/`) and the
documents (`docs/`). We split the program into modules, one for each job. Only `main.py` reads the
command line and prints; all the other modules just compute and return values, so the tests can call them directly.

| Module | Job |
|---|---|
| `config.py` | reads the TOML file, checks every key and value, returns a dictionary of settings |
| `validation.py` | reads the two CSV files, collects all problems, writes `validation_report.txt` |
| `database.py` | SQLite tables, import without duplicates, the SQL summaries, saving the runs |
| `demand.py` | NumPy: table of past sales, mean demand, random Poisson demand |
| `policies.py` | `ReplenishmentPolicy` and its two subclasses |
| `storage.py` | extension B: allocation rules and capacity check |
| `simulation.py` | the daily simulation (the same for every policy) and its measures: revenue, COGS, costs, operating result, fill rate, final stock |
| `workflow.py` | puts the steps together: check + import, compare the policies, repeat the comparison with other seeds (seed check) |
| `reporting.py` | writes the CSV files and `report.txt`; chooses the recommended option and summarises the seed check |
| `common.py` | used by every module: our exceptions, the named tuples, money in cents |
| `main.py` | command line (the only module that prints) |
| `tests.py` | all the automated tests |

**Following one record from input to output.** A line of `historical_sales.csv` is read by
`validation.read_sales` and becomes a `SaleRecord` → `database.import_data` inserts it in the
table `historical_sales` → `database.load_history_rows` reads it back → `demand.history_matrix`
puts it in one cell of the (days × products) array → `estimate_means` uses it in the mean of its
product → that mean is used by `generate_demand` → `run_simulation` → the tables
`daily_results` and the output files.

## 2. Inheritance

All policies share the same rule: *order only when the end-of-day stock is strictly below the
threshold*. This rule is written once, in `ReplenishmentPolicy.order_quantity()`. The subclasses
only redefine `how_much_to_order()`:

* `FixedQuantityPolicy` → always `quantity`;
* `OrderUpToPolicy` → `target - stock`.

The simulation only calls `policy.order_quantity(stock)`, so the daily logic is written once and
works with any policy. To add a new policy we would only write a new subclass.

## 3. Database

| Table | Primary key | Main constraints |
|---|---|---|
| `products` | `product_id` | costs and prices > 0, stock ≥ 0 |
| `historical_sales` | (`sale_date`, `product_id`) | foreign key → products, units ≥ 0 |
| `simulation_runs` | `run_id` (automatic) | scenario, policy, seed, NumPy version, configuration (JSON) |
| `daily_results` | (`run_id`, `day`, `product_id`) | foreign keys; quantities ≥ 0; `sold + lost = demand`; `opening + received - sold = closing` |

The primary key of `historical_sales` makes "one row per product per day" a rule of the database
too. All queries use `?` placeholders. Each import and each saved run is one transaction
(`with conn:`): if anything fails, nothing is saved.

The four SQL summaries are in `database.py`: `sales_by_product`, `revenue_by_category` (with a
JOIN), `best_sellers(start, end, limit)` and `runs_summary` (JOIN + GROUP BY).

**Import rule.** A record identical to one already stored is skipped, so importing twice changes
nothing. A record with different values, or a database that contains data not present in the
files, cancels the whole import. To load a different dataset: `init-db --reset`.

## 4. Python types we used and why

* **dictionaries** when we look things up by a key: the settings (`config["days"]`), the products
  by id, the measures by product, the allocation rules (`name → function`), the commands of the
  command line (`name → function`).
* **lists** for collections in order that grow: problems found, sales records, runs.
* **named tuples** (`Product`, `SaleRecord`) for records that must not change: a price cannot be
  modified by mistake during a simulation, and fields are read by name.
* **sets** when we only need to know if something was already seen: product ids,
  (date, product) pairs.
* **NumPy arrays** for days × products: `np.minimum` for sales, sums with `axis=0` (one total per
  product) and `axis=1` (one total per day).

## 5. Our main design decision: the same demand for every policy

`run_comparison` generates the random demand **once** and gives the same array to all six runs
(2 policies × 3 scenarios). The array is made read-only (`demand.flags.writeable = False`),
so no policy can change it by mistake (we test this). So when two
runs give different results, the reason is the policy or the allocation rule, not luck.

Second decision: **money in integer cents**, so sums are exact and our historical totals match
the teacher's check file to the cent.

## 6. Extension B – storage capacity

We check capacity **before ordering**: closing stock + tonight's orders ≤ capacity. Orders arrive
in the morning and then stock can only go down, so the warehouse is never over capacity. If the
initial stock is above capacity, the input is refused before importing anything.

When orders do not all fit, products are served in the order of the allocation rule; each one gets
what it asked for or what is left:

* `product_id_ascending` – P001 first, then P002, ...;
* `unit_margin_descending` – the highest (price − cost) first, ties by product_id.

We compare three scenarios on the same demand: no limit, and one for each rule.

## 7. Seed check

The main comparison uses one demand path (seed 2026), and the two best options differ by only
EUR 4.52. To see if the recommendation is stable, `run_seed_check` repeats the whole comparison
with `seeds_to_check` seeds (2026 to 2045). The rules are the same as in the main comparison: for
each seed **one** demand array is shared by all six options, and no other parameter changes. We do
not search for better parameters (that would be extension C): we only check the ranking.

We save the daily rows in the database only for the main seed. The other runs keep only the shop
totals (`seed_check.csv` and section 6 of the report), so the submitted database stays small.

Result with the sample data: the rule `product_id_ascending` is part of the best option in 20 of
20 seeds, so the choice of the allocation rule is stable. The two policies instead win 10 seeds
each, and their mean operating results differ by EUR 1.72 (fixed quantity 2729.48, order-up-to
2727.76), while one option goes from about EUR 2530 to EUR 2890 from one seed to another. So the
difference between the two policies is too small to be reliable; fixed quantity loses fewer units
on average (6.5 against 13.7).

## 8. Assumptions

* Past sales = past demand (no stock-outs in the history).
* Daily demand is Poisson with the historical mean.
* Lost sales are lost; orders always arrive the next morning.
* Prices and costs do not change; holding cost on end-of-day stock; one fixed cost per product order.
* Orders of the last day are paid but reported as outstanding, not as stock.

## 9. Limitations

1. The seed check uses only 20 seeds and no confidence intervals: it shows if the ranking
   changes, not how precise the means are.
2. No seasons, weekdays or trends; products are independent.
3. If the shop had stock-outs in the past, mean demand is too low.
4. The same thresholds for all products, even though P002 sells ~15 a day and P008 less than 1.
5. The allocation rules are simple "greedy" rules, not the best possible allocation.

## 10. Code style

We followed the style of the course notebooks: type hints on parameters and return values, short
docstrings with `#` comments for the details, classes with `__init__(...) -> None` and annotated
attributes, `__str__` to print a policy, `rng = np.random.default_rng(seed)` for random numbers,
and tests written as plain `assert` statements with the `must_raise` helper from the exercises.
