"""Ordering rules sharing the same interface for the simulation engine."""


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
