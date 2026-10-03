import toml
import json

PATH_TOML = 'config.toml'

def read_toml():
    config = toml.load(PATH_TOML)
    weight_kg = config['metrics']["weight_kg"]
    height_cm = config['metrics']["height_cm"]
    age = config['metrics']["age"]
    activity_level = config['metrics']["activity_level"]
    gender = config['metrics']["gender"]

    return weight_kg, height_cm, age, activity_level, gender

def estimate_maintanence():
    """https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/dietary-reference-intakes/tables/equations-estimate-energy-requirement.html

    This website has been used to determine EER(estimate of energy requirement).
    """

    weight_kg, height_cm, age, activity_level, gender = read_toml()

    if activity_level:
        if activity_level == 'inactive':
            maintanence = 753.07 - (10.83 * age) + (6.50 * height_cm) + (14.10 * weight_kg)
        if activity_level == 'low_active':
            maintanence = 581.47 - (10.83 * age) + (8.30 * height_cm) + (14.94 * weight_kg)
        if activity_level == 'active':
            maintanence = 1,004.82 - (10.83 * age) + (6.52 * height_cm) + (15.91 * weight_kg)
        if activity_level == 'very_active':
            maintanence = -517.88 - (10.83 * age) + (15.61 * height_cm) + (19.11 * weight_kg)

        return maintanence
    else:
        raise ValueError('Missing activity_level.')

def get_ranges():
    weight_kg, height_cm, age, activity_level, gender = read_toml()
    datas = ["element", "macronutrient", "vitamin"]
    for data in datas: 
        with open(f'health_canada_{data}_dris.json', 'r', encoding='utf-8') as f:
            raw = f.read()
        file = json.loads(raw)
        #get life stage

        if gender == "male":
            type = "males"
        if gender == "female":
            type = "females"
        
        if age > 70:
            stage = ">70 y"
        if 51 <= age <= 70:
            stage = "51–70 y"
        if 31 <= age <= 50:
            stage = "31–50 y"
        if 19 <= age <= 30:
            stage = "19–30 y"
        if 14 <= age <= 18:
            stage = "14–18 y"
        if 9 <= age <= 13:
            stage = "14–18 y"

        bounds = {}

        if data == 'element':
            key = 'elements'
        if data == 'macronutrient':
            key = 'macronutrients'
        if data == 'vitamin':
            key = 'vitamins'

        for element in file[key]:
            values = file[key][element]["values"][type][stage]

            if "UL" in values:
                upper_bound = values["UL"]
            else:
                upper_bound = None
            if "RDA_AI" in values:
                lower_bound = values["RDA_AI"]
            else:
                if "AI" in values:
                    lower_bound = values["AI"]
                else:
                    lower_bound = None

            if (not lower_bound) and (not upper_bound):
                continue

            bounds[element] = {"lower_bound": lower_bound, "upper_bound": upper_bound}

        print(bounds)



if __name__ == "__main__":
    get_ranges()