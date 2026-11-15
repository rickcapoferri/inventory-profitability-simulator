"""Generate demand and define the two inventory policies."""

import numpy as np
from decimal import Decimal, ROUND_HALF_UP

class ReplenishmentPolicy:
    """Base interface for deciding how many units to order."""

    def __init__(self, policy_name: str):
        self.policy_name = policy_name

    def order_quantity(self, stock: int) -> int:
        """Return the requested order quantity for the current stock."""
        raise NotImplementedError(
            "Subclasses must define their ordering rules."
        )


class FixedQuantityPolicy(ReplenishmentPolicy):
    """Order a fixed quantity when stock is strictly below the threshold."""

    def __init__(self, threshold: int, quantity: int):
        super().__init__("fixed_quantity")
        self.threshold = threshold
        self.quantity = quantity

    def order_quantity(self, stock: int) -> int:
        """Return the fixed quantity, or zero when no order is needed."""
        if stock < self.threshold:
            return self.quantity
        return 0


class OrderUpToPolicy(ReplenishmentPolicy):
    """Below the threshold, order enough units to reach the target."""

    def __init__(self, threshold: int, target: int):
        super().__init__("order_up_to")
        self.threshold = threshold
        self.target = target

    def order_quantity(self, stock: int) -> int:
        """Return the gap to the target, or zero when no order is needed."""
        if stock < self.threshold:
            return self.target - stock
        return 0


def generate_demand(
    historical_summary: list[dict],
    days: int,
    seed: int,
) -> tuple[list[str], np.ndarray]:
    """Return sorted product IDs and a day-by-product Poisson demand array.

    Each product's historical daily mean is its Poisson parameter: demand
    varies around that mean and consists of non-negative integer counts.
    Rows represent days; columns follow the returned product IDs. Generate
    once and pass this same array to every policy in a comparison.
    The array is read-only to prevent policies from accidentally changing it.
    """
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if not historical_summary:
        raise ValueError("historical_summary must contain at least one product")

    means_by_product = {}
    for row in historical_summary:
        product_id = row["product_id"]
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id must be a non-empty string")
        if product_id in means_by_product:
            raise ValueError(f"Duplicate product in historical summary: {product_id}")
        mean = row["mean_daily_units"]
        if isinstance(mean, bool) or not isinstance(mean, (int, float)):
            raise ValueError(f"Historical mean for {product_id} must be numeric")
        if not np.isfinite(mean) or mean < 0:
            raise ValueError(f"Historical mean for {product_id} must be finite and non-negative")
        means_by_product[product_id] = mean

    product_ids = sorted(means_by_product)
    means = np.array([means_by_product[product_id] for product_id in product_ids])
    generator = np.random.default_rng(seed)
    demand = generator.poisson(lam=means, size=(days, len(product_ids))).astype(np.int64)
    demand.setflags(write=False)
    return product_ids, demand


def simulate_inventory(
    products: list[dict],
    product_ids: list[str],
    demand: np.ndarray,
    policy: ReplenishmentPolicy,
    holding_per_unit_per_day: float,
    fixed_per_product_order: float,
) -> dict:
    """Simulate one policy using validated catalogue rows and shared demand.

    Rows of demand are days; columns follow product_ids. Day 1 starts with
    initial stock and no pending orders. Orders arrive the next morning.
    Final-day orders incur a cost but remain outstanding, outside final stock.
    Inputs are not modified. All financial results use integer cents; unit
    prices and cost rates are rounded half up to cents before calculation.
    """
    products_by_id = {}
    for product in products:
        product_id = product["product_id"]
        if product_id in products_by_id:
            raise ValueError(f"Duplicate product: {product_id}")
        products_by_id[product_id] = product
    if (
        not product_ids
        or len(set(product_ids)) != len(product_ids)
        or set(product_ids) != set(products_by_id)
    ):
        raise ValueError("product_ids must contain every catalogue product exactly once")
    if (
        not isinstance(demand, np.ndarray)
        or demand.ndim != 2
        or demand.shape[0] == 0
        or demand.shape[1] != len(product_ids)
        or not np.issubdtype(demand.dtype, np.integer)
        or (demand < 0).any()
    ):
        raise ValueError("demand must be a non-negative integer day-by-product array")

    holding_rate = _money_to_cents(holding_per_unit_per_day)
    order_cost = _money_to_cents(fixed_per_product_order)
    stock = np.array(
        [products_by_id[pid]["initial_stock"] for pid in product_ids], dtype=np.int64
    )
    if (stock < 0).any():
        raise ValueError("initial_stock must be non-negative")
    purchase_costs = []
    selling_prices = []
    for product_id in product_ids:
        product = products_by_id[product_id]
        purchase_costs.append(_money_to_cents(product["purchase_cost"]))
        selling_prices.append(_money_to_cents(product["selling_price"]))
    pending_orders = np.zeros(len(product_ids), dtype=np.int64)
    daily_results = []

    for day_index in range(demand.shape[0]):
        opening_stock = stock.copy()
        received = pending_orders.copy()
        available_stock = opening_stock + received
        daily_demand = demand[day_index]
        # NumPy applies sales and stock calculations to all products together.
        sold = np.minimum(daily_demand, available_stock)
        lost = daily_demand - sold
        stock = available_stock - sold

        for column, product_id in enumerate(product_ids):
            closing_stock = int(stock[column])
            quantity = policy.order_quantity(closing_stock)
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                raise ValueError("The policy must return a non-negative integer order")
            pending_orders[column] = quantity
            units_sold = int(sold[column])
            revenue = units_sold * selling_prices[column]
            cost_of_goods_sold = units_sold * purchase_costs[column]
            gross_profit = revenue - cost_of_goods_sold
            holding_cost = closing_stock * holding_rate
            ordering_cost = order_cost if quantity > 0 else 0
            daily_results.append({
                "policy": policy.policy_name,
                "day": day_index + 1,
                "product_id": product_id,
                "opening_stock": int(opening_stock[column]),
                "received_units": int(received[column]),
                "available_stock": int(available_stock[column]),
                "demand": int(daily_demand[column]),
                "units_sold": units_sold,
                "units_lost": int(lost[column]),
                "closing_stock": closing_stock,
                "ordered_units": quantity,
                "revenue_cents": revenue,
                "cost_of_goods_sold_cents": cost_of_goods_sold,
                "gross_profit_cents": gross_profit,
                "holding_cost_cents": holding_cost,
                "ordering_cost_cents": ordering_cost,
                "operating_result_cents": gross_profit - holding_cost - ordering_cost,
            })

    product_summary = []
    for column, product_id in enumerate(product_ids):
        rows = [row for row in daily_results if row["product_id"] == product_id]
        summary = _summarize_simulation(rows)
        summary["product_id"] = product_id
        summary["final_stock"] = int(stock[column])
        summary["outstanding_orders"] = int(pending_orders[column])
        summary["final_inventory_value_cents"] = int(stock[column]) * purchase_costs[column]
        product_summary.append(summary)

    shop_summary = _summarize_simulation(daily_results)
    for key in ("final_stock", "outstanding_orders", "final_inventory_value_cents"):
        shop_summary[key] = sum(row[key] for row in product_summary)
    return {
        "policy": policy.policy_name,
        "daily_results": daily_results,
        "product_summary": product_summary,
        "shop_summary": shop_summary,
    }


def _summarize_simulation(rows: list[dict]) -> dict:
    """Sum daily quantities and money, then compute the fulfilment rate."""
    summary = {}
    for key in (
        "demand", "units_sold", "units_lost", "ordered_units", "received_units",
        "revenue_cents", "cost_of_goods_sold_cents", "gross_profit_cents",
        "holding_cost_cents", "ordering_cost_cents", "operating_result_cents",
    ):
        summary[key] = sum(row[key] for row in rows)
    summary["fulfilment_rate"] = None
    if summary["demand"] > 0:
        summary["fulfilment_rate"] = summary["units_sold"] / summary["demand"]
    return summary


def _money_to_cents(value: float) -> int:
    """Round a non-negative price or cost rate to cents, using half up."""
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Prices and cost rates must be finite and non-negative")
    return int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
