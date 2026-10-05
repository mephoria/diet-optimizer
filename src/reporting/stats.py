import csv

from models.records import zero_consumption_record, ConsumptionRecord

def day_stats(date):
    total = zero_consumption_record()
    with open('data/food_intake.csv', 'r', newline='', encoding='utf-8') as f:
        dict_reader = csv.DictReader(f)

        for row in dict_reader:
            if row['date'] == str(date):
                # do addition with consumption records
                total += ConsumptionRecord.from_csv_row(row)

    return total