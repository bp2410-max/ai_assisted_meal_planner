from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import smtplib
from email.message import EmailMessage
from typing import Any

import streamlit as st


ANALYTICS_PATH = Path("data/analytics.json")
ESTIMATED_GROCERY_ITEM_COST = 3.50


def ensure_analytics_file(path: Path = ANALYTICS_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_text("[]\n")


@st.cache_data(show_spinner=False)
def load_events_cached(path_str: str) -> list[dict[str, Any]]:
    path = Path(path_str)
    ensure_analytics_file(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def load_events(path: Path = ANALYTICS_PATH) -> list[dict[str, Any]]:
    return load_events_cached(str(path))


def append_event(event_type: str, payload: dict[str, Any] | None = None, path: Path = ANALYTICS_PATH) -> None:
    ensure_analytics_file(path)
    events = load_events(path)
    events.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            "payload": payload or {},
        }
    )
    path.write_text(json.dumps(events[-2000:], indent=2) + "\n")
    load_events_cached.clear()


def month_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m")


def previous_month_key(current: str) -> str:
    year, month = (int(part) for part in current.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def event_month(event: dict[str, Any]) -> str:
    try:
        return datetime.fromisoformat(event["timestamp"]).strftime("%Y-%m")
    except Exception:
        return ""


def aggregate_month(events: list[dict[str, Any]], target_month: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "month": target_month,
        "meals_completed": 0,
        "pantry_utilization_values": [],
        "grocery_items_avoided": 0,
        "grocery_savings": 0.0,
        "cuisine_frequency": Counter(),
        "protein_adherent_days": 0,
        "protein_days": 0,
        "swaps_performed": 0,
        "ai_generated_recipes_used": 0,
        "eating_out_meals": 0,
        "meal_prep_sessions": 0,
        "recipe_frequency": Counter(),
        "completed_by_week": defaultdict(int),
        "pantry_trend": [],
    }

    for event in events:
        if event_month(event) != target_month:
            continue
        payload = event.get("payload", {})
        event_type = event.get("type")

        if event_type == "meal_completed":
            summary["meals_completed"] += 1
            recipe_name = payload.get("recipe_name")
            if recipe_name:
                summary["recipe_frequency"][recipe_name] += 1
            cuisine = payload.get("cuisine")
            if cuisine:
                summary["cuisine_frequency"][cuisine] += 1
            try:
                week_num = datetime.fromisoformat(event["timestamp"]).isocalendar().week
                summary["completed_by_week"][f"Week {week_num}"] += 1
            except Exception:
                pass

        elif event_type == "plan_generated":
            summary["grocery_items_avoided"] += int(payload.get("grocery_items_avoided", 0))
            summary["eating_out_meals"] += int(payload.get("eating_out_meals", 0))
            summary["meal_prep_sessions"] += int(payload.get("meal_prep_sessions", 0))
            summary["ai_generated_recipes_used"] += int(payload.get("ai_generated_recipes_used", 0))
            for cuisine, count in payload.get("cuisine_frequency", {}).items():
                summary["cuisine_frequency"][cuisine] += int(count)
            for recipe_name, count in payload.get("recipe_frequency", {}).items():
                summary["recipe_frequency"][recipe_name] += int(count)
            utilization = payload.get("pantry_utilization")
            if utilization is not None:
                summary["pantry_utilization_values"].append(float(utilization))
                summary["pantry_trend"].append(
                    {
                        "date": event.get("timestamp", "")[:10],
                        "pantry_utilization": float(utilization),
                    }
                )
            summary["protein_adherent_days"] += int(payload.get("protein_adherent_days", 0))
            summary["protein_days"] += int(payload.get("protein_days", 0))

        elif event_type == "meal_swapped":
            summary["swaps_performed"] += 1

        elif event_type == "ai_recipe_added":
            summary["ai_generated_recipes_used"] += int(payload.get("count", 1))

    avg_utilization = (
        sum(summary["pantry_utilization_values"]) / len(summary["pantry_utilization_values"])
        if summary["pantry_utilization_values"]
        else 0
    )
    summary["pantry_utilization"] = round(avg_utilization, 1)
    summary["grocery_savings"] = round(summary["grocery_items_avoided"] * ESTIMATED_GROCERY_ITEM_COST, 2)
    summary["most_used_cuisine"] = summary["cuisine_frequency"].most_common(1)[0][0] if summary["cuisine_frequency"] else "-"
    summary["top_recipe"] = summary["recipe_frequency"].most_common(1)[0][0] if summary["recipe_frequency"] else "-"
    summary["protein_target_adherence"] = (
        round((summary["protein_adherent_days"] / summary["protein_days"]) * 100, 1)
        if summary["protein_days"]
        else 0
    )
    summary["cuisine_frequency"] = dict(summary["cuisine_frequency"])
    summary["recipe_frequency"] = dict(summary["recipe_frequency"])
    summary["completed_by_week"] = dict(summary["completed_by_week"])
    return summary


def compare_months(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {}
    keys = ["meals_completed", "pantry_utilization", "grocery_savings", "protein_target_adherence"]
    return {key: round(current.get(key, 0) - previous.get(key, 0), 1) for key in keys}


def monthly_report_markdown(summary: dict[str, Any], comparison: dict[str, Any] | None = None, ai_summary: str | None = None) -> str:
    comparison = comparison or {}
    lines = [
        f"# Meal Planner Monthly Report - {summary['month']}",
        "",
        f"- Meals completed: {summary['meals_completed']} ({comparison.get('meals_completed', 0):+})",
        f"- Pantry utilization: {summary['pantry_utilization']}% ({comparison.get('pantry_utilization', 0):+}%)",
        f"- Grocery savings estimate: ${summary['grocery_savings']:.2f} ({comparison.get('grocery_savings', 0):+})",
        f"- Most-used cuisine: {summary['most_used_cuisine']}",
        f"- Top recipe: {summary['top_recipe']}",
        f"- Protein target adherence: {summary['protein_target_adherence']}%",
        "",
    ]
    if ai_summary:
        lines.extend(["## AI Summary", "", ai_summary, ""])
    lines.extend(
        [
            "## Operational Notes",
            "",
            f"- Swaps performed: {summary['swaps_performed']}",
            f"- AI-generated recipes used: {summary['ai_generated_recipes_used']}",
            f"- Eating-out meals: {summary['eating_out_meals']}",
            f"- Meal-prep sessions: {summary['meal_prep_sessions']}",
            "",
        ]
    )
    return "\n".join(lines)


def monthly_report_text(summary: dict[str, Any], comparison: dict[str, Any] | None = None, ai_summary: str | None = None) -> str:
    return monthly_report_markdown(summary, comparison, ai_summary).replace("# ", "").replace("## ", "")


def monthly_report_json(summary: dict[str, Any], comparison: dict[str, Any] | None = None, ai_summary: str | None = None) -> str:
    return json.dumps({"summary": summary, "comparison": comparison or {}, "ai_summary": ai_summary}, indent=2) + "\n"


def email_preview(summary: dict[str, Any], comparison: dict[str, Any] | None = None, ai_summary: str | None = None) -> str:
    body = monthly_report_text(summary, comparison, ai_summary)
    return f"Subject: Your {summary['month']} meal planning report\n\n{body}"


def generate_ai_summary(summary: dict[str, Any], comparison: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is not set."
    try:
        from openai import OpenAI
    except ImportError:
        return None, "The openai package is not installed."
    try:
        response = OpenAI(api_key=api_key).chat.completions.create(
            model=os.getenv("OPENAI_REPORT_MODEL", "gpt-4.1-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "Write a calm, concise monthly meal-planning ops summary. No markdown table.",
                },
                {
                    "role": "user",
                    "content": json.dumps({"summary": summary, "comparison": comparison or {}}),
                },
            ],
            temperature=0.4,
        )
        return response.choices[0].message.content, None
    except Exception as exc:
        return None, f"AI summary failed: {exc}"


def send_email(subject: str, body: str, to_email: str | None = None) -> tuple[bool, str]:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM") or user
    to_email = to_email or os.getenv("SMTP_TO")
    if not all([host, user, password, from_email, to_email]):
        return False, "Email credentials are not configured. Preview is available."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True, "Email sent."
    except Exception as exc:
        return False, f"Email send failed: {exc}"


def plan_analytics_payload(
    week: dict[str, Any],
    recipes: list[dict[str, Any]],
    pantry_metrics: list[dict[str, Any]],
    grocery_items_avoided: int,
    protein_target: int,
) -> dict[str, Any]:
    recipe_lookup = {recipe.get("id"): recipe for recipe in recipes}
    cuisine = Counter()
    recipe_frequency = Counter()
    eating_out_meals = 0
    meal_prep_sessions = 0
    ai_used = 0
    protein_adherent_days = 0
    protein_days = 0

    for day in week.get("plan", {}).values():
        if day.get("eatingOut"):
            eating_out_meals += 2
            continue
        day_protein = 0
        for meal_type in ("breakfast", "snack", "lunch", "dinner"):
            meal = day.get(meal_type)
            recipe_id = meal if meal_type in {"breakfast", "snack"} else (meal or {}).get("recipeId")
            if meal_type in {"lunch", "dinner"} and meal is None:
                eating_out_meals += 1
                continue
            recipe = recipe_lookup.get(recipe_id)
            if not recipe:
                continue
            cuisine[recipe.get("cuisine", "other")] += 1
            recipe_frequency[recipe.get("name", recipe_id)] += 1
            day_protein += int(recipe.get("protein", 0))
            if recipe.get("generated") or recipe.get("source") == "ai_generated":
                ai_used += 1
            if meal_type in {"lunch", "dinner"} and isinstance(meal, dict) and meal.get("source") == "cook-today":
                meal_prep_sessions += 1
        protein_days += 1
        if day_protein >= protein_target:
            protein_adherent_days += 1

    utilization_values = [float(item.get("pantry_utilization", 0)) for item in pantry_metrics]
    utilization = sum(utilization_values) / len(utilization_values) if utilization_values else 0
    return {
        "pantry_utilization": round(utilization, 1),
        "grocery_items_avoided": grocery_items_avoided,
        "cuisine_frequency": dict(cuisine),
        "recipe_frequency": dict(recipe_frequency),
        "protein_adherent_days": protein_adherent_days,
        "protein_days": protein_days,
        "ai_generated_recipes_used": ai_used,
        "eating_out_meals": eating_out_meals,
        "meal_prep_sessions": meal_prep_sessions,
    }
