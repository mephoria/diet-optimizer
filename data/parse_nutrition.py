"""
Parse a No Frills / PC Express product page (HTML) into structured JSON,
capturing top-level product info (name, price, weight, description) and
the Nutrition Facts panel in a nested macro/micronutrient shape.

Usage:
    python parse_product.py input.html output.json
    # or, to parse an inline HTML string:
    python parse_product.py --html "<div>...</div>" output.json
    # or pipe HTML via stdin:
    cat input.html | python parse_product.py > product.json

    # To merge the parsed result into a category inside an existing
    # (or new) aggregate JSON file, e.g. data.json under "fresh_fruits":
    python parse_product.py input.html --merge-into data.json --category fresh_fruits

Requires: beautifulsoup4  (pip install beautifulsoup4)
"""

import os
import sys
import re
import json
import argparse
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Selector configuration -- confirmed against real No Frills / PC Express
# product page markup (verified against the "Red Seedless Watermelon"
# product page). Each is tried in order; the first one that matches and
# yields non-empty text wins, so alternate/legacy layouts still degrade
# gracefully instead of crashing.
# ---------------------------------------------------------------------------
PRODUCT_NAME_SELECTORS = [
    "h1.product-name__item--name",
    ".product-name__item--name",
    "h1[class*='product'][class*='name']",
    "h1",
]

PRODUCT_PRICE_SELECTORS = [
    ".selling-price-list__item__price--now-price__value",
    ".price__value",
    "[class*='now-price__value']",
    "[class*='price']",
]

PRODUCT_WEIGHT_SELECTORS = [
    ".product-name__item--package-size",
    "[class*='package-size']",
    "[class*='weight']",
]

PRODUCT_DESCRIPTION_SELECTORS = [
    ".product-description-text__text",
    "[class*='description-text']",
    "[class*='product'][class*='description']",
]


