# AGENTS.md — EVE SP Farm Planner

## 1. Project Summary

Build an interactive decision-support app for planning and operating an EVE Online SP farm.

Primary product focus:

- Track characters' SP progression over time.
- Show each character's current SP, projected SP, active skill, queue health,
  and next SP milestone.
- Group progression clearly by `Account Group -> Account -> Character`.
- Treat farm readiness, extraction planning, market pricing, wallet/assets, and
  profitability scenarios as supporting features around SP tracking.
- Use profitability, market prices, and break-even logic to decide what to do
  with those characters, not as the app's main identity.

The app should start from the existing Excel profitability model and evolve into a Python-based dashboard that can:

- calculate SP farm profitability across Omega, MCT, extractor, and Large Skill Injector combinations;
- rank scenarios by total profit and profit/month;
- track multiple EVE accounts and multiple characters grouped for readability;
- monitor character readiness for extraction;
- ingest useful EVE ESI API data;
- track market prices and break-even thresholds;
- help decide whether to extract now, wait, buy extractors, or delay farming.

The app is not only a spreadsheet replacement. It should become a practical operational planner for SP farming.

---

## 2. Core Business Logic

### Main objective

Track SP progression for multiple EVE characters and make the next useful SP
decision obvious: keep training, fix a queue, prepare for extraction, or review
profitability assumptions.

SP farming and extraction remain important supported workflows: train farm
characters at optimized Omega speed, extract skill points above the extraction
floor, create Large Skill Injectors, sell them, and compare net ISK revenue
against Omega, MCT, extractor, and tax/fee costs.

### Core assumptions from the current model

- Optimized Omega training rate: `45 SP/min`.
- Optimized monthly SP per queue: `1,944,000 SP / 30 days`.
- One Large Skill Injector requires `500,000 SP`.
- Extraction requires the character to remain above the minimum extraction floor.
- The model should support fractional injectors for long-run financial simulation, because leftover SP carries forward.
- Baseline single-queue Omega farming is usually unprofitable under normal prices.
- Profitability depends on stacking:
  - discounted Omega;
  - discounted MCT;
  - discounted or cheap Skill Extractors;
  - favorable Large Skill Injector sale prices;
  - low effective sales taxes and fees.

### Important interpretation

Do not treat a green scenario as automatically safe. A profitable result depends on the input assumptions. Market prices, taxes, extractor costs, and sale discounts must be editable.

---

## 3. Existing Inputs and Reference Workbook

The current baseline workbook is:

`eve_sp_farm_plex_only_profit_model.xlsx`

It contains:

1. `01 Base Costs` — editable assumptions.
2. `02 Scenario Matrix` — all profitability combinations.
3. `03 Best Results` — ranked best scenarios.
4. `04 Combination Analysis` — grouped analysis.
5. `05 SP Farm Guide` — practical guide and formulas.
6. `06 Sources` — source references.

The first technical milestone is to reproduce the workbook calculations in Python and verify that Python outputs match Excel results within a small rounding tolerance.

---

## 4. Recommended Tech Stack

Initial stack:

- Python 3.11+
- Streamlit for dashboard UI
- pandas for scenario tables and data manipulation
- Plotly for charts
- SQLite for local storage
- YAML for assumptions/configuration
- pytest for tests
- httpx or requests for ESI API calls
- Docker later, after the app works locally

Possible later stack:

- FastAPI backend if Streamlit becomes limiting
- PostgreSQL if the project becomes multi-user or large-scale
- React frontend only if a more formal app is needed later

Do not start with React/FastAPI unless necessary. Start with tested Python logic and Streamlit.

---

## 5. Suggested Project Structure

