from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_QUANTITY_RE = re.compile(r"^(-?\d+\.?\d*)\s*([a-zA-Z%]*)$")


def parse_quantity(raw: Optional[str]) -> Optional["Quantity"]:
    """Parse strings like '1.5g', '30mg', '35cal', '0%' into a Quantity(value, unit)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return Quantity(value=float(raw), unit="%")
    match = _QUANTITY_RE.match(raw.strip())
    if not match:
        return None
    value_str, unit = match.groups()
    return Quantity(value=float(value_str), unit=unit or None)


@dataclass
class Quantity:
    value: Optional[float] = None
    unit: Optional[str] = None


@dataclass
class ComparisonPrice:
    value: Optional[float] = None
    unit: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ComparisonPrice":
        return cls(value=d.get("value"), unit=d.get("unit"))


@dataclass
class Ingredients:
    raw: Optional[str] = None
    items: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Ingredients":
        return cls(raw=d.get("raw"), items=list(d.get("items", []) or []))


@dataclass
class FatBreakdown:
    total: Optional[Quantity] = None
    saturates: Optional[Quantity] = None
    trans: Optional[Quantity] = None
    monounsaturates: Optional[Quantity] = None
    polyunsaturates: Optional[Quantity] = None
    omega_3_fatty_acids: Optional[Quantity] = None

    @classmethod
    def from_dict(cls, d: dict) -> "FatBreakdown":
        return cls(
            total=parse_quantity(d.get("total")),
            saturates=parse_quantity(d.get("saturates")),
            trans=parse_quantity(d.get("+ trans")),
            monounsaturates=parse_quantity(d.get("monounsaturates")),
            polyunsaturates=parse_quantity(d.get("polyunsaturates")),
            omega_3_fatty_acids=parse_quantity(d.get("omega-3 fatty acids")),
        )


@dataclass
class CarbohydrateBreakdown:
    total: Optional[Quantity] = None
    sugars: Optional[Quantity] = None
    fiber: Optional[Quantity] = None
    other_carbohydrate: Optional[Quantity] = None

    @classmethod
    def from_dict(cls, d: dict) -> "CarbohydrateBreakdown":
        return cls(
            total=parse_quantity(d.get("total")),
            sugars=parse_quantity(d.get("sugars")),
            fiber=parse_quantity(d.get("fiber")),
            other_carbohydrate=parse_quantity(d.get("other carbohydrate")),
        )


@dataclass
class Macronutrients:
    fat: Optional[FatBreakdown] = None
    carbohydrate: Optional[CarbohydrateBreakdown] = None
    protein: Optional[Quantity] = None
    potassium: Optional[Quantity] = None
    cholesterol: Optional[Quantity] = None
    sodium: Optional[Quantity] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Macronutrients":
        return cls(
            fat=FatBreakdown.from_dict(d["fat"]) if isinstance(d.get("fat"), dict) else None,
            carbohydrate=CarbohydrateBreakdown.from_dict(d["carbohydrate"])
            if isinstance(d.get("carbohydrate"), dict)
            else None,
            protein=parse_quantity(d.get("protein")),
            potassium=parse_quantity(d.get("potassium")),
            cholesterol=parse_quantity(d.get("cholesterol")),
            sodium=parse_quantity(d.get("sodium")),
        )


@dataclass
class MicronutrientsPercent:
    vitamin_a: Optional[Quantity] = None
    vitamin_c: Optional[Quantity] = None
    vitamin_d: Optional[Quantity] = None
    vitamin_e: Optional[Quantity] = None
    vitamin_k: Optional[Quantity] = None
    thiamine: Optional[Quantity] = None
    riboflavin: Optional[Quantity] = None
    niacin: Optional[Quantity] = None
    vitamin_b6: Optional[Quantity] = None
    folate: Optional[Quantity] = None
    vitamin_b12: Optional[Quantity] = None
    pantothenate: Optional[Quantity] = None
    biotin: Optional[Quantity] = None
    calcium: Optional[Quantity] = None
    iron: Optional[Quantity] = None
    phosphorus: Optional[Quantity] = None
    magnesium: Optional[Quantity] = None
    zinc: Optional[Quantity] = None
    selenium: Optional[Quantity] = None
    chromium: Optional[Quantity] = None

    @classmethod
    def from_dict(cls, d: dict) -> "MicronutrientsPercent":
        return cls(
            vitamin_a=parse_quantity(d.get("vitamin a")),
            vitamin_c=parse_quantity(d.get("vitamin c")),
            vitamin_d=parse_quantity(d.get("vitamin d")),
            vitamin_e=parse_quantity(d.get("vitamin e")),
            vitamin_k=parse_quantity(d.get("vitamin k")),
            thiamine=parse_quantity(d.get("thiamine")),
            riboflavin=parse_quantity(d.get("riboflavin")),
            niacin=parse_quantity(d.get("niacin")),
            vitamin_b6=parse_quantity(d.get("vitamin b6")),
            folate=parse_quantity(d.get("folate")),
            vitamin_b12=parse_quantity(d.get("vitamin b12")),
            pantothenate=parse_quantity(d.get("pantothenate")),
            biotin=parse_quantity(d.get("biotin")),
            calcium=parse_quantity(d.get("calcium")),
            iron=parse_quantity(d.get("iron")),
            phosphorus=parse_quantity(d.get("phosphorus")),
            magnesium=parse_quantity(d.get("magnesium")),
            zinc=parse_quantity(d.get("zinc")),
            selenium=parse_quantity(d.get("selenium")),
            chromium=parse_quantity(d.get("chromium")),
        )


@dataclass
class Nutrients:
    per: Optional[str] = None
    calories: Optional[Quantity] = None
    macronutrients: Optional[Macronutrients] = None
    micronutrients_percent: Optional[MicronutrientsPercent] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Nutrients":
        return cls(
            per=d.get("per"),
            calories=parse_quantity(d.get("calories")),
            macronutrients=Macronutrients.from_dict(d["macronutrients"])
            if isinstance(d.get("macronutrients"), dict)
            else None,
            micronutrients_percent=MicronutrientsPercent.from_dict(d["micronutrients_percent"])
            if isinstance(d.get("micronutrients_percent"), dict)
            else None,
        )


@dataclass
class FoodItem:
    name: Optional[str] = None
    price: Optional[float] = None
    price_display: Optional[str] = None
    comparison_prices: list[ComparisonPrice] = field(default_factory=list)
    average_weight: Optional[str] = None
    product_number: Optional[str] = None
    description: Optional[str] = None
    ingredients: Optional[Ingredients] = None
    nutrients: Optional[Nutrients] = None
    breadcrumb: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "FoodItem":
        return cls(
            name=d.get("name"),
            price=d.get("price"),
            price_display=d.get("price_display"),
            comparison_prices=[
                ComparisonPrice.from_dict(c) for c in (d.get("comparison_prices") or [])
            ],
            average_weight=d.get("average_weight"),
            product_number=d.get("product_number"),
            description=d.get("description"),
            ingredients=Ingredients.from_dict(d["ingredients"])
            if isinstance(d.get("ingredients"), dict)
            else None,
            nutrients=Nutrients.from_dict(d["nutrients"]) if isinstance(d.get("nutrients"), dict) else None,
            breadcrumb=list(d.get("breadcrumb", []) or []),
        )