"""
Food LP data builder + scipy.optimize.linprog solver.

Conventions (applied consistently everywhere):
  * Decision variable x_i = number of SERVINGS of food i, where one serving is
    the food's own `nutrients.per` amount (e.g. "170 g" or "1 cup").
  * Every nutrient value is taken per serving, exactly as listed in the data.
  * Macros are in grams, potassium/sodium/cholesterol in mg, micronutrients in
    % daily value, calories in kcal.  Every limit is expressed in those same
    units, so a row of A and its entry in b are always comparable.

Bugs fixed in this revision (on top of the earlier cleanup):
  1. Unit mismatch between A and b.  Limits were in kcal (e.g. 9*fat_g,
     4*protein_g, total_fibre*4, omega3*9, 10% of calories) but the food rows
     held grams.  Limits are now in grams (kcal / 9 for fat-type limits,
     kcal / 4 for sugars).
  2. Calories were divided by the serving size while every other nutrient was
     not, so the calorie row was on a different scale (per gram vs per
     serving) than the rest of the model.  Nothing is divided any more; x is
     servings, which is also what format_serving_amount assumes.
  3. compute_targets treated the macro percentages as percentages of GRAMS.
     They are percentages of CALORIES: fat is 9 kcal/g, so the old code
     produced ~171 g fat and ~3143 kcal instead of ~76 g and ~2286 kcal.
  4. Omega-3 (alpha-linolenic acid) is an Adequate Intake, i.e. a minimum, but
     it was applied as an upper bound.  It is now a lower bound.
  5. load_unique_foods dropped a food name as "seen" even if that first entry
     was invalid, hiding later valid duplicates; and it kept foods that had
     only one of calories/per, which crashed later.  Both are fixed.
  6. build_lp_inputs / build_scipy_vectors crashed on missing values
     (None / 0) - now read through one None-safe helper.
  7. solve_with_scipy: divide-by-zero when a scale was 0, O(n^2) and
     duplicate-unsafe `foods.index(item)`, and an infeasible model silently
     returned None with nothing to look at.

New:
  * report_constraint_match(): after the selected foods are printed, shows
    every constraint (min / max / achieved / status).
  * If the hard LP is infeasible, an "elastic" LP is solved that minimizes
    total relative constraint violation, so the report shows how close the
    best possible diet gets.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from food import FoodItem, parse_foods, extract_measurement, _get_quantity_value

NUTRIENT_PATHS = {
    "calories": ("calories",),
    "fat_total": ("macronutrients", "fat", "total"),
    "saturates": ("macronutrients", "fat", "saturates"),
    "trans": ("macronutrients", "fat", "trans"),
    "monounsaturates": ("macronutrients", "fat", "monounsaturates"),
    "polyunsaturates": ("macronutrients", "fat", "polyunsaturates"),
    "omega_3_fatty_acids": ("macronutrients", "fat", "omega_3_fatty_acids"),
    "total_carbohydrate": ("macronutrients", "carbohydrate", "total"),
    "sugars": ("macronutrients", "carbohydrate", "sugars"),
    "fiber": ("macronutrients", "carbohydrate", "fiber"),
    "other_carbohydrate": ("macronutrients", "carbohydrate", "other_carbohydrate"),
    "protein": ("macronutrients", "protein"),
    "potassium": ("macronutrients", "potassium"),
    "cholesterol": ("macronutrients", "cholesterol"),
    "sodium": ("macronutrients", "sodium"),
    "vitamin_a": ("micronutrients_percent", "vitamin_a"),
    "vitamin_c": ("micronutrients_percent", "vitamin_c"),
    "vitamin_d": ("micronutrients_percent", "vitamin_d"),
    "vitamin_e": ("micronutrients_percent", "vitamin_e"),
    "vitamin_k": ("micronutrients_percent", "vitamin_k"),
    "thiamine": ("micronutrients_percent", "thiamine"),
    "riboflavin": ("micronutrients_percent", "riboflavin"),
    "niacin": ("micronutrients_percent", "niacin"),
    "vitamin_b6": ("micronutrients_percent", "vitamin_b6"),
    "folate": ("micronutrients_percent", "folate"),
    "vitamin_b12": ("micronutrients_percent", "vitamin_b12"),
    "pantothenate": ("micronutrients_percent", "pantothenate"),
    "biotin": ("micronutrients_percent", "biotin"),
    "calcium": ("micronutrients_percent", "calcium"),
    "iron": ("micronutrients_percent", "iron"),
    "phosphorus": ("micronutrients_percent", "phosphorus"),
    "magnesium": ("micronutrients_percent", "magnesium"),
    "zinc": ("micronutrients_percent", "zinc"),
    "selenium": ("micronutrients_percent", "selenium"),
    "chromium": ("micronutrients_percent", "chromium"),
}

MICRONUTRIENT_KEYS = [
    "vitamin_a", "vitamin_c", "vitamin_d", "vitamin_e", "vitamin_k",
    "thiamine", "riboflavin", "niacin", "vitamin_b6", "folate",
    "vitamin_b12", "pantothenate", "biotin", "calcium", "iron",
    "phosphorus", "magnesium", "zinc", "selenium", "chromium",
]

# Nutrients that are pinned to a target (lb == ub unless a tolerance is given).
EQUALITY_NUTRIENTS = ("calories", "fat_total", "total_carbohydrate", "protein")

_UNITS = {"calories": "kcal", "potassium": "mg", "sodium": "mg", "cholesterol": "mg"}


def unit_for(nutrient: str) -> str:
    if nutrient in MICRONUTRIENT_KEYS:
        return "%DV"
    return _UNITS.get(nutrient, "g")


@dataclass
class Targets:
    protein_g: float
    carb_g: float
    fat_g: float
    total_calories: float
    alpha_linolenic_acid_n3: float
    total_fibre: float
    potassium_lb: Optional[float]
    potassium_ub: Optional[float]
    sodium_lb: Optional[float]
    sodium_ub: Optional[float]


def compute_targets(
    protein_intake: float = 200,
    protein_pct: float = 35,
    carb_pct: float = 35,
    fat_pct: float = 30,
    alpha_linolenic_acid_n3: float = 1.6,
    total_fibre: float = 38,
    potassium_lb: Optional[float] = 3400,
    potassium_ub: Optional[float] = None,
    sodium_lb: Optional[float] = 1500,
    sodium_ub: Optional[float] = 2300,
) -> Targets:
    """Macro percentages are shares of CALORIES (protein/carb 4 kcal/g, fat 9 kcal/g)."""
    if not np.isclose(protein_pct + carb_pct + fat_pct, 100.0):
        raise ValueError("protein_pct + carb_pct + fat_pct must equal 100")

    total_calories = 4 * protein_intake / (protein_pct / 100)
    carb_g = total_calories * (carb_pct / 100) / 4
    fat_g = total_calories * (fat_pct / 100) / 9
    return Targets(
        protein_g=protein_intake,
        carb_g=carb_g,
        fat_g=fat_g,
        total_calories=total_calories,
        alpha_linolenic_acid_n3=alpha_linolenic_acid_n3,
        total_fibre=total_fibre,
        potassium_lb=potassium_lb,
        potassium_ub=potassium_ub,
        sodium_lb=sodium_lb,
        sodium_ub=sodium_ub,
    )


def build_constraint_specs(t: Targets, macro_tolerance: float = 0.0):
    """Return an ordered list of (nutrient_key, direction, limit).

    direction is 'ub' or 'lb'. Both may be present for the same nutrient_key
    -- that is intentional and produces two rows.  All limits are in the same
    units as the food data (see module docstring).

    macro_tolerance: fractional band (e.g. 0.02 = +/-2%) applied to the four
    pinned nutrients (calories, fat, carbs, protein).  0.0 keeps them as exact
    equalities, which is fragile because listed calories rarely equal
    4*P + 4*C + 9*F exactly.
    """
    hi = 1 + macro_tolerance
    lo = 1 - macro_tolerance
    cal = t.total_calories

    micronutrient_ub = {k: 200 for k in MICRONUTRIENT_KEYS}
    micronutrient_lb = {k: 70 for k in MICRONUTRIENT_KEYS}

    ub_values = {
        "calories": cal * hi,
        "fat_total": t.fat_g * hi,
        "saturates_trans": (cal * 0.10) / 9,      # <=10% of kcal, in grams
        "monounsaturates": None,
        "polyunsaturates": (cal * 0.112) / 9,     # <=11.2% of kcal, in grams
        "omega_3_fatty_acids": None,
        "total_carbohydrate": t.carb_g * hi,
        "fiber": None,
        "sugars": (cal * 0.10) / 4,               # <=10% of kcal, in grams
        "other_carbohydrate": None,
        "protein": t.protein_g * hi,
        "cholesterol": None,
        "potassium": t.potassium_ub,
        "sodium": t.sodium_ub,
        **micronutrient_ub,
    }

    lb_values = {
        "calories": cal * lo,
        "fat_total": t.fat_g * lo,
        "saturates_trans": None,
        "monounsaturates": None,
        "polyunsaturates": (cal * 0.056) / 9,     # >=5.6% of kcal, in grams
        "omega_3_fatty_acids": t.alpha_linolenic_acid_n3,  # AI = minimum, grams
        "total_carbohydrate": t.carb_g * lo,
        "fiber": t.total_fibre,                   # grams
        "sugars": None,
        "other_carbohydrate": None,
        "protein": t.protein_g * lo,
        "potassium": t.potassium_lb,
        "cholesterol": None,
        "sodium": t.sodium_lb,
        **micronutrient_lb,
    }

    specs = []
    for nutrient, limit in ub_values.items():
        if limit is not None:
            specs.append((nutrient, "ub", limit))
    for nutrient, limit in lb_values.items():
        if limit is not None:
            specs.append((nutrient, "lb", limit))
    return specs


def build_b_vector(specs) -> np.ndarray:
    return np.array([-limit if direction == "lb" else limit for _, direction, limit in specs])


def _qty(nutrients_obj, path) -> float:
    """None-safe wrapper around _get_quantity_value."""
    value = _get_quantity_value(nutrients_obj, path)
    return 0.0 if value is None else float(value)


def get_nutrient_value(nutrients_obj, nutrient_key: str) -> float:
    """One nutrient's amount PER SERVING (per `nutrients_obj.per`)."""
    if nutrient_key == "saturates_trans":
        return _qty(nutrients_obj, NUTRIENT_PATHS["saturates"]) + _qty(
            nutrients_obj, NUTRIENT_PATHS["trans"]
        )
    return _qty(nutrients_obj, NUTRIENT_PATHS[nutrient_key])


