from dataclasses import dataclass
from datetime import datetime
from typing import Literal
import os
import csv



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
    @classmethod
    def construct_consumption(cls, d):
        ...