```text
sp-farm-planner/
├── AGENTS.md
├── README.md
├── app.py
├── requirements.txt
├── .env.example
├── data/
│   ├── assumptions.yaml
│   ├── sp_farm.db
│   └── reference_workbook/
│       └── eve_sp_farm_plex_only_profit_model.xlsx
├── pages/
│   ├── 1_Command_Center.py
│   ├── 2_Accounts_Characters.py
│   ├── 3_Scenario_Matrix.py
│   ├── 4_Market_APIs.py
│   ├── 5_Extraction_Planner.py
│   ├── 6_Break_Even.py
│   └── 7_Guide_Sources.py
├── src/
│   ├── calculations/
│   │   ├── sp_training.py
│   │   ├── profitability.py
│   │   ├── break_even.py
│   │   └── scenarios.py
│   ├── data/
│   │   ├── models.py
│   │   ├── database.py
│   │   └── repositories.py
│   ├── integrations/
│   │   ├── esi_public.py
│   │   ├── esi_auth.py
│   │   ├── sso.py
│   │   └── token_store.py
│   ├── services/
│   │   ├── market_service.py
│   │   ├── character_service.py
│   │   ├── scenario_service.py
│   │   ├── extraction_service.py
│   │   └── alert_service.py
│   └── charts/
│       ├── profitability_charts.py
│       ├── market_charts.py
│       └── account_charts.py
└── tests/
    ├── test_sp_training.py
    ├── test_profitability.py
    ├── test_break_even.py
    ├── test_scenarios.py
    └── test_excel_equivalence.py
```

---

## 6. Main App Pages

### 6.1 Command Center

Purpose: high-level operational overview.

Should show:

- total accounts;
- total characters;
- characters ready to extract;
- projected monthly profit;
- current PLEX price;
- current LSI price;
- current Skill Extractor price;
- API health;
- alerts;
- profit by account group;
- extraction readiness summary.

### 6.2 Accounts & Characters

Purpose: track multiple accounts and characters with clear grouping. This is
the main app workflow and should lead with SP progression, queue health, and
next milestones before farm/extraction metrics.

Required UX principle:

`Account Group → Account → Character`

Should show:

- account groups, such as Main Farm Cluster, Alt Farm Cluster, Hybrid Accounts;
- each account’s Omega status;
- MCT status and active queues;
- wallet balance if available;
- sync status;
- nested character rows.

For each character, show:

- character name;
- total SP;
- projected current SP;
- SP/month projection;
- trained skills by skill ID/name, level, and SP;
- current training skill;
- queue health and queue end time;
- next SP milestone;
- extractable SP;
- SP above extraction floor;
- current skill queue;
- full training queue with positions, target levels, start/finish times, and queue gaps;
- queue end time;
- attribute/implant profile;
- estimated injectors;
- ready to extract status;
- estimated monthly contribution.

### 6.3 Scenario Matrix

Purpose: reproduce and improve the Excel scenario matrix.

Should support filters for:

- Omega plan;
- MCT source/discount;
- queue count;
- extractor source;
- extractor sale type;
- profitability status.

Columns should include:

- scenario ID;
- Omega plan;
- MCT plan;
- queues;
- extractor source;
- total cost;
- revenue;
- profit;
- profit/month;
- break-even LSI price;
- status.

### 6.4 Market & APIs

Purpose: show live and historical market/API-driven information.

Should show:

- PLEX price;
- Large Skill Injector price;
- Skill Extractor price;
- market spread;
- 7-day and 30-day averages;
- API health;
- last sync time;
- market trend charts;
- break-even monitor;
- manual sale assumptions.

Important: some data will come from ESI, while NES discounts and special sale bundles may remain manual inputs.

### 6.5 Extraction Planner

Purpose: supporting feature for operational planning when SP tracking indicates
characters are ready or approaching readiness. This should not replace SP
tracking as the main app workflow.

Should show:

- ready characters;
- injectors available this week;
- total extractable SP;
- planned revenue;
- planned cost;
- projected net profit;
- extraction calendar;
- extraction queue grouped by account and character;
- action buttons/statuses such as:
  - Extract Now;
  - Wait 1 Day;
  - Wait 2 Days;
  - Queue Blocked;
  - Review.

### 6.6 Break-even

Purpose: help decide whether current prices justify extraction.

Should include:

- break-even LSI price;
- max extractor price;
- max Omega cost;
- profit sensitivity to extractor price;
- profit sensitivity to LSI price;
- heatmap of profitable/unprofitable zones.

### 6.7 Guide & Sources

Purpose: document assumptions, formulas, and references.

Should include:

- SP training assumptions;
- extraction rules;
- MCT rules;
- formula explanations;
- source links;
- manual update notes.

---

## 7. Data Model

Use these conceptual entities.

