from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
import re
from pathlib import Path
from typing import Any


VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
HISTORY_PATH = Path("data/adjustment_history.json")


def ensure_history_file(path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_text("[]\n")


def load_adjustment_history(path: Path = HISTORY_PATH) -> list[dict[str, Any]]:
    ensure_history_file(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def append_adjustment_history(entry: dict[str, Any], path: Path = HISTORY_PATH) -> None:
    history = load_adjustment_history(path)
    history.append(entry)
    path.write_text(json.dumps(history[-100:], indent=2) + "\n")


def recipe_by_id(recipes: list[dict[str, Any]], recipe_id: str | None) -> dict[str, Any] | None:
    if not recipe_id:
        return None
    return next((recipe for recipe in recipes if recipe.get("id") == recipe_id), None)


def current_recipe_id(day: dict[str, Any], meal_type: str) -> str | None:
    if meal_type in {"breakfast", "snack"}:
        return day.get(meal_type)
    meal = day.get(meal_type) or {}
    return meal.get("recipeId")


def current_source(day: dict[str, Any], meal_type: str) -> str:
    if meal_type in {"breakfast", "snack"}:
        return "fresh"
    return (day.get(meal_type) or {}).get("source", "cook-today")


def recipe_minutes(recipe: dict[str, Any]) -> int:
    return int(recipe.get("prepMin", 0)) + int(recipe.get("cookMin", 0))


def recipe_contains(recipe: dict[str, Any], term: str) -> bool:
    haystack = " ".join(
        [
            recipe.get("name", ""),
            " ".join(recipe.get("ingredients", [])),
            " ".join(recipe.get("tags", [])),
        ]
    ).lower()
    return term.lower() in haystack


def is_allowed(recipe: dict[str, Any], profile: dict[str, Any]) -> bool:
    exclusions = set(profile.get("exclusions", []))
    blocked_flags = {
        "beef": "hasBeef",
        "fish": "hasFish",
        "pork": "hasPork",
        "chicken": "hasChicken",
        "lamb": "hasLamb",
        "shrimp": "hasShrimp",
        "egg": "hasEgg",
        "dairy": "hasDairy",
    }
    return not any(item in exclusions and recipe.get(flag) for item, flag in blocked_flags.items())


def passes_warm_filter(recipe: dict[str, Any], profile: dict[str, Any]) -> bool:
    return not profile.get("prefersWarm", True) or recipe.get("warm") is not False


def plan_context(
    week: dict[str, Any],
    profile: dict[str, Any],
    pantry: list[str],
    recipes: list[dict[str, Any]],
) -> dict[str, Any]:
    compact_plan: dict[str, Any] = {}
    for iso, day in week.get("plan", {}).items():
        compact_plan[iso] = {
            "eatingOut": day.get("eatingOut", False),
            "skippedMeals": day.get("skippedMeals", {}),
            "breakfast": current_recipe_id(day, "breakfast"),
            "snack": current_recipe_id(day, "snack"),
            "lunch": day.get("lunch"),
            "dinner": day.get("dinner"),
        }
    compact_recipes = [
        {
            "id": recipe.get("id"),
            "name": recipe.get("name"),
            "mealTypes": recipe.get("mealTypes", []),
            "cuisine": recipe.get("cuisine"),
            "kcal": recipe.get("kcal", 0),
            "protein": recipe.get("protein", 0),
            "carbs": recipe.get("carbs", 0),
            "fat": recipe.get("fat", 0),
            "minutes": recipe_minutes(recipe),
            "ingredients": recipe.get("ingredients", []),
            "tags": recipe.get("tags", []),
            "flags": {
                "hasDairy": recipe.get("hasDairy", False),
                "hasEgg": recipe.get("hasEgg", False),
                "hasChicken": recipe.get("hasChicken", False),
                "hasShrimp": recipe.get("hasShrimp", False),
                "hasLamb": recipe.get("hasLamb", False),
                "hasBeef": recipe.get("hasBeef", False),
                "hasFish": recipe.get("hasFish", False),
                "hasPork": recipe.get("hasPork", False),
            },
        }
        for recipe in recipes
    ]
    return {
        "week_start": week.get("startDate"),
        "plan": compact_plan,
        "profile": profile,
        "pantry": pantry,
        "available_recipes": compact_recipes,
    }


def resolve_day(request: str, week: dict[str, Any]) -> str | None:
    lower = request.lower()
    start = datetime.fromisoformat(week["startDate"]).date()
    week_days = [(start + timedelta(days=index)).isoformat() for index in range(7)]
    weekday_names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, weekday in weekday_names.items():
        if name in lower:
            for iso in week_days:
                if datetime.fromisoformat(iso).date().weekday() == weekday:
                    return iso
    if "tomorrow" in lower:
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        return tomorrow if tomorrow in week_days else None
    if "today" in lower:
        today = datetime.now().date().isoformat()
        return today if today in week_days else None
    return None


def meal_types_from_request(request: str) -> list[str]:
    lower = request.lower()
    found = [meal_type for meal_type in VALID_MEAL_TYPES if meal_type in lower]
    if found:
        return found
    if "meal" in lower:
        return ["lunch", "dinner"]
    return ["lunch", "dinner"]


def score_candidate(
    recipe: dict[str, Any],
    request: str,
    current: dict[str, Any] | None,
    pantry: list[str],
) -> int:
    lower = request.lower()
    score = 0
    if "protein" in lower:
        score += int(recipe.get("protein", 0)) * 4
        if current:
            score += max(0, int(recipe.get("protein", 0)) - int(current.get("protein", 0))) * 10
    if "lighter" in lower or "light" in lower:
        score += max(0, 800 - int(recipe.get("kcal", 0)))
        if current:
            score += max(0, int(current.get("kcal", 0)) - int(recipe.get("kcal", 0))) * 2
    if "dairy" in lower and ("reduce" in lower or "less" in lower):
        score += 500 if not recipe.get("hasDairy") else -500
    minute_match = re.search(r"(\d+)\s*(?:min|mins|minutes)", lower)
    if minute_match:
        max_minutes = int(minute_match.group(1))
        score += 500 if recipe_minutes(recipe) <= max_minutes else -1000
    use_match = re.search(r"use ([a-zA-Z ]+?)(?: before| this| today| tomorrow|$)", lower)
    if use_match and recipe_contains(recipe, use_match.group(1).strip()):
        score += 600
    pantry_lower = [item.lower() for item in pantry]
    for ingredient in recipe.get("ingredients", []):
        if any(item in ingredient.lower() for item in pantry_lower):
            score += 5
    return score


def best_replacement(
    meal_type: str,
    current_recipe_id_value: str | None,
    request: str,
    profile: dict[str, Any],
    pantry: list[str],
    recipes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current = recipe_by_id(recipes, current_recipe_id_value)
    candidates = [
        recipe
        for recipe in recipes
        if recipe.get("id") != current_recipe_id_value
        and meal_type in recipe.get("mealTypes", [])
        and is_allowed(recipe, profile)
        and passes_warm_filter(recipe, profile)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda recipe: score_candidate(recipe, request, current, pantry))


def mock_adjustment_response(
    request: str,
    week: dict[str, Any],
    profile: dict[str, Any],
    pantry: list[str],
    recipes: list[dict[str, Any]],
) -> dict[str, Any]:
    lower = request.lower()
    changes: list[dict[str, Any]] = []
    target_day = resolve_day(request, week)

    if "eating out" in lower or "eat out" in lower:
        if target_day:
            for meal_type in meal_types_from_request(request):
                if meal_type in {"lunch", "dinner"}:
                    changes.append(
                        {
                            "action": "skip",
                            "iso": target_day,
                            "meal_type": meal_type,
                            "reason": "User is eating out.",
                        }
                    )
        return {"changes": changes}

    target_days = [target_day] if target_day else list(week.get("plan", {}))
    target_meals = meal_types_from_request(request)
    if "dinner" in lower and "lunch" not in lower:
        target_meals = ["dinner"]

    for iso in target_days:
        day = week.get("plan", {}).get(iso, {})
        if day.get("eatingOut"):
            continue
        for meal_type in target_meals:
            current_id = current_recipe_id(day, meal_type)
            if not current_id:
                continue
            replacement = best_replacement(meal_type, current_id, request, profile, pantry, recipes)
            if replacement:
                changes.append(
                    {
                        "action": "replace",
                        "iso": iso,
                        "meal_type": meal_type,
                        "recipe_id": replacement["id"],
                        "reason": "Best match for the requested adjustment.",
                    }
                )
        if target_day and changes:
            break
        if len(changes) >= 8:
            break
    return {"changes": changes}


def generate_adjustment_response(
    request: str,
    week: dict[str, Any],
    profile: dict[str, Any],
    pantry: list[str],
    recipes: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None, bool]:
    api_key = os.getenv("OPENAI_API_KEY")
    context = plan_context(week, profile, pantry, recipes)
    if not api_key:
        return mock_adjustment_response(request, week, profile, pantry, recipes), "OPENAI_API_KEY is not set, using a mock response.", True
    try:
        from openai import OpenAI
    except ImportError:
        return mock_adjustment_response(request, week, profile, pantry, recipes), "The openai package is not installed, using a mock response.", True

    prompt = {
        "task": "Return JSON only. Modify an existing weekly meal plan by proposing changes. Preserve dietary exclusions and meal types.",
        "allowed_actions": [
            {"action": "replace", "fields": ["iso", "meal_type", "recipe_id", "reason"]},
            {"action": "skip", "fields": ["iso", "meal_type", "reason"]},
        ],
        "rules": [
            "Use only recipe_id values from available_recipes.",
            "meal_type must be breakfast, lunch, dinner, or snack.",
            "Replacement recipe must support the same meal_type.",
            "Do not use recipes violating profile.exclusions.",
            "Return at most 8 changes.",
        ],
        "user_request": request,
        "context": context,
    }
    try:
        response = OpenAI(api_key=api_key).chat.completions.create(
            model=os.getenv("OPENAI_ADJUST_MODEL", "gpt-4.1-mini"),
            messages=[
                {"role": "system", "content": "You are a careful meal-planning adjustment agent. Return strict JSON only."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content), None, False
    except Exception as exc:
        return None, f"AI adjustment failed: {exc}", False


def validate_adjustment_response(
    response: dict[str, Any],
    week: dict[str, Any],
    profile: dict[str, Any],
    recipes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(response, dict):
        return [], ["AI response was not a JSON object."]
    changes = response.get("changes")
    if not isinstance(changes, list):
        return [], ["AI response must include a changes list."]

    valid_changes: list[dict[str, Any]] = []
    for index, change in enumerate(changes, start=1):
        if not isinstance(change, dict):
            errors.append(f"Change {index} is not an object.")
            continue
        action = change.get("action")
        iso = change.get("iso")
        meal_type = change.get("meal_type")
        if action not in {"replace", "skip"}:
            errors.append(f"Change {index}: invalid action.")
            continue
        if iso not in week.get("plan", {}):
            errors.append(f"Change {index}: day is not in the current week.")
            continue
        if meal_type not in VALID_MEAL_TYPES:
            errors.append(f"Change {index}: invalid meal type.")
            continue
        day = week["plan"][iso]
        current_id = current_recipe_id(day, meal_type)
        if not current_id:
            errors.append(f"Change {index}: current {meal_type} is already empty.")
            continue
        current_recipe = recipe_by_id(recipes, current_id)
        preview = {
            "action": action,
            "iso": iso,
            "meal_type": meal_type,
            "current_recipe_id": current_id,
            "current_name": current_recipe.get("name", "Eating out") if current_recipe else "Eating out",
            "reason": str(change.get("reason", "Requested adjustment.")),
        }
        if action == "replace":
            recipe = recipe_by_id(recipes, change.get("recipe_id"))
            if not recipe:
                errors.append(f"Change {index}: replacement recipe is not in the recipe database.")
                continue
            if meal_type not in recipe.get("mealTypes", []):
                errors.append(f"Change {index}: replacement does not support {meal_type}.")
                continue
            if not is_allowed(recipe, profile):
                errors.append(f"Change {index}: replacement violates dietary exclusions.")
                continue
            preview.update(
                {
                    "recipe_id": recipe["id"],
                    "proposed_name": recipe["name"],
                }
            )
        else:
            if meal_type not in {"lunch", "dinner"}:
                errors.append(f"Change {index}: only lunch or dinner can be marked eating out.")
                continue
            preview["proposed_name"] = "Eating out"
        valid_changes.append(preview)
    return valid_changes, errors


def propagate_leftover(week: dict[str, Any], iso: str, meal_type: str, old_id: str, new_id: str) -> None:
    if meal_type not in {"lunch", "dinner"}:
        return
    days = sorted(week.get("plan", {}))
    if iso not in days:
        return
    for next_iso in days[days.index(iso) + 1:]:
        meal = week["plan"].get(next_iso, {}).get(meal_type) or {}
        if meal.get("source") == "cook-today":
            return
        if meal.get("source") == "leftover" and meal.get("recipeId") == old_id:
            meal["recipeId"] = new_id
            return


def apply_adjustments(week: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    next_week = deepcopy(week)
    for change in changes:
        day = next_week["plan"][change["iso"]]
        meal_type = change["meal_type"]
        old_id = current_recipe_id(day, meal_type)
        if change["action"] == "skip":
            day.setdefault("skippedMeals", {})[meal_type] = True
            day[meal_type] = None
            continue
        if meal_type in {"breakfast", "snack"}:
            day[meal_type] = change["recipe_id"]
        else:
            source = (day.get(meal_type) or {}).get("source", "cook-today")
            day[meal_type] = {"recipeId": change["recipe_id"], "source": source}
            if old_id and source == "cook-today":
                propagate_leftover(next_week, change["iso"], meal_type, old_id, change["recipe_id"])
    return next_week
