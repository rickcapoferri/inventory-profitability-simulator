"""Generate demand and define the two inventory policies."""

import numpy as np

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
