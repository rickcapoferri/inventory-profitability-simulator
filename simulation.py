"""The daily simulation (one function for every policy) and its measures."""

import numpy as np

from storage import ALLOCATION_RULES, allocate, check_initial_stock

# Every day:
#   1. receive the orders placed the evening before
#   2. sell min(demand, available stock)
#   3. the demand we cannot satisfy is lost (customers do not wait)
#   4. holding cost is paid on the stock left at the end of the day
#   5. the policy decides the orders, which arrive tomorrow morning
# Orders of the last day are paid but never arrive: they are "outstanding".


def run_simulation(products: list, demand: np.ndarray, policy, holding_cost: int,
                   order_cost: int, scenario: str = "baseline", capacity=None,
                   rule=None) -> dict:
    """Simulate one policy on a demand array of shape (days, products)."""
    # holding_cost and order_cost are in cents.
    # capacity and rule are used only by the storage extension (None = no limit).
    days = demand.shape[0]
    n = len(products)

    if capacity is not None:
        check_initial_stock(products, capacity)
        priority = ALLOCATION_RULES[rule](products)

    # one row per day, one column per product
    opening = np.zeros((days, n), dtype=int)
    received = np.zeros((days, n), dtype=int)
    sold = np.zeros((days, n), dtype=int)
    closing = np.zeros((days, n), dtype=int)
    ordered = np.zeros((days, n), dtype=int)

    stock = np.array([p.initial_stock for p in products])
    arriving = np.zeros(n, dtype=int)  # nothing is on order on day 1

    for day in range(days):
        opening[day] = stock
        received[day] = arriving                       # 1. arrivals
        stock = stock + arriving
        sold[day] = np.minimum(demand[day], stock)     # 2. sales
        stock = stock - sold[day]                      # 3. the rest is lost
        closing[day] = stock                           # 4. holding cost on this

        orders = [policy.order_quantity(int(s)) for s in stock]   # 5. orders
        if capacity is not None:
            orders = allocate(orders, list(stock), capacity, priority)
        ordered[day] = orders
        arriving = np.array(orders)

    # money in cents, for all days and products at once
    prices = np.array([p.selling_price_cents for p in products])
    costs = np.array([p.purchase_cost_cents for p in products])

    # demand is copied, not changed: the same array is reused for every policy
    result: dict = {}
    result["scenario"] = scenario
    result["policy"] = policy
    result["product_ids"] = [p.product_id for p in products]
    result["opening_stock"] = opening
    result["received"] = received
    result["demand"] = demand.copy()
    result["sold"] = sold
    result["lost"] = demand - sold
    result["closing_stock"] = closing
    result["ordered"] = ordered
    result["revenue"] = sold * prices
    result["cogs"] = sold * costs
    result["holding_cost"] = closing * holding_cost
    result["ordering_cost"] = (ordered > 0) * order_cost   # True * cost = cost
    return result


def daily_rows(result: dict) -> list:
    """One tuple per (day, product), in the column order of daily_results."""
    columns = ["opening_stock", "received", "demand", "sold", "lost", "closing_stock",
               "ordered", "revenue", "cogs", "holding_cost", "ordering_cost"]
    rows: list = []
    days = result["demand"].shape[0]
    for day in range(days):
        for j, product_id in enumerate(result["product_ids"]):
            # int() turns NumPy numbers into normal Python integers for sqlite3
            values = [int(result[c][day, j]) for c in columns]
            rows.append((day + 1, product_id, *values))
    return rows


# Measures computed from a simulation result (money in cents)

# revenue          = units sold x selling price
# COGS             = units sold x purchase cost (unsold units are NOT COGS)
# gross profit     = revenue - COGS
# operating result = gross profit - holding cost - ordering cost
# fill rate        = units sold / demand (None = not applicable if demand is 0)
# outstanding      = units ordered on the last day, not arrived yet


def make_measures(demand, sold, revenue, cogs, holding, ordering, orders_placed,
                  final_stock, final_value, outstanding, outstanding_value) -> dict:
    """Put already-summed numbers in a dictionary and compute the results."""
    measures: dict = {}
    measures["demand"] = int(demand)
    measures["sold"] = int(sold)
    measures["lost"] = int(demand - sold)
    measures["revenue"] = int(revenue)
    measures["cogs"] = int(cogs)
    measures["gross_profit"] = int(revenue - cogs)
    measures["holding_cost"] = int(holding)
    measures["ordering_cost"] = int(ordering)
    measures["operating_result"] = int(revenue - cogs - holding - ordering)
    measures["orders_placed"] = int(orders_placed)
    measures["final_stock"] = int(final_stock)
    measures["final_inventory_value"] = int(final_value)
    measures["outstanding_units"] = int(outstanding)
    measures["outstanding_value"] = int(outstanding_value)
    if demand > 0:
        measures["fill_rate"] = int(sold) / int(demand)
    else:
        measures["fill_rate"] = None
    return measures


def compute_metrics(result: dict, products: list) -> tuple:
    """Return (by_product, shop): measures per product and for the whole shop."""
    costs = np.array([p.purchase_cost_cents for p in products])
    # sum(axis=0) adds up the days: one total per product (per column)
    demand = result["demand"].sum(axis=0)
    sold = result["sold"].sum(axis=0)
    revenue = result["revenue"].sum(axis=0)
    cogs = result["cogs"].sum(axis=0)
    holding = result["holding_cost"].sum(axis=0)
    ordering = result["ordering_cost"].sum(axis=0)
    orders_placed = (result["ordered"] > 0).sum(axis=0)
    final_stock = result["closing_stock"][-1]          # last row = last day
    outstanding = result["ordered"][-1]

    by_product: dict = {}
    for j, product_id in enumerate(result["product_ids"]):
        by_product[product_id] = make_measures(
            demand[j], sold[j], revenue[j], cogs[j], holding[j], ordering[j],
            orders_placed[j], final_stock[j], final_stock[j] * costs[j],
            outstanding[j], outstanding[j] * costs[j])

    shop: dict = make_measures(
        demand.sum(), sold.sum(), revenue.sum(), cogs.sum(), holding.sum(), ordering.sum(),
        orders_placed.sum(), final_stock.sum(), (final_stock * costs).sum(),
        outstanding.sum(), (outstanding * costs).sum())
    return by_product, shop
