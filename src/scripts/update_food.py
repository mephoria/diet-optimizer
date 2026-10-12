import json
import os
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable

from models.food import FoodItem

PRODUCTS_PATH = Path(__file__).resolve().parents[1] / "data" / "products.json"


def update_foods(
    name: str,
    update: Callable[[dict], None],
    *,
    dry_run: bool = True,
    expected_matches: int | None = None,
    path: str | Path = PRODUCTS_PATH,
) -> dict:
    """Edit all exact name matches. Preview by default; pass dry_run=False to save.

    The callback edits raw product dictionaries in place. Parsing checks do
    not validate the mathematical correctness of unit or price conversions.
    Do not run alongside another writer to the same products file.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    def walk_products(node):
        yield from node.get("products", [])
        for child in node.get("subcategories", {}).values():
            yield from walk_products(child)

    matches = [
        product for product in walk_products(data["home"])
        if product.get("name") == name
    ]
    if expected_matches is not None and len(matches) != expected_matches:
        raise ValueError(
            f"Expected {expected_matches} matches for {name!r}, "
            f"but found {len(matches)}. Nothing was saved."
        )

    changed = 0
    examples = []
    for product in matches:
        before = deepcopy(product)
        update(product)
        FoodItem.from_dict(product)
        if product != before:
            changed += 1
            if len(examples) < 3:
                keys = {
                    key for key in before.keys() | product.keys()
                    if before.get(key) != product.get(key)
                    or (key in before) != (key in product)
                }
                examples.append({
                    "product_number": product.get("product_number"),
                    "before": {key: before[key] for key in sorted(keys) if key in before},
                    "after": {key: product[key] for key in sorted(keys) if key in product},
                })

    saved = False
    if changed and not dry_run:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as file:
                temp_path = Path(file.name)
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            shutil.copy2(path, path.with_suffix(".json.bak"))
            os.replace(temp_path, path)
            saved = True
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return {
        "name": name, "matched": len(matches), "changed": changed,
        "dry_run": dry_run, "saved": saved, "examples": examples,
    }


def update_comparison_units(
    name: str,
    new_unit: str,
    *,
    old_unit: str | None = None,
    dry_run: bool = True,
    expected_matches: int | None = None,
    path: str | Path = PRODUCTS_PATH,
) -> dict:
    """Relabel comparison units, preserving values (not a price conversion).

    If old_unit is supplied, only exact matching unit labels are changed.
    """
    if not isinstance(new_unit, str) or not new_unit.strip():
        raise ValueError("new_unit must be a non-empty string.")

    def edit(product):
        for comparison in product.get("comparison_prices") or []:
            if old_unit is None or comparison.get("unit") == old_unit:
                comparison["unit"] = new_unit

    return update_foods(
        name, edit, dry_run=dry_run,
        expected_matches=expected_matches, path=path,
    )