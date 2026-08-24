import toml

def read_toml(path):
    config = toml.load(path)
    weight_kg = config['metrics']["weight_kg"]
    height_cm = config['metrics']["height_cm"]

    print(weight_kg)
    print(height_cm)

def estimate_maintanence():
    """https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/dietary-reference-intakes/tables/equations-estimate-energy-requirement.html

    This website has been used to determine EER(estimate of energy requirement).
    """
    config = toml.load('config.toml')

    weight_kg = config['metrics']["weight_kg"]
    height_cm = config['metrics']["height_cm"]
    age = config['metrics']["age"]
    activity_level = config['metrics']["activity_level"]

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


if __name__ == "__main__":
    print(estimate_maintanence())