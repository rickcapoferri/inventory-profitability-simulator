"""Replenishment policies: a base class and two subclasses."""

from common import ConfigError


class ReplenishmentPolicy:
    """Common rule of every policy: order only when stock < threshold."""

    name = "base"

    def __init__(self, threshold: int) -> None:
        if threshold < 0:
            raise ConfigError(f"{self.name}: threshold must be >= 0")
        self.threshold: int = threshold

    def order_quantity(self, stock: int) -> int:
        """Units to order tonight for one product with this closing stock."""
        if stock < self.threshold:
            return self.how_much_to_order(stock)
        return 0

    def how_much_to_order(self, stock: int) -> int:
        """Redefined by each subclass."""
        raise NotImplementedError("subclasses must define how_much_to_order")

    def __str__(self) -> str:
        return f"{self.name}(threshold={self.threshold})"


class FixedQuantityPolicy(ReplenishmentPolicy):
    """Below the threshold, always order the same quantity."""

    name = "fixed_quantity"

    def __init__(self, threshold: int, quantity: int) -> None:
        super().__init__(threshold)
        if quantity <= 0:
            raise ConfigError(f"{self.name}: quantity must be > 0")
        self.quantity: int = quantity

    def how_much_to_order(self, stock: int) -> int:
        return self.quantity

    def __str__(self) -> str:
        return f"{self.name}(threshold={self.threshold}, quantity={self.quantity})"


class OrderUpToPolicy(ReplenishmentPolicy):
    """Below the threshold, order enough units to go back up to the target."""

    name = "order_up_to"

    def __init__(self, threshold: int, target: int) -> None:
        super().__init__(threshold)
        if target < threshold:
            raise ConfigError(f"{self.name}: target must be >= threshold")
        self.target: int = target

    def how_much_to_order(self, stock: int) -> int:
        # stock < threshold <= target, so the result is always positive
        return self.target - stock

    def __str__(self) -> str:
        return f"{self.name}(threshold={self.threshold}, target={self.target})"


def policies_from_config(config: dict) -> list:
    """The two policies we compare, with the parameters of the TOML file."""
    fixed = FixedQuantityPolicy(config["fq_threshold"], config["fq_quantity"])
    up_to = OrderUpToPolicy(config["out_threshold"], config["out_target"])
    return [fixed, up_to]