```text
AccountGroup
- id
- name
- notes

Account
- id
- group_id
- name
- omega_status
- omega_expires_at
- mct_slots
- wallet_balance
- sync_status
- notes

Character
- id
- account_id
- name
- eve_character_id
- total_sp
- extractable_sp
- sp_above_floor
- current_skill
- queue_ends_at
- attribute_profile
- implant_profile
- ready_state
- estimated_injectors
- estimated_monthly_profit

MarketSnapshot
- id
- timestamp
- region_id
- plex_buy_price
- plex_sell_price
- lsi_buy_price
- lsi_sell_price
- extractor_buy_price
- extractor_sell_price
- source

ScenarioResult
- id
- scenario_key
- omega_plan
- mct_plan
- queue_count
- extractor_source
- months
- total_sp
- injectors
- net_revenue
- total_cost
- profit
- profit_per_month
- break_even_lsi_price
- status

ExtractionEvent
- id
- character_id
- timestamp
- sp_extracted
- injectors_created
- extractor_cost
- lsi_sale_price
- realized_revenue
- realized_profit

SaleAssumption
- id
- name
- type
- discount_pct
- plex_cost
- isk_cost
- start_date
- end_date
- notes

ApiToken
- id
- character_id
- scopes
- encrypted_refresh_token
- expires_at
- last_refresh_at
- status
```

---

## 8. Calculation Functions

Keep calculation code independent from Streamlit UI.

### `sp_training.py`

Functions:

```python
sp_per_minute(primary: float, secondary: float) -> float
sp_per_month(sp_per_minute: float, days: int = 30) -> float
injectors_from_sp(sp: float, sp_per_injector: float = 500_000) -> float
```

### `profitability.py`

Functions:

```python
calculate_lsi_revenue(injectors: float, lsi_price: float, tax_rate: float) -> float
calculate_extractor_cost(injectors: float, extractor_unit_cost: float) -> float
calculate_training_cost(omega_cost: float, mct_cost: float) -> float
calculate_profit(net_revenue: float, total_cost: float) -> float
profit_per_month(profit: float, months: int) -> float
```

### `break_even.py`

Functions:

```python
break_even_lsi_price(total_cost: float, injectors: float, tax_rate: float) -> float
max_extractor_price(net_revenue: float, training_cost: float, injectors: float) -> float
max_omega_cost(net_revenue: float, extractor_cost: float) -> float
```

### `scenarios.py`

Functions:

```python
generate_scenario_matrix(assumptions: dict) -> pandas.DataFrame
rank_scenarios(df: pandas.DataFrame) -> pandas.DataFrame
filter_profitable(df: pandas.DataFrame) -> pandas.DataFrame
```

---

## 9. API Integration Plan

### Phase 1 — No API

Manual inputs only.

Goal: reproduce workbook and build a usable dashboard.

### Phase 2 — Authenticated EVE SSO / ESI

Use EVE SSO as the preferred source of truth for character progression. Manual
character entry remains a fallback, but the app should be designed around
authorized character sync.

Initial SSO scopes should stay narrow:

- `esi-skills.read_skills.v1`;
- `esi-skills.read_skillqueue.v1`;
- `esi-clones.read_implants.v1`.

Authenticated data that is directly useful for SP farming:

- character identity;
- total skill points;
- trained skills by skill ID/name, trained level, active level, and SP;
- skill queue end time;
- active training queue;
- full training queue positions, target levels, start/finish times, and gaps;
- attributes and active implants;
- token status.

Wallet, market orders, assets, and location are optional later scopes. Do not
request them until the app has a concrete view or decision that uses them.

Do not request more scopes than needed.

### Phase 3 — Public ESI market data

Fetch market information for:

- PLEX;
- Large Skill Injector;
- Skill Extractor.

Use this for:

- current market snapshot;
- historical price storage;
- break-even comparison;
- profitability status.

### Phase 4 — Alerts and automations

Possible alerts:

- character ready to extract;
- queue ending soon;
- token expiring soon;
- LSI above break-even;
- extractor price below target;
- PLEX price spike;
- MCT/Omega/extractor sale manually entered.

---

## 10. Security Rules

- Never ask for or store EVE account passwords.
- Use EVE SSO OAuth flow for authenticated data.
- Store refresh tokens encrypted if implemented.
- Never commit `.env`, secrets, tokens, or local databases with private data.
- Provide `.env.example` only.
- Keep the app local-first unless deployment is explicitly requested.
- Allow users to delete/revoke locally stored tokens.

