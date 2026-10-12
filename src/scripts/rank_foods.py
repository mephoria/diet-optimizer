from math import isfinite

from models.food import FoodItem, Quantity, extract_measurement
from models.records import consumption_price


def resolve_nutrient(food: FoodItem, nutrient: str) -> Quantity | None:
    """
    Resolve a nutrient path.

    Examples:
        "calories"
        "protein"
        "fat.total"
        "carbohydrate.fiber"
        "fiber"
        "vitamin a"
        "micronutrients_percent.iron"
    """
    if food.nutrients is None:
        return None

    aliases = {
        "+ trans": "trans",
        "omega-3 fatty acids": "omega_3_fatty_acids",
    }

    def normalize(part):
        part = part.strip().lower()
        return aliases.get(part, part.replace(" ", "_").replace("-", "_"))

    parts = [normalize(part) for part in nutrient.split(".")]

    if parts[0] == "nutrients":
        parts = parts[1:]

    if not parts or any(not part for part in parts):
        raise ValueError("Nutrient path cannot be empty.")

    candidates = [
        tuple(parts),
        ("macronutrients", *parts),
        ("micronutrients_percent", *parts),
        ("macronutrients", "fat", *parts),
        ("macronutrients", "carbohydrate", *parts),
    ]

    # Check the schema as well as the data so absent nutrients aren't
    # mistaken for invalid paths.
    from dataclasses import fields
    from models.food import (
        Nutrients,
        Macronutrients,
        MicronutrientsPercent,
        FatBreakdown,
        CarbohydrateBreakdown,
    )

    nested_types = {
        (Nutrients, "macronutrients"): Macronutrients,
        (Nutrients, "micronutrients_percent"): MicronutrientsPercent,
        (Macronutrients, "fat"): FatBreakdown,
        (Macronutrients, "carbohydrate"): CarbohydrateBreakdown,
    }

    valid_paths = []

    for path in candidates:
        schema = Nutrients

        for index, part in enumerate(path):
            if part not in {field.name for field in fields(schema)}:
                break

            child_type = nested_types.get((schema, part))

            if index == len(path) - 1:
                if child_type is None and part != "per":
                    valid_paths.append(path)
            elif child_type is not None:
                schema = child_type
            else:
                break

    if not valid_paths:
        raise ValueError(f"Unknown nutrient: {nutrient!r}")

    if len(valid_paths) > 1:
        options = ", ".join(".".join(path) for path in valid_paths)
        raise ValueError(
            f"Ambiguous nutrient {nutrient!r}. Use one of: {options}"
        )

    value = food.nutrients

    for part in valid_paths[0]:
        value = getattr(value, part, None)
        if value is None:
            return None

    return value if isinstance(value, Quantity) else None


def nutrient_per_dollar(
    food: FoodItem,
    nutrient: str,
) -> float | None:
    """Return the selected nutrient's amount per dollar."""
    quantity = resolve_nutrient(food, nutrient)

    if quantity is None or quantity.value is None:
        return None

    value = quantity.value

    if not isfinite(value) or value < 0:
        return None

    serving_amount, _ = extract_measurement(food.nutrients.per or "")

    if (
        serving_amount is None
        or not isfinite(serving_amount)
        or serving_amount <= 0
    ):
        return None

    price = consumption_price(food, serving_amount)

    if price is None or not isfinite(price) or price <= 0:
        return None

    return value / price


def sort_foods_by_nutrient_price(
    foods: list[FoodItem],
    nutrient: str,
    *,
    descending: bool = True,
) -> list[FoodItem]:
    """
    Sort by the selected nutrient per dollar.

    Excludes entries with missing nutrient data or unusable prices.
    Preserves duplicates and does not modify the original list.

    Nutrient quantities must use consistent units across foods.
    """
    scored = []

    for food in foods:
        score = nutrient_per_dollar(food, nutrient)

        if score is not None:
            scored.append((score, food))

    scored.sort(key=lambda pair: pair[0], reverse=descending)

    return [food for score, food in scored]

def inspect_nutrient_ranking(foods, nutrient, limit=10):
    ranked = sort_foods_by_nutrient_price(foods, nutrient)

    for food in ranked[:limit]:
        quantity = resolve_nutrient(food, nutrient)
        serving_amount, serving_unit = extract_measurement(
            food.nutrients.per
        )
        serving_price = consumption_price(food, serving_amount)
        score = quantity.value / serving_price

        print(f"\n{food.name}")
        print(f"  Product number: {food.product_number}")
        print(f"  Nutrient:       {nutrient}")
        print(f"  Amount:         {quantity.value} {quantity.unit}")
        print(f"  Raw serving:    {food.nutrients.per!r}")
        print(f"  Parsed serving: {serving_amount} {serving_unit}")
        print(
            "  Comparisons:    "
            f"{[(p.value, p.unit) for p in food.comparison_prices]}"
        )
        print(f"  Serving price:  ${serving_price:.8f}")
        print(f"  Score:          {score:.2f} {quantity.unit}/$")
