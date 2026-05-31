# EVE SP Farm Planner Product Roadmap

## Product Direction

The app is an SP tracking command center for EVE Online characters. Its first
job is to make progression, queue health, and training efficiency easy to
inspect. SP farming, extraction planning, wallet tracking, market prices, and
profitability are supporting workflows.

The target visual direction is the dense EVE-like dashboard shown in the
project reference image: a persistent left navigation rail, compact KPI tiles,
operational tables, restrained cyan highlights, and clear warning states.

## ESI SSO Boundary

EVE SSO authorizes one selected character at a time.

During login, the player signs in to EVE Online, selects a character, and
grants scopes. The resulting access token is valid for that character and those
scopes. Its subject claim identifies the selected character in the form
`CHARACTER:EVE:<character-id>`.

The token does not expose the EVE login account or a list of sibling characters.
The app therefore cannot discover or prove that several authorized characters
share the same subscription account.

The local model remains:

```text
Account Group -> Local Account -> Authorized Character
```

Attaching a character to an account is a user-managed organizational action.
The UI should be optimized for the normal EVE account layout of up to three
character slots, but the app must not enforce a three-character limit. Since
grouping is local and manual, enforcement would create false validation without
an ESI source of truth.

Official reference:
[EVE SSO documentation](https://developers.eveonline.com/docs/services/sso/).

## Current Baseline

### Developed

- Workbook-equivalent SP farm profitability calculations with tests.
- Scenario matrix, ranking, break-even analysis, and sensitivity views.
- SQLite-backed account groups, local accounts, and characters.
- SP snapshots, projected SP, queue health, queue milestones, and attention
  alerts.
- Per-character trained skill inventory and full training queue sync.
- EVE SSO with PKCE and encrypted local refresh-token storage.
- Granular ESI sync diagnostics and token health.
- Wallet snapshot sync and tracked asset sync.
- Public ESI market prices for PLEX, Large Skill Injectors, and Skill
  Extractors.
- Extraction planning, event lifecycle tracking, and post-extraction ESI
  reconciliation.
- Left navigation rail and an initial EVE-like Streamlit dashboard shell.

### Partial

- Character attributes are fetched but stored mainly as display text.
- Active implant IDs are fetched but not resolved into names and bonuses.
- Monthly SP is calculated but is not prominent in account and character
  tracking views.
- Wallet and asset data exist per character but do not yet have a dedicated
  overview.
- Account grouping exists but does not yet have a focused account inspector.
- The first `SP Overview` screen is dashboard-like but not yet the final main
  dashboard.

### Missing

- Full skill catalog, including untrained skills.
- Structured base attributes, implant bonuses, and calculated effective
  attributes.
- Skill primary and secondary attributes, SP/minute per skill, and training
  efficiency analysis.
- Manual account-level PLEX Vault tracking. ESI asset sync can detect loose
  character assets, but ESI does not expose an account-level PLEX Vault
  endpoint.
- Dedicated wallet overview with ISK and PLEX totals by character and account.
- Final visual redesign and responsive layout pass.

## Implementation Roadmap

Each phase should be implemented as a reviewable prompt and committed after
tests pass. Avoid deep visual polish until the data model used by the first
dashboard is stable.

### Phase 1: Skill Catalog And Structured Training Data

Goal: make SP tracking complete rather than limited to already trained skills.

Scope:

- Add a versioned static-data catalog for skills.
- Join the catalog with ESI character skills and the current queue.
- Classify each skill as untrained, trained, completed, or in progress.
- Store character attributes in structured columns.
- Store active implants as structured rows.
- Resolve implant names and attribute bonuses from static data.
- Calculate effective attributes explicitly.
- Calculate SP/minute for each skill using its primary and secondary
  attributes.
- Add catalog freshness and source metadata.

Acceptance criteria:

- The character inspector can browse the whole skill catalog.
- Every skill shows state, current level, target level when queued, primary
  attribute, secondary attribute, and current SP/minute.
- The character inspector shows reported attributes, implant bonuses, and
  effective totals separately.
- Static-data and calculation tests cover representative skills and implants.

### Phase 2: Account Inspector And Holdings Model

Goal: make local account organization operationally useful.

Scope:

- Add an account inspector grouped as `Account Group -> Account -> Character`.
- Design each account panel around three visible character slots while
  allowing overflow gracefully.
- Keep character-to-account assignment editable.
- Add a manual account-level PLEX Vault field with updated-at timestamp and
  notes.
- Show account Omega status, MCT slots, active queues, queue issues, wallet
  totals, and manual PLEX Vault amount.
- Clarify which fields are ESI-synced and which are manual.

Acceptance criteria:

- A user can inspect one account and its characters without opening each
  character separately.
- The app never claims that ESI verified account membership.
- The layout remains readable if a local account contains more than three
  character rows.

### Phase 3: Wallet And SP Performance Overview

Goal: make the first screen the useful daily dashboard.

Scope:

- Rename and restructure `SP Overview` as the main dashboard.
- Show total SP, observed SP gain, expected SP/day, queue coverage, and monthly
  SP projection.
- Add account and character tables with projected monthly SP per character.
- Add wallet overview with ISK and tracked loose PLEX per character.
- Add account totals including manual PLEX Vault values.
- Add snapshot trend charts and expected-versus-observed SP deltas.
- Add freshness badges for ESI, market, and manual values.

Acceptance criteria:

- The first screen answers: who is training, who needs attention, what is the
  projected SP output, and how current is the data?
- Wallet and PLEX values always identify their source and freshness.

### Phase 4: Farming And Extraction Refinement

Goal: keep farming powerful but clearly secondary to SP tracking.

Scope:

- Expose optimal farming setups using current public market snapshots and
  editable manual assumptions.
- Show expected monthly SP and estimated injector output for each character.
- Connect extraction readiness to the training dashboard.
- Add account-level projected profit contribution.
- Add an extraction calendar and upcoming readiness forecast.
- Preserve planned, completed, and reconciled extraction states.

Acceptance criteria:

- Farming stays under its own navigation area.
- Every profitability recommendation shows the prices, discounts, fees,
  source timestamps, and manual assumptions used.

### Phase 5: UI Refactor Before Final Redesign

Goal: reduce Streamlit UI coupling before investing in visual polish.

Scope:

- Split `src/ui/character_pages.py` into focused modules for dashboard,
  accounts, character inspector, wallet, extraction, and SSO controls.
- Keep services independent from Streamlit.
- Consolidate reusable KPI cards, badges, panel headers, tables, and freshness
  labels.
- Define a small set of spacing, color, border, and typography tokens.
- Keep custom CSS shallow enough that Streamlit updates remain manageable.

Acceptance criteria:

- Each major navigation area has a focused render module.
- Business calculations and persistence stay outside UI modules.
- Existing functional tests remain green.

### Phase 6: Visual Redesign

Goal: converge on the reference-image style without changing product behavior.

Prompt 1 - Application shell:

- Refine the persistent left rail, compact header, active-navigation state,
  scenario preset area, refresh state, and consistent panel styling.
- Establish desktop density and a deliberate narrower-screen fallback.

Prompt 2 - Main dashboard:

- Build the final SP-first dashboard hierarchy.
- Use compact KPI tiles, account panels, attention alerts, snapshot trends, and
  freshness indicators.
- Keep farm readiness visible but secondary.

Prompt 3 - Secondary views and QA:

- Apply the same component language to account inspector, character inspector,
  wallet, market, farming, scenario matrix, and break-even views.
- Verify tables, charts, forms, expanders, and empty states at desktop and
  narrower widths.

Acceptance criteria:

- The first viewport resembles an operational EVE dashboard rather than a
  default Streamlit prototype.
- No raw HTML is visible.
- No text overlaps, clipped controls, blank panels, or unreadable tables remain
  in the validated viewports.

## Proposed Features

### High Value

1. Queue coverage forecast

   Show the remaining queue duration, the next gap, and a configurable warning
   horizon. This directly prevents lost training time.

2. Training efficiency advisor

   Compare the active queue against current attributes and implants. Highlight
   slower skills, estimate avoidable SP loss, and identify when a remap or
   implant change is worth reviewing.

3. Extraction readiness calendar

   Forecast when each character crosses the next 500k SP boundary and aggregate
   expected injectors by week and month.

4. Data confidence center

   Show SSO token health, endpoint failures, stale snapshots, stale market
   prices, and manual fields that need review in one place.

5. Account economics

   Attribute projected SP output, injector output, recurring cost, and expected
   profit to each local account so underperforming setups are obvious.

### Useful Later

6. Actual-versus-projected history

   Compare observed SP growth and realized extraction revenue against plans.
   This catches queue downtime and optimistic assumptions.

7. Market execution presets

   Separate immediate buy-order sales from posted sell-order assumptions.
   Store editable taxes, broker fees, and expected slippage.

8. Backup and export

   Add a local database backup action and CSV exports for characters, wallets,
   snapshots, extraction events, and scenario results.

9. Static-data refresh workflow

   Add a manual refresh action and visible SDE version so skill and implant
   metadata can be updated deliberately.

10. Local scheduled sync

   Add an opt-in local background sync path after the dashboard workflow is
   stable. Respect ESI rate limits, cache responses, and surface the last
   successful refresh.

## Technical Guardrails

- Treat local account grouping as user-managed metadata.
- Do not infer sibling characters from token data.
- Keep ESI scopes limited to visible product value.
- Keep manual values clearly labeled.
- Store source timestamps for ESI, market, static-data, and manual data.
- Keep static-data ingestion isolated from character sync.
- Keep financial calculations independent from Streamlit.
- Add migrations and tests for every persisted field.
- Refactor UI modules before the final design pass.
