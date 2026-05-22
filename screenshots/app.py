"""Python equivalent of the browser meal planner logic.

This module ports the data/model parts of app.js to Python:
- profile/state persistence
- date helpers
- macro totals
- recipe filtering/scoring
- weekly plan generation
- grocery list generation
- simple meal swapping and completion tracking

The original JavaScript also renders DOM views. In Python those browser UI
functions are represented as data-returning methods that a CLI, Flask app, or
desktop UI can call.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
import random
import re
from pathlib import Path
from typing import Any

from recipes import DRINKS, PANTRY_COMMON, RECIPES


STATE_FILE = Path("meal_planner_state.json")

DEFAULT_PROFILE: dict[str, Any] = {
    "kcal": 1600,
    "protein": 110,
    "carbs": 160,
    "fat": 55,
    "exclusions": ["beef", "fish"],
    "chaiDrinkId": "masala-chai",
    "chaiCount": 2,
    "lockedBreakfastIds": [],
    "lockedSnackIds": ["paneer-tikka-bites", "masala-makhana"],
    "prefersWarm": True,
    "slotTimes": {
        "chai1": "08:00",
        "breakfast": "09:00",
        "lunch": "13:00",
        "chai2": "16:00",
        "snack": "16:30",
        "dinner": "19:30",
    },
}

ZERO_MACROS = {"kcal": 0, "protein": 0, "carbs": 0, "fat": 0}


def fmt_iso(value: date | datetime) -> str:
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()


def today() -> str:
    return date.today().isoformat()


def parse_iso(iso: str) -> date:
    return date.fromisoformat(iso)


def day_name(iso: str) -> str:
    return parse_iso(iso).strftime("%A")


def short_date(iso: str) -> str:
    # Similar to JS: "Sat, May 10"
    d = parse_iso(iso)
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}"


def add_days(iso: str, n: int) -> str:
    return (parse_iso(iso) + timedelta(days=n)).isoformat()


def is_today(iso: str) -> bool:
    return iso == today()


def find_saturday(iso: str) -> str:
    d = parse_iso(iso)
    # Python Monday=0 ... Sunday=6; Saturday=5.
    back = (d.weekday() - 5) % 7
    return (d - timedelta(days=back)).isoformat()


def time_to_minutes(hhmm: str | None) -> int:
    if not hhmm:
        return 0
    hour, minute = (int(part) for part in hhmm.split(":"))
    return hour * 60 + minute


def now_minutes() -> int:
    now = datetime.now()
    return now.hour * 60 + now.minute


def format_time_12(hhmm: str | None) -> str:
    if not hhmm:
        return ""
    hour, minute = (int(part) for part in hhmm.split(":"))
    period = "pm" if hour >= 12 else "am"
    hour_12 = 12 if hour % 12 == 0 else hour % 12
    return f"{hour_12}:{minute:02d} {period}"


def recipe_by_id(recipe_id: str | None) -> dict[str, Any] | None:
    if not recipe_id:
        return None
    return next((recipe for recipe in RECIPES if recipe["id"] == recipe_id), None)


def macro_dict(item: dict[str, Any] | None) -> dict[str, int]:
    if not item:
        return dict(ZERO_MACROS)
    return {
        "kcal": int(item.get("kcal", 0)),
        "protein": int(item.get("protein", 0)),
        "carbs": int(item.get("carbs", 0)),
        "fat": int(item.get("fat", 0)),
    }


def sum_macros(items: list[dict[str, int]]) -> dict[str, int]:
    return {
        key: sum(int(item.get(key, 0)) for item in items)
        for key in ("kcal", "protein", "carbs", "fat")
    }


def interleave(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out


def load_state(path: Path = STATE_FILE) -> dict[str, Any]:
    if not path.exists():
        return {"profile": deepcopy(DEFAULT_PROFILE), "pantry": [], "currentWeek": None, "history": {}}
    state = json.loads(path.read_text())
    return migrate_state(state)


def save_state(state: dict[str, Any], path: Path = STATE_FILE) -> None:
    path.write_text(json.dumps(state, indent=2))


def migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("profile", {})
    for key, value in DEFAULT_PROFILE.items():
        state["profile"].setdefault(key, deepcopy(value))
    if not isinstance(state["profile"].get("slotTimes"), dict):
        state["profile"]["slotTimes"] = deepcopy(DEFAULT_PROFILE["slotTimes"])
    state.setdefault("pantry", [])
    state.setdefault("currentWeek", None)
    state.setdefault("history", {})
    return state


@dataclass
class MealPlanner:
    state: dict[str, Any] = field(default_factory=lambda: load_state())
    state_path: Path = STATE_FILE

    def __post_init__(self) -> None:
        self.state = migrate_state(self.state)

    @property
    def profile(self) -> dict[str, Any]:
        return self.state["profile"]

    @property
    def pantry(self) -> list[str]:
        return self.state["pantry"]

    def save(self) -> None:
        save_state(self.state, self.state_path)

    def in_current_week(self, iso: str) -> bool:
        week = self.state.get("currentWeek")
        if not week:
            return False
        start = week["startDate"]
        return start <= iso <= add_days(start, 6)

    def drink_info(self) -> dict[str, Any]:
        return DRINKS.get(self.profile.get("chaiDrinkId"), DRINKS["masala-chai"])

    def daily_drink_macros(self) -> dict[str, int]:
        drink = self.drink_info()
        count = int(self.profile.get("chaiCount", 0))
        return {key: int(drink.get(key, 0)) * count for key in ("kcal", "protein", "carbs", "fat")}

    def recipe_macros(self, recipe_id: str | None) -> dict[str, int]:
        return macro_dict(recipe_by_id(recipe_id))

    def day_total_macros(self, iso: str) -> dict[str, int]:
        week = self.state.get("currentWeek")
        day = week.get("plan", {}).get(iso) if week else None
        if not day or day.get("eatingOut"):
            return dict(ZERO_MACROS)
        lunch = day.get("lunch") or {}
        dinner = day.get("dinner") or {}
        return sum_macros(
            [
                self.daily_drink_macros(),
                self.recipe_macros(day.get("breakfast")),
                self.recipe_macros(day.get("snack")),
                self.recipe_macros(lunch.get("recipeId")),
                self.recipe_macros(dinner.get("recipeId")),
            ]
        )

    def is_allowed(self, recipe: dict[str, Any]) -> bool:
        exclusions = set(self.profile.get("exclusions", []))
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

    def passes_warm_filter(self, recipe: dict[str, Any]) -> bool:
        return not self.profile.get("prefersWarm", True) or recipe.get("warm") is not False

    def score_recipe(self, recipe: dict[str, Any]) -> int:
        pantry_lower = [item.lower() for item in self.pantry]
        score = 0
        for ingredient in recipe.get("ingredients", []):
            lower = ingredient.lower()
            if any(pantry_item in lower for pantry_item in pantry_lower):
                score += 1
        return score

    def filter_pool(self, meal_type: str) -> list[dict[str, Any]]:
        allowed = [
            recipe
            for recipe in RECIPES
            if meal_type in recipe.get("mealTypes", []) and self.is_allowed(recipe)
        ]
        if not self.profile.get("prefersWarm", True):
            return allowed
        warm = [recipe for recipe in allowed if recipe.get("warm") is not False]
        return warm if len(warm) >= 2 else allowed

    def generate_plan(
        self,
        start_date: str,
        eating_out_days: list[str] | None = None,
        eating_out_meals: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        eating_out = set(eating_out_days or [])
        skipped_by_day: dict[str, set[str]] = {}
        for iso, meal_types in (eating_out_meals or {}).items():
            skipped_by_day[iso] = {
                meal_type
                for meal_type in meal_types
                if meal_type in {"lunch", "dinner"}
            }
        breakfasts = self.filter_pool("breakfast")

        mains_by_id: dict[str, dict[str, Any]] = {}
        for recipe in [*self.filter_pool("lunch"), *self.filter_pool("dinner")]:
            mains_by_id.setdefault(recipe["id"], recipe)
        mains = sorted(mains_by_id.values(), key=self.score_recipe, reverse=True)

        indian_mains = [recipe for recipe in mains if recipe.get("cuisine") == "indian"]
        western_mains = [recipe for recipe in mains if recipe.get("cuisine") == "western"]
        lunch_pool = interleave(indian_mains, western_mains)[:8]
        dinner_pool = interleave(western_mains, indian_mains)[:8]

        used_ids: set[str] = set()
        lunch_picks: list[dict[str, Any]] = []
        dinner_picks: list[dict[str, Any]] = []

        for recipe in lunch_pool:
            if len(lunch_picks) >= 4:
                break
            if recipe["id"] not in used_ids:
                lunch_picks.append(recipe)
                used_ids.add(recipe["id"])

        for recipe in dinner_pool:
            if len(dinner_picks) >= 4:
                break
            if recipe["id"] not in used_ids:
                dinner_picks.append(recipe)
                used_ids.add(recipe["id"])

        for recipe in mains:
            if len(lunch_picks) < 4 and recipe["id"] not in used_ids:
                lunch_picks.append(recipe)
                used_ids.add(recipe["id"])
            if len(dinner_picks) < 4 and recipe["id"] not in used_ids:
                dinner_picks.append(recipe)
                used_ids.add(recipe["id"])

        active_meals = {
            meal_type: [
                add_days(start_date, i)
                for i in range(7)
                if add_days(start_date, i) not in eating_out
                and meal_type not in skipped_by_day.get(add_days(start_date, i), set())
            ]
            for meal_type in ("lunch", "dinner")
        }
        active_index = {
            meal_type: {iso: idx for idx, iso in enumerate(days)}
            for meal_type, days in active_meals.items()
        }

        plan: dict[str, Any] = {}
        for i in range(7):
            iso = add_days(start_date, i)
            if iso in eating_out:
                plan[iso] = {
                    "eatingOut": True,
                    "skippedMeals": {"lunch": True, "dinner": True},
                }
                continue

            locked_breakfasts = self.profile.get("lockedBreakfastIds") or []
            breakfast_id = (
                locked_breakfasts[i % len(locked_breakfasts)]
                if locked_breakfasts
                else (breakfasts[i % len(breakfasts)]["id"] if breakfasts else None)
            )

            skipped_meals = skipped_by_day.get(iso, set())
            lunch_idx = active_index["lunch"].get(iso)
            dinner_idx = active_index["dinner"].get(iso)
            lunch_recipe = (
                lunch_picks[(lunch_idx or 0) // 2 % len(lunch_picks)]
                if lunch_idx is not None and lunch_picks
                else None
            )
            dinner_recipe = (
                dinner_picks[(dinner_idx or 0) // 2 % len(dinner_picks)]
                if dinner_idx is not None and dinner_picks
                else None
            )
            lunch_source = "cook-today" if lunch_idx is not None and lunch_idx % 2 == 0 else "leftover"
            dinner_source = "cook-today" if dinner_idx is not None and dinner_idx % 2 == 0 else "leftover"

            locked_snacks = self.profile.get("lockedSnackIds") or []
            if locked_snacks:
                snack_pool = locked_snacks
            else:
                snack_pool = [
                    recipe["id"]
                    for recipe in RECIPES
                    if "snack" in recipe.get("mealTypes", [])
                    and self.is_allowed(recipe)
                    and self.passes_warm_filter(recipe)
                ]
            snack_id = snack_pool[i % len(snack_pool)] if snack_pool else None

            plan[iso] = {
                "eatingOut": False,
                "skippedMeals": {meal_type: True for meal_type in sorted(skipped_meals)},
                "breakfast": breakfast_id,
                "snack": snack_id,
                "lunch": (
                    None
                    if "lunch" in skipped_meals
                    else {"recipeId": lunch_recipe["id"] if lunch_recipe else None, "source": lunch_source}
                ),
                "dinner": (
                    None
                    if "dinner" in skipped_meals
                    else {"recipeId": dinner_recipe["id"] if dinner_recipe else None, "source": dinner_source}
                ),
            }

        week = {"startDate": start_date, "plan": plan, "groceryChecked": {}}
        self.state["currentWeek"] = week
        return week

    def build_grocery_list(self) -> dict[str, list[dict[str, str]]]:
        week = self.state.get("currentWeek")
        if not week:
            return {}

        cooked_ids: set[str] = set()
        for day in week["plan"].values():
            if day.get("eatingOut"):
                continue
            if day.get("breakfast"):
                cooked_ids.add(day["breakfast"])
            if day.get("snack"):
                cooked_ids.add(day["snack"])
            lunch = day.get("lunch") or {}
            dinner = day.get("dinner") or {}
            if lunch.get("source") == "cook-today" and lunch.get("recipeId"):
                cooked_ids.add(lunch["recipeId"])
            if dinner.get("source") == "cook-today" and dinner.get("recipeId"):
                cooked_ids.add(dinner["recipeId"])

        pantry_lower = [item.lower() for item in self.pantry]
        groups: dict[str, list[dict[str, str]]] = {
            "Produce": [],
            "Protein": [],
            "Dairy": [],
            "Pantry": [],
            "Spices": [],
        }
        seen: set[str] = set()

        for recipe_id in cooked_ids:
            recipe = recipe_by_id(recipe_id)
            if not recipe:
                continue
            for ingredient in recipe.get("ingredients", []):
                lower = ingredient.lower()
                if any(pantry_item in lower for pantry_item in pantry_lower):
                    continue
                if ingredient in seen:
                    continue
                seen.add(ingredient)
                groups[self.categorize_ingredient(ingredient)].append(
                    {"text": ingredient, "fromRecipe": recipe["name"]}
                )
        return groups

    @staticmethod
    def categorize_ingredient(text: str) -> str:
        t = text.lower()
        if re.search(
            r"chicken|lamb|shrimp|beef|pork|bacon|egg|tofu|paneer|lentil|dal|"
            r"chickpea|kidney bean|whey|cottage cheese",
            t,
        ):
            return "Protein"
        if re.search(r"yogurt|milk|paneer|cheese|cream|butter|ghee", t):
            return "Dairy"
        if re.search(
            r"onion|tomato|garlic|ginger|spinach|pepper|cilantro|lemon|lime|cucumber|"
            r"carrot|broccoli|peas|avocado|berries|romaine|lettuce|cabbage|celery|"
            r"scallion|basil|zucchini|cauliflower|chili",
            t,
        ):
            return "Produce"
        if re.search(
            r"spice|cumin|turmeric|garam|coriander|paprika|chili|pepper|masala|"
            r"ajwain|mustard|cardamom|cinnamon|bay leaf|kasuri|methi|thyme|"
            r"oregano|salt|chaat",
            t,
        ):
            return "Spices"
        if re.search(
            r"rice|oats|flour|besan|quinoa|pasta|tortilla|bread|toast|honey|"
            r"soy|sesame|oil|chia|makhana|almonds|seeds|tahini|dijon",
            t,
        ):
            return "Pantry"
        return "Pantry"

    def get_day_slots(self, day: dict[str, Any]) -> list[dict[str, Any]]:
        times = self.profile.get("slotTimes") or DEFAULT_PROFILE["slotTimes"]
        slots: list[dict[str, Any]] = []
        if self.profile.get("chaiCount", 0) >= 1:
            slots.append({"key": "chai1", "label": "Morning chai", "time": times["chai1"], "kind": "chai"})
        if day.get("breakfast"):
            slots.append(
                {
                    "key": "breakfast",
                    "label": "Breakfast",
                    "time": times["breakfast"],
                    "kind": "meal",
                    "recipeId": day["breakfast"],
                }
            )
        lunch = day.get("lunch") or {}
        dinner = day.get("dinner") or {}
        if lunch.get("recipeId"):
            slots.append(
                {
                    "key": "lunch",
                    "label": "Lunch",
                    "time": times["lunch"],
                    "kind": "meal",
                    "recipeId": lunch["recipeId"],
                    "source": lunch["source"],
                }
            )
        if self.profile.get("chaiCount", 0) >= 2:
            slots.append({"key": "chai2", "label": "Afternoon chai", "time": times["chai2"], "kind": "chai"})
        if day.get("snack"):
            slots.append(
                {
                    "key": "snack",
                    "label": "Snack",
                    "time": times["snack"],
                    "kind": "meal",
                    "recipeId": day["snack"],
                }
            )
        if dinner.get("recipeId"):
            slots.append(
                {
                    "key": "dinner",
                    "label": "Dinner",
                    "time": times["dinner"],
                    "kind": "meal",
                    "recipeId": dinner["recipeId"],
                    "source": dinner["source"],
                }
            )
        return sorted(slots, key=lambda slot: time_to_minutes(slot.get("time")))

    def next_slot(self, slots: list[dict[str, Any]], checked: dict[str, bool]) -> dict[str, Any] | None:
        current = now_minutes()
        for slot in slots:
            if checked.get(slot["key"]):
                continue
            if time_to_minutes(slot.get("time")) + 60 >= current:
                return slot
        return None

    def today_summary(self) -> dict[str, Any]:
        iso = today()
        week = self.state.get("currentWeek")
        if not week or not self.in_current_week(iso):
            return {"status": "no-plan", "date": iso}
        day = week["plan"].get(iso)
        if not day or day.get("eatingOut"):
            return {"status": "eating-out" if day and day.get("eatingOut") else "no-day", "date": iso}
        checked = self.state.get("history", {}).get(iso, {})
        slots = self.get_day_slots(day)
        return {
            "status": "ok",
            "date": iso,
            "macros": self.day_total_macros(iso),
            "target": self.profile,
            "next": self.next_slot(slots, checked),
            "slots": slots,
            "checked": checked,
        }

    def toggle_checked(self, iso: str, key: str) -> bool:
        history = self.state.setdefault("history", {})
        day = history.setdefault(iso, {})
        day[key] = not day.get(key, False)
        return day[key]

    def toggle_grocery(self, key: str) -> bool:
        week = self.state["currentWeek"]
        checked = week.setdefault("groceryChecked", {})
        checked[key] = not checked.get(key, False)
        return checked[key]

    def swap_meal(self, iso: str, slot: str) -> dict[str, Any] | None:
        day = self.state.get("currentWeek", {}).get("plan", {}).get(iso)
        if not day:
            return None

        is_string_slot = slot in {"breakfast", "snack"}
        current = day.get(slot) if is_string_slot else (day.get(slot) or {}).get("recipeId")
        candidates = [
            recipe
            for recipe in RECIPES
            if recipe["id"] != current and slot in recipe.get("mealTypes", []) and self.is_allowed(recipe)
        ]
        if not candidates:
            return None

        pick = random.choice(candidates)
        if is_string_slot:
            day[slot] = pick["id"]
        else:
            day[slot] = {"recipeId": pick["id"], "source": "cook-today"}
        return pick


def print_week(planner: MealPlanner) -> None:
    week = planner.state.get("currentWeek")
    if not week:
        print("No plan yet.")
        return
    for i in range(7):
        iso = add_days(week["startDate"], i)
        day = week["plan"].get(iso, {})
        if day.get("eatingOut"):
            print(f"{short_date(iso)}: Eating out")
            continue
        breakfast = recipe_by_id(day.get("breakfast"))
        lunch_slot = day.get("lunch") or {}
        dinner_slot = day.get("dinner") or {}
        lunch = recipe_by_id(lunch_slot.get("recipeId"))
        dinner = recipe_by_id(dinner_slot.get("recipeId"))
        print(f"{short_date(iso)}")
        print(f"  B: {breakfast['name'] if breakfast else '-'}")
        print(f"  L: {lunch['name'] if lunch else '-'} ({lunch_slot.get('source', '-')})")
        print(f"  D: {dinner['name'] if dinner else '-'} ({dinner_slot.get('source', '-')})")


if __name__ == "__main__":
    planner = MealPlanner()
    if not planner.state.get("currentWeek"):
        planner.generate_plan(today(), [])
        planner.save()
    print_week(planner)
