
"""
Parse a No Frills / PC Express product page (HTML) into a structured JSON
catalog whose shape mirrors the page's breadcrumb hierarchy, e.g.

    Home > Food > Fruits & Vegetables > Fresh Fruits > Bananas

becomes:

    {
      "home": {
        "label": "Home",
        "subcategories": {
          "food": {
            "label": "Food",
            "subcategories": {
              "fruits_vegetables": {
                "label": "Fruits & Vegetables",
                "subcategories": {
                  "fresh_fruits": {
                    "label": "Fresh Fruits",
                    "subcategories": {
                      "bananas": {
                        "label": "Bananas",
                        "subcategories": {},
                        "products": [ { ...full product record... } ]
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }

Each product record includes name, price, comparison prices, average
weight, product number, description, ingredients, the full nutrition
facts panel (macro/micronutrients), and the raw breadcrumb trail.

If you point --merge-into at an existing catalog JSON file, the new
product is merged into the tree: shared branches (e.g. "home > food")
are reused, and new leaves/branches are created only where the
breadcrumb path diverges.

Usage:
    python parse_product_category.py input.html output.json
    python parse_product_category.py input.html --merge-into catalog.json
    cat input.html | python parse_product_category.py - out.json

Requires: beautifulsoup4  (pip install beautifulsoup4)
"""

import os
import re
import sys
import json
import argparse
from bs4 import BeautifulSoup
import logging


# ---------------------------------------------------------------------------
# small text/number helpers
# ---------------------------------------------------------------------------

def clean_text(s):
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", s or "").strip()


def parse_amount_unit(text):
    """Split a value like '120 cal', '0.5 g', '500 mg' into (amount, unit)."""
    text = clean_text(text)
    if not text:
        return None, None
    m = re.match(r"([\d.]+)\s*([a-zA-Z]*)", text)
    if not m:
        return None, text or None
    numstr, unit = m.group(1), m.group(2) or None
    amount = float(numstr) if "." in numstr else int(numstr)
    return amount, unit


def parse_percent(text):
    """Turn '15 %' -> 15 (int/float). Empty/missing -> None."""
    text = clean_text(text)
    if not text:
        return None
    m = re.search(r"([\d.]+)", text)
    if not m:
        return None
    val = m.group(1)
    return float(val) if "." in val else int(val)


def parse_price(text):
    """Extract a numeric price from a string like '$19.94', 'CAD 19.94'."""
    if not text:
        return None
    m = re.search(r"(\d+\.?\d*)", text.replace(",", ""))
    return float(m.group(1)) if m else None


def format_value(amount, unit):
    """Render (amount, unit) back into a compact string like '6g' or '55mg'."""
    if amount is None:
        return None
    return f"{amount}{unit}" if unit else f"{amount}"


