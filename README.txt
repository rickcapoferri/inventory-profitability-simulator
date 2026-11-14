INVENTORY AND PROFITABILITY PROJECT - STUDENT SAMPLE FILES

START HERE
Unzip the complete folder. Read this file alongside the project specification.
These are fictional teaching inputs, not a finished application or a model solution.
There is no executable command supplied: your group implements the application and documents its commands.

CONTENTS
 data/products.csv: 8 products in 3 categories; positive prices and costs.
 data/historical_sales.csv: 90 consecutive days, 2026-01-01 to 2026-03-31 inclusive;
   720 rows excluding the header; exactly one row per product per day, including zeros.
 config/core.toml: core development settings only.
 config/promotion.toml, storage.toml, policy_tuning.toml: full alternative configurations.
 checks/expected_historical_by_product.csv: deterministic historical calculation checks.
 validation/: independent intentionally invalid datasets and an explanation of expected failures.

WORKFLOW
1. Implement configuration reading and validate data/products.csv and data/historical_sales.csv.
2. Start with config/core.toml while developing the compulsory core.
3. Compare your historical summaries with checks/expected_historical_by_product.csv.
4. Implement both replenishment-policy subclasses and compare them using the same demand array.
5. Choose exactly ONE extension config for your final submission. You do not have to implement all three.
6. Test invalid inputs separately; create your own additional tests.
7. Have your program create working/ and results/ as needed and produce all outputs required by the specification.

FILE FORMATS AND MEANINGS
CSV is UTF-8, comma-separated, with one header row; dates are YYYY-MM-DD.
Money is in EUR with a decimal point, no currency symbols or thousands separators.
product_id is text. Stock and units_sold are non-negative integers.
initial_stock is stock at the start of the FUTURE simulation, not at the start of historical sales.
Historical sales are assumed to equal demand: the shop had no historical stock shortages.
Do not decrement initial_stock using historical sales.

CONFIGURATION CONVENTIONS
The example key names are an illustrative interface, not an additional mandatory architecture.
You may rename/restructure keys if documented and all required parameters remain external.
Paths are resolved relative to the selected TOML file. Keep the folder layout intact.
The empty extension.selected in core.toml means core-only development, not a fourth final extension.
Both policy tables are active comparison candidates; their parameters apply to every product here.
Initial total stock is 270 units. The 300-unit storage capacity is therefore initially feasible.
Simulation days are numbered 1 to 60; arrival lead time is the compulsory one day.
Charge holding cost on end-of-day stock and fixed ordering cost once per product order with positive quantity.
Follow the daily event order and final-day order convention in the specification.

EXTENSION SETTINGS
Promotion: days 15-30 inclusive; discount and demand multiplier apply only to P001 and P002.
A discount_fraction of 0.10 means 10 percent. Other days/products retain baseline settings.
Compare promotion and no-promotion cases. Document how promotion demand is generated.
Storage: compare the two listed allocation rules. One unit occupies one storage unit.
For these example rules, allocate each product's requested order, up to remaining capacity,
then proceed to the next product. Unit margin is selling_price minus purchase_cost;
for equal margins, use ascending product_id. Do not exceed the desired order quantity.
Policy tuning: 3 thresholds x 3 quantities = 9 candidates for fixed_quantity.
Evaluate mean operating result on 20 selection runs, select a candidate, then evaluate
it on 20 fresh runs with the evaluation seed. Within each run share demand across candidates.
Use a reproducible random-stream design so the 20 runs are not identical copies.
The order_up_to policy remains required as part of the compulsory core.

CHECKS AND REPRODUCIBILITY
Historical expected values cover the entire 90-day window. Means are rounded to 8 decimals;
compare means with tolerance 1e-8 and money to the nearest cent. Totals use unrounded counts.
These values do not include simulated holding/ordering costs and are not simulation outputs.
No unique expected random simulation results are supplied: valid RNG implementations and
call ordering may differ. Record your NumPy version, RNG method and seed; your own runs
must be reproducible. Keep product and day ordering consistent in demand arrays.
The historical data were generated synthetically with NumPy default_rng(21011), drawing
a vector each day with Poisson means [8,15,9,4,1.2,1.8,2.5,0.7] in P001-P008 order.
Estimate forecast means from the supplied observations, NOT these generation parameters.

WHAT YOU STILL IMPLEMENT
Your application, database schema and SQL, classes and inheritance, validations, numerical
analysis and simulations, reporting and tests. Do not treat the checks as application inputs.
Submit the required source, configuration, data, outputs, tests, README, design note,
contribution/AI-use statements and five-minute presentation as specified in the handout.
