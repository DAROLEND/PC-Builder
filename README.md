# PC Builder

**A PC configurator that actually checks whether the parts fit together.** Pick a CPU, a board, memory, a graphics card, a cooler, a PSU and a case, and every choice is checked against ~30 real compatibility rules: sockets and chipsets, DDR4/DDR5, slot counts, GPU length and cooler height against the case, cooling capacity under load, power supply headroom. Builds can be saved, shared, commented on and ordered; an AI advisor assembles a complete build for a budget through the app's own API; a Telegram bot sends price alerts.

**Live site: <https://pcbuilder-ife5.onrender.com>** · demo account `demo` / `demo12345`

[Українською](README.uk.md) · [API docs](https://pcbuilder-api-8qs9.onrender.com/api/docs/)

![Configurator with a live compatibility report](docs/screenshots/configurator.png)

| Build page with the compatibility report | Catalog sorted by popularity |
|---|---|
| ![Build](docs/screenshots/build.png) | ![Catalog](docs/screenshots/catalog.png) |

| AI advisor | Mobile |
|---|---|
| ![Advisor](docs/screenshots/advisor.png) | <img src="docs/screenshots/mobile.png" width="260" alt="Mobile"> |

---

## Features

- **Configurator with live compatibility checks.** ~30 rules in a pure-Python engine; errors block saving, warnings explain the risk ("the AK400 handles the i7-14700K at its 125 W TDP, but under full load it draws up to 253 W"). The part pickers show only what fits the parts already chosen, filtered in SQL.
- **Catalog of ~650 parts** with full specifications, typical (median) market price, a daily price history chart (30 days … all time), popularity ranking and market badges: *Top #1*, *−8 % in a month*, *Lowest in a year*.
- **Builds:** public or private, comments, cloning, orders with a status machine and Stripe Checkout (fake provider by default).
- **AI advisor:** Claude with tool use calls the app's own endpoints (`search_components`, `check_build`) and must pass the same compatibility engine before its answer is accepted; without an API key a deterministic planner answers.
- **Price alerts in Telegram:** watch a part or a whole build (±N % either way and/or a target price); the bot links to the account through a one-time code, respects quiet hours and never loses an alert.
- **Two languages** (Ukrainian / English) with type-checked dictionaries; prices in UAH or USD at the NBU rate.

## Stack

| Layer | Technologies |
|---|---|
| Backend | Python 3.13, Django 5.2, Django REST Framework, PostgreSQL 17 (JSONB + GIN, window functions), SimpleJWT, drf-spectacular (OpenAPI 3), django-filter |
| Background work | Celery + Redis, Celery beat (exchange rate, market refresh, price alerts, order expiry) |
| Integrations | Anthropic Claude API (tool use), Telegram Bot API (long polling or webhook), Stripe Checkout + webhooks, NBU exchange-rate API, market data from product pages (off by default, on in the live demo; see [Live prices and photos](#live-prices-and-photos)) |
| Frontend | React 19, TypeScript, Vite, TanStack Query, React Router, `openapi-fetch` with **types generated from the OpenAPI schema**, typed i18n |
| Tests | pytest + pytest-django + factory_boy + responses (286 tests), Vitest + Testing Library (16), Playwright for manual end-to-end checks |
| Infrastructure | Docker Compose (7 services), nginx, Caddy (HTTPS), GitHub Actions (lint, migrations, schema drift, tests, image build, stack smoke test) |

## Quick start

```bash
docker compose up --build
```

Open <http://localhost:8080>. The first start applies migrations and loads the demo catalog (65 parts with hand-checked specs, 5 public builds, the `demo` account).

| What | Where |
|---|---|
| App | http://localhost:8080 |
| Swagger UI | http://localhost:8080/api/docs/ |
| Django admin | http://localhost:8080/admin/ (`docker compose exec backend python manage.py createsuperuser`) |

Everything works without keys. Optional extras in [`.env.example`](.env.example): `ANTHROPIC_API_KEY` (Claude instead of the planner), `TELEGRAM_BOT_TOKEN` (price alerts), `PAYMENT_PROVIDER=stripe` with test keys.

<details>
<summary>Without Docker</summary>

```bash
# Backend (PostgreSQL required; Redis for background tasks)
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgres://user:pass@localhost:5432/pcbuilder DJANGO_DEBUG=1
python manage.py migrate && python manage.py seed_catalog
python manage.py runserver

# Frontend (proxies /api and /media to :8000)
cd frontend
npm install
npm run dev          # http://localhost:5173
```
</details>

Deployment to a VPS with automatic HTTPS, or a free demo on Render + Neon: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

---

## Architecture

```mermaid
flowchart LR
    B[Browser<br/>React + TanStack Query] -->|HTTPS| C[Caddy]
    C --> N[nginx<br/>SPA, /media]
    N -->|/api, JWT| D[Django + DRF<br/>gunicorn]
    D --> P[(PostgreSQL<br/>JSONB + GIN)]
    D -->|on_commit| R[(Redis)]
    R --> W[Celery worker]
    BT[Celery beat] --> R
    W --> P
    W -->|rate| NBU[NBU API]
    D -->|Checkout| S[Stripe]
    S -->|webhook| D
    D -->|tool use| CL[Claude API]
    TG[Telegram bot<br/>long polling] --> P
    W -->|alerts| TGA[Telegram API]
```

```
backend/
  apps/catalog/    categories, manufacturers, components (specs in JSONB), price history,
                   spec schemas, "compatible with the selection" filter, market data,
                   popularity and price signals
  apps/builds/     Build → BuildComponent (through) → Component, comments, permissions,
                   compatibility.py: the rule engine (plain Python, no Django)
  apps/orders/     orders with a price snapshot, state machine, payment providers, Stripe webhook
  apps/stats/      aggregations and window functions
  apps/advisor/    AI advisor: Claude tool-use loop + deterministic planner
  apps/alerts/     price watches, Telegram linking, the bot, the alert check
  apps/accounts/   sign-up, JWT
frontend/src/
  api/schema.d.ts  generated from backend/schema.yml, never edited by hand
  api/hooks.ts     every request goes through TanStack Query
  pages/           configurator, catalog, part page, builds, orders, advisor, stats, profile
```

`Component.specs` is JSONB because every category has different characteristics (a CPU has a socket and TDP, a GPU has length and VRAM); a wide table with dozens of nullable columns would be worse. The price of that flexibility is that the database no longer guarantees the shape, so `catalog/specs.py` does: a schema per category with types, enums, minimums and in-component rules (threads ≥ cores; an air cooler needs a height, a liquid one a radiator size).

## Compatibility rules

All rules live in [`backend/apps/builds/compatibility.py`](backend/apps/builds/compatibility.py). The engine takes plain `Part` objects and returns a `Report` with an issue **code and parameters**, so the frontend renders the message in either language. It knows nothing about Django, so every rule is tested without a database.

| Rule | Level |
|---|---|
| CPU socket = board socket; the board's chipset supports this CPU | error |
| Memory type matches the board and the CPU; no DDR4/DDR5 mix; modules ≤ slots; capacity ≤ board maximum | error |
| Board form factor and PSU form factor fit the case | error |
| GPU length ≤ case limit (tight fit < 10 mm is a warning; unknown length is a warning) | error / warning |
| Cooler: supports the socket, fits the case (height / radiator), **can dissipate the CPU's power under load** (Intel's max turbo power, AMD's PPT = 1.35 × TDP), CPU sold without a cooler | error / warning |
| PSU wattage ≥ estimated draw, 30 % headroom, ≥ the GPU vendor's recommendation | error / warning |
| M.2 drives ≤ M.2 slots, SATA drives ≤ ports; no GPU needs a CPU with integrated graphics | error |

**Where each check lives, and why:** database constraints (price ≥ 0, quantity range, uniqueness) are the last line of defence; `Model.clean()` validates specs for the admin and seeding too; the serializer's `validate()` runs the engine because the rules are cross-field; the order service checks "complete, compatible and still on sale", a rule of one operation, not a property of the data; one `TRANSITIONS` table drives the order state machine.

## Engineering notes worth asking about

- **JSONB + GIN (`jsonb_path_ops`).** Filters are built as `specs @> '{"socket": "AM5"}'`, which the GIN index serves; `specs__socket="AM5"` would compile to `specs -> 'socket' = …`, which it does not. A test asserts the SQL uses `@>`.
- **"Only compatible" filtering in SQL, not Python** (`catalog/compat_query.py`): hard rules become `WHERE` clauses, so pagination and ordering stay in the database. It is a pre-filter that never hides a valid part; the engine stays the single source of truth.
- **`EXISTS` instead of a join filter.** Filtering builds by a component and then summing prices reused the join and summed one row ($260 instead of $735). Regression test included.
- **Subquery instead of `Count("comments")`**, because two aggregates over two joins multiply each other's rows.
- **Constant query counts** (N+1) for lists and details, enforced by tests.
- **Window functions:** top-N per category (`RANK() OVER (PARTITION BY category)`), popularity rank (`ROW_NUMBER`), price ladder (`PERCENT_RANK`).
- **Money is always a decimal string**, never a float, in Python and TypeScript.
- **Concurrency:** `select_for_update()` plus idempotency for Stripe webhooks; the "expire order ↔ payment webhook" race is guarded and tested.
- **Frontend ↔ backend contract:** CI regenerates the OpenAPI schema and the TypeScript types and fails if either differs from the committed files.
- **Typical price, not the minimum:** the headline price is the median of new-condition shop offers; the cheapest offer alone is often a shop without stock.
- **Market signals that don't lie:** price drops compare weekly medians and are shown only for parts sold by ≥ 5 shops; with one or two sellers the "average" jumps with every listing (a CPU "fell 75 %" because an overpriced single shop was joined by normal ones).
- **Reading a Nuxt page state without executing it:** a small strict parser for exactly the syntax the serializer emits; anything else is rejected, so a changed page can make us learn less, never run foreign code.

## Live prices and photos

Catalog prices are never edited by hand. Every part has a `MarketListing`, a link to the same model on hotline.ua (or a shop page), and every 30 minutes Celery beat refreshes listings older than 20 hours (on the free demo the nightly *Market data* workflow does it):

- **Where the data comes from.** The schema.org `Product` markup sites publish for search engines (JSON-LD, falling back to microdata and OpenGraph) and the page state: price range across shops, offers, stock, rating, photos. No site-specific HTML is scraped, so a redesign breaks nothing. No private shop APIs are used; the one internal endpoint is hotline's price chart (see *Price history*).
- **Politeness.** robots.txt is checked per host (cached for a day), requests to one host are spaced out, the bot has an honest User-Agent and only visits product pages.
- **Guarding against garbage.** The title on the page is matched against ours by model tokens (`9800x3d`, `b650m`, `rm850x`); if a URL starts showing another product the listing becomes `mismatch` and the price stays. "No photo" placeholders are dropped, prices in unknown currencies are not converted.
- **Which price is shown.** The typical one: the **median** of new-condition shop offers, with the min–max range next to it. The cheapest offer alone often belongs to a shop without stock. In-stock offers win; if none is in stock, the last known price stays.
- **Price history** comes from hotline's own chart (daily average, min and max for the last year), which its pages load from an undocumented internal GraphQL endpoint (`/svc/frontend-api/graphql`); every refresh adds the new days, and `manage.py sync_price_history` backfills the whole catalog. If that source changes, nothing breaks: we record one point a day ourselves.
- **Photos** are mirrored once as WebP (360 / 1000 px). Specs are mapped per category and validated; unknown values are dropped, so a part stays "catalog only" rather than getting a guessed spec. Parts sold by fewer than 3 shops are hidden from browsing and come back when supply returns.

## Telegram price alerts

"Watch price" on a part or build page stores a condition (±N % either way and/or a target price). After every market refresh `check_watches()` compares the price with a baseline that moves **only after a successful delivery**, so an alert held back by quiet hours (22:00–08:00 Kyiv) or a Telegram outage is sent later instead of being lost. Linking needs no password in the bot: the site issues a one-time code, the user opens `t.me/<bot>?start=<code>`. Commands `/list`, `/stop`, `/on`; a user who blocks the bot is switched off automatically. The bot receives messages by long polling (`run_telegram_bot`, the `bot` service in Docker Compose) or, on a host without background workers, through a webhook into the API (`TELEGRAM_WEBHOOK=1`, secret-checked, each update handled once).

## AI advisor

`POST /api/advisor/ {budget, currency, use_case, preferences}` returns a complete, compatible build within budget (budget in UAH or USD).

- **With an Anthropic key:** a Claude tool-use loop where the tools are the app's own API. The model cannot just name a build: `submit_build` is checked server-side by the same engine, and an incompatible, incomplete or over-budget answer goes back to the model as an error to fix. Refusals, API errors and a site-wide daily call cap fall back to the planner.
- **Without a key:** a deterministic planner splits the budget by use case, upgrades and downgrades, and reports an unreachable budget honestly. Parametrized tests cover 4 use cases × 5 budgets.

## Tests and quality

```bash
cd backend && pytest --cov        # 286 tests, needs PostgreSQL
cd frontend && npm test && npm run typecheck && npm run lint
```

Covered: every compatibility rule; permissions (someone else's private build is a 404, not a 403); database constraints; SQL query counts; aggregations on data where a naive query is wrong; the order state machine and races; the Stripe webhook; external APIs through `responses` (no network); the Claude loop through a scripted fake client; the Telegram bot and alert check; the page-state parser against malicious input.