---

## 11. Testing Requirements

Testing is mandatory because this is a financial decision tool.

Required tests:

- SP/month formula test.
- Injector production test.
- LSI revenue after taxes test.
- Extractor cost test.
- Profit/loss test.
- Break-even LSI price test.
- Scenario ranking test.
- Excel equivalence test using known workbook rows.

Example acceptance rule:

```text
For selected reference scenarios from the Excel workbook,
Python output must match Excel output within a small rounding tolerance.
```

---

## 12. Development Roadmap

### Milestone 1 — Python Calculation Engine

- Port formulas from Excel to Python.
- Add unit tests.
- Add assumptions YAML.
- Validate against workbook outputs.

### Milestone 2 — Manual Streamlit Dashboard

- Build Command Center.
- Build Scenario Matrix.
- Build Break-even page.
- Build Guide/Sources page.

### Milestone 3 — Account and Character Tracking

- Add SQLite database.
- Add Account Groups, Accounts, and Characters.
- Add manual character readiness tracking.
- Add grouped UI.

### Milestone 4 — Authenticated ESI / SSO

- Implement PKCE-based SSO.
- Store refresh tokens securely.
- Fetch character skills and full skill queue.
- Add per-character skill inventory and training queue tracking views.
- Add active implant and attribute summaries.
- Add token health and sync logs.

### Milestone 5 — Public Market API

- Add ESI public market fetcher.
- Track PLEX, LSI, and extractor prices.
- Store price history.
- Add market charts and break-even monitor.

### Milestone 6 — Extraction Planner

- Add extraction calendar.
- Add action planning.
- Add expected revenue/cost/profit per character.
- Add extraction event logs.

### Milestone 7 — Alerts and Polish

- Add alerts.
- Add exports.
- Add Docker setup.
- Improve styling and documentation.

---

## 13. UI/UX Principles

- Lead with SP tracking and queue health. Farm readiness, extraction, market,
  and profitability panels should support that workflow.
- Prioritize readability over visual complexity.
- Group data clearly: Account Group → Account → Character.
- Use green for profitable/ready, red for loss/not ready, yellow/orange for warning/wait.
- Always show units: ISK, PLEX, SP, days, months.
- Do not hide assumptions.
- Every profitability result should make clear which prices and discounts were used.
- Do not imply certainty when market prices are estimates.

---

## 14. Coding Guidelines for Codex

When working on this project:

1. Read `AGENTS.md` first.
2. Keep the calculation engine separate from the UI.
3. Do not hard-code market prices in calculation functions.
4. Put editable defaults in `data/assumptions.yaml`.
5. Add or update tests when changing formulas.
6. Do not remove existing workbook-equivalence checks.
7. Prefer small, reviewable commits.
8. Avoid unnecessary dependencies.
9. Keep API code isolated under `src/integrations/`.
10. Never commit secrets, tokens, or real account data.

---

## 15. Initial Codex Task Suggestion

First implementation task:

```text
Create the initial Python project for EVE SP Farm Planner.

Requirements:
- Use this AGENTS.md as project context.
- Create a Streamlit app skeleton.
- Implement the calculation modules:
  - sp_training.py
  - profitability.py
  - break_even.py
  - scenarios.py
- Create data/assumptions.yaml with editable defaults.
- Add pytest tests for the core formulas.
- Add a simple Scenario Matrix page that generates and ranks scenarios.
- Add a Command Center placeholder page.
- Do not implement EVE SSO yet.
- Keep API code as stubs only for now.
```

---

## 16. Non-goals for the First Version

Do not implement these in the first version unless explicitly requested:

- full React frontend;
- cloud deployment;
- multi-user authentication;
- automated market trading;
- automatic NES sale scraping;
- mobile app;
- complex corporation management;
- advanced notification systems.

Focus first on correctness, readable grouping, and profitability decisions.

---

## 17. Implementation Guidance From Initial Review

Use the workbook as the financial source of truth until the Python engine has
proven equivalence. The first version should prioritize reproducible
calculations over UI breadth.

Recommended implementation approach:

1. Treat workbook parity as Milestone 0.
   - Load selected rows from `eve_sp_farm_plex_only_profit_model.xlsx`.
   - Recreate those rows in Python from assumptions.
   - Compare core outputs: total SP, injectors, net revenue, total cost, profit,
     profit/month, and break-even LSI price.
   - Keep tolerances explicit, because Excel cached values and Python floating
     point values may differ slightly.