def build_food_row(nutrients_obj, specs) -> list:
    """One entry per constraint spec, in the same order as `specs`/`b`."""
    row = []
    for nutrient, direction, _limit in specs:
        # Lower bounds must be flipped: A_lb @ x >= L  ->  -A_lb @ x <= -L
        multiplier = -1 if direction == "lb" else 1
        row.append(get_nutrient_value(nutrients_obj, nutrient) * multiplier)
    return row


def load_unique_foods() -> list:
    seen = set()
    result = []
    for item in parse_foods():
        if item.name in seen:
            continue
        n = item.nutrients
        # Need calories AND a serving definition to use the food at all.
        if not n or n.calories is None or n.per is None:
            continue
        seen.add(item.name)  # only mark as seen once we've accepted it
        result.append(item)
    return result


def build_lp_inputs(foods: list, specs):
    """Build A (constraints x foods), b (constraints,), c (kcal per serving)."""
    c = []
    rows = []
    for item in foods:
        c.append(get_nutrient_value(item.nutrients, "calories"))
        rows.append(build_food_row(item.nutrients, specs))

    A = np.array(rows).T  # (n_constraints, n_foods)
    b = build_b_vector(specs)
    return A, b, np.array(c)


def build_scipy_vectors(foods: list):
    """Per-serving calories/protein/carbs/fat/cost vectors, aligned to `foods`.

    NOTE: the food data model doesn't include price. If your FoodItem
    exposes a real `cost`/`price` field (per serving), it is used; otherwise
    this falls back to 1.0/serving so the objective still runs end-to-end.
    """
    calories, protein, carbs, fat, cost, names = [], [], [], [], [], []
    for item in foods:
        n = item.nutrients
        calories.append(get_nutrient_value(n, "calories"))
        protein.append(get_nutrient_value(n, "protein"))
        carbs.append(get_nutrient_value(n, "total_carbohydrate"))
        fat.append(get_nutrient_value(n, "fat_total"))
        cost.append(getattr(item, "cost", None) or getattr(item, "price", None) or 1.0)
        names.append(item.name)

    return (
        np.array(calories),
        np.array(protein),
        np.array(carbs),
        np.array(fat),
        np.array(cost),
        names,
    )


