'''things to do are:
1. check products identifiers are unique
2. costs and selling prices must be positve
3. stock and sales quantities must be non negative integers
4. dates must be valid ISO dates
5. Each sales record must reference an existing product
6. each product.date pair may occur at most once'''

import pandas as pd


def products_csv_validation():
    products = pd.read_csv("../../data/products.csv")
    product_identifiers_unique(products['product_id'])

def product_identifiers_unique(products):
    for product in enumerate(products):
        if products.count(product) > 1:
            raise ValueError(f"Product identifier {product} is not unique.")

def costs_and_selling_prices_positive(products):
    pass

def stock_and_sales_quantities_non_negative(products, sales):
    pass

def dates_valid_iso(products, sales):
    pass

def sales_reference_existing_product(products, sales):
    pass

def product_date_pair_unique(products, sales):
    pass