2. Use typed assumptions instead of passing loose dictionaries everywhere.
   - Keep editable values in `data/assumptions.yaml`.
   - Convert YAML into small dataclasses or Pydantic models at load time.
   - Separate market assumptions, tax assumptions, Omega plans, MCT plans, and
     extractor plans.

3. Separate long-run simulation from operational extraction.
   - Financial scenario analysis may use fractional injectors because leftover
     SP carries forward.
   - Character extraction events must use whole extractors/injectors and must
     preserve the extraction floor.
   - The UI should label these modes clearly.

4. Model selling and buying strategy explicitly.
   - Buying extractors from sell orders is different from staging buy orders.
   - Selling LSIs immediately to buy orders is different from posting sell
     orders.
   - Sales tax, broker fee, structure fees, and relist costs should be separate
     editable assumptions, even if the first UI shows a combined effective fee.

5. Keep setup costs separate from recurring profitability.
   - Initial 5.5M SP seed, implants, skillbooks, character transfer cost, and
     hauling/order-management costs should not be silently mixed into monthly
     farm profitability.
   - Add an optional setup-cost amortization view later.

6. Use ESI public market data as supporting evidence, not certainty.
   - Default region should be configurable; The Forge is a practical default.
   - Useful type IDs: PLEX `44992`, Skill Extractor `40519`, Large Skill
     Injector `40520`.
   - Store market snapshots with source, region, timestamp, and data age.
   - Do not treat live API prices as guaranteed execution prices.

7. Keep Streamlit thin.
   - Pages should call service functions and display results.
   - Calculation modules should not import Streamlit.
   - Database repositories should not know about Streamlit session state.

8. Keep authenticated ESI scoped to visible user value.
   - Keep token storage behind an interface.
   - Request only the scopes needed for the next visible feature.
   - Provide token deletion/revocation controls before relying on auth data.

9. Design decisions should expose uncertainty.
   - Every recommendation should show the assumptions used.
   - Show stale market data warnings.
   - Prefer labels such as `profitable under current assumptions` over implying
     that a scenario is universally safe.

---

## 18. UI Style Direction

Aim for an EVE-like operational dashboard rather than a default Streamlit
prototype. The target style is a dark, dense, tactical planning interface with
clear hierarchy and restrained sci-fi polish.

If the user places a concept/reference image in the project directory, treat it
as the visual and functional north star for future UI work. Do not copy it
exactly, but preserve its overall direction: left navigation, dark EVE-like
panels, compact KPI cards, dense scenario tables, assumption controls,
sensitivity charts, and an operational planner feel.

Visual direction:

- Use a dark navy/black background with subtle panel borders and low-opacity
  blue/cyan highlights.
- Prefer compact, information-dense panels over large marketing-style sections.
- Use a persistent left navigation rail for major app areas.
- Use a top row of KPI tiles for core market and profitability signals.
- Use cyan/teal as the main accent, with green for profitable/ready, red for
  loss/problem, and yellow/orange for warnings.
- Use icons where they improve scanning, especially for navigation, KPI cards,
  export/download actions, refresh, and settings.
- Keep typography compact and dashboard-like; avoid oversized hero text after
  the app is past the landing/placeholder stage.
- Use charts and tables in bordered operational panels with consistent spacing.
- Use sliders, steppers, and numeric inputs for market assumptions and discounts.
- Make scenario-set controls feel like saved presets, not loose form fields.

Interaction direction:

- The first screen should be the working planner, not an explanatory landing
  page.
- The Overview/Command Center should lead with account and character SP
  progression, extraction readiness, and projected SP/injector output, then
  combine assumptions, top scenarios, profitability charts, and
  break-even/sensitivity views.
- The Scenario Matrix should remain accessible as a detailed audit table.
- Downloads/export controls should be visible but secondary.
- The UI should always make the active scenario set and last-updated/manual
  data state obvious.

Implementation note:

- Continue using Streamlit while the model is evolving, but use custom CSS and
  structured components to move toward this dashboard style.
- Do not switch to React only for aesthetics. Consider React later only if
  Streamlit becomes limiting for interaction, layout, or state management.