def format_serving_amount(item: FoodItem, units: float) -> str:
    """
    Turn a number of servings into a human-readable amount.

    Example:
      per = "170 g", units = 2.5  -> "425.00 g (2.500 x 170 g)"
    """
    per_amount, per_label = extract_measurement(item.nutrients.per)

    if per_amount is None or not per_label:
        return f"{units:.3f} x {item.nutrients.per or 'serving'}"

    total_amount = units * per_amount
    return f"{total_amount:.2f} {per_label} ({units:.3f} x {per_amount:g} {per_label})"


# --------------------------------------------------------------------------
# Constraint-match report
# --------------------------------------------------------------------------

def report_constraint_match(specs, A, servings, rel_tol=1e-6, abs_tol=1e-6, verbose=True):
    """Compare what the diet actually delivers against every constraint.

    Achieved amounts are recomputed as A @ servings (sign-corrected for lower
    bounds), independently of anything the solver reports.

    Returns a list of dicts, one per nutrient:
      nutrient, unit, lb, ub, achieved, status, violation, off_by_pct
    where status is one of: OK, OK (at min), OK (at max), OK (on target),
    BELOW MIN, ABOVE MAX.
    """
    activity = A @ servings

    grouped = {}
    for (nutrient, direction, limit), act in zip(specs, activity):
        g = grouped.setdefault(nutrient, {"lb": None, "ub": None, "achieved": 0.0})
        g[direction] = limit
        g["achieved"] = -act if direction == "lb" else act

    results = []
    for nutrient, g in grouped.items():
        ach, lb, ub = g["achieved"], g["lb"], g["ub"]
        limits = [v for v in (lb, ub) if v is not None]
        tol = max(abs_tol, rel_tol * max(abs(v) for v in limits))
        at_tol = max(abs_tol, 1e-4 * max(abs(v) for v in limits))

        violation, ref = 0.0, None
        if lb is not None and ach < lb - tol:
            status, violation, ref = "BELOW MIN", lb - ach, lb
        elif ub is not None and ach > ub + tol:
            status, violation, ref = "ABOVE MAX", ach - ub, ub
        elif lb is not None and ub is not None and abs(ub - lb) <= at_tol:
            status = "OK (on target)"
        elif lb is not None and abs(ach - lb) <= at_tol:
            status = "OK (at min)"
        elif ub is not None and abs(ach - ub) <= at_tol:
            status = "OK (at max)"
        else:
            status = "OK"

        off_by_pct = 100 * violation / abs(ref) if ref else violation
        results.append({
            "nutrient": nutrient,
            "unit": unit_for(nutrient),
            "lb": lb,
            "ub": ub,
            "achieved": ach,
            "status": status,
            "violation": violation,
            "off_by_pct": off_by_pct,
        })

    if verbose:
        def fmt(v):
            return f"{v:>11.2f}" if v is not None else f"{'-':>11s}"

        print("\nConstraint match:")
        print(f"  {'Nutrient':22s} {'Min':>11s} {'Max':>11s} {'Achieved':>11s}  {'Status':16s} Off by")
        print("  " + "-" * 82)
        for r in results:
            label = f"{r['nutrient']} ({r['unit']})"
            off = f"{r['off_by_pct']:.2f}%" if r["violation"] > 0 else ""
            print(
                f"  {label:22s} {fmt(r['lb'])} {fmt(r['ub'])} {fmt(r['achieved'])}  "
                f"{r['status']:16s} {off}"
            )

        n_ok = sum(r["status"].startswith("OK") for r in results)
        print(f"\n  {n_ok}/{len(results)} nutrient constraints satisfied.")
        bad = [r for r in results if not r["status"].startswith("OK")]
        if bad:
            worst = max(bad, key=lambda r: r["off_by_pct"])
            print(
                f"  Worst miss: {worst['nutrient']} ({worst['status'].lower()}, "
                f"off by {worst['off_by_pct']:.2f}%)."
            )
    return results


