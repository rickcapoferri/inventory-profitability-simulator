import numpy as np
import pytest

from inventory_profitability.demand import generate_demand


SUMMARY = [
    {"product_id": "P002", "mean_daily_units": 4.0},
    {"product_id": "P001", "mean_daily_units": 0.0},
]


def test_reproducible_demand_with_stable_columns_and_zero_mean():
    product_ids, demand = generate_demand(SUMMARY, days=60, seed=2026)
    _, repeated = generate_demand(list(reversed(SUMMARY)), days=60, seed=2026)

    assert product_ids == ["P001", "P002"]
    assert demand.shape == (60, 2)
    assert np.issubdtype(demand.dtype, np.integer)
    assert (demand >= 0).all()
    assert (demand[:, 0] == 0).all()
    assert np.array_equal(demand, repeated)
    assert not demand.flags.writeable


def test_poisson_sample_mean_is_close_to_historical_mean():
    _, demand = generate_demand(SUMMARY, days=100_000, seed=123)
    assert demand[:, 1].mean() == pytest.approx(4.0, abs=0.05)


@pytest.mark.parametrize("mean", [-1, float("nan"), float("inf"), True, "4"])
def test_rejects_unusable_historical_means(mean):
    with pytest.raises(ValueError, match="Historical mean"):
        generate_demand([{"product_id": "P001", "mean_daily_units": mean}], 10, 1)


@pytest.mark.parametrize("days,seed", [(0, 1), (True, 1), (1, -1), (1, True)])
def test_rejects_invalid_days_or_seed(days, seed):
    with pytest.raises(ValueError):
        generate_demand(SUMMARY, days, seed)
