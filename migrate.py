#!/usr/bin/env python3
"""Миграция товаров из InSales в WooCommerce CSV.

Выгружает только товары, находящиеся в продаже (available=True, quantity>0).
Обрабатывает по 10 товаров за раз, записывая промежуточные результаты.
"""

import csv
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

BATCH_SIZE = 10
OUTPUT_DIR = "output"


# ─── Интерактивный мастер настройки ───────────────────────────────────────────

SETUP_BANNER = """
╔══════════════════════════════════════════════════════════════╗
║         Настройка подключения к InSales API                 ║
╚══════════════════════════════════════════════════════════════╝

Файл конфигурации config.py не найден или не настроен.

┌──────────────────────────────────────────────────────────────┐
│  Где взять данные:                                           │
│                                                              │
│  1. Войдите в админку вашего магазина InSales                │
│  2. Перейдите: Расширения → Разработчикам                    │
│  3. Увидите блок с данными API — скопируйте его целиком      │
└──────────────────────────────────────────────────────────────┘

Скопируйте данные одним из способов:

  Способ 1 — Вставьте весь блок целиком:

    экспорт товаров
    Идентификатор
    1234567890abcdef1234567890abcdef
    Пароль
    aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    Формат URL
    http://apikey:password@hostname/admin/resource.json
    Пример URL
    https://79f3d62d...:72236c...@myshop.myinsales.ru/admin/orders.json
    Дата подключения
    20.07.2026

  Способ 2 — Только Пример URL:

    https://1234567890abcdef1234567890abcdef:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa@myshop.myinsales.ru/admin/orders.json

  Способ 3 — Идентификатор + Пароль (домен спросим):

    Идентификатор
    1234567890abcdef1234567890abcdef
    Пароль
    aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

Вставьте данные ниже (завершите пустой строкой):
"""


def parse_insales_input(text):
    """Разобрать данные InSales из скопированного блока.

    Поддерживаемые форматы:
    1. Полный блок (Идентификатор + Пароль + Формат URL + Пример URL)
    2. Только Пример URL
    3. Идентификатор + Пароль (домен запрашивается отдельно)
    """
    text = text.strip()
    if not text:
        return None

    api_id = None
    api_password = None
    shop = None

    lines = text.splitlines()

    # 1. Ищем Идентификатор и Пароль по ключевым словам
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Идентификатор" and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not candidate.startswith("http"):
                api_id = candidate
        elif stripped == "Пароль" and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not candidate.startswith("http"):
                api_password = candidate

    # 2. Ищем URL — пропускаем шаблон формата (http://apikey:password@hostname/...)
    for line in lines:
        line = line.strip()
        if not line.startswith("http"):
            continue
        if "apikey:password@" in line or "hostname" in line:
            continue
        parsed_url = urlparse(line)
        if parsed_url.hostname and "." in parsed_url.hostname:
            shop = parsed_url.hostname
            if not api_id and parsed_url.username:
                api_id = parsed_url.username
            if not api_password and parsed_url.password:
                api_password = parsed_url.password
            break

    # 3. Если нашли ID и пароль, но нет домена — спросим
    if api_id and api_password and not shop:
        return {"shop": None, "api_id": api_id, "api_password": api_password}

    if all([shop, api_id, api_password]):
        return {"shop": shop, "api_id": api_id, "api_password": api_password}

    # 4. Если это просто URL (одна строка)
    if not api_id:
        first_line = lines[0].strip()
        if first_line.startswith("http") or "@" in first_line:
            parsed_url = urlparse(first_line)
            if parsed_url.hostname and parsed_url.username and parsed_url.password:
                return {"shop": parsed_url.hostname, "api_id": parsed_url.username, "api_password": parsed_url.password}

    return None


