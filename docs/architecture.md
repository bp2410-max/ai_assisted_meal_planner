# Architecture Overview

## System Goals

The platform was designed to:

- reduce meal-planning friction
- optimize pantry utilization
- automate grocery generation
- support AI-assisted planning workflows
- remain lightweight and responsive
- maintain modular architecture

---

# High-Level Architecture

```text
User Inputs
↓
Session State
↓
Planning Engine
↓
Recommendation Engine
↓
AI Generation Layer
↓
Weekly Plan Orchestration
↓
Grocery Dependency Resolution
↓
Analytics & Reporting
↓
Export / Email Workflows
```

---

# Core Components

## 1. Streamlit UI Layer

Responsibilities:
- render pages/tabs
- collect user input
- display plans/reports
- trigger workflows
- manage interaction state

Examples:
- Today page
- Weekly planner
- Recipe library
- Reports dashboard
- Export workflows

---

## 2. Session State Layer

Uses:
- `st.session_state`

Stores:
- weekly plan
- pantry inventory
- profile settings
- completed meals
- generated recipes
- adjustment history

Purpose:
- avoid unnecessary recomputation
- preserve UX continuity
- maintain workflow state

---

## 3. Recipe Data Layer

### Static Recipes
Stored in:
- `recipes.json`

### AI-Generated Recipes
Stored in:
- `generated_recipes.json`

Purpose:
- combine curated and dynamic content
- support persistence
- maintain lifecycle separation

---

# Planning Engine

Core orchestration logic responsible for:

- meal selection
- scheduling
- pantry-aware prioritization
- weekly plan generation

Functions include:
- recipe scoring
- filtering
- orchestration
- scheduling

---

# Recommendation / Scoring Engine

Uses:
- pantry inventory
- exclusions
- macros
- tags
- meal type

Purpose:
- rank recipes intelligently
- reduce grocery waste
- prioritize relevant meals

---

# AI Recipe Generation Layer

Uses LLM workflows to dynamically generate recipes from natural-language prompts.

Example:
- "High protein Indian dinners using paneer"

Generated recipes:
- validated against schema
- stored persistently
- merged into planning workflows

---

# AI Adjustment Agent

Allows natural-language modifications to existing weekly plans.

Example:
- "Use spinach before expiry"
- "Reduce dairy this week"

Workflow:

User Request
↓
Current Plan Analysis
↓
Constraint Validation
↓
Structured AI Output
↓
Plan Modification
↓
Grocery / Metrics Update

---

# Grocery Dependency Generator

Purpose:
- identify missing ingredients
- generate procurement requirements

Logic:
- compare meal plan ingredients
- subtract pantry inventory
- generate grouped grocery lists

---

# Analytics Layer

Tracks:
- meals completed
- pantry utilization
- grocery savings
- cuisine frequency
- swaps
- AI-generated recipe usage

Stored in:
- `analytics.json`

Design goals:
- incremental updates
- lightweight persistence
- low latency

---

# Reporting Layer

Supports:
- monthly summaries
- behavioral analytics
- AI-generated insights
- email preview/export

Example insights:
- pantry efficiency
- cuisine trends
- nutrition adherence

---

# Export Layer

Supports:
- markdown export
- text export
- CSV grocery lists
- JSON backups

Purpose:
- portability
- sharing
- lightweight backup

---

# Performance Optimizations

The system includes:

- cached recipe loading
- lazy AI execution
- session-state reuse
- pagination
- incremental analytics
- lightweight JSON persistence

AI workflows are executed only when explicitly triggered.

---

# Validation & Guardrails

AI-generated recipes are validated for:
- schema correctness
- required macros
- ingredient presence
- dietary constraint compatibility

Adjustment workflows:
- preserve exclusions
- prevent invalid meal assignments
- avoid malformed outputs

---

# Design Philosophy

The platform prioritizes:
- operational workflows
- low-friction UX
- modular architecture
- lightweight orchestration
- explainability
- responsiveness

The goal was not to build a generic chatbot wrapper, but a practical AI-assisted operational planning system.

---
