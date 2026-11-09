from pathlib import Path

import pandas as pd
import pytest

from inventory_profitability.csv_validation import CSVValidationError, products_csv_validation

ROOT = Path(__file__).resolve().parents[1]


def test_valid_inputs_from_another_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    products, sales = products_csv_validation()
    assert len(sales) == 720
    assert products['product_id'].is_unique
    assert pd.api.types.is_numeric_dtype(products['purchase_cost'])
    assert pd.api.types.is_numeric_dtype(sales['units_sold'])


@pytest.mark.parametrize('filename,expected', [
    ('products_zero_cost.csv', 'purchase_cost'),
    ('sales_negative_quantity.csv', 'units_sold'),
    ('sales_missing_day.csv', 'incomplete history'),
    ('sales_duplicate_pair.csv', 'duplicate product-date'),
    ('sales_unknown_product.csv', 'unknown products'),
])
def test_supplied_invalid_examples(filename, expected):
    products = ROOT / 'data/products.csv'
    sales = ROOT / 'data/historical_sales.csv'
    invalid = ROOT / 'validation' / filename
    if filename.startswith('products'):
        products = invalid
    else:
        sales = invalid
    with pytest.raises(CSVValidationError, match=expected):
        products_csv_validation(products, sales)


@pytest.mark.parametrize('table,column,value,expected', [
    ('products', 'purchase_cost', '0', 'purchase_cost'),
    ('products', 'selling_price', '-1', 'selling_price'),
    ('products', 'purchase_cost', 'inf', 'finite positive'),
    ('products', 'purchase_cost', 'NaN', 'finite positive'),
    ('products', 'selling_price', 'abc', 'finite positive'),
    ('products', 'initial_stock', '1.5', 'non-negative integers'),
    ('products', 'initial_stock', '-1', 'non-negative integers'),
    ('sales', 'units_sold', '1.5', 'non-negative integers'),
    ('sales', 'units_sold', 'inf', 'non-negative integers'),
    ('sales', 'date', '2026-02-30', 'YYYY-MM-DD'),
    ('sales', 'date', '2026-1-01', 'YYYY-MM-DD'),
    ('sales', 'date', '20260101', 'YYYY-MM-DD'),
    ('sales', 'date', '2026-01-01T00:00:00', 'YYYY-MM-DD'),
    ('products', 'product_id', '', 'missing values'),
    ('products', 'name', '  ', 'missing values'),
])
def test_invalid_values_report_rows(tmp_path, table, column, value, expected):
    frames = {
        'products': pd.read_csv(ROOT / 'data/products.csv', dtype=str),
        'sales': pd.read_csv(ROOT / 'data/historical_sales.csv', dtype=str),
    }
    frames[table].loc[0, column] = value
    for name, frame in frames.items():
        frame.to_csv(tmp_path / f'{name}.csv', index=False)
    with pytest.raises(CSVValidationError, match=expected) as error:
        products_csv_validation(tmp_path / 'products.csv', tmp_path / 'sales.csv')
    assert 'CSV rows 2' in str(error.value)


@pytest.mark.parametrize('case,expected', [
    ('duplicate_product', 'duplicate identifiers'),
    ('missing_column', 'missing columns'),
    ('empty_catalogue', 'at least one data row'),
    ('short_history', 'at least 30 consecutive'),
    ('missing_product', 'incomplete history'),
    ('missing_entire_day', 'incomplete history'),
])
def test_invalid_structure(tmp_path, case, expected):
    products = pd.read_csv(ROOT / 'data/products.csv', dtype=str)
    sales = pd.read_csv(ROOT / 'data/historical_sales.csv', dtype=str)
    if case == 'duplicate_product':
        products = pd.concat([products, products.iloc[[0]]], ignore_index=True)
    elif case == 'missing_column':
        products = products.drop(columns='purchase_cost')
    elif case == 'empty_catalogue':
        products = products.iloc[:0]
    elif case == 'short_history':
        sales = sales[sales['date'].isin(sorted(sales['date'].unique())[:29])]
    elif case == 'missing_product':
        sales = sales[sales['product_id'] != products.loc[0, 'product_id']]
    elif case == 'missing_entire_day':
        sales = sales[sales['date'] != sorted(sales['date'].unique())[1]]
    products.to_csv(tmp_path / 'products.csv', index=False)
    sales.to_csv(tmp_path / 'sales.csv', index=False)
    with pytest.raises(CSVValidationError, match=expected):
        products_csv_validation(tmp_path / 'products.csv', tmp_path / 'sales.csv')


def test_preserves_identifiers_and_accepts_zero_sales(tmp_path):
    products = pd.DataFrame([{
        'product_id': '001', 'name': 'NA', 'category': 'NA',
        'purchase_cost': '0.20', 'selling_price': '0.50', 'initial_stock': '0',
    }])
    sales = pd.DataFrame({
        'date': pd.date_range('2026-01-01', periods=30).strftime('%Y-%m-%d'),
        'product_id': '001', 'units_sold': '0',
    })
    products.to_csv(tmp_path / 'products.csv', index=False)
    sales.to_csv(tmp_path / 'sales.csv', index=False)
    catalogue, history = products_csv_validation(tmp_path / 'products.csv', tmp_path / 'sales.csv')
    assert catalogue.loc[0, 'product_id'] == '001'
    assert catalogue.loc[0, 'name'] == 'NA'
    assert history['units_sold'].eq(0).all()
