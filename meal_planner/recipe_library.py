from __future__ import annotations

from math import ceil
from typing import Any


def source_label(recipe: dict[str, Any]) -> str:
    return "AI-generated" if recipe.get("generated") or recipe.get("source") == "ai_generated" else "Static recipe"


def recipe_minutes(recipe: dict[str, Any]) -> int:
    return int(recipe.get("prepMin", 0)) + int(recipe.get("cookMin", 0))


def pantry_match_score(recipe: dict[str, Any], pantry: list[str]) -> int:
    pantry_lower = [item.lower() for item in pantry if item]
    score = 0
    for ingredient in recipe.get("ingredients", []):
        lower = ingredient.lower()
        if any(item in lower for item in pantry_lower):
            score += 1
    return score


def search_recipes(recipes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return recipes
    return [
        recipe
        for recipe in recipes
        if q in recipe.get("name", "").lower()
        or q in " ".join(recipe.get("ingredients", [])).lower()
        or q in " ".join(recipe.get("tags", [])).lower()
    ]


def filter_recipes(
    recipes: list[dict[str, Any]],
    meal_type: str = "All",
    cuisine: str = "All",
    source: str = "All",
    high_protein: bool = False,
    warm_meal: bool = False,
    meal_prep: bool = False,
    exclusions: list[str] | None = None,
) -> list[dict[str, Any]]:
    exclusions = exclusions or []
    filtered = recipes
    if meal_type != "All":
        filtered = [recipe for recipe in filtered if meal_type in recipe.get("mealTypes", [])]
    if cuisine != "All":
        filtered = [recipe for recipe in filtered if recipe.get("cuisine") == cuisine]
    if source == "Static":
        filtered = [recipe for recipe in filtered if not recipe.get("generated")]
    if source == "AI-generated":
        filtered = [recipe for recipe in filtered if recipe.get("generated") or recipe.get("source") == "ai_generated"]
    if high_protein:
        filtered = [recipe for recipe in filtered if int(recipe.get("protein", 0)) >= 25]
    if warm_meal:
        filtered = [recipe for recipe in filtered if recipe.get("warm") is not False]
    if meal_prep:
        filtered = [recipe for recipe in filtered if recipe.get("prePrep") or int(recipe.get("servings", 1)) >= 2]
    for exclusion in exclusions:
        flag = {
            "beef": "hasBeef",
            "fish": "hasFish",
            "pork": "hasPork",
            "chicken": "hasChicken",
            "lamb": "hasLamb",
            "shrimp": "hasShrimp",
            "egg": "hasEgg",
            "dairy": "hasDairy",
        }.get(exclusion)
        if flag:
            filtered = [recipe for recipe in filtered if not recipe.get(flag)]
    return filtered


def sort_recipes(recipes: list[dict[str, Any]], sort_by: str, pantry: list[str]) -> list[dict[str, Any]]:
    if sort_by == "Pantry match score":
        return sorted(recipes, key=lambda recipe: pantry_match_score(recipe, pantry), reverse=True)
    if sort_by == "Protein highest first":
        return sorted(recipes, key=lambda recipe: int(recipe.get("protein", 0)), reverse=True)
    if sort_by == "Calories lowest first":
        return sorted(recipes, key=lambda recipe: int(recipe.get("kcal", 0)))
    if sort_by == "Cook time shortest first":
        return sorted(recipes, key=recipe_minutes)
    if sort_by == "Recently added":
        return sorted(recipes, key=lambda recipe: recipe.get("created_at", ""), reverse=True)
    return recipes


def paginate(recipes: list[dict[str, Any]], page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    total_pages = max(1, ceil(len(recipes) / page_size))
    safe_page = min(max(page, 1), total_pages)
    start = (safe_page - 1) * page_size
    return recipes[start:start + page_size], total_pages


def favorite_ids(state: dict[str, Any]) -> list[str]:
    return list(state.get("favoriteRecipeIds", []))


def toggle_favorite(state: dict[str, Any], recipe_id: str) -> bool:
    favorites = set(favorite_ids(state))
    if recipe_id in favorites:
        favorites.remove(recipe_id)
        is_favorite = False
    else:
        favorites.add(recipe_id)
        is_favorite = True
    state["favoriteRecipeIds"] = sorted(favorites)
    return is_favorite


def add_to_week_plan(
    weekly_plan: dict[str, Any],
    iso: str,
    meal_type: str,
    recipe_id: str,
) -> None:
    day = weekly_plan["plan"][iso]
    if meal_type in {"breakfast", "snack"}:
        day[meal_type] = recipe_id
    else:
        source = (day.get(meal_type) or {}).get("source", "cook-today")
        day[meal_type] = {"recipeId": recipe_id, "source": source}
        day.setdefault("skippedMeals", {}).pop(meal_type, None)
