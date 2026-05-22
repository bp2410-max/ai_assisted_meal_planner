from __future__ import annotations

import csv
import io
import json
from typing import Any


def recipe_by_id(recipes: list[dict[str, Any]], recipe_id: str | None) -> dict[str, Any] | None:
    if not recipe_id:
        return None
    return next((recipe for recipe in recipes if recipe.get("id") == recipe_id), None)


def meal_recipe_id(day: dict[str, Any], meal_type: str) -> str | None:
    if meal_type in {"breakfast", "snack"}:
        return day.get(meal_type)
    meal = day.get(meal_type) or {}
    return meal.get("recipeId")


def meal_name(day: dict[str, Any], meal_type: str, recipes: list[dict[str, Any]]) -> str:
    if day.get("eatingOut") or (meal_type in {"lunch", "dinner"} and day.get(meal_type) is None):
        return "Eating out"
    recipe = recipe_by_id(recipes, meal_recipe_id(day, meal_type))
    return recipe.get("name", "-") if recipe else "-"


def day_macros(day: dict[str, Any], recipes: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    if day.get("eatingOut"):
        return totals
    for meal_type in ("breakfast", "snack", "lunch", "dinner"):
        recipe = recipe_by_id(recipes, meal_recipe_id(day, meal_type))
        if not recipe:
            continue
        for key in totals:
            totals[key] += int(recipe.get(key, 0))
    return totals


def weekly_plan_rows(weekly_plan: dict[str, Any], recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for iso in sorted(weekly_plan.get("plan", {})):
        day = weekly_plan["plan"][iso]
        macros = day_macros(day, recipes)
        rows.append(
            {
                "day": iso,
                "breakfast": meal_name(day, "breakfast", recipes),
                "lunch": meal_name(day, "lunch", recipes),
                "dinner": meal_name(day, "dinner", recipes),
                "kcal": macros["kcal"],
                "protein": macros["protein"],
            }
        )
    return rows


def weekly_plan_markdown(weekly_plan: dict[str, Any], recipes: list[dict[str, Any]]) -> str:
    lines = [f"# Weekly Meal Plan", "", f"Week starts: {weekly_plan.get('startDate', '-')}", ""]
    lines.append("| Day | Breakfast | Lunch | Dinner | Calories | Protein |")
    lines.append("|---|---|---|---|---:|---:|")
    for row in weekly_plan_rows(weekly_plan, recipes):
        lines.append(
            f"| {row['day']} | {row['breakfast']} | {row['lunch']} | {row['dinner']} | "
            f"{row['kcal']} | {row['protein']}g |"
        )
    return "\n".join(lines) + "\n"


def weekly_plan_text(weekly_plan: dict[str, Any], recipes: list[dict[str, Any]]) -> str:
    lines = ["Weekly Meal Plan", f"Week starts: {weekly_plan.get('startDate', '-')}", ""]
    for row in weekly_plan_rows(weekly_plan, recipes):
        lines.extend(
            [
                row["day"],
                f"  Breakfast: {row['breakfast']}",
                f"  Lunch: {row['lunch']}",
                f"  Dinner: {row['dinner']}",
                f"  Summary: {row['kcal']} kcal, {row['protein']}g protein",
                "",
            ]
        )
    return "\n".join(lines)


def grocery_markdown(groups: dict[str, list[dict[str, str]]]) -> str:
    lines = ["# Grocery List", ""]
    if not groups:
        return "# Grocery List\n\nNo grocery items.\n"
    for category, items in groups.items():
        if not items:
            continue
        lines.extend([f"## {category}", ""])
        for item in items:
            source = f" ({item.get('fromRecipe')})" if item.get("fromRecipe") else ""
            lines.append(f"- {item.get('text', '')}{source}")
        lines.append("")
    return "\n".join(lines)


def grocery_text(groups: dict[str, list[dict[str, str]]]) -> str:
    lines = ["Grocery List", ""]
    if not groups:
        return "Grocery List\n\nNo grocery items.\n"
    for category, items in groups.items():
        if not items:
            continue
        lines.append(category)
        for item in items:
            source = f" ({item.get('fromRecipe')})" if item.get("fromRecipe") else ""
            lines.append(f"  - {item.get('text', '')}{source}")
        lines.append("")
    return "\n".join(lines)


def grocery_csv(groups: dict[str, list[dict[str, str]]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["category", "item", "from_recipe"])
    writer.writeheader()
    for category, items in groups.items():
        for item in items:
            writer.writerow(
                {
                    "category": category,
                    "item": item.get("text", ""),
                    "from_recipe": item.get("fromRecipe", ""),
                }
            )
    return output.getvalue()


def prep_plan_markdown(prep_plan: dict[str, list[str]]) -> str:
    lines = ["# Weekly Prep Plan", ""]
    if not prep_plan:
        return "# Weekly Prep Plan\n\nNo prep plan available.\n"
    for section, tasks in prep_plan.items():
        if not tasks:
            continue
        lines.extend([f"## {section}", ""])
        for task in tasks:
            lines.append(f"- {task}")
        lines.append("")
    return "\n".join(lines)


def prep_plan_text(prep_plan: dict[str, list[str]]) -> str:
    lines = ["Weekly Prep Plan", ""]
    if not prep_plan:
        return "Weekly Prep Plan\n\nNo prep plan available.\n"
    for section, tasks in prep_plan.items():
        if not tasks:
            continue
        lines.append(section)
        for task in tasks:
            lines.append(f"  - {task}")
        lines.append("")
    return "\n".join(lines)


def monthly_report_markdown(monthly_report: Any) -> str:
    if not monthly_report:
        return "# Monthly Report\n\nNo monthly report available.\n"
    if isinstance(monthly_report, str):
        return monthly_report if monthly_report.startswith("#") else f"# Monthly Report\n\n{monthly_report}\n"
    return "# Monthly Report\n\n```json\n" + json.dumps(monthly_report, indent=2) + "\n```\n"


def monthly_report_text(monthly_report: Any) -> str:
    if not monthly_report:
        return "Monthly Report\n\nNo monthly report available.\n"
    if isinstance(monthly_report, str):
        return monthly_report
    return "Monthly Report\n\n" + json.dumps(monthly_report, indent=2)


def json_backup(
    profile: dict[str, Any],
    pantry: list[str],
    weekly_plan: dict[str, Any] | None,
    generated_recipes: list[dict[str, Any]],
    completed_meals: dict[str, Any],
) -> str:
    payload = {
        "profile": profile,
        "pantry": pantry,
        "weekly_plan": weekly_plan,
        "generated_recipes": generated_recipes,
        "completed_meals": completed_meals,
    }
    return json.dumps(payload, indent=2) + "\n"
