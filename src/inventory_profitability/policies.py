class ReplenishmentPolicy:
    def __init__(self, policy_name):
        self.policy_name = policy_name

    def order_quantity(self, stock):
        raise NotImplementedError(
            "Subclasses must define their ordering rules."
            )

class FixedQuantityPolicy(ReplenishmentPolicy):
    def __init__(self, threshold, quantity):
        super().__init__("fixed_quantity")
        self.threshold = threshold
        self.quantity = quantity

    def order_quantity(self, stock):
        if stock < self.threshold:
            return self.quantity
        return 0
