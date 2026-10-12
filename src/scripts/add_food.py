import json
import shutil
from pathlib import Path

from models.food import FoodItem

PRODUCTS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "products.json"
)


def add_food(product: dict) -> FoodItem:
    # Check that the entry can be parsed before modifying the file.
    food = FoodItem.from_dict(product)

    if not food.name:
        raise ValueError("Food must have a name.")

    if (
        food.nutrients is None
        or not food.nutrients.per
        or food.nutrients.calories is None
        or food.nutrients.calories.value is None
    ):
        raise ValueError("Food must have a serving size and valid calories.")

    with PRODUCTS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Check all categories because the LP deduplicates foods by name.
    def contains_name(node):
        if any(
            p.get("name") == food.name
            for p in node.get("products", [])
        ):
            return True

        return any(
            contains_name(child)
            for child in node.get("subcategories", {}).values()
        )

    if contains_name(data["home"]):
        raise ValueError(f"A food named {food.name!r} already exists.")

    data["home"].setdefault("products", []).append(product)

    shutil.copy2(
        PRODUCTS_PATH,
        PRODUCTS_PATH.with_suffix(".json.bak"),
    )

    with PRODUCTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return food


if __name__ == "__main__":
    new_food = {
        "name": "My Greek Yogurt",
        "price": 1.25,
        "nutrients": {
            "per": "170 g",
            "calories": "100 kcal",
            "macronutrients": {
                "fat": {"total": "0 g"},
                "carbohydrate": {
                    "total": "6 g",
                    "sugars": "6 g",
                    "fiber": "0 g",
                },
                "protein": "17 g",
                "potassium": "240 mg",
                "sodium": "60 mg",
            },
            "micronutrients_percent": {
                "calcium": "15%",
            },
        },
    }

    print("Added:", add_food(new_food))