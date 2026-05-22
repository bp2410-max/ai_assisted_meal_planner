from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import streamlit as st

import ai_adjustments
import app as planner_core
from app import (
    DEFAULT_PROFILE,
    MealPlanner,
    add_days,
    find_saturday,
    format_time_12,
    recipe_by_id,
    short_date,
    today,
)
from meal_planner import export_utils
from meal_planner import recipe_library
from meal_planner import reports
from recipes import DRINKS, PANTRY_COMMON, RECIPES as FALLBACK_STATIC_RECIPES


STATE_PATH = Path("meal_planner_state.json")
DATA_DIR = Path("data")
STATIC_RECIPES_PATH = DATA_DIR / "recipes.json"
GENERATED_RECIPES_PATH = DATA_DIR / "generated_recipes.json"
REQUIRED_RECIPE_FIELDS = {
    "id",
    "name",
    "cuisine",
    "meal_types",
    "macros",
    "ingredients",
    "steps",
    "tags",
    "dietary_flags",
}
REQUIRED_MACROS = {"kcal", "protein", "carbs", "fat"}
VALID_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
VALID_CUISINES = {"indian", "western"}


st.set_page_config(
    page_title="Meal Planner",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_planner() -> MealPlanner:
    configure_recipe_pool()
    if "planner" not in st.session_state:
        st.session_state.planner = MealPlanner(state_path=STATE_PATH)
    if st.session_state.planner.state.get("currentWeek") and "generated_meal_plan" not in st.session_state:
        st.session_state.generated_meal_plan = st.session_state.planner.state["currentWeek"]
    return st.session_state.planner


def ensure_recipe_files() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not STATIC_RECIPES_PATH.exists():
        STATIC_RECIPES_PATH.write_text(json.dumps(FALLBACK_STATIC_RECIPES, indent=2))
    if not GENERATED_RECIPES_PATH.exists():
        GENERATED_RECIPES_PATH.write_text("[]\n")


@st.cache_data(show_spinner=False)
def load_recipe_file_cached(path_str: str) -> tuple[list[dict[str, Any]], str | None]:
    path = Path(path_str)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"Could not load {path}: {exc}"
    if not isinstance(data, list):
        return [], f"{path} must contain a JSON list."
    return data, None


def load_recipe_file(path: Path, fallback: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    ensure_recipe_files()
    data, error = load_recipe_file_cached(str(path))
    if error:
        st.session_state.recipe_storage_error = error
        return list(fallback or [])
    return data


def save_generated_recipes(recipes: list[dict[str, Any]]) -> None:
    ensure_recipe_files()
    GENERATED_RECIPES_PATH.write_text(json.dumps(recipes, indent=2) + "\n")
    load_recipe_file_cached.clear()
    st.session_state.generated_recipes = recipes
    configure_recipe_pool()


def get_static_recipes() -> list[dict[str, Any]]:
    if "static_recipes" not in st.session_state:
        st.session_state.static_recipes = load_recipe_file(STATIC_RECIPES_PATH, FALLBACK_STATIC_RECIPES)
        for recipe in st.session_state.static_recipes:
            recipe["generated"] = False
            recipe["source"] = "static"
    return st.session_state.static_recipes


def get_generated_recipes() -> list[dict[str, Any]]:
    if "generated_recipes" not in st.session_state:
        static_ids = {recipe.get("id") for recipe in get_static_recipes()}
        generated_recipes = []
        seen_ids = set(static_ids)
        for recipe in load_recipe_file(GENERATED_RECIPES_PATH, []):
            recipe_id = recipe.get("id")
            if not recipe_id or recipe_id in seen_ids:
                continue
            recipe["generated"] = True
            recipe["source"] = "ai_generated"
            generated_recipes.append(recipe)
            seen_ids.add(recipe_id)
        st.session_state.generated_recipes = generated_recipes
    return st.session_state.generated_recipes


def get_all_recipes() -> list[dict[str, Any]]:
    return [*get_static_recipes(), *get_generated_recipes()]


def configure_recipe_pool() -> None:
    planner_core.RECIPES = get_all_recipes()


def save_and_rerun(planner: MealPlanner) -> None:
    planner.save()
    st.rerun()


def meal_name(recipe_id: str | None) -> str:
    recipe = recipe_by_id(recipe_id)
    return recipe["name"] if recipe else "-"


def recipe_label(recipe: dict[str, Any]) -> str:
    meal_types = ", ".join(recipe.get("mealTypes", []))
    warm = "warm" if recipe.get("warm") is not False else "cold"
    source = "AI-generated" if recipe.get("source") == "ai_generated" or recipe.get("generated") else "Static"
    return f"{recipe['name']} · {recipe['cuisine']} · {meal_types} · {warm} · {source}"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "generated-recipe"


def validate_recipe(
    raw_recipe: dict[str, Any],
    existing_ids: set[str],
    existing_names: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(raw_recipe, dict):
        return None, ["Recipe must be a JSON object."]

    existing_names = existing_names or set()
    recipe = dict(raw_recipe)

    if "meal_types" not in recipe and "mealTypes" in recipe:
        recipe["meal_types"] = recipe["mealTypes"]
    if "macros" not in recipe and all(field in recipe for field in REQUIRED_MACROS):
        recipe["macros"] = {field: recipe[field] for field in REQUIRED_MACROS}
    if "dietary_flags" not in recipe:
        recipe["dietary_flags"] = {
            "veg": recipe.get("veg", False),
            "hasEgg": recipe.get("hasEgg", False),
            "hasDairy": recipe.get("hasDairy", False),
            "hasBeef": recipe.get("hasBeef", False),
            "hasFish": recipe.get("hasFish", False),
            "hasPork": recipe.get("hasPork", False),
            "hasChicken": recipe.get("hasChicken", False),
            "hasLamb": recipe.get("hasLamb", False),
            "hasShrimp": recipe.get("hasShrimp", False),
        }
    if "tags" not in recipe:
        recipe["tags"] = []

    missing = sorted(REQUIRED_RECIPE_FIELDS - set(recipe))
    if missing:
        errors.append("Missing fields: " + ", ".join(missing))

    recipe["id"] = str(recipe.get("id") or slugify(str(recipe.get("name", "generated recipe"))))
    recipe["id"] = slugify(recipe["id"])
    if not recipe["id"].startswith("ai-"):
        recipe["id"] = "ai-" + recipe["id"]
    if recipe["id"] in existing_ids:
        errors.append(f"Duplicate recipe id: {recipe['id']}")

    recipe["name"] = str(recipe.get("name", "")).strip()
    if not recipe["name"]:
        errors.append("Name cannot be empty.")
    elif recipe["name"].lower() in existing_names:
        errors.append(f"Duplicate recipe name: {recipe['name']}")

    cuisine = str(recipe.get("cuisine", "")).lower().strip()
    if cuisine not in VALID_CUISINES:
        errors.append("Cuisine must be indian or western.")
    recipe["cuisine"] = cuisine

    meal_types = recipe.get("meal_types", [])
    if not isinstance(meal_types, list):
        errors.append("meal_types must be a list.")
        meal_types = []
    meal_types = [str(meal_type).lower().strip() for meal_type in meal_types]
    invalid_meal_types = sorted(set(meal_types) - VALID_MEAL_TYPES)
    if invalid_meal_types:
        errors.append("Invalid mealTypes: " + ", ".join(invalid_meal_types))
    if not meal_types:
        errors.append("At least one mealType is required.")
    recipe["meal_types"] = meal_types
    recipe["mealTypes"] = meal_types

    for field in ("ingredients", "steps"):
        value = recipe.get(field, [])
        if not isinstance(value, list) or not value:
            errors.append(f"{field} must be a non-empty list.")
            recipe[field] = []
        else:
            recipe[field] = [str(item).strip() for item in value if str(item).strip()]
            if not recipe[field]:
                errors.append(f"{field} cannot be empty.")

    for field in ("tags",):
        value = recipe.get(field, [])
        if not isinstance(value, list):
            errors.append(f"{field} must be a list.")
            recipe[field] = []
        else:
            recipe[field] = [str(item).strip() for item in value if str(item).strip()]

    dietary_flags = recipe.get("dietary_flags", {})
    if not isinstance(dietary_flags, dict):
        errors.append("dietary_flags must be an object.")
        dietary_flags = {}
    recipe["dietary_flags"] = dietary_flags

    macros = recipe.get("macros", {})
    if not isinstance(macros, dict):
        errors.append("macros must be an object with kcal, protein, carbs, and fat.")
        macros = {}
    missing_macros = sorted(REQUIRED_MACROS - set(macros))
    if missing_macros:
        errors.append("Missing macros: " + ", ".join(missing_macros))

    for field in ("kcal", "protein", "carbs", "fat"):
        try:
            recipe[field] = int(macros.get(field, 0))
        except (TypeError, ValueError):
            errors.append(f"macros.{field} must be a number.")
            recipe[field] = 0
        if recipe[field] < 0:
            errors.append(f"macros.{field} cannot be negative.")
        if field in {"kcal", "protein"} and recipe[field] == 0:
            errors.append(f"macros.{field} must be greater than 0.")
    recipe["macros"] = {field: recipe[field] for field in ("kcal", "protein", "carbs", "fat")}

    for field, default in (("prepMin", 10), ("cookMin", 20), ("servings", 2)):
        try:
            recipe[field] = int(recipe.get(field, default))
        except (TypeError, ValueError):
            errors.append(f"{field} must be a number.")
            recipe[field] = default
        if recipe[field] < 0:
            errors.append(f"{field} cannot be negative.")
        if field == "servings" and recipe[field] == 0:
            errors.append("servings must be greater than 0.")

    for field in ("veg", "hasBeef", "hasFish", "hasPork", "hasChicken", "hasLamb", "hasShrimp", "hasEgg", "hasDairy", "warm", "prePrep", "generated"):
        recipe[field] = bool(recipe.get(field, dietary_flags.get(field, False)))

    recipe["generated"] = True
    recipe["source"] = "ai_generated"
    recipe["created_at"] = str(recipe.get("created_at") or datetime.now().isoformat(timespec="seconds"))
    return (None, errors) if errors else (recipe, [])


def parse_recipe_json(text: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], (
            "I could not read the generated recipe JSON. "
            f"Details: {exc.msg} at line {exc.lineno}, column {exc.colno}."
        )

    if isinstance(data, dict) and "recipes" in data:
        data = data["recipes"]
    elif isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        return [], "JSON must be a recipe object, a list of recipes, or an object with a recipes list."
    return data, None


def placeholder_recipe_from_request(request: str) -> list[dict[str, Any]]:
    request_lower = request.lower()
    use_paneer = "paneer" in request_lower
    use_spinach = "spinach" in request_lower or "palak" in request_lower
    protein = "paneer" if use_paneer else "chickpeas"
    greens = "spinach" if use_spinach else "mixed vegetables"
    cuisine = "indian" if "indian" in request_lower else "western"
    meal_type = "dinner" if "dinner" in request_lower else "lunch"
    name = f"{protein.title()} {greens.title()} Protein Bowl"
    return [
        {
            "id": slugify(name),
            "name": name,
            "cuisine": cuisine,
            "meal_types": [meal_type],
            "macros": {
                "kcal": 520,
                "protein": 34 if use_paneer else 24,
                "carbs": 42,
                "fat": 24 if use_paneer else 16,
            },
            "tags": ["high-protein", "warm", cuisine],
            "dietary_flags": {
                "veg": True,
                "hasEgg": False,
                "hasDairy": use_paneer,
                "hasBeef": False,
                "hasFish": False,
                "hasPork": False,
                "hasChicken": False,
                "hasLamb": False,
                "hasShrimp": False,
            },
            "warm": True,
            "prepMin": 10,
            "cookMin": 20,
            "servings": 2,
            "ingredients": [
                f"300g {protein}",
                f"3 cups {greens}",
                "1 onion, chopped",
                "1 tomato, chopped",
                "1 tsp oil or ghee",
                "Cumin, turmeric, garam masala, chili, salt",
                "1 cup cooked brown rice or roti",
            ],
            "steps": [
                "Heat oil and saute onion for 3 min.",
                "Add tomato and spices, then cook 4 min.",
                f"Add {protein} and {greens}; cook until hot and tender.",
                "Serve warm with rice or roti.",
            ],
        }
    ]


def generate_recipe_json_with_openai(request: str) -> tuple[str | None, str | None]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is not set, so a placeholder recipe was created."

    try:
        from openai import OpenAI
    except ImportError:
        return None, "The openai package is not installed, so a placeholder recipe was created."

    schema_hint = {
        "id": "kebab-case-id",
        "name": "Recipe name",
        "cuisine": "indian or western",
        "meal_types": ["lunch", "dinner"],
        "macros": {"kcal": 500, "protein": 30, "carbs": 45, "fat": 18},
        "tags": ["high-protein", "warm"],
        "dietary_flags": {
            "veg": True,
            "hasEgg": False,
            "hasDairy": True,
            "hasBeef": False,
            "hasFish": False,
            "hasPork": False,
            "hasChicken": False,
            "hasLamb": False,
            "hasShrimp": False,
        },
        "warm": True,
        "prepMin": 10,
        "cookMin": 20,
        "servings": 2,
        "ingredients": ["ingredient line"],
        "steps": ["step line"],
    }
    prompt = (
        "Return only valid JSON. Generate 1 to 3 meal-planner recipes matching the user request. "
        "Use this exact schema for each recipe. macros, ingredients, steps, tags, and dietary_flags are required. "
        "Do not include markdown fences or commentary. "
        f"Schema example: {json.dumps(schema_hint)}\n"
        f"User request: {request}"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_RECIPE_MODEL", "gpt-4.1-mini"),
            messages=[
                {"role": "system", "content": "You generate compact recipe JSON for a meal planner."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
    except Exception as exc:
        return None, f"OpenAI request failed, so a placeholder recipe was created: {exc}"

    return response.choices[0].message.content, None


def macro_row(macros: dict[str, int]) -> None:
    cols = st.columns(4)
    cols[0].metric("Calories", f"{macros['kcal']} kcal")
    cols[1].metric("Protein", f"{macros['protein']} g")
    cols[2].metric("Carbs", f"{macros['carbs']} g")
    cols[3].metric("Fat", f"{macros['fat']} g")


def day_recipe_ids(day: dict[str, Any], cooked_only: bool = False) -> list[str]:
    recipe_ids: list[str] = []
    if day.get("eatingOut"):
        return recipe_ids
    for key in ("breakfast", "snack"):
        if day.get(key):
            recipe_ids.append(day[key])
    for key in ("lunch", "dinner"):
        meal = day.get(key) or {}
        if meal.get("recipeId") and (not cooked_only or meal.get("source") == "cook-today"):
            recipe_ids.append(meal["recipeId"])
    return recipe_ids


def pantry_utilization_for_day(planner: MealPlanner, day: dict[str, Any]) -> dict[str, Any]:
    pantry = [item.strip().lower() for item in planner.pantry if item.strip()]
    if not pantry:
        return {
            "pantry_items_used": 0,
            "grocery_items_avoided": 0,
            "pantry_utilization": 0,
            "used_items": [],
        }

    used_items: set[str] = set()
    grocery_items_avoided = 0
    missing_ingredient_lines = 0

    for recipe_id in day_recipe_ids(day):
        recipe = recipe_by_id(recipe_id)
        if not recipe:
            continue
        for ingredient in recipe.get("ingredients", []):
            lower = ingredient.lower()
            matches = [item for item in pantry if item in lower]
            if matches:
                grocery_items_avoided += 1
                used_items.update(matches)
            else:
                missing_ingredient_lines += 1

    total_needed_lines = grocery_items_avoided + missing_ingredient_lines
    utilization = round((grocery_items_avoided / total_needed_lines) * 100) if total_needed_lines else 0
    return {
        "pantry_items_used": len(used_items),
        "grocery_items_avoided": grocery_items_avoided,
        "pantry_utilization": utilization,
        "used_items": sorted(used_items),
    }


def render_pantry_metrics(planner: MealPlanner, day: dict[str, Any]) -> None:
    metrics = pantry_utilization_for_day(planner, day)
    st.subheader("Pantry utilization")
    cols = st.columns(3)
    cols[0].metric("Pantry items used", metrics["pantry_items_used"])
    cols[1].metric("Grocery items avoided", metrics["grocery_items_avoided"])
    cols[2].metric("Pantry utilization", f"{metrics['pantry_utilization']}%")
    if metrics["used_items"]:
        st.caption("Used today: " + ", ".join(metrics["used_items"]))


def record_plan_generated_analytics(planner: MealPlanner, week: dict[str, Any]) -> None:
    pantry_metrics = [
        pantry_utilization_for_day(planner, day)
        for day in week.get("plan", {}).values()
        if not day.get("eatingOut")
    ]
    grocery_items_avoided = sum(int(item.get("grocery_items_avoided", 0)) for item in pantry_metrics)
    payload = reports.plan_analytics_payload(
        week=week,
        recipes=get_all_recipes(),
        pantry_metrics=pantry_metrics,
        grocery_items_avoided=grocery_items_avoided,
        protein_target=int(planner.profile.get("protein", 0)),
    )
    reports.append_event("plan_generated", payload)


def weekly_cooked_recipe_ids(week: dict[str, Any]) -> list[str]:
    cooked_ids: list[str] = []
    seen: set[str] = set()
    for day in week.get("plan", {}).values():
        for recipe_id in day_recipe_ids(day, cooked_only=True):
            if recipe_id not in seen:
                cooked_ids.append(recipe_id)
                seen.add(recipe_id)
    return cooked_ids


def build_weekly_prep_plan(week: dict[str, Any]) -> dict[str, list[str]]:
    recipe_ids = weekly_cooked_recipe_ids(week)
    recipes = [recipe_by_id(recipe_id) for recipe_id in recipe_ids]
    recipes = [recipe for recipe in recipes if recipe]
    ingredient_text = " | ".join(
        ingredient.lower()
        for recipe in recipes
        for ingredient in recipe.get("ingredients", [])
    )
    recipe_id_set = {recipe["id"] for recipe in recipes}

    sunday_tasks: list[str] = []
    if "onion" in ingredient_text or "tomato" in ingredient_text:
        sunday_tasks.append("Chop onions and tomatoes for curry bases.")
    if "garlic" in ingredient_text or "ginger" in ingredient_text:
        sunday_tasks.append("Mince garlic and ginger, then refrigerate in a small container.")
    if "egg" in ingredient_text:
        sunday_tasks.append("Boil eggs for breakfasts or snacks.")
    if "masala-makhana" in recipe_id_set or "makhana" in ingredient_text:
        sunday_tasks.append("Roast makhana with ghee and spices.")
    if "dal" in ingredient_text:
        sunday_tasks.append("Cook a dal batch and portion it for reheating.")
    if "rice" in ingredient_text:
        sunday_tasks.append("Cook or rinse rice for the first two cook days.")
    if "chickpea" in ingredient_text:
        sunday_tasks.append("Drain chickpeas or roast a snack batch.")
    if "paneer" in ingredient_text:
        sunday_tasks.append("Cube paneer and mix a tikka-style spice blend.")
    if "chicken" in ingredient_text:
        sunday_tasks.append("Portion chicken and prep a simple marinade.")
    if any(recipe.get("prePrepNote") for recipe in recipes):
        sunday_tasks.extend(
            recipe["prePrepNote"]
            for recipe in recipes
            if recipe.get("prePrepNote")
        )

    cook_day_tasks: list[str] = []
    for index in range(7):
        iso = add_days(week["startDate"], index)
        day = week["plan"].get(iso, {})
        if day.get("eatingOut"):
            continue
        meals: list[str] = []
        for label, key in (("Lunch", "lunch"), ("Dinner", "dinner")):
            meal = day.get(key) or {}
            if meal.get("source") == "cook-today":
                meals.append(f"{label}: {meal_name(meal.get('recipeId'))}")
        if meals:
            cook_day_tasks.append(f"{short_date(iso)} - batch cook " + "; ".join(meals))

    if not sunday_tasks:
        sunday_tasks.append("Review the week and portion any staples you already have.")

    return {
        "Sunday prep": list(dict.fromkeys(sunday_tasks)),
        "Cook-day plan": cook_day_tasks,
    }


def render_weekly_prep_plan(planner: MealPlanner) -> None:
    week = planner.state.get("currentWeek")
    if not week:
        return

    prep_plan = build_weekly_prep_plan(week)
    st.header("Weekly prep plan")
    with st.container(border=True):
        st.subheader("Sunday prep")
        for task in prep_plan["Sunday prep"]:
            st.write(f"- {task}")

        if prep_plan["Cook-day plan"]:
            st.subheader("Cook-day plan")
            for task in prep_plan["Cook-day plan"]:
                st.write(f"- {task}")


def recipe_card(recipe_id: str | None, source: str | None = None) -> None:
    recipe = recipe_by_id(recipe_id)
    if not recipe:
        st.info("No recipe selected.")
        return

    total_min = 3 if source == "leftover" else recipe.get("prepMin", 0) + recipe.get("cookMin", 0)
    source_text = "Leftover, reheat" if source == "leftover" else "Cook today" if source else "Fresh"

    with st.container(border=True):
        st.subheader(recipe["name"])
        st.caption(
            f"{total_min} min · {recipe.get('cuisine', '').title()} · {source_text} · "
            f"serves {recipe.get('servings', 1)}"
        )
        macro_row(
            {
                "kcal": recipe.get("kcal", 0),
                "protein": recipe.get("protein", 0),
                "carbs": recipe.get("carbs", 0),
                "fat": recipe.get("fat", 0),
            }
        )
        if recipe.get("prePrepNote"):
            st.info(recipe["prePrepNote"])
        with st.expander("Ingredients and steps"):
            st.markdown("**Ingredients**")
            for ingredient in recipe.get("ingredients", []):
                st.write(f"- {ingredient}")
            st.markdown("**Steps**")
            for index, step in enumerate(recipe.get("steps", []), start=1):
                st.write(f"{index}. {step}")


def render_today(planner: MealPlanner) -> None:
    st.title("Today")
    iso = today()

    if not planner.state.get("currentWeek") or not planner.in_current_week(iso):
        st.info("No plan yet. Generate a week plan to see today's meals.")
        if st.button("Plan this week", type="primary"):
            st.session_state.page = "Plan Week"
            st.rerun()
        return

    day = planner.state["currentWeek"]["plan"].get(iso)
    if not day or day.get("eatingOut"):
        st.success("Eating out today." if day and day.get("eatingOut") else "No plan for today.")
        return

    totals = planner.day_total_macros(iso)
    target = planner.profile
    progress = min(1.0, totals["kcal"] / max(target.get("kcal", 1), 1))

    st.caption(datetime.now().strftime("%A, %B %-d"))
    macro_row(totals)
    st.progress(progress, text=f"{totals['kcal']} / {target['kcal']} kcal")
    render_pantry_metrics(planner, day)

    checked = planner.state.get("history", {}).get(iso, {})
    slots = planner.get_day_slots(day)
    next_slot = planner.next_slot(slots, checked)

    if next_slot:
        st.header("Right now")
        render_slot(planner, iso, next_slot, checked, hero=True)
    else:
        st.success("All done for today.")

    upcoming = [slot for slot in slots if not checked.get(slot["key"]) and slot != next_slot]
    done = [slot for slot in slots if checked.get(slot["key"])]

    if upcoming:
        st.header("Later today")
        for slot in upcoming:
            render_slot(planner, iso, slot, checked)

    if done:
        st.header("Done")
        for slot in done:
            render_slot(planner, iso, slot, checked)


def render_slot(
    planner: MealPlanner,
    iso: str,
    slot: dict[str, Any],
    checked: dict[str, bool],
    hero: bool = False,
) -> None:
    is_checked = checked.get(slot["key"], False)
    with st.container(border=True):
        st.caption(f"{slot['label']} · {format_time_12(slot.get('time'))}")

        if slot["kind"] == "chai":
            drink = planner.drink_info()
            st.subheader(drink["name"])
            if drink.get("note"):
                st.write(drink["note"])
            macro_row(
                {
                    "kcal": drink.get("kcal", 0),
                    "protein": drink.get("protein", 0),
                    "carbs": drink.get("carbs", 0),
                    "fat": drink.get("fat", 0),
                }
            )
        else:
            recipe_card(slot.get("recipeId"), slot.get("source"))

        col1, col2 = st.columns([1, 1])
        if col1.button("Undo" if is_checked else "Mark done", key=f"done-{iso}-{slot['key']}", type="primary" if hero else "secondary"):
            new_value = planner.toggle_checked(iso, slot["key"])
            if new_value and slot["kind"] == "meal":
                recipe = recipe_by_id(slot.get("recipeId"))
                reports.append_event(
                    "meal_completed",
                    {
                        "iso": iso,
                        "meal_type": slot["key"],
                        "recipe_id": slot.get("recipeId"),
                        "recipe_name": recipe.get("name") if recipe else None,
                        "cuisine": recipe.get("cuisine") if recipe else None,
                    },
                )
            save_and_rerun(planner)
        if slot["kind"] == "meal" and col2.button("Swap", key=f"swap-{iso}-{slot['key']}"):
            old_recipe_id = slot.get("recipeId")
            picked = planner.swap_meal(iso, slot["key"])
            if picked:
                reports.append_event(
                    "meal_swapped",
                    {
                        "iso": iso,
                        "meal_type": slot["key"],
                        "from_recipe_id": old_recipe_id,
                        "to_recipe_id": picked.get("id"),
                    },
                )
            save_and_rerun(planner)


def render_week(planner: MealPlanner) -> None:
    st.title("This Week")
    week = planner.state.get("currentWeek")
    if not week:
        st.info("No plan yet.")
        return

    render_weekly_prep_plan(planner)

    for index in range(7):
        iso = add_days(week["startDate"], index)
        day = week["plan"].get(iso, {})
        with st.container(border=True):
            heading = f"{short_date(iso)}"
            if iso == today():
                heading += " · Today"
            st.subheader(heading)
            if day.get("eatingOut"):
                st.write("Eating out")
                continue

            rows = [
                ("Breakfast", meal_name(day.get("breakfast")), ""),
                ("Snack", meal_name(day.get("snack")), ""),
                (
                    "Lunch",
                    meal_name((day.get("lunch") or {}).get("recipeId")) if day.get("lunch") else "Eating out",
                    (day.get("lunch") or {}).get("source", ""),
                ),
                (
                    "Dinner",
                    meal_name((day.get("dinner") or {}).get("recipeId")) if day.get("dinner") else "Eating out",
                    (day.get("dinner") or {}).get("source", ""),
                ),
            ]
            for label, name, source in rows:
                st.write(f"**{label}:** {name}" + (f" ({source})" if source else ""))


def render_plan(planner: MealPlanner) -> None:
    st.title("Plan Week")

    default_start = datetime.strptime(find_saturday(today()), "%Y-%m-%d").date()
    start = st.date_input("Week start", value=default_start)

    pantry_selected = st.multiselect(
        "Pantry items you already have",
        PANTRY_COMMON,
        default=[item for item in planner.pantry if item in PANTRY_COMMON],
    )
    extra_pantry = st.text_input(
        "Anything else? Comma-separated",
        value=", ".join(item for item in planner.pantry if item not in PANTRY_COMMON),
    )

    st.subheader("Eating out meals")
    st.caption("Select the exact lunches or dinners you will eat out. Those meals are removed from the plan, grocery list, and batch-cooking schedule.")
    eating_out_meals: dict[str, list[str]] = {}
    columns = st.columns(7)
    for index in range(7):
        iso = add_days(start.isoformat(), index)
        with columns[index]:
            st.markdown(f"**{short_date(iso)}**")
            skipped: list[str] = []
            if st.checkbox("Lunch", key=f"eat-out-lunch-{iso}"):
                skipped.append("lunch")
            if st.checkbox("Dinner", key=f"eat-out-dinner-{iso}"):
                skipped.append("dinner")
            if skipped:
                eating_out_meals[iso] = skipped

    if st.button("Generate plan", type="primary"):
        extras = [item.strip() for item in extra_pantry.split(",") if item.strip()]
        planner.state["pantry"] = [*pantry_selected, *extras]
        started_at = time.perf_counter()
        week = planner.generate_plan(start.isoformat(), eating_out_meals=eating_out_meals)
        st.session_state.generated_meal_plan = week
        st.session_state.plan_generation_seconds = time.perf_counter() - started_at
        record_plan_generated_analytics(planner, week)
        save_and_rerun(planner)

    if planner.state.get("currentWeek"):
        st.success("Current plan is ready.")
        if "plan_generation_seconds" in st.session_state:
            st.caption(f"Last plan generation: {st.session_state.plan_generation_seconds:.2f}s")
        cols = st.columns(3)
        if cols[0].button("View Week", type="primary"):
            st.session_state.page = "Week"
            st.rerun()
        if cols[1].button("Grocery List"):
            st.session_state.page = "Grocery List"
            st.rerun()
        if cols[2].button("Today"):
            st.session_state.page = "Today"
            st.rerun()


def render_grocery(planner: MealPlanner) -> None:
    st.title("Grocery List")
    if not planner.state.get("currentWeek"):
        st.info("No plan yet.")
        return

    groups = planner.build_grocery_list()
    checked = planner.state["currentWeek"].setdefault("groceryChecked", {})
    total = sum(len(items) for items in groups.values())
    st.caption(f"{total} items to buy. Pantry items are already excluded.")

    for group_name, items in groups.items():
        if not items:
            continue
        st.subheader(group_name)
        for item in items:
            key = item["text"]
            value = st.checkbox(
                key,
                value=checked.get(key, False),
                key=f"grocery-{group_name}-{key}",
                help=f"From {item['fromRecipe']}",
            )
            if value != checked.get(key, False):
                checked[key] = value
                planner.save()


def render_ai_adjust_plan(planner: MealPlanner) -> None:
    st.title("AI Adjust Plan")
    st.caption("Tell the agent what changed. Review the preview, then apply.")

    week = planner.state.get("currentWeek")
    if not week:
        st.info("Generate a weekly plan first.")
        return

    request = st.text_area(
        "Adjustment request",
        placeholder="I only have 15 minutes to cook on Wednesday",
        height=90,
    )
    if st.button("Generate Adjustment", type="primary", disabled=not request.strip()):
        started_at = time.perf_counter()
        response, warning, used_mock = ai_adjustments.generate_adjustment_response(
            request=request.strip(),
            week=week,
            profile=planner.profile,
            pantry=planner.pantry,
            recipes=get_all_recipes(),
        )
        st.session_state.adjustment_generation_seconds = time.perf_counter() - started_at
        st.session_state.pending_adjustment_request = request.strip()
        st.session_state.pending_adjustment = None

        if warning:
            st.warning(warning)
        if response is None:
            st.error("I could not generate a safe adjustment. Your current plan was not changed.")
            ai_adjustments.append_adjustment_history(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "request": request.strip(),
                    "applied_changes": [],
                    "status": "failed",
                    "error": warning or "No response generated.",
                }
            )
        else:
            preview, errors = ai_adjustments.validate_adjustment_response(
                response=response,
                week=week,
                profile=planner.profile,
                recipes=get_all_recipes(),
            )
            if errors:
                st.error("I found the request, but the proposed changes were not safe to apply.")
                for error in errors:
                    st.write(f"- {error}")
                ai_adjustments.append_adjustment_history(
                    {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "request": request.strip(),
                        "applied_changes": [],
                        "status": "invalid",
                        "error": "; ".join(errors),
                    }
                )
            elif not preview:
                st.info("No changes were proposed. Your current plan was not changed.")
            else:
                st.session_state.pending_adjustment = {
                    "request": request.strip(),
                    "changes": preview,
                    "used_mock": used_mock,
                }

    if "adjustment_generation_seconds" in st.session_state:
        st.caption(f"Last adjustment generation: {st.session_state.adjustment_generation_seconds:.2f}s")

    pending = st.session_state.get("pending_adjustment")
    if pending:
        st.subheader("Preview")
        for change in pending["changes"]:
            with st.container(border=True):
                st.write(f"**{short_date(change['iso'])} {change['meal_type'].title()}**")
                cols = st.columns(2)
                cols[0].metric("Current", change["current_name"])
                cols[1].metric("Proposed", change["proposed_name"])
                st.caption(change["reason"])

        if st.button("Apply Changes", type="primary"):
            next_week = ai_adjustments.apply_adjustments(week, pending["changes"])
            planner.state["currentWeek"] = next_week
            st.session_state.generated_meal_plan = next_week
            planner.save()
            ai_adjustments.append_adjustment_history(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "request": pending["request"],
                    "applied_changes": pending["changes"],
                    "status": "applied_mock" if pending.get("used_mock") else "applied",
                }
            )
            st.session_state.pending_adjustment = None
            st.success("Plan updated. Grocery list, prep plan, Today, and metrics will use the adjusted plan.")
            st.rerun()

    history = ai_adjustments.load_adjustment_history()
    if history:
        with st.expander("Adjustment history"):
            for entry in reversed(history[-8:]):
                st.write(f"**{entry.get('timestamp', '')}** - {entry.get('status', '')}")
                st.caption(entry.get("request", ""))


def render_export(planner: MealPlanner) -> None:
    st.title("Export")
    st.caption("Create copy-friendly exports only when you need them.")

    week = planner.state.get("currentWeek")
    if not week:
        st.info("No weekly plan exists yet. Generate a plan before exporting meals, groceries, or prep.")

    export_type = st.selectbox(
        "What do you want to export?",
        ["Weekly meal plan", "Grocery list", "Prep plan", "Monthly report", "JSON backup"],
    )

    if st.button("Generate Preview", type="primary"):
        content = ""
        filename = "meal-planner-export.txt"
        mime = "text/plain"
        extra_downloads: list[dict[str, str]] = []

        if export_type == "Weekly meal plan":
            if not week:
                st.session_state.export_error = "No weekly plan is available."
            else:
                content = export_utils.weekly_plan_markdown(week, get_all_recipes())
                filename = "weekly-meal-plan.md"
                mime = "text/markdown"
                extra_downloads.append(
                    {
                        "label": "Download TXT",
                        "data": export_utils.weekly_plan_text(week, get_all_recipes()),
                        "file_name": "weekly-meal-plan.txt",
                        "mime": "text/plain",
                    }
                )

        elif export_type == "Grocery list":
            if not week:
                st.session_state.export_error = "No grocery list is available until a weekly plan exists."
            else:
                groups = planner.build_grocery_list()
                content = export_utils.grocery_markdown(groups)
                filename = "grocery-list.md"
                mime = "text/markdown"
                extra_downloads.extend(
                    [
                        {
                            "label": "Download TXT",
                            "data": export_utils.grocery_text(groups),
                            "file_name": "grocery-list.txt",
                            "mime": "text/plain",
                        },
                        {
                            "label": "Download CSV",
                            "data": export_utils.grocery_csv(groups),
                            "file_name": "grocery-list.csv",
                            "mime": "text/csv",
                        },
                    ]
                )

        elif export_type == "Prep plan":
            if not week:
                st.session_state.export_error = "No prep plan is available until a weekly plan exists."
            else:
                prep_plan = build_weekly_prep_plan(week)
                content = export_utils.prep_plan_markdown(prep_plan)
                filename = "prep-plan.md"
                mime = "text/markdown"
                extra_downloads.append(
                    {
                        "label": "Download TXT",
                        "data": export_utils.prep_plan_text(prep_plan),
                        "file_name": "prep-plan.txt",
                        "mime": "text/plain",
                    }
                )

        elif export_type == "Monthly report":
            monthly_report = st.session_state.get("monthly_report") or planner.state.get("monthlyReport")
            if not monthly_report:
                st.session_state.export_error = "No monthly report is available yet."
            else:
                content = export_utils.monthly_report_markdown(monthly_report)
                filename = "monthly-report.md"
                mime = "text/markdown"
                extra_downloads.append(
                    {
                        "label": "Download TXT",
                        "data": export_utils.monthly_report_text(monthly_report),
                        "file_name": "monthly-report.txt",
                        "mime": "text/plain",
                    }
                )

        elif export_type == "JSON backup":
            content = export_utils.json_backup(
                profile=planner.profile,
                pantry=planner.pantry,
                weekly_plan=week,
                generated_recipes=get_generated_recipes(),
                completed_meals=planner.state.get("history", {}),
            )
            filename = "meal-planner-backup.json"
            mime = "application/json"

        if content:
            st.session_state.export_payload = {
                "title": export_type,
                "content": content,
                "filename": filename,
                "mime": mime,
                "extra_downloads": extra_downloads,
            }
            st.session_state.export_error = None

    if st.session_state.get("export_error"):
        st.warning(st.session_state.export_error)

    payload = st.session_state.get("export_payload")
    if payload:
        st.subheader("Preview")
        st.text_area("Copy-friendly text", payload["content"], height=320)
        st.download_button(
            f"Download {payload['filename'].split('.')[-1].upper()}",
            data=payload["content"],
            file_name=payload["filename"],
            mime=payload["mime"],
        )
        for item in payload.get("extra_downloads", []):
            st.download_button(
                item["label"],
                data=item["data"],
                file_name=item["file_name"],
                mime=item["mime"],
            )


def render_reports() -> None:
    st.title("Reports")
    st.caption("A lightweight monthly operational review of your meal planning.")

    events = reports.load_events()
    if not events:
        st.info("No analytics yet. Complete meals, generate plans, or add AI recipes to start building a report.")
        return

    current_month = reports.month_key()
    available_months = sorted({reports.event_month(event) for event in events if reports.event_month(event)}, reverse=True)
    selected_month = st.selectbox("Month", available_months, index=available_months.index(current_month) if current_month in available_months else 0)
    summary = reports.aggregate_month(events, selected_month)
    previous = reports.aggregate_month(events, reports.previous_month_key(selected_month))
    comparison = reports.compare_months(summary, previous) if previous else {}

    st.subheader("Monthly snapshot")
    cols = st.columns(5)
    cols[0].metric("Meals completed", summary["meals_completed"], comparison.get("meals_completed"))
    cols[1].metric("Pantry utilization", f"{summary['pantry_utilization']}%", comparison.get("pantry_utilization"))
    cols[2].metric("Grocery savings", f"${summary['grocery_savings']:.0f}", comparison.get("grocery_savings"))
    cols[3].metric("Most-used cuisine", summary["most_used_cuisine"])
    cols[4].metric("Top recipe", summary["top_recipe"])

    chart_col1, chart_col2 = st.columns(2)
    if summary["cuisine_frequency"]:
        chart_col1.subheader("Cuisine distribution")
        chart_col1.bar_chart(summary["cuisine_frequency"])
    if summary["completed_by_week"]:
        chart_col2.subheader("Meals completed by week")
        chart_col2.bar_chart(summary["completed_by_week"])
    if summary["pantry_trend"]:
        st.subheader("Pantry utilization trend")
        st.line_chart(summary["pantry_trend"], x="date", y="pantry_utilization")

    st.subheader("AI summary")
    if st.button("Generate AI Summary"):
        ai_summary, error = reports.generate_ai_summary(summary, comparison)
        if error:
            st.warning(error)
        else:
            st.session_state.monthly_ai_summary = ai_summary
    ai_summary = st.session_state.get("monthly_ai_summary")
    if ai_summary:
        st.info(ai_summary)

    st.subheader("Email preview")
    email_text = reports.email_preview(summary, comparison, ai_summary)
    st.text_area("Preview", email_text, height=260)
    to_email = st.text_input("Send to", placeholder="you@example.com")
    if st.button("Send Email"):
        subject, _, body = email_text.partition("\n\n")
        ok, message = reports.send_email(subject.replace("Subject: ", ""), body, to_email or None)
        if ok:
            st.success(message)
        else:
            st.warning(message)

    st.subheader("Export")
    md = reports.monthly_report_markdown(summary, comparison, ai_summary)
    txt = reports.monthly_report_text(summary, comparison, ai_summary)
    js = reports.monthly_report_json(summary, comparison, ai_summary)
    dl_cols = st.columns(3)
    dl_cols[0].download_button("Download Markdown", md, file_name=f"meal-report-{selected_month}.md", mime="text/markdown")
    dl_cols[1].download_button("Download TXT", txt, file_name=f"meal-report-{selected_month}.txt", mime="text/plain")
    dl_cols[2].download_button("Download JSON", js, file_name=f"meal-report-{selected_month}.json", mime="application/json")


def render_recipes(planner: MealPlanner) -> None:
    st.title("Recipe Library")
    recipes = get_all_recipes()
    cuisines = sorted({recipe.get("cuisine", "other") for recipe in recipes})
    meal_types = sorted({meal_type for recipe in recipes for meal_type in recipe.get("mealTypes", [])})
    st.caption(f"{len(get_static_recipes())} static recipes · {len(get_generated_recipes())} AI-generated recipes")

    search = st.text_input("Search recipes", placeholder="paneer, dal, breakfast...")
    col1, col2, col3 = st.columns(3)
    meal_type = col1.selectbox("Meal type", ["All", *meal_types])
    cuisine = col2.selectbox("Cuisine", ["All", *cuisines])
    source = col3.selectbox("Source", ["All", "Static", "AI-generated"])

    col4, col5, col6, col7 = st.columns(4)
    high_protein = col4.checkbox("High protein")
    warm_meal = col5.checkbox("Warm meal")
    meal_prep = col6.checkbox("Meal-prep friendly")
    hide_excluded = col7.checkbox("Hide my exclusions", value=True)

    sort_by = st.selectbox(
        "Sort by",
        [
            "Pantry match score",
            "Protein highest first",
            "Calories lowest first",
            "Cook time shortest first",
            "Recently added",
        ],
    )

    filtered = recipe_library.search_recipes(recipes, search)
    filtered = recipe_library.filter_recipes(
        filtered,
        meal_type=meal_type,
        cuisine=cuisine,
        source=source,
        high_protein=high_protein,
        warm_meal=warm_meal,
        meal_prep=meal_prep,
        exclusions=planner.profile.get("exclusions", []) if hide_excluded else [],
    )
    filtered = recipe_library.sort_recipes(filtered, sort_by, planner.pantry)

    if not filtered:
        st.info("No recipes match these filters.")
        return

    page_size = st.selectbox("Cards per page", [10, 15, 20], index=1)
    total_pages = max(1, (len(filtered) + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
    visible, total_pages = recipe_library.paginate(filtered, int(page), page_size)
    st.caption(f"Showing {len(visible)} of {len(filtered)} recipes · page {int(page)} of {total_pages}")

    favorites = set(recipe_library.favorite_ids(planner.state))
    week = planner.state.get("currentWeek")

    for recipe in visible:
        pantry_score = recipe_library.pantry_match_score(recipe, planner.pantry)
        minutes = recipe_library.recipe_minutes(recipe)
        source_text = recipe_library.source_label(recipe)
        is_ai = source_text == "AI-generated"
        is_favorite = recipe["id"] in favorites

        with st.container(border=True):
            top = st.columns([3, 1])
            top[0].subheader(recipe["name"])
            top[1].caption(source_text)
            st.caption(
                f"{', '.join(recipe.get('mealTypes', []))} · {recipe.get('cuisine', '').title()} · "
                f"{recipe.get('kcal', 0)} kcal · P {recipe.get('protein', 0)}g · "
                f"{minutes} min · Pantry {pantry_score}"
            )

            actions = st.columns([1, 1, 1, 1])
            if actions[0].button("Unpin" if is_favorite else "Pin", key=f"pin-{recipe['id']}"):
                recipe_library.toggle_favorite(planner.state, recipe["id"])
                planner.save()
                st.rerun()

            if week:
                eligible_meals = [meal for meal in recipe.get("mealTypes", []) if meal in {"breakfast", "lunch", "dinner", "snack"}]
                with actions[1].popover("Add to week"):
                    if not eligible_meals:
                        st.info("No compatible meal slots.")
                    else:
                        iso = st.selectbox("Day", sorted(week.get("plan", {})), format_func=short_date, key=f"add-day-{recipe['id']}")
                        slot = st.selectbox("Slot", eligible_meals, key=f"add-slot-{recipe['id']}")
                        if st.button("Add", key=f"add-week-{recipe['id']}"):
                            recipe_library.add_to_week_plan(week, iso, slot, recipe["id"])
                            planner.save()
                            st.success("Added to this week's plan.")
                            st.rerun()

            if is_ai:
                confirm = actions[2].checkbox("Confirm delete", key=f"confirm-delete-{recipe['id']}")
                if actions[3].button("Delete", key=f"delete-library-{recipe['id']}", disabled=not confirm):
                    delete_generated_recipe(recipe["id"])
                    st.rerun()
            else:
                actions[2].caption("Static recipes cannot be deleted.")

            with st.expander("Ingredients and steps"):
                st.markdown("**Ingredients**")
                for ingredient in recipe.get("ingredients", []):
                    st.write(f"- {ingredient}")
                st.markdown("**Steps**")
                for index, step in enumerate(recipe.get("steps", []), start=1):
                    st.write(f"{index}. {step}")


def render_ai_recipes() -> None:
    st.title("AI Recipes")
    st.caption("Generate recipes, validate them, then use them in your next meal plan.")

    with st.container(border=True):
        request = st.text_area(
            "Recipe request",
            placeholder="high protein Indian dinners using paneer and spinach",
            height=90,
        )
        generate = st.button("Generate recipe", type="primary", disabled=not request.strip())

    if generate:
        started_at = time.perf_counter()
        with st.spinner("Creating recipe JSON..."):
            generated_text, warning = generate_recipe_json_with_openai(request.strip())
            if warning:
                st.warning(warning)
            if generated_text:
                raw_recipes, parse_error = parse_recipe_json(generated_text)
            else:
                raw_recipes, parse_error = placeholder_recipe_from_request(request), None
            st.session_state.ai_generation_seconds = time.perf_counter() - started_at

        if parse_error:
            st.error(parse_error)
            with st.expander("Raw model output"):
                st.code(generated_text or "", language="json")
        else:
            add_valid_recipes(raw_recipes)

    if "ai_generation_seconds" in st.session_state:
        st.caption(f"Last AI recipe generation: {st.session_state.ai_generation_seconds:.2f}s")

    with st.expander("Paste recipe JSON instead"):
        pasted = st.text_area(
            "JSON",
            placeholder='{"recipes": [{"id": "ai-example", "name": "..."}]}',
            height=160,
        )
        if st.button("Validate and add JSON", disabled=not pasted.strip()):
            raw_recipes, parse_error = parse_recipe_json(pasted)
            if parse_error:
                st.error(parse_error)
            else:
                add_valid_recipes(raw_recipes)

    generated_recipes = get_generated_recipes()
    st.subheader("Saved AI-generated recipes")
    if len(generated_recipes) > 100:
        st.warning("You have more than 100 saved AI-generated recipes. Consider deleting old ones to keep the app quick.")
    if not generated_recipes:
        st.info("No AI recipes yet.")
        return

    selected_label = st.selectbox(
        "Saved recipe",
        [recipe_label(recipe) for recipe in generated_recipes],
        key="saved-ai-recipe",
    )
    selected = generated_recipes[[recipe_label(recipe) for recipe in generated_recipes].index(selected_label)]
    recipe_card(selected["id"])
    if st.button("Delete", key=f"delete-ai-{selected['id']}"):
        delete_generated_recipe(selected["id"])
        st.rerun()

    if st.button("Delete all AI-generated recipes"):
        save_generated_recipes([])
        st.rerun()


def add_valid_recipes(raw_recipes: list[dict[str, Any]]) -> None:
    existing_ids = {recipe["id"] for recipe in get_all_recipes()}
    existing_names = {recipe.get("name", "").strip().lower() for recipe in get_all_recipes()}
    valid_recipes: list[dict[str, Any]] = []
    validation_errors: list[str] = []

    for index, raw_recipe in enumerate(raw_recipes, start=1):
        recipe, errors = validate_recipe(raw_recipe, existing_ids, existing_names)
        if errors:
            validation_errors.append(f"Recipe {index}: " + " ".join(errors))
            continue
        valid_recipes.append(recipe)
        existing_ids.add(recipe["id"])
        existing_names.add(recipe["name"].strip().lower())

    if validation_errors:
        st.error("Some recipes could not be added.")
        for error in validation_errors:
            st.write(f"- {error}")

    if valid_recipes:
        save_generated_recipes([*get_generated_recipes(), *valid_recipes])
        reports.append_event("ai_recipe_added", {"count": len(valid_recipes)})
        st.success(f"Added {len(valid_recipes)} recipe{'s' if len(valid_recipes) != 1 else ''}.")


def delete_generated_recipe(recipe_id: str) -> None:
    generated_recipes = get_generated_recipes()
    next_recipes = [recipe for recipe in generated_recipes if recipe.get("id") != recipe_id]
    if len(next_recipes) == len(generated_recipes):
        st.warning("That AI-generated recipe was not found.")
        return
    save_generated_recipes(next_recipes)
    st.success("Deleted AI-generated recipe.")


def render_profile(planner: MealPlanner) -> None:
    st.title("Profile")
    profile = planner.profile
    recipes = get_all_recipes()

    with st.form("profile-form"):
        st.subheader("Daily targets")
        cols = st.columns(4)
        kcal = cols[0].number_input("Calories", min_value=0, value=int(profile.get("kcal", 1600)))
        protein = cols[1].number_input("Protein (g)", min_value=0, value=int(profile.get("protein", 110)))
        carbs = cols[2].number_input("Carbs (g)", min_value=0, value=int(profile.get("carbs", 160)))
        fat = cols[3].number_input("Fat (g)", min_value=0, value=int(profile.get("fat", 55)))

        st.subheader("Drinks")
        drink_ids = list(DRINKS.keys())
        drink_id = st.selectbox(
            "What you drink",
            drink_ids,
            index=drink_ids.index(profile.get("chaiDrinkId", "masala-chai")),
            format_func=lambda drink_key: DRINKS[drink_key]["name"],
        )
        chai_count = st.number_input("How many per day", min_value=0, max_value=6, value=int(profile.get("chaiCount", 2)))

        st.subheader("Preferences")
        prefers_warm = st.checkbox("Prefer warm meals", value=bool(profile.get("prefersWarm", True)))
        exclusions = st.multiselect(
            "Exclusions",
            ["beef", "fish", "pork", "chicken", "lamb", "shrimp", "egg", "dairy"],
            default=profile.get("exclusions", []),
        )

        breakfasts = [recipe for recipe in recipes if "breakfast" in recipe.get("mealTypes", [])]
        snacks = [recipe for recipe in recipes if "snack" in recipe.get("mealTypes", [])]
        locked_breakfasts = st.multiselect(
            "Locked breakfasts",
            [recipe["id"] for recipe in breakfasts],
            default=profile.get("lockedBreakfastIds", []),
            format_func=meal_name,
        )
        locked_snacks = st.multiselect(
            "Locked snacks",
            [recipe["id"] for recipe in snacks],
            default=profile.get("lockedSnackIds", []),
            format_func=meal_name,
        )

        st.subheader("Slot times")
        times = profile.get("slotTimes") or DEFAULT_PROFILE["slotTimes"]
        time_cols = st.columns(3)
        chai1 = time_cols[0].time_input("Morning chai", value=datetime.strptime(times["chai1"], "%H:%M").time())
        breakfast = time_cols[1].time_input("Breakfast", value=datetime.strptime(times["breakfast"], "%H:%M").time())
        lunch = time_cols[2].time_input("Lunch", value=datetime.strptime(times["lunch"], "%H:%M").time())
        chai2 = time_cols[0].time_input("Afternoon chai", value=datetime.strptime(times["chai2"], "%H:%M").time())
        snack = time_cols[1].time_input("Snack", value=datetime.strptime(times["snack"], "%H:%M").time())
        dinner = time_cols[2].time_input("Dinner", value=datetime.strptime(times["dinner"], "%H:%M").time())

        submitted = st.form_submit_button("Save profile", type="primary")

    if submitted:
        profile.update(
            {
                "kcal": int(kcal),
                "protein": int(protein),
                "carbs": int(carbs),
                "fat": int(fat),
                "chaiDrinkId": drink_id,
                "chaiCount": int(chai_count),
                "prefersWarm": bool(prefers_warm),
                "exclusions": list(exclusions),
                "lockedBreakfastIds": list(locked_breakfasts),
                "lockedSnackIds": list(locked_snacks),
                "slotTimes": {
                    "chai1": chai1.strftime("%H:%M"),
                    "breakfast": breakfast.strftime("%H:%M"),
                    "lunch": lunch.strftime("%H:%M"),
                    "chai2": chai2.strftime("%H:%M"),
                    "snack": snack.strftime("%H:%M"),
                    "dinner": dinner.strftime("%H:%M"),
                },
            }
        )
        save_and_rerun(planner)


def main() -> None:
    configure_recipe_pool()
    planner = get_planner()

    st.sidebar.title("Meal Planner")
    pages = ["Today", "Plan Week", "Week", "AI Adjust Plan", "Grocery List", "Reports", "Export", "Recipe Library", "AI Recipes", "Profile"]
    default_page = st.session_state.get("page", "Today")
    if default_page == "Recipes":
        default_page = "Recipe Library"
    if default_page not in pages:
        default_page = "Today"
    page = st.sidebar.radio("View", pages, index=pages.index(default_page))
    st.session_state.page = page
    st.sidebar.caption(f"{len(get_static_recipes())} static · {len(get_generated_recipes())} AI-generated")
    if len(get_generated_recipes()) > 100:
        st.sidebar.warning("Over 100 AI-generated recipes saved.")
    if "plan_generation_seconds" in st.session_state:
        st.sidebar.caption(f"Plan: {st.session_state.plan_generation_seconds:.2f}s")
    if "ai_generation_seconds" in st.session_state:
        st.sidebar.caption(f"AI recipe: {st.session_state.ai_generation_seconds:.2f}s")
    if st.session_state.get("recipe_storage_error"):
        st.sidebar.warning(st.session_state.recipe_storage_error)

    if planner.state.get("currentWeek"):
        start = planner.state["currentWeek"]["startDate"]
        st.sidebar.caption(f"Current week starts {short_date(start)}")
    else:
        st.sidebar.caption("No week planned yet")

    if st.sidebar.button("Save state"):
        planner.save()
        st.sidebar.success("Saved")

    if page == "Today":
        render_today(planner)
    elif page == "Week":
        render_week(planner)
    elif page == "Plan Week":
        render_plan(planner)
    elif page == "AI Adjust Plan":
        render_ai_adjust_plan(planner)
    elif page == "Grocery List":
        render_grocery(planner)
    elif page == "Reports":
        render_reports()
    elif page == "Export":
        render_export(planner)
    elif page == "Recipe Library":
        render_recipes(planner)
    elif page == "AI Recipes":
        render_ai_recipes()
    elif page == "Profile":
        render_profile(planner)


if __name__ == "__main__":
    main()