# --------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------

def _solve_elastic(c, A, b, bounds, violation_weight):
    """Minimize c@x + weight * sum(relative violation).

    Each row becomes  A_i x - s_i <= b_i  with slack s_i >= 0, and s_i is
    penalized in proportion to |b_i| so every constraint counts by percent.
    """
    from scipy.optimize import linprog

    m, n = A.shape
    scale = np.maximum(np.abs(b), 1.0)
    A_el = np.hstack([A, -np.eye(m)])
    c_el = np.concatenate([c, violation_weight / scale])
    bounds_el = list(bounds) + [(0, None)] * m
    return linprog(c_el, A_ub=A_el, b_ub=b, bounds=bounds_el, method="highs")


def solve_with_scipy(
    foods: list,             # list[FoodItem]
    specs,
    A: np.ndarray,
    b: np.ndarray,
    calories: np.ndarray,
    cost: np.ndarray,
    max_units_per_food: float = 10.0,
    w_cal: float = 0.5,
    w_cost: float = 0.5,
    fallback_to_soft: bool = True,
    violation_weight: float = 1e4,
):
    from scipy.optimize import linprog

    cal_scale = calories.max() or 1.0
    cost_scale = cost.max() or 1.0
    c = w_cal * (calories / cal_scale) + w_cost * (cost / cost_scale)

    bounds = [(0, max_units_per_food) for _ in foods]
    res = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method="highs")

    print("=== scipy.optimize.linprog (full constraints) ===")
    print("Status:", res.message)

    if res.success:
        servings = res.x
    elif res.status == 2 and fallback_to_soft:  # 2 = infeasible
        print("\nNo diet satisfies every constraint. Solving for the minimum-violation "
              "diet instead (see 'Constraint match' below).")
        res_soft = _solve_elastic(c, A, b, bounds, violation_weight)
        if not res_soft.success:
            print("Elastic solve failed:", res_soft.message)
            return None
        servings = res_soft.x[: len(foods)]
    else:
        return None

    print("\nSelected foods:")
    for item, per_serving_kcal, units in zip(foods, calories, servings):
        if units > 1e-6:
            amount = format_serving_amount(item, units)
            print(f"  {item.name:35s} {amount:35s}  {per_serving_kcal * units:.0f} kcal")

    print(f"\nTotal calories : {calories @ servings:.1f} kcal")
    print(f"Total cost     : ${cost @ servings:.2f}")

    report_constraint_match(specs, A, servings)
    return servings


if __name__ == "__main__":
    targets = compute_targets()
    specs = build_constraint_specs(targets)
    foods = load_unique_foods()
    A, b, c = build_lp_inputs(foods, specs)

    print(f"A shape: {A.shape}")
    print(f"b shape: {b.shape}")
    print(f"c shape: {c.shape}")
    assert A.shape[0] == b.shape[0], "constraint count mismatch between A and b"
    assert A.shape[1] == c.shape[0], "food count mismatch between A and c"

    calories, protein, carbs, fat, cost, food_names = build_scipy_vectors(foods)
    solve_with_scipy(
        foods,
        specs,
        A, b,
        calories, cost,
        max_units_per_food=10.0,
        w_cal=0.5,
        w_cost=0.5,
    )