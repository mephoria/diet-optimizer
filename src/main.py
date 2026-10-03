from models.records import WeightRecord
from datetime import date

weight_today = WeightRecord(
    date=date.today(),
    weight=210,
    unit='lb'
    )

weight_today.to_csv('src/data/weight.csv')

