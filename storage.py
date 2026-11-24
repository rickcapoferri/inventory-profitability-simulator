"""Extension B: maximum storage capacity and allocation rules."""

from common import ConfigError

# Each unit of any product uses one storage unit. We check the capacity
# BEFORE ordering: tonight's stock + tonight's orders must fit, because the
# orders arrive tomorrow morning and then sales can only reduce the stock.


def product_id_order(products: list) -> list:
    """Positions of the products sorted by product_id (P001 first)."""
    pairs: list = []
    for i, p in enumerate(products):
        pairs.append((p.product_id, i))
    pairs.sort()
    return [i for product_id, i in pairs]


def unit_margin_order(products: list) -> list:
    """Positions sorted by unit margin, highest first; ties by product_id."""
    triples: list = []
    for i, p in enumerate(products):
        margin = p.selling_price_cents - p.purchase_cost_cents
        triples.append((-margin, p.product_id, i))  # minus sign: highest margin first
    triples.sort()
    return [i for minus_margin, product_id, i in triples]


# name used in the TOML file -> function that gives the order of the products
ALLOCATION_RULES = {
    "product_id_ascending": product_id_order,
    "unit_margin_descending": unit_margin_order,
}


def allocate(wanted: list, stock: list, capacity: int, order: list) -> list:
    """Reduce the wanted orders so that stock + orders <= capacity."""
    free_space: int = capacity - sum(stock)
    allocated: list = [0] * len(wanted)
    # the first product in 'order' is served first, then the next one...
    for i in order:
        allocated[i] = min(wanted[i], free_space)
        free_space = free_space - allocated[i]
    return allocated


def check_initial_stock(products: list, capacity: int) -> None:
    """The starting stock must already fit in the warehouse."""
    total = sum(p.initial_stock for p in products)
    if total > capacity:
        raise ConfigError(f"initial stock is {total} units, more than "
                          f"capacity_units = {capacity}")
