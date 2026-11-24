"""Demand estimation and generation with NumPy."""

import numpy as np

from common import DataNotLoadedError

# Every array has one row per day and one column per product, and the
# products are always in product_id order: column j is always the same product.


def history_matrix(rows: list, product_ids: list) -> np.ndarray:
    """Build the (days, products) array of historical units sold."""
    # rows are (date, product_id, units) tuples read from the database
    units: dict = {}
    for sale_date, product_id, units_sold in rows:
        units[(sale_date, product_id)] = units_sold
    dates = sorted(set(sale_date for sale_date, product_id, units_sold in rows))
    if len(dates) == 0:
        raise DataNotLoadedError("no historical sales in the database: run 'import' first")

    table: list = []
    for sale_date in dates:
        row: list = []
        for product_id in product_ids:
            if (sale_date, product_id) not in units:
                raise DataNotLoadedError(f"no sales record for {product_id} on {sale_date}")
            row.append(units[(sale_date, product_id)])
        table.append(row)
    return np.array(table)


def estimate_means(history: np.ndarray) -> np.ndarray:
    """Mean daily demand of each product (mean of each column)."""
    # we assume that past sales were equal to demand (no past stock-outs)
    return history.mean(axis=0)


def generate_demand(means: np.ndarray, days: int, seed: int) -> np.ndarray:
    """Random Poisson demand, an array of shape (days, products)."""
    # Poisson: whole numbers >= 0 that vary around the mean.
    # The same seed always gives exactly the same array.
    rng = np.random.default_rng(seed)
    demand = rng.poisson(lam=means, size=(days, len(means)))
    # read-only: the same array is shared by every policy, nobody may change it
    demand.flags.writeable = False
    return demand