def slugify(s):
    """Turn a breadcrumb label into a JSON-friendly key, e.g.
    'Fruits & Vegetables' -> 'fruits_vegetables'."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# ---------------------------------------------------------------------------
# breadcrumb
# ---------------------------------------------------------------------------

def parse_breadcrumb(soup):
    """Return the breadcrumb trail as a list of labels, e.g.
    ['Home', 'Food', 'Fruits & Vegetables', 'Fresh Fruits', 'Bananas']."""
    crumbs = soup.select(".breadcrumbs .breadcrumb")
    return [clean_text(a.get_text()) for a in crumbs if clean_text(a.get_text())]


# ---------------------------------------------------------------------------
# top-level product fields
# ---------------------------------------------------------------------------

def parse_product_fields(soup):
    name_node = soup.select_one(".product-name__item--name")
    price_node = soup.select_one(".selling-price-list__item__price--now-price__value")
    weight_node = soup.select_one(".product-avarage-weight")
    desc_node = soup.select_one(".product-description-text__text")
    number_node = soup.select_one(".product-number__code")

    # note: price_node's text already includes the "$" sign on this page
    price_text = clean_text(price_node.get_text()) if price_node else None

    comparison_prices = []
    for li in soup.select(".comparison-price-list__item"):
        val = li.select_one(".comparison-price-list__item__price__value")
        unit = li.select_one(".comparison-price-list__item__price__unit")
        comparison_prices.append({
            "value": parse_price(val.get_text()) if val else None,
            "unit": clean_text(unit.get_text()) if unit else None,
        })

    return {
        "name": clean_text(name_node.get_text()) if name_node else None,
        "price": parse_price(price_text),
        "price_display": f"{price_text} est." if price_text else None,
        "comparison_prices": comparison_prices,
        "average_weight": clean_text(weight_node.get_text()) if weight_node else None,
        "product_number": clean_text(number_node.get_text()) if number_node else None,
        "description": clean_text(desc_node.get_text()) if desc_node else None,
    }


# ---------------------------------------------------------------------------
# nutrition facts panel
# ---------------------------------------------------------------------------

def parse_serving_size(soup):
    li = soup.select_one(".nutritional-value-list__item")
    if not li:
        return None
    spans = li.select(".nutritional-value__name, .nutritional-value__value")
    raw_parts = [clean_text(sp.get_text()) for sp in spans]
    return clean_text(" ".join(raw_parts)) or None


def parse_nutrient_label(labelnode):
    namespan = labelnode.select_one(".nutrient-per-serving__label__name")
    gramspan = labelnode.select_one(".nutrient-per-serving__label__value__gram")
    percentspan = labelnode.select_one(".nutrient-per-serving__label__value__percent")
    name = clean_text(namespan.get_text()) if namespan else None
    amount, unit = (None, None)
    if gramspan:
        amount, unit = parse_amount_unit(gramspan.get_text())
    percent = parse_percent(percentspan.get_text()) if percentspan else None
    return name, amount, unit, percent


def collect_level1_blocks(soup):
    table = soup.select_one(".product-nutrition__nutrients-per-serving-table")
    blocks = []
    if table is None:
        return blocks
    for column in table.select(".product-nutrition__nutrients-per-serving-column"):
        for item in column.select(":scope > .product-nutrition__nutrients-per-serving-column__item"):
            level1 = item.find(
                "div",
                class_=lambda c: c and "nutrient-per-serving--level-1" in c,
                recursive=False,
            )
            if level1 is None:
                continue
            label = level1.find("div", class_="nutrient-per-serving__label", recursive=False)
            if label is None:
                continue
            name, amount, unit, percent = parse_nutrient_label(label)
            is_micro = any("microNutrient" in c for c in level1.get("class", []))
            blocks.append((name, amount, unit, percent, is_micro, level1))
    return blocks


def collect_level2_subnutrients(level1div):
    subs = []
    for child in level1div.find_all("div", class_="nutrient-per-serving", recursive=False):
        label = child.find("div", class_="nutrient-per-serving__label", recursive=False)
        if label is None:
            continue
        name, amount, unit, percent = parse_nutrient_label(label)
        if name:
            subs.append((name.strip().lower(), amount, unit, percent))
    return subs


def parse_nutrients(soup):
    nutrients = {
        "per": parse_serving_size(soup),
        "calories": None,
        "macronutrients": {},
        "micronutrients_percent": {},
    }
    for name, amount, unit, percent, is_micro, level1 in collect_level1_blocks(soup):
        if not name:
            continue
        key = name.strip().lower()
        if key == "calories":
            nutrients["calories"] = format_value(amount, unit)
            continue
        if is_micro:
            nutrients["micronutrients_percent"][key] = percent
            continue
        subs = collect_level2_subnutrients(level1)
        if key == "fat":
            entry = {"total": format_value(amount, unit)}
            entry.update({sk: format_value(sa, su) for sk, sa, su, sp in subs})
            nutrients["macronutrients"]["fat"] = entry
        elif key == "carbohydrate":
            entry = {"total": format_value(amount, unit)}
            entry.update({sk: format_value(sa, su) for sk, sa, su, sp in subs})
            nutrients["macronutrients"]["carbohydrate"] = entry
        else:
            nutrients["macronutrients"][key] = format_value(amount, unit)
    return nutrients


def parse_ingredients(soup):
    layout = soup.select_one(".product-details-page-info-layout--ingredients")
    if not layout:
        return None, []
    content = layout.select_one(".product-details-page-info-layout-content")
    if not content:
        return None, []
    raw = clean_text(content.get_text())
    items = [clean_text(x) for x in re.split(r"[,]", raw.rstrip(".")) if clean_text(x)]
    return raw, items


# ---------------------------------------------------------------------------
# top-level build + breadcrumb nesting
# ---------------------------------------------------------------------------

def build_product_record(html: str) -> dict:
    """Parse one product page HTML string into a flat product dict."""
    soup = BeautifulSoup(html, "html.parser")
    result = parse_product_fields(soup)
    ing_raw, ing_items = parse_ingredients(soup)
    result["ingredients"] = {"raw": ing_raw, "items": ing_items}
    result["nutrients"] = parse_nutrients(soup)
    result["breadcrumb"] = parse_breadcrumb(soup)
    return result


def nest_into_tree(breadcrumb_path, product, tree=None):
    """Insert `product` into `tree` following breadcrumb_path, creating
    branches as needed and reusing any that already exist. Returns the
    (possibly new) tree root."""
    if tree is None:
        tree = {}
    node = tree
    for i, crumb in enumerate(breadcrumb_path):
        key = slugify(crumb)
        if key not in node:
            node[key] = {"label": crumb, "subcategories": {}}
        if i == len(breadcrumb_path) - 1:
            node[key].setdefault("products", []).append(product)
        node = node[key]["subcategories"]
    return tree


def build_catalog(html: str) -> dict:
    """Top-level entry point: HTML string in, nested category JSON out."""
    product = build_product_record(html)
    breadcrumb = product["breadcrumb"]
    return nest_into_tree(breadcrumb, product)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def body_to_json(html):

    OUTPUT_PATH = "automated.json"
    PARENT_PATH = "products.json"


    product = build_product_record(html)
    breadcrumb = product["breadcrumb"]

    if PARENT_PATH:
        if os.path.exists(PARENT_PATH):
            with open(PARENT_PATH, "r", encoding="utf-8") as f:
                try:
                    tree = json.load(f)
                except json.JSONDecodeError:
                    tree = {}
        else:
            tree = {}
        tree = nest_into_tree(breadcrumb, product, tree)
        with open(PARENT_PATH, "w", encoding="utf-8") as f:
            json.dump(tree, f, indent=2, ensure_ascii=False)
        detail = f"Merged '{product['name']}' into {PARENT_PATH} under {' > '.join(breadcrumb)}"
        logging.info(detail)
        print(detail)
        return

    catalog = nest_into_tree(breadcrumb, product)
    output_json = json.dumps(catalog, indent=2, ensure_ascii=False)

    if OUTPUT_PATH:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Wrote {OUTPUT_PATH}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()