def clean_text(s: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", s or "").strip()


def first_match_text(soup: BeautifulSoup, selectors):
    """Try each CSS selector in order; return cleaned text of the first match with content."""
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            text = clean_text(node.get_text())
            if text:
                return text
    return None


def parse_amount_unit(text: str):
    """
    Split a value like '120 cal', '0.5 g', '500 mg', '0.0 g' into
    (amount: float|int|None, unit: str|None).
    """
    text = clean_text(text)
    if not text:
        return None, None
    m = re.match(r"^([\d.]+)\s*([a-zA-Z%]*)$", text)
    if not m:
        return None, text or None
    num_str, unit = m.group(1), m.group(2) or None
    amount = float(num_str) if "." in num_str else int(num_str)
    return amount, unit


def parse_percent(text: str):
    """Turn '15 %' -> 15 (int/float). Empty/missing -> None."""
    text = clean_text(text)
    if not text:
        return None
    m = re.search(r"([\d.]+)", text)
    if not m:
        return None
    val = m.group(1)
    return float(val) if "." in val else int(val)


def parse_price(text: str):
    """
    Extract a numeric price from a string like '$19.94', 'CAD 19.94',
    '19.94 $'. Returns a float, or None if no number is found.
    """
    if not text:
        return None
    m = re.search(r"([\d]+(?:\.\d+)?)", text.replace(",", ""))
    return float(m.group(1)) if m else None


def parse_product_fields(soup: BeautifulSoup):
    """Extract top-level product fields: name, price, weight, description."""
    name = first_match_text(soup, PRODUCT_NAME_SELECTORS)
    price_text = first_match_text(soup, PRODUCT_PRICE_SELECTORS)
    weight = first_match_text(soup, PRODUCT_WEIGHT_SELECTORS)
    description = first_match_text(soup, PRODUCT_DESCRIPTION_SELECTORS)

    return {
        "name": name,
        "price": parse_price(price_text),
        "weight": weight,
        "description": description,
    }


def parse_serving_size(soup: BeautifulSoup):
    """
    Extract serving size text from the '.nutritional-value-list' block, e.g.
    'Serving Size Per 10.0 oz (280 g)' -> '280g' (prefers metric grams).
    """
    li = soup.select_one(".nutritional-value-list__item")
    if not li:
        return None

    spans = li.select(".nutritional-value__name, .nutritional-value__value")
    raw_parts = [clean_text(sp.get_text()) for sp in spans]
    raw_text = clean_text(" ".join(raw_parts))

    metric_match = re.search(r"\(([\d.]+)\s*([a-zA-Z]+)\)", raw_text)
    if metric_match:
        return f"{metric_match.group(1)}{metric_match.group(2)}"

    value_span = li.select_one(".nutritional-value__value")
    if value_span:
        amount, unit = parse_amount_unit(value_span.get_text())
        if amount is not None:
            return f"{amount}{unit if unit else ''}"

    return raw_text or None


def format_value(amount, unit):
    """Render (amount, unit) back into a compact string like '6g' or '55mg'."""
    if amount is None:
        return None
    return f"{amount}{unit if unit else ''}"


def parse_nutrient_label(label_node):
    """Parse a '.nutrient-per-serving__label' node into (name, amount, unit, percent)."""
    name_span = label_node.select_one(".nutrient-per-serving__label__name")
    gram_span = label_node.select_one(".nutrient-per-serving__label__value__gram")
    percent_span = label_node.select_one(".nutrient-per-serving__label__value__percent")

    name = clean_text(name_span.get_text()) if name_span else None
    amount, unit = (None, None)
    if gram_span:
        amount, unit = parse_amount_unit(gram_span.get_text())
    percent = parse_percent(percent_span.get_text()) if percent_span else None

    return name, amount, unit, percent


def collect_level1_blocks(soup: BeautifulSoup):
    """
    Return a list of (name, amount, unit, percent, is_micro, level_div)
    for every top-level (level-1) nutrient block in the nutrients table.
    """
    table = soup.select_one(".product-nutrition__nutrients-per-serving-table")
    if table is None:
        return []

    blocks = []
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


def collect_level2_subnutrients(level1_div):
    """Return {name_lower: (amount, unit, percent)} for direct child nutrient blocks."""
    subs = {}
    for child in level1_div.find_all("div", class_="nutrient-per-serving", recursive=False):
        label = child.find("div", class_="nutrient-per-serving__label", recursive=False)
        if label is None:
            continue
        name, amount, unit, percent = parse_nutrient_label(label)
        if name:
            subs[name.strip().lower()] = (amount, unit, percent)
    return subs


def parse_nutrients(soup: BeautifulSoup):
    """
    Build the nested nutrients structure:
        {
          "per": "280g",
          "calories": "80cal",
          "macronutrients": {
              "fat": {"total": "0.4g", "saturates": "0.0g", "+ trans": "0.0g", ...},
              "carbohydrate": {"total": "21g", "sugars": "17g", "fiber": "1g", ...},
              "protein": "2g",
              "cholesterol": "0mg",
              "sodium": "3mg",
              "potassium": "300mg"
          },
          "micronutrients (percent)": {"vitamin a": 8, "vitamin c": 25, ...}
        }

    BUG FIX: Fat and Carbohydrate are the only nutrients with nested
    (level-2) children. Earlier versions only stored their sub-nutrient
    dict and silently dropped the nutrient's OWN top-level amount (e.g.
    Fat -> 0.4 g, Carbohydrate -> 21 g), which is why those numbers never
    showed up in the output even though Saturates/Sugars/etc. worked fine.
    That top-level amount is now stored under a "total" key alongside the
    sub-nutrients. Nutrients flagged with the microNutrient CSS class go
    under "micronutrients (percent)" keyed by their %DV. Other level-1
    nutrients (Protein, Sodium, Potassium, Cholesterol) remain flat
    scalar strings since they have no sub-nutrients to nest.
    """
    nutrients = {
        "per": parse_serving_size(soup),
        "calories": None,
        "macronutrients": {},
        "micronutrients (percent)": {},
    }

    macro = nutrients["macronutrients"]
    micro = nutrients["micronutrients (percent)"]

    for name, amount, unit, percent, is_micro, level1 in collect_level1_blocks(soup):
        if not name:
            continue
        key = name.strip().lower()

        if key == "calories":
            nutrients["calories"] = format_value(amount, unit)
            continue

        if is_micro:
            micro[key] = percent if percent is not None else None
            continue

        subs = collect_level2_subnutrients(level1)

        if key == "fat":
            fat_entry = {"total": format_value(amount, unit)}
            fat_entry.update({sk: format_value(sa, su) for sk, (sa, su, _sp) in subs.items()})
            macro["fat"] = fat_entry
        elif key == "carbohydrate":
            carb_entry = {"total": format_value(amount, unit)}
            carb_entry.update({sk: format_value(sa, su) for sk, (sa, su, _sp) in subs.items()})
            macro["carbohydrate"] = carb_entry
        else:
            macro[key] = format_value(amount, unit)

    return nutrients


def parse_ingredients(soup: BeautifulSoup):
    """Extract ingredients text and split into a list of individual items."""
    layout = soup.select_one(".product-details-page-info-layout--ingredients")
    if not layout:
        return {"raw": None, "items": []}

    content = layout.select_one("[class*='product-details-page-info-layout-content']")
    if not content:
        return {"raw": None, "items": []}

    raw = clean_text(content.get_text())
    items = [clean_text(x) for x in re.split(r",(?![^(]*\))", raw.rstrip(".")) if clean_text(x)]

    return {"raw": raw, "items": items}


def build_product_json(html: str) -> dict:
    """Top-level entry point: HTML string in, structured product dict out."""
    soup = BeautifulSoup(html, "html.parser")

    result = parse_product_fields(soup)
    result["nutrients"] = parse_nutrients(soup)
    result["ingredients"] = parse_ingredients(soup)
    return result


def merge_into_category_file(result: dict, merge_path: str, category: str) -> int:
    """
    Load (or create) an aggregate JSON file shaped like:
        {"items": [{"name": "fresh_fruits", "items": [...]}, ...]}
    and append `result` into the list for the given category name,
    creating the file and/or category if they don't already exist.
    Returns the number of items now filed under that category.
    """
    if os.path.exists(merge_path):
        with open(merge_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
    else:
        data = {}

    if "items" not in data or not isinstance(data["items"], list):
        data["items"] = []

    target = next(
        (entry for entry in data["items"]
         if isinstance(entry, dict) and entry.get("name") == category),
        None,
    )

    if target is None:
        target = {"name": category, "items": []}
        data["items"].append(target)

    if "items" not in target or not isinstance(target["items"], list):
        target["items"] = []

    target["items"].append(result)

    with open(merge_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return len(target["items"])


def main():
    parser = argparse.ArgumentParser(description="Convert a product page HTML into JSON.")
    parser.add_argument("input", nargs="?", help="Path to input HTML file (omit if using --html or stdin).")
    parser.add_argument("output", nargs="?", help="Path to output JSON file (omit to print to stdout).")
    parser.add_argument("--html", help="Inline HTML string instead of a file path.")
    parser.add_argument("--merge-into", help="Path to an aggregate JSON file to append this product into (created if missing).")
    parser.add_argument("--category", default="uncategorized",
                         help="Category name to file this product under when using --merge-into (default: uncategorized).")
    args = parser.parse_args()

    if args.html:
        html = args.html
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        html = sys.stdin.read()

    result = build_product_json(html)
    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Wrote {args.output}")
    else:
        print(f'Wrote item: {result["name"]}')

    if args.merge_into:
        count = merge_into_category_file(result, args.merge_into, args.category)
        print(
            f"Merged into '{args.merge_into}' under category '{args.category}' "
            f"({count} item(s) now in that category)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()