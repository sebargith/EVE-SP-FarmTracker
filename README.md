# EVE SP Farm Planner

Local-first EVE Online skill-point farm planner. The main product direction is
tracking character SP progression, queue health, and next SP milestones.
Farm readiness, extraction planning, profitability, market prices, wallet, and
assets are supporting features around that SP tracking workflow.

See [docs/PRODUCT_ROADMAP.md](docs/PRODUCT_ROADMAP.md) for the planned feature
sequence, the ESI account-grouping boundary, and the visual redesign plan.

## Current Scope

- Workbook-equivalent scenario calculations.
- Editable defaults in `data/assumptions.yaml`.
- Scenario presets and manual market assumptions.
- Streamlit dashboard with scenario ranking and break-even views.
- SQLite-backed account, character, SP snapshot, and readiness tracking.
- SP-first tracking dashboard with queue health, projected SP, SP/month, and
  snapshot history.
- EVE SSO/ESI authorization flow for syncing character skills, queues, and
  active implant counts.
- Character detail views for trained skill inventory, full training queue,
  wallet snapshots, and relevant asset tracking.
- Public ESI market snapshots for LSI, Skill Extractors, and PLEX where the
  public order book exposes a price.
- Locked reference fixture tests plus optional full Excel workbook audit.
- Multi-character Loot Tracker sessions with explicit start, stop, retry, and
  editable confirmation steps using stored EVE SSO asset permissions.

Extraction planning history is planned later.

## Setup

Create the local virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
```

For dependency updates during development, install from `requirements.txt`,
verify the app, then refresh `requirements-lock.txt`:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip freeze | Sort-Object | Set-Content requirements-lock.txt
```

## Run

Double-click either launcher in the project directory:

- `EVE SP Farm Planner.lnk`
- `Run EVE SP Farm Planner.cmd`

The launcher starts Streamlit on `http://localhost:8766` by default. If that
port is occupied by another process, it will find the next available port up to
`8799` instead of opening the wrong app.

Manual command:

```powershell
.\.venv\Scripts\python -m streamlit run app.py --server.port 8766
```

## EVE SSO Setup

Create an application in the EVE Developers portal and register this callback:

```text
http://localhost:8766
```

Then create a local `.env` file from `.env.example` and set:

```dotenv
EVE_CLIENT_ID=your_eve_application_client_id
EVE_CALLBACK_URL=http://localhost:8766
EVE_SCOPES=esi-skills.read_skills.v1 esi-skills.read_skillqueue.v1 esi-clones.read_implants.v1 esi-wallet.read_character_wallet.v1 esi-assets.read_assets.v1
```

The app uses Authorization Code with PKCE, so no EVE client secret is needed for
the local desktop flow. EVE SSO authorizes one character at a time; connect each
farm character under the local account where you want it grouped.

## Test

Run the normal suite:

```powershell
.\.venv\Scripts\python -m pytest -q
```

Run the optional full workbook audit against cached Excel outputs:

```powershell
$env:RUN_WORKBOOK_AUDIT='1'
.\.venv\Scripts\python -m pytest tests\test_excel_equivalence.py -q
Remove-Item Env:\RUN_WORKBOOK_AUDIT
```

## Notes

- `data/assumptions.yaml` is editable. The app cache keys include the file
  modified time, so changes are picked up on rerun without restarting the
  Streamlit server.
- `data/sp_farm.db` is created locally on first run and seeded with replaceable
  sample farm data if empty.
- EVE refresh tokens are stored in `data/sp_farm.db` encrypted with Windows
  DPAPI for the current Windows user.
- `requirements-lock.txt` captures the currently working local environment.
- Local databases, logs, virtual environments, `.env`, and shortcuts are ignored
  by Git.
