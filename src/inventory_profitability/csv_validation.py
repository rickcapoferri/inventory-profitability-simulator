import pandas as pd


def products_csv_validation():
    products = pd.read_csv("../../data/products.csv") #fix this to make it run from any directory
    product_identifiers_unique(products['product_id'])

def product_identifiers_unique(products) -> None:
    if not products.is_unique:
        raise ValueError(f"Product identifier {products} is not unique.")

def costs_and_selling_prices_positive(products) -> None:
    if products['cost'].lt(0).any():
        raise ValueError(f"Cost values must be positive. Found negative values: {products['cost'][products['cost'] < 0]}")
    if products['selling_price'].lt(0).any():
        raise ValueError(f"Selling price values must be positive. Found negative values: {products['selling_price'][products['selling_price'] < 0]}")

def stock_and_sales_quantities_non_negative(products, sales) -> None:
    if products['stock'].lt(0).any():
        raise ValueError(f"Stock values must be non-negative. Found negative values: {products['stock'][products['stock'] < 0]}")
    if sales['quantity'].lt(0).any():
        raise ValueError(f"Sales quantity values must be non-negative. Found negative values: {sales['quantity'][sales['quantity'] < 0]}")

def dates_valid_iso(products, sales) -> None:
    try:
        pd.to_datetime(products['date'], format='%Y-%m-%d', errors = 'raise')
    except ValueError:
        raise ValueError("Date values must be valid ISO dates.")

def sales_reference_existing_product(products, sales) -> None:
    if not sales['sales_product_id'].isin(products['product_id']).all():
        raise ValueError('Each sales record must reference an existing product. Found sales records with non existing product IDs.')
    

def product_date_pair_unique(products, sales) -> None:
    product_date_pairs = sales[['sales_product_id', 'date']].drop_duplicates()
    if len(product_date_pairs) != len(sales):
        raise ValueError('Each product.date pair may occur at most once. Found duplicate product.date pairs in sales records.')

