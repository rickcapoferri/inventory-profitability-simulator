import pytest

from inventory_profitability.policies import FixedQuantityPolicy, OrderUpToPolicy


@pytest.mark.parametrize("stock,fixed_order,target_order", [
    (0, 40, 60),
    (15, 40, 45),
    (19, 40, 41),
    (20, 0, 0),
    (25, 0, 0),
    (70, 0, 0),
])
def test_policy_rules_below_at_and_above_threshold(stock, fixed_order, target_order):
    fixed = FixedQuantityPolicy(threshold=20, quantity=40)
    order_up_to = OrderUpToPolicy(threshold=20, target=60)

    assert fixed.order_quantity(stock) == fixed_order
    assert order_up_to.order_quantity(stock) == target_order
    assert fixed.policy_name == "fixed_quantity"
    assert order_up_to.policy_name == "order_up_to"


def test_order_up_to_target_can_equal_threshold():
    policy = OrderUpToPolicy(threshold=20, target=20)

    assert policy.order_quantity(15) == 5
    assert policy.order_quantity(20) == 0


def test_zero_threshold_places_no_order_for_non_negative_stock():
    policies = [
        FixedQuantityPolicy(threshold=0, quantity=40),
        OrderUpToPolicy(threshold=0, target=60),
    ]
    for policy in policies:
        assert policy.order_quantity(0) == 0
