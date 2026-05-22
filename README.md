# AI-Assisted Meal Prep & Pantry Optimization Platform

An AI-assisted meal planning and pantry optimization application built with Python and Streamlit.

The platform combines pantry-aware recommendation systems, dynamic AI-generated recipes, workflow orchestration, analytics, reporting, and AI-powered meal adjustment workflows to reduce planning friction, improve grocery efficiency, and streamline weekly meal operations.
Live Demo: https://aiassistedmealplanner-bjcbmnhpw5zaxa7xfnjasd.streamlit.app/

---

# Overview

This project began as a lightweight JavaScript prototype focused on reducing meal-planning decision fatigue and grocery waste. It was later migrated to a Python + Streamlit architecture to support:

- AI-assisted recipe generation
- Dynamic workflow orchestration
- Weekly planning systems
- Grocery dependency generation
- Analytics and reporting
- Export and sharing workflows
- Persistent generated recipe management
- AI meal adjustment agents

The goal was to build a practical AI-assisted operational planning system rather than a simple recipe browser or chatbot wrapper.

---

# Problem

Meal planning is repetitive, operationally inefficient, and mentally taxing.

Common pain points include:

- Repeated decision fatigue
- Forgotten pantry inventory
- Grocery waste
- Difficulty balancing nutrition goals
- Time-consuming weekly planning
- Poor execution consistency
- Manual grocery tracking
- Limited adaptability when schedules change

---

# Solution

The platform generates personalized weekly meal plans using:

- Pantry inventory
- Dietary constraints
- Nutrition targets
- Meal preferences
- AI-generated recipes
- AI-assisted meal adjustments
- Weekly scheduling workflows

It then orchestrates:

- Grocery list generation
- Prep planning
- Swap workflows
- Reporting and analytics
- Export/share capabilities
- Monthly behavioral summaries

---

# Key Features

## Pantry-Aware Planning
Prioritizes recipes using existing pantry inventory to reduce waste and unnecessary purchases.

## Weekly Meal Orchestration
Generates full weekly breakfast/lunch/dinner plans with execution-focused workflows.

## AI Recipe Generation
Users can dynamically generate recipes using natural-language prompts.

Example:
- "High protein Indian dinners using paneer and spinach"

## AI Meal Adjustment Agent
Users can modify an existing weekly plan using natural-language instructions.

Example:
- "I'm eating out Friday dinner"
- "Increase protein this week"
- "Use spinach before it expires"

## Grocery Dependency Generation
Automatically generates grocery lists based on missing ingredients.

## Recipe Library UX
Supports:
- filtering
- search
- pantry matching
- favorites
- AI-generated recipe management
- pagination

## Monthly Analytics & Reporting
Tracks:
- pantry utilization
- grocery savings
- cuisine frequency
- protein adherence
- meal completion
- AI-generated recipe usage

Includes AI-generated behavioral summaries.

## Export & Share
Supports exporting:
- weekly plans
- grocery lists
- prep plans
- reports

Formats:
- Markdown
- TXT
- JSON
- CSV

---

# Architecture

High-level workflow:

User Inputs
↓
Session State
↓
Planning Engine
↓
Recommendation / Scoring Engine
↓
AI Recipe Generation
↓
AI Adjustment Agent
↓
Weekly Plan Orchestration
↓
Grocery Dependency Generation
↓
Analytics Layer
↓
Monthly Reporting / Export

Detailed architecture documentation:
See `docs/architecture.md`

---

# Tech Stack

## Frontend
- Streamlit

## Backend / Logic
- Python

## Data Storage
- JSON persistence
- Session state management

## AI
- OpenAI API
- AI-assisted orchestration workflows

## Analytics / Reporting
- Streamlit metrics
- lightweight analytics pipelines

---

# Production / Performance Considerations

The application includes lightweight production-aware optimizations:

- cached recipe loading
- session-state reuse
- lazy AI execution
- pagination
- lightweight persistence
- incremental analytics updates
- validation guardrails
- structured AI outputs

AI calls are executed only when explicitly triggered.

---

# Example Workflows

## Weekly Planning Workflow

Pantry Inventory
↓
Recommendation Scoring
↓
Weekly Plan Generation
↓
Grocery Dependency Resolution
↓
Prep Planning
↓
Execution Tracking

---

## AI Adjustment Workflow

Natural Language Request
↓
Current Plan Analysis
↓
Constraint Validation
↓
Structured AI Output
↓
Plan Adjustment
↓
Grocery / Metrics Update

---

# Repository Structure

# Repository Structure

```text
ai_assisted_meal_planner/
├── app.py
├── requirements.txt
├── README.md
├── meal_planner_state.json
│
├── data/
│   ├── recipes.json
│   ├── generated_recipes.json
│   └── analytics.json
│
├── docs/
│   ├── architecture.md
│   ├── product-requirements.md
│   ├── migration-notes.md
│   └── interview-talking-points.md
│
├── meal_planner/
│   ├── __init__.py
│   ├── planner.py
│   ├── grocery.py
│   ├── reports.py
│   ├── export_utils.py
│   ├── ai_adjustments.py
│   ├── recipe_library.py
│   └── analytics.py
│
├── screenshots/
│   ├── today.png
│   ├── weekly-plan.png
│   ├── recipe-library.png
│   └── reports.png
│
└── .streamlit/
    └── config.toml
```

---

# Setup

## Install dependencies

```bash
pip install -r requirements.txt
```

## Run locally

```bash
streamlit run app.py
```

---

# Future Improvements

Potential future enhancements include:

- SQLite/Postgres migration
- Multi-user accounts
- Cloud deployment
- Vector search / semantic recipe retrieval
- Mobile-first responsive UI
- Notification workflows
- Calendar integrations
- Expiry-aware pantry prioritization
- Budget optimization
- Multi-agent orchestration


---

# Why This Project Exists

This project was intentionally designed as a practical AI operations and workflow orchestration platform rather than a thin chatbot wrapper.

The focus was:
- operational workflows
- constraint management
- orchestration
- product usability
- AI-assisted automation
- behavioral analytics
- scalable architecture thinking

---
