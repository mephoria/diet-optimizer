from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from models.records import ConsumptionRecord


def json_default(value):
    if isinstance(value, date):
        return value.isoformat()

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


@dataclass
class Fridge:
    items: list[FridgeItem] = field(default_factory=list)

    def save_state(self, path: str | Path) -> None:
        # Preserve your existing project-root convention.
        root = Path(os.getcwd()).parent
        json_path = root / path

        # Serialize before opening the destination so serialization
        # errors don't truncate an existing file.
        content = json.dumps(
            asdict(self),
            indent=2,
            ensure_ascii=False,
            default=json_default,
        )

        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(content, encoding="utf-8")

    @classmethod
    def load_state(cls, path: str | Path) -> Fridge:
        root = Path(os.getcwd()).parent
        json_path = root / path

        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return cls(
            items=[
                FridgeItem(
                    meal=ConsumptionRecord.from_dict(item["meal"])
                )
                for item in data["items"]
            ]
        )

    
@dataclass
class FridgeItem:
    meal: ConsumptionRecord

    def eat(self, amount):
        multiplier = amount / self.meal.amount
        remaining_ratio = 1 - multiplier

        eaten = self.meal.multiply(multiplier)
        self.meal = self.meal.multiply(remaining_ratio)
        self.meal.item = f"{self.meal.item}'s leftovers, (%{remaining_ratio * 100} remain)"

        return eaten