#!/usr/bin/env python3
"""Тесты для migrate.py."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from migrate import (
    build_category_tree,
    build_csv_rows,
    collect_variant_attrs,
    determine_product_type,
    is_on_sale,
    make_sku,
    parse_insales_input,
    parse_variant_attributes,
)


# === parse_insales_input ===

def test_parse_full_block():
    block = """экспорт товаров
Идентификатор
79f3d62dcddec08763ce2e4b1702f2c4
Пароль
72236c31baba7f835dc0ee51c343a794
Формат URL
http://apikey:password@hostname/admin/resource.json
Пример URL
https://79f3d62dcddec08763ce2e4b1702f2c4:72236c31baba7f835dc0ee51c343a794@myshop-bqr991.myinsales.ru/admin/orders.json
Дата подключения
20.07.2026"""
    result = parse_insales_input(block)
    assert result is not None
    assert result["shop"] == "myshop-bqr991.myinsales.ru"
    assert result["api_id"] == "79f3d62dcddec08763ce2e4b1702f2c4"
    assert result["api_password"] == "72236c31baba7f835dc0ee51c343a794"


def test_parse_url_only():
    url = "https://79f3d62dcddec08763ce2e4b1702f2c4:72236c31baba7f835dc0ee51c343a794@myshop-bqr991.myinsales.ru/admin/orders.json"
    result = parse_insales_input(url)
    assert result is not None
    assert result["shop"] == "myshop-bqr991.myinsales.ru"


def test_parse_id_and_password_only():
    creds = "Идентификатор\n79f3d62dcddec08763ce2e4b1702f2c4\nПароль\n72236c31baba7f835dc0ee51c343a794"
    result = parse_insales_input(creds)
    assert result is not None
    assert result["shop"] is None
    assert result["api_id"] == "79f3d62dcddec08763ce2e4b1702f2c4"


def test_parse_empty():
    assert parse_insales_input("") is None
    assert parse_insales_input("   ") is None


def test_parse_skips_format_url():
    """Убеждаемся, что формат URL (apikey:password@hostname) не подхватывается."""
    block = """Идентификатор
abc123
Пароль
xyz789
Формат URL
http://apikey:password@hostname/admin/resource.json
Пример URL
https://abc123:xyz789@real-shop.myinsales.ru/admin/orders.json"""
    result = parse_insales_input(block)
    assert result["shop"] == "real-shop.myinsales.ru"


# === is_on_sale ===

def test_on_sale_with_available_variant():
    assert is_on_sale({"variants": [{"available": True, "quantity": 5}]}) is True


def test_not_on_sale_zero_quantity():
    assert is_on_sale({"variants": [{"available": True, "quantity": 0}]}) is False


def test_not_on_sale_unavailable():
    assert is_on_sale({"variants": [{"available": False, "quantity": 5}]}) is False


def test_on_sale_no_variants_with_quantity():
    assert is_on_sale({"variants": [], "quantity": 3}) is True


def test_not_on_sale_empty():
    assert is_on_sale({"variants": []}) is False


# === build_category_tree ===

def test_category_tree_single_level():
    cats = [
        {"id": 1, "title": "Электроника", "parent_id": None},
        {"id": 2, "title": "Одежда", "parent_id": None},
    ]
    result = build_category_tree(cats)
    assert result[1] == "Электроника"
    assert result[2] == "Одежда"


def test_category_tree_nested():
    cats = [
        {"id": 1, "title": "Электроника", "parent_id": None},
        {"id": 2, "title": "Телефоны", "parent_id": 1},
        {"id": 3, "title": "iPhone", "parent_id": 2},
    ]
    result = build_category_tree(cats)
    assert result[3] == "Электроника > Телефоны > iPhone"


def test_category_tree_empty():
    assert build_category_tree([]) == {}


# === parse_variant_attributes ===

def test_parse_variant_slash_space():
    assert parse_variant_attributes("Красный / M") == {"Вариант 1": "Красный", "Вариант 2": "M"}


def test_parse_variant_no_slash():
    assert parse_variant_attributes("Черный 64GB") == {}


def test_parse_variant_empty():
    assert parse_variant_attributes("") == {}


# === collect_variant_attrs ===

def test_collect_variant_attrs_basic():
    variants = [{"title": "Красный / S"}, {"title": "Синий / M"}]
    all_vals, per_var = collect_variant_attrs(variants)
    assert all_vals["Вариант 1"] == {"Красный", "Синий"}
    assert all_vals["Вариант 2"] == {"S", "M"}


# === determine_product_type ===

def test_simple_no_variants():
    assert determine_product_type({"variants": [], "images": []}) == "simple"


def test_variable_multiple_variants():
    p = {"title": "Футболка", "variants": [{"title": "S"}, {"title": "M"}]}
    assert determine_product_type(p) == "variable"


# === make_sku ===

def test_sku_from_variant():
    assert make_sku({"id": 1, "sku": "P"}, {"sku": "V"}) == "V"


def test_sku_from_product():
    assert make_sku({"id": 1, "sku": "P"}, None) == "P"


def test_sku_generated():
    assert make_sku({"id": 12345, "sku": ""}, None) == "INS-12345"


# === build_csv_rows ===

def test_simple_product_row():
    products = [{
        "id": 1, "title": "Тест", "description": "Описание", "price": "100.00",
        "sku": "T-001", "category_id": 10, "quantity": 50,
        "variants": [{"title": "Тест", "price": "100.00", "sku": "T-001", "quantity": 50}],
        "images": [{"url": "https://example.com/img1.jpg", "position": 1}],
    }]
    rows = build_csv_rows(products, {10: "Категория"})
    assert len(rows) == 1
    assert rows[0]["SKU"] == "T-001"
    assert rows[0]["Regular price"] == "100.00"


def test_variable_product_rows():
    products = [{
        "id": 2, "title": "Футболка", "description": "", "price": "500.00",
        "sku": "TSHIRT", "category_id": None, "quantity": 0,
        "variants": [
            {"title": "Красный / S", "price": "500.00", "sku": "TSHIRT-RS", "quantity": 10},
            {"title": "Синий / M", "price": "550.00", "sku": "TSHIRT-SM", "quantity": 5},
        ],
        "images": [],
    }]
    rows = build_csv_rows(products, {})
    assert len(rows) == 3
    assert rows[0]["Type"] == "variable"
    assert "Красный" in rows[0]["Attribute 1 value(s)"]
    assert rows[1]["Type"] == "variation"
    assert rows[1]["Attribute 1 value(s)"] == "Красный"


# === Запуск ===

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  OK  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {test.__name__}: {e}")
    print(f"\nРезультат: {passed}/{len(tests)} прошли, {failed} упали")
    sys.exit(1 if failed else 0)