def validate_api(shop, api_id, api_password):
    """Проверить подключение к API."""
    url = f"https://{api_id}:{api_password}@{shop}/admin/products.json"
    try:
        resp = requests.get(url, params={"per_page": 1}, timeout=15)
        if resp.status_code == 200:
            return True, None
        elif resp.status_code == 401:
            return False, "Неверный идентификатор или пароль API"
        elif resp.status_code == 404:
            return False, f"Магазин не найден: {shop}"
        else:
            return False, f"Ошибка HTTP {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, f"Не удалось подключиться к {shop}"
    except requests.exceptions.Timeout:
        return False, "Таймаут подключения"


def write_config(shop, api_id, api_password):
    """Записать файл конфигурации."""
    config_path = os.path.join(os.path.dirname(__file__) or ".", "config.py")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(f'# Конфигурация InSales API\n')
        f.write(f'# Создано автоматически мастером настройки\n\n')
        f.write(f'SHOP = "{shop}"\n')
        f.write(f'API_ID = "{api_id}"\n')
        f.write(f'API_PASSWORD = "{api_password}"\n')
        f.write(f'\n')
        f.write(f'# Количество записей на страницу API (макс. 250)\n')
        f.write(f'PER_PAGE = 250\n')
    return config_path


def setup_wizard():
    """Интерактивный мастер настройки подключения."""
    print(SETUP_BANNER)

    while True:
        print("─" * 60)
        print("Вставьте скопированные данные из InSales")
        print("(или введите \'q\' для выхода):")
        print()

        # Считываем многострочный ввод (до пустой строки)
        lines = []
        while True:
            try:
                line = input("  > ")
            except (EOFError, KeyboardInterrupt):
                print("\nОтмена.")
                sys.exit(0)

            if line.strip().lower() in ("q", "quit", "exit", "выход"):
                print("Отмена.")
                sys.exit(0)

            if not line.strip() and lines:
                break

            lines.append(line)

        raw = "\n".join(lines)

        if not raw.strip():
            print("\n  Ввод пустой. Попробуйте ещё раз.\n")
            continue

        parsed = parse_insales_input(raw)

        # Если нет домена — спрашиваем
        if parsed and parsed.get("shop") is None:
            print()
            print("  Домен магазина не найден в данных.")
            print("  Введите домен (например: myshop.myinsales.ru):")
            try:
                shop_input = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nОтмена.")
                sys.exit(0)
            if shop_input:
                shop_input = shop_input.replace("https://", "").replace("http://", "").rstrip("/")
                parsed["shop"] = shop_input

        if not parsed:
            print()
            print("  Не удалось распознать данные.")
            print()
            print("  Что нужно вставить:")
            print("  ─────────────────────────────────────────────────────────")
            print("  Откройте в браузере:")
            print("    https://<ваш-домен>.myinsales.ru/admin")
            print("  Перейдите: Расширения → Разработчикам")
            print("  Скопируйте ВЕСЬ блок данных и вставьте сюда.")
            print()
            print("  Данные должны выглядеть примерно так:")
            print("  ─────────────────────────────────────────────────────────")
            print("    экспорт товаров")
            print("    Идентификатор")
            print("    1234567890abcdef1234567890abcdef")
            print("    Пароль")
            print("    aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            print("    Формат URL")
            print("    http://apikey:password@hostname/admin/resource.json")
            print("    Пример URL")
            print("    https://...@myshop.myinsales.ru/admin/orders.json")
            print("  ─────────────────────────────────────────────────────────")
            print()
            print("  Или вставьте только URL из строки 'Пример URL':")
            print("    https://79f3d62d...:72236c...@myshop.myinsales.ru/...")
            print()
            continue

        if not all([parsed.get("shop"), parsed.get("api_id"), parsed.get("api_password")]):
            print("\n  Не все данные распознаны. Попробуйте ещё раз.\n")
            continue

        print()
        print(f"  Магазин:  {parsed['shop']}")
        print(f"  API ID:   {parsed['api_id'][:12]}...")
        print(f"  Пароль:   {'*' * 12}")

        print("\n  Проверка подключения...", end=" ", flush=True)
        ok, error = validate_api(parsed["shop"], parsed["api_id"], parsed["api_password"])

        if ok:
            print("OK")
            config_path = write_config(parsed["shop"], parsed["api_id"], parsed["api_password"])
            print(f"\n  Конфигурация сохранена: {config_path}")
            print("─" * 60)
            return parsed
        else:
            print(f"ОШИБКА")
            print(f"\n  {error}")
            print("  Попробуйте ещё раз.\n")


# ─── Загрузка конфигурации ────────────────────────────────────────────────────

def load_config():
    """Загрузить конфигурацию. Если нет — запустить мастер настройки."""
    try:
        from config import API_ID, API_PASSWORD, PER_PAGE, SHOP
        # Проверяем, что это не шаблонные значения
        if SHOP == "your-shop.myinsales.ru" or API_ID == "your-api-id":
            print("Конфигурация содержит шаблонные значения. Запуск мастера настройки...\n")
            result = setup_wizard()
            return result["api_id"], result["api_password"], result["shop"], 250
        return API_ID, API_PASSWORD, SHOP, PER_PAGE
    except ImportError:
        result = setup_wizard()
        return result["api_id"], result["api_password"], result["shop"], 250


# ─── API ──────────────────────────────────────────────────────────────────────

def make_base_url(api_id, api_password, shop):
    return f"https://{api_id}:{api_password}@{shop}/admin"


def api_get(base_url, path, params=None):
    """GET-запрос к InSales API с обработкой лимитов."""
    url = f"{base_url}{path}"
    for attempt in range(3):
        resp = requests.get(
            url,
            params=params,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            print(f"  Лимит запросов, ожидание {retry_after}s...")
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp.json()
    return []


def fetch_all_products(base_url, per_page):
    """Получить все товары с пагинацией."""
    params = {"per_page": per_page, "page": 1}
    results = []
    while True:
        batch = api_get(base_url, "/products.json", params)
        if not batch:
            break
        results.extend(batch)
        print(f"  Список товаров: {len(results)}...")
        if len(batch) < per_page:
            break
        params["page"] += 1
    return results


def fetch_all(base_url, path, per_page, params=None):
    """Получить все страницы данных."""
    params = dict(params or {})
    params["per_page"] = per_page
    params["page"] = 1
    results = []
    while True:
        batch = api_get(base_url, path, params)
        if not batch:
            break
        results.extend(batch)
        if len(batch) < per_page:
            break
        params["page"] += 1
    return results


# ─── Логика миграции ──────────────────────────────────────────────────────────

def is_on_sale(product):
    """Проверить, находится ли товар в продаже."""
    variants = product.get("variants", [])
    if variants:
        return any(
            v.get("available", False) and (v.get("quantity", 0) or 0) > 0
            for v in variants
        )
    return (product.get("quantity", 0) or 0) > 0


def load_enriched_product(base_url, product_id):
    """Загрузить полную информацию о товаре (варианты + изображения)."""
    product = api_get(base_url, f"/products/{product_id}.json")
    if not product:
        return None
    if isinstance(product, list):
        product = product[0] if product else None
    if not product:
        return None
    product["variants"] = api_get(base_url, f"/products/{product_id}/variants.json") or []
    product["images"] = api_get(base_url, f"/products/{product_id}/images.json") or []
    return product


def build_category_tree(categories):
    """Построить дерево категорий и соответствие id → путь."""
    by_id = {c["id"]: c for c in categories}
    paths = {}

    def path_for(cat_id):
        if cat_id in paths:
            return paths[cat_id]
        cat = by_id.get(cat_id)
        if not cat:
            return ""
        if cat.get("parent_id"):
            parent_path = path_for(cat["parent_id"])
            full = f"{parent_path} > {cat['title']}" if parent_path else cat["title"]
        else:
            full = cat["title"]
        paths[cat_id] = full
        return full

    for c in categories:
        path_for(c["id"])
    return paths


def parse_variant_attributes(variant_title):
    """Извлечь атрибуты из названия варианта."""
    attrs = {}
    if " / " in variant_title:
        parts = [p.strip() for p in variant_title.split(" / ")]
        for i, part in enumerate(parts):
            attrs[f"Вариант {i + 1}"] = part
    elif "/" in variant_title:
        parts = [p.strip() for p in variant_title.split("/")]
        for i, part in enumerate(parts):
            attrs[f"Вариант {i + 1}"] = part
    return attrs


def collect_variant_attrs(variants):
    """Собрать все уникальные значения атрибутов по вариантам."""
    all_values = {}
    per_variant = []
    for v in variants:
        v_attrs = parse_variant_attributes(v.get("title", ""))
        per_variant.append(v_attrs)
        for attr_name, val in v_attrs.items():
            all_values.setdefault(attr_name, set()).add(val)
    return all_values, per_variant


def determine_product_type(product):
    """Определить тип товара: variable или simple."""
    variants = product.get("variants", [])
    if len(variants) > 1:
        return "variable"
    if len(variants) == 1:
        v = variants[0]
        if v.get("title") and v["title"] != product.get("title"):
            return "variable"
    return "simple"


def make_sku(product, variant=None):
    """Сгенерировать SKU, если отсутствует."""
    if variant and variant.get("sku"):
        return variant["sku"]
    if product.get("sku"):
        return product["sku"]
    return f"INS-{product['id']}"


def build_csv_rows(products, categories_map):
    """Сформировать строки CSV для WooCommerce."""
    rows = []
    for product in products:
        variants = product.get("variants", [])
        images = product.get("images", [])
        product_type = determine_product_type(product)

        cat_id = product.get("category_id")
        category = categories_map.get(cat_id, "") if cat_id else ""

        image_urls = sorted(images, key=lambda x: x.get("position", 0))
        images_str = ", ".join(img["url"] for img in image_urls)

        all_values, per_variant = collect_variant_attrs(variants)

        if product_type == "simple" or not all_values:
            v = variants[0] if variants else {}
            row = {
                "Type": "simple",
                "SKU": make_sku(product, v),
                "Name": product.get("title", ""),
                "Published": 1,
                "Is featured?": 0,
                "Visibility in catalog": "visible",
                "Short description": "",
                "Description": product.get("description", ""),
                "Regular price": v.get("price", product.get("price", "")),
                "Sale price": "",
                "Categories": category,
                "Tags": "",
                "Images": images_str,
                "Stock": v.get("quantity", product.get("quantity", "")),
                "Parent": "",
            }
            rows.append(row)
        else:
            parent_sku = make_sku(product)
            attr_names = sorted(all_values.keys())

            parent_row = {
                "Type": "variable",
                "SKU": parent_sku,
                "Name": product.get("title", ""),
                "Published": 1,
                "Is featured?": 0,
                "Visibility in catalog": "visible",
                "Short description": "",
                "Description": product.get("description", ""),
                "Regular price": "",
                "Sale price": "",
                "Categories": category,
                "Tags": "",
                "Images": images_str,
                "Stock": "",
                "Parent": "",
            }

            for i, attr_name in enumerate(attr_names, 1):
                vals = sorted(all_values[attr_name])
                parent_row[f"Attribute {i} name"] = attr_name
                parent_row[f"Attribute {i} value(s)"] = ", ".join(vals)
                parent_row[f"Attribute {i} visible"] = 1
                parent_row[f"Attribute {i} global"] = 0

            rows.append(parent_row)

            for v, v_attrs in zip(variants, per_variant):
                var_row = {
                    "Type": "variation",
                    "SKU": make_sku(product, v),
                    "Name": f"{product.get('title', '')} - {v.get('title', '')}",
                    "Published": 1,
                    "Regular price": v.get("price", ""),
                    "Stock": v.get("quantity", ""),
                    "Parent": parent_sku,
                    "Images": "",
                }
                for i, attr_name in enumerate(attr_names, 1):
                    var_row[f"Attribute {i} name"] = attr_name
                    var_row[f"Attribute {i} value(s)"] = v_attrs.get(attr_name, "")
                    var_row[f"Attribute {i} visible"] = 1
                    var_row[f"Attribute {i} global"] = 0

                rows.append(var_row)

    return rows


def write_csv(rows, filepath):
    """Записать строки в CSV файл."""
    if not rows:
        return
    fieldnames = [
        "Type", "SKU", "Name", "Published", "Is featured?",
        "Visibility in catalog", "Short description", "Description",
        "Regular price", "Sale price", "Categories", "Tags",
        "Images", "Stock", "Parent",
    ]
    attr_cols = set()
    for row in rows:
        for k in row:
            if k.startswith("Attribute"):
                attr_cols.add(k)
    fieldnames.extend(sorted(attr_cols))

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ─── Точка входа ──────────────────────────────────────────────────────────────

def main():
    # Загрузка или создание конфигурации
    api_id, api_password, shop, per_page = load_config()
    base_url = make_base_url(api_id, api_password, shop)

    print("=" * 60)
    print("Миграция InSales → WooCommerce")
    print("=" * 60)
    print(f"Магазин: {shop}")
    print(f"Размер пакета: {BATCH_SIZE}")

    # Загрузка справочников
    print("\n[1/3] Загрузка категорий...")
    categories = fetch_all(base_url, "/categories.json", per_page)
    categories_map = build_category_tree(categories)
    print(f"  Категорий: {len(categories_map)}")

    # Загрузка всех товаров (список)
    print("\n[2/3] Загрузка списка товаров...")
    all_products = fetch_all_products(base_url, per_page)
    print(f"  Всего товаров в каталоге: {len(all_products)}")

    # Фильтрация: только в продаже
    on_sale = [p for p in all_products if is_on_sale(p)]
    print(f"  В продаже: {len(on_sale)}")

    if not on_sale:
        print("\nНет товаров в продаже. Завершение.")
        return

    # Обработка пакетами по BATCH_SIZE
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    total_batches = (len(on_sale) + BATCH_SIZE - 1) // BATCH_SIZE
    total_rows = 0
    total_products_exported = 0

    print(f"\n[3/3] Обработка {len(on_sale)} товаров пакетами по {BATCH_SIZE}...")
    print(f"  Всего пакетов: {total_batches}")

    for batch_num in range(total_batches):
        start = batch_num * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(on_sale))
        batch = on_sale[start:end]

        print(f"\n  Пакет {batch_num + 1}/{total_batches} (товары {start + 1}-{end} из {len(on_sale)}):")

        enriched = []
        for i, product_stub in enumerate(batch):
            pid = product_stub["id"]
            print(f"    [{i + 1}/{len(batch)}] id={pid} {product_stub.get('title', '')[:40]}...")
            full = load_enriched_product(base_url, pid)
            if full:
                enriched.append(full)

        rows = build_csv_rows(enriched, categories_map)
        total_rows += len(rows)
        total_products_exported += len(enriched)

        filepath = os.path.join(OUTPUT_DIR, f"batch_{batch_num + 1:03d}.csv")
        write_csv(rows, filepath)
        print(f"    → {filepath} ({len(rows)} строк)")

    # Итоговый объединённый файл
    print("\nСборка итогового файла...")
    all_rows = []
    for batch_num in range(total_batches):
        filepath = os.path.join(OUTPUT_DIR, f"batch_{batch_num + 1:03d}.csv")
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows.extend(reader)

    final_path = os.path.join(OUTPUT_DIR, "products.csv")
    write_csv(all_rows, final_path)

    print("\n" + "=" * 60)
    print("Готово!")
    print(f"  Товаров в продаже: {len(on_sale)}")
    print(f"  Экспортировано: {total_products_exported}")
    print(f"  Строк CSV: {total_rows}")
    print(f"  Пакетов: {total_batches} (папка {OUTPUT_DIR}/batch_*.csv)")
    print(f"  Итоговый файл: {final_path}")


if __name__ == "__main__":
    main()
