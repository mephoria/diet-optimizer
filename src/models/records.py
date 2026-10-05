from dataclasses import dataclass, asdict
from datetime import datetime, date
from typing import Literal
from difflib import get_close_matches

from models.food import Macronutrients, MicronutrientsPercent, Quantity, FatBreakdown, CarbohydrateBreakdown
from dataclasses import dataclass, asdict, fields, replace

import os
import csv
import json



@dataclass
class WeightRecord:
    date: datetime
    weight: float
    unit: Literal['lb', 'kg']

    def to_csv(self, path):
        root = os.path.dirname(os.getcwd())
        csv_path = os.path.join(root, path)
        exists = os.path.exists(csv_path)

        # if file doesnt exist
        if not exists:
            with open(csv_path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(['date', 'weight', 'unit'])
                writer.writerow([self.date, self.weight, self.unit])

        if exists:
            with open(csv_path, 'a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([self.date, self.weight, self.unit])

@dataclass
class WorkoutRecord:
    date: datetime
    type: str
    weight: float
    unit: Literal['lb', 'kg']
    reps: int

    def to_csv(self, path):
            root = os.path.dirname(os.getcwd())
            csv_path = os.path.join(root, path)
            exists = os.path.exists(csv_path)
    
            # if file doesnt exist
            if not exists:
                with open(csv_path, "w", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)

                    writer.writerow(['date', 'type', 'weight', 'unit', 'reps'])
                    writer.writerow([self.date, self.type, self.weight, self.unit, self.reps])
    
            if exists:
                with open(csv_path, 'a', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)

                    writer.writerow([self.date, self.type, self.weight, self.unit, self.reps])

@dataclass
class ConsumptionRecord:
    date: datetime
    item: str
    amount: float
    calories: int
    macronutrients: Macronutrients
    micronutrients_percent: MicronutrientsPercent

    @classmethod
    def construct_consumption(cls, name, amount, food_list, cutoff):
        """food_list is expected to have items of FoodItem"""
        food_names = {
            food.name: food 
            for food in food_list 
            if food.name is not None
        }

        key = closest_string(name, list(food_names), cutoff)
        food = food_names[key]
        calories, macronutrients, micronutrients_percent = food.nutrients.compute_amount(amount)

        return cls(
            date=date.today(),
            item=key,
            amount=amount,
            calories=calories,
            macronutrients=macronutrients,
            micronutrients_percent=micronutrients_percent
        )

    def to_csv(self, path):
        # Match the path handling in your WorkoutRecord.
        root = os.path.dirname(os.getcwd())
        csv_path = os.path.join(root, path)

        # Create the destination folder if needed.
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

        write_header = (
            not os.path.exists(csv_path)
            or os.path.getsize(csv_path) == 0
        )

        with open(csv_path, "a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)

            if write_header:
                writer.writerow(["date","item","amount","calories","macronutrients","micronutrients_percent"])

            writer.writerow([self.date, self.item, self.amount, self.calories, json.dumps(asdict(self.macronutrients)), json.dumps(asdict(self.micronutrients_percent))])
    def __add__(self, other):
        if not isinstance(other, ConsumptionRecord):
            return NotImplemented

        if self.date != other.date:
            raise ValueError("Consumption records must have the same date")

        return replace(
            self,
            amount=self.amount + other.amount,
            calories=self.calories + other.calories,
            macronutrients=add_nutrients(
                self.macronutrients,
                other.macronutrients,
            ),
            micronutrients_percent=add_nutrients(
                self.micronutrients_percent,
                other.micronutrients_percent,
            ),
        )

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "ConsumptionRecord":
        return cls(
            date=date.fromisoformat(row["date"]),
            item=row["item"],
            amount=float(row["amount"]),
            calories=float(row["calories"]),
            macronutrients=macronutrients_from_dict(
                json.loads(row["macronutrients"])
            ),
            micronutrients_percent=quantity_fields_from_dict(
                MicronutrientsPercent,
                json.loads(row["micronutrients_percent"]),
            ),
        )

    def __repr__(self):
        def format_quantity(quantity):
            if quantity is None or quantity.value is None:
                return None

            unit = quantity.unit or ""
            return f"{quantity.value:,.2f} {unit}".rstrip()

        def add_quantity(lines, label, quantity, indent=2):
            formatted = format_quantity(quantity)
            if formatted is not None:
                lines.append(f"{' ' * indent}{label}: {formatted}")

        lines = [
            f"{self.item} | {self.date.isoformat()}",
            f"Amount: {self.amount:,.2f}",
            f"Calories: {self.calories:,.2f}",
        ]

        macros = self.macronutrients

        if macros is not None:
            lines.append("Macronutrients:")

            if macros.fat is not None:
                add_quantity(lines, "Fat", macros.fat.total)

                for field in fields(macros.fat):
                    if field.name != "total":
                        add_quantity(
                            lines,
                            field.name.replace("_", " ").capitalize(),
                            getattr(macros.fat, field.name),
                            indent=4,
                        )

            if macros.carbohydrate is not None:
                add_quantity(
                    lines, "Carbohydrate", macros.carbohydrate.total
                )

                for field in fields(macros.carbohydrate):
                    if field.name != "total":
                        add_quantity(
                            lines,
                            field.name.replace("_", " ").capitalize(),
                            getattr(macros.carbohydrate, field.name),
                            indent=4,
                        )

            for name in ("protein", "potassium", "cholesterol", "sodium"):
                add_quantity(
                    lines,
                    name.capitalize(),
                    getattr(macros, name),
                )

        micros = self.micronutrients_percent

        if micros is not None:
            micro_lines = []

            for field in fields(micros):
                add_quantity(
                    micro_lines,
                    field.name.replace("_", " ").capitalize(),
                    getattr(micros, field.name),
                )

            if micro_lines:
                lines.append("Micronutrients (% daily value):")
                lines.extend(micro_lines)

        return "\n".join(lines)

# UTILITIES/HELPERS

def closest_string(
    query: str,
    candidates: list[str],
    cutoff: float = 0.4,
) -> str | None:
    # Exact match against the original food names.
    for candidate in candidates:
        if query in candidate:
            return candidate

    normalized = [text.strip().casefold() for text in candidates]
    normalized_query = query.strip().casefold()

    # Match ignoring capitalization and surrounding whitespace.
    if normalized_query in normalized:
        return candidates[normalized.index(normalized_query)]

    # Fall back to fuzzy matching.
    matches = get_close_matches(
        normalized_query,
        normalized,
        n=1,
        cutoff=cutoff,
    )

    if not matches:
        return None

    return candidates[normalized.index(matches[0])]

def add_nutrients(left, right):
    if left is None and right is None:
        return None

    if left is None:
        return add_nutrients(right, None)

    if right is not None and type(left) is not type(right):
        raise TypeError("Cannot add different nutrient types")

    if isinstance(left, Quantity):
        if right is not None and left.unit != right.unit:
            raise ValueError(
                f"Cannot add quantities with units "
                f"{left.unit!r} and {right.unit!r}"
            )

        left_value = left.value if left.value is not None else 0.0
        right_value = (
            right.value
            if right is not None and right.value is not None
            else 0.0
        )

        return replace(left, value=left_value + right_value)

    return replace(
        left,
        **{
            field.name: add_nutrients(
                getattr(left, field.name),
                getattr(right, field.name) if right is not None else None,
            )
            for field in fields(left)
        },
    )

def zero_consumption_record() -> ConsumptionRecord:
    def zero_fields(cls, unit):
        return cls(**{
            field.name: Quantity(value=0.0, unit=unit)
            for field in fields(cls)
        })

    return ConsumptionRecord(
        date=date.today(),
        item="Total",
        amount=0.0,
        calories=0.0,
        macronutrients=Macronutrients(
            fat=zero_fields(FatBreakdown, "g"),
            carbohydrate=zero_fields(CarbohydrateBreakdown, "g"),
            protein=Quantity(0.0, "g"),
            potassium=Quantity(0.0, "mg"),
            cholesterol=Quantity(0.0, "mg"),
            sodium=Quantity(0.0, "mg"),
        ),
        micronutrients_percent=zero_fields(
            MicronutrientsPercent,
            "%",
        ),
    )

def quantity_from_dict(data):
    return Quantity(**data) if data is not None else None


def quantity_fields_from_dict(cls, data):
    """Rebuild a dataclass whose fields are all optional Quantities."""
    if data is None:
        return None

    return cls(**{
        field.name: quantity_from_dict(data.get(field.name))
        for field in fields(cls)
    })


def macronutrients_from_dict(data):
    if data is None:
        return None

    values = {}

    for field in fields(Macronutrients):
        raw = data.get(field.name)

        if field.name == "fat":
            values[field.name] = quantity_fields_from_dict(
                FatBreakdown, raw
            )
        elif field.name == "carbohydrate":
            values[field.name] = quantity_fields_from_dict(
                CarbohydrateBreakdown, raw
            )
        else:
            values[field.name] = quantity_from_dict(raw)

    return Macronutrients(**values)