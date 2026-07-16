# The Ledger — Multi-Platform Analytics & Reporting

**The Ledger** automates recurring marketing/analytics reporting across a client's
whole Google + Meta footprint. Save each site once, pick a period, and every
report section is pulled live as a **month-over-month table** (this period vs the
previous). Claude writes **AI insights** per section, one click **exports to Google
Sheets or a branded Google Slides deck**, and a free-text **Ask** panel lets you
query a site's data in plain English. Background jobs keep the cache warm and can
run scheduled exports.

The app supports **two auth models side by side**:

- **Service account** — one (or several) GCP JSON key(s); no user login. Fast,
  headless, ideal for GA4 + Sheets/Slides export.
- **OAuth connections** — connect a Google or Meta account through the UI to
  **discover** everything it can see (GA4 properties, Google Ads, Merchant Center,
  Search Console sites, Meta ad accounts) and save them as sites in a few clicks.

---

## Features

- **Saved sites (profiles)** — add a site once and reuse it everywhere. A profile
  can carry a GA4 Property ID, a custom channel-group dimension, a GCP Project ID,
  a Google Sheet ID, a Google Slides deck ID, and per-platform IDs:
  Google Ads Customer ID, **Merchant Center ID**, **Search Console Site URL**,
  Meta Ad Account ID, and MoEngage App ID / Data Center / API key.
- **OAuth account connections** — *Connect a Google/Meta account* → the app
  discovers all accessible GA4, Google Ads, Merchant Center, Search Console and
  Meta ad accounts. Select what you want and **"Use selected in new site"** creates
  the profile. When you pick a GA4 property, a matching Merchant Center / Search
  Console entry from the same account is **auto-suggested** (name-slug match) so
  related sources get linked in one step.
- **Shared report template** — the same report set runs for every site. Edit
  `backend/report_defs.json` to change metrics/dimensions/rows; no code changes.
- **Month-over-month** — "Last month vs previous" (or a custom range); each table
  shows both periods side by side with a grand-total row.
- **AI insights** — Claude (Opus/Sonnet, configurable) turns each comparison into
  bullet insights; regenerate for a different angle. Falls back to rule-based
  insights when no `ANTHROPIC_API_KEY` is set.
- **Ask (free-text Q&A)** — ask a plain-English question about a site; Claude
  queries the APIs itself via tools and answers from the numbers it retrieves.
  Tools are offered per-profile: GA4 always; **Search Console** and
  **Merchant Center** only when that site has the relevant ID configured.
- **Platform pages** — the sidebar's **Platform** section (GA4 / Merchant Center /
  Search Console) lists every site in one table with its platform ID and
  credential source, and a **Connect** link for sites not yet wired to that
  platform.
- **Exports** — per-section CSV, all reports to a Google Sheet (one tab each), and
  a branded **Google Slides** deck matching the monthly-report template.
- **Scheduled jobs** — per-site recurring `sheets_export` / `slides_export` /
  `insights_digest` jobs (daily / weekly / monthly), plus background cache warming.
- **Data sources beyond GA4** — a report definition can set `source: "moengage"`
  to pull from MoEngage instead of GA4; both return the same normalized shape so
  everything downstream is source-agnostic.

---

## Architecture

```
Browser
  ▼
Next.js (frontend/)  ── /api/ga proxy ──►  FastAPI (backend/)
      │                                      │  service-account keys  +  OAuth tokens
      └── /oauth/* rewrite ─────────────────►│  (encrypted at rest)
                                             │
        ┌───────────────┬──────────────┬─────┴──────┬───────────────┬───────────┐
        ▼               ▼              ▼            ▼               ▼           ▼
   GA4 Data/Admin   Google Ads   Merchant Center  Search Console  Meta Graph  MoEngage
        │           Sheets API   Content API      webmasters v3   API         API
        │           Slides API
        ▼
   Redis cache  ◄── APScheduler warms every saved site + runs due jobs
        ▲
   profiles.json · report_defs.json · connections.json · jobs.json · ask_history.json
```

- **frontend/** — Next.js (App Router, TypeScript). Site + date controls, table
  sections, CSV/Sheets/Slides export, connections manager, platform pages, Ask
  panel, admin. Proxies API calls to the backend via `/api/ga/*`; OAuth
  login/callback are rewritten straight to the backend so provider redirects land
  on the frontend origin.
- **backend/** — FastAPI. Config-driven report engine, dual-auth (service account
  + OAuth), profile/connection/job stores, per-platform query helpers, Sheets &
  Slides writers, insights, and the Ask tool loop.
- **Redis** — caches report responses (TTL) and backs the scheduled refresh.

### Backend modules

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, CORS, router wiring, scheduler lifespan |
| `config.py` | Settings from `.env` (Pydantic Settings) |
| `ga4.py` | Service-account + OAuth credentials, GA4 report engine, comparisons |
| `ga4_query.py` | Ad-hoc GA4 reports + metadata (for Ask) |
| `search_console_query.py` | Search Console Search Analytics queries (for Ask) |
| `merchant_center_query.py` | Merchant Center ProductPerformanceView queries (for Ask) |
| `moengage.py` | MoEngage data source |
| `datasource.py` | Routes a report to GA4 or MoEngage by its `source` field |
| `google_oauth.py` | Google OAuth flow + account discovery (GA4/Ads/Merchant/Search Console) |
| `meta_oauth.py` | Meta OAuth flow + ad-account discovery |
| `connections.py` | Connection store, token refresh, encryption |
| `profiles.py` | Saved-site store (`profiles.json`) |
| `report_defs.py` | Shared report template (`report_defs.json`) |
| `insights.py` | AI + rule-based insights |
| `jobs.py` / `scheduler.py` | Scheduled jobs + background cache warming |
| `sheets.py` / `slides.py` | Google Sheets / Slides export |
| `cache.py` / `shape.py` | Redis cache + normalized report shapes |

### Data / state files (git-ignored, created on first run)

- `backend/report_defs.json` — shared report template. Each report:
  `{key, name, dimensions[], metrics[], orderBy, limit, sheetTab, source?}`.
  Use `"{channelGroup}"` in `dimensions` to plug in each site's custom channel
  group (falls back to `sessionDefaultChannelGroup`).
- `backend/profiles.json` — saved sites (created via **+ Add site**).
- `backend/connections.json` — OAuth connections (tokens encrypted at rest).
- `backend/jobs.json` — scheduled per-site jobs.
- `backend/ask_history.json` — Ask question/answer history.

---

## 1. Google Cloud setup (service-account path)

For the headless GA4 + Sheets/Slides path you need one GCP project, the APIs
enabled, and a service account granted access to each GA4 property.

1. **Create a project** — https://console.cloud.google.com/projectcreate. Note the
   project ID.
2. **Enable APIs** — *APIs & Services → Library*:
   - Google Analytics Data API (`analyticsdata.googleapis.com`)
   - Google Analytics Admin API (`analyticsadmin.googleapis.com`)
   - Google Sheets API (`sheets.googleapis.com`) — Sheets export
   - Google Slides API (`slides.googleapis.com`) — Slides export
   - *(OAuth/discovery also uses)* Google Ads API, Content API for Shopping
     (`shoppingcontent.googleapis.com`), and Search Console API
     (`searchconsole.googleapis.com` / `webmasters`).
3. **Create a service account** — *IAM & Admin → Service Accounts → Create*. No
   project roles required. **Keys → Add key → Create new key → JSON**, save as
   `backend/service-account.json` (git-ignored). Copy its email
   (`...@<project>.iam.gserviceaccount.com`).
4. **Grant it GA4 access** — in **Google Analytics** (not GCP): *Admin → Property →
   Property Access Management → add* the service-account email as **Viewer**
   (per property).
5. **Find your Property ID** — GA4 *Admin → Property Settings* (numeric, e.g.
   `123456789`). Enter it when adding a site.
6. **For Sheets export** — Share the target spreadsheet with the service-account
   email as **Editor**; copy its ID from `.../spreadsheets/d/<ID>/edit`.
7. **For Slides export** — Share a Slides deck with the service-account email as
   **Editor**; copy its ID from `.../presentation/d/<ID>/edit`. Each export
   rebuilds the deck's slides.

Multiple clients/projects: `SERVICE_ACCOUNT_FILE` accepts a **comma-separated**
list of key files. Each key is matched to a site by the profile's `projectId`;
the first key listed is the default for profiles without one.

## 2. OAuth connections setup (optional but recommended)

Lets users connect their own Google/Meta accounts in the UI and auto-discover
everything they can access.

- **Google OAuth** — in GCP, *APIs & Services → Credentials → Create OAuth client
  ID (Web application)*. Add the redirect URI
  `http://localhost:3030/oauth/google/callback` (match `GOOGLE_OAUTH_REDIRECT_URI`).
  Requested scopes: Analytics (readonly), Ads, Content (Merchant Center),
  Search Console (`webmasters.readonly`), plus `openid`/email. Set
  `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.
  - Google Ads discovery additionally needs `GOOGLE_ADS_DEVELOPER_TOKEN`
    (skipped gracefully if unset).
- **Meta OAuth** — create a Meta app (scopes `ads_read`, `business_management`),
  add the redirect `http://localhost:3030/oauth/meta/callback`, and set
  `META_APP_ID` / `META_APP_SECRET`.
- **Token encryption** — connection tokens are encrypted at rest with a Fernet
  key. Set `TOKEN_ENCRYPTION_KEY` in `.env` for production; if unset, a key is
  generated per-process (fine for dev, but connections won't survive a restart).

## 3. AI insights & Ask

Get a Claude API key from https://console.anthropic.com and set
`ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_MODEL`, default `claude-sonnet-5`).
Without a key, insights fall back to rule-based text and the **Ask** feature is
disabled (it has no non-AI fallback).

---

## 4. Configure environment

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

**`backend/.env`**

| Variable | Purpose | Default |
|---|---|---|
| `SERVICE_ACCOUNT_FILE` | Path(s) to service-account JSON key(s), comma-separated | — |
| `QUOTA_PROJECT_ID` | GCP project for quota/billing attribution | — |
| `ANTHROPIC_API_KEY` | Claude key for insights + Ask | — |
| `ANTHROPIC_MODEL` | Claude model | `claude-sonnet-5` |
| `REDIS_URL` | Redis connection | `redis://127.0.0.1:6379/0` |
| `CACHE_TTL_SECONDS` | Cached-report freshness | `1800` |
| `REFRESH_INTERVAL_MIN` | Background cache-warm interval | `30` |
| `CORS_ORIGINS` | Allowed frontend origin(s) | `http://localhost:3030` |
| `CURRENCY_SYMBOL` | Display currency | `₹` |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | Google OAuth app | — |
| `GOOGLE_OAUTH_REDIRECT_URI` | Google callback | `http://localhost:3030/oauth/google/callback` |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Enables Ads discovery | — |
| `META_APP_ID` / `META_APP_SECRET` | Meta OAuth app | — |
| `META_REDIRECT_URI` | Meta callback | `http://localhost:3030/oauth/meta/callback` |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for connection tokens | auto (dev only) |

> Note: the shipped `backend/.env.example` covers the service-account + cache +
> AI settings. Add the OAuth/Meta/encryption variables above if you use
> connections.

**`frontend/.env.local`**

| Variable | Purpose | Default |
|---|---|---|
| `BACKEND_URL` | FastAPI base URL (browser reaches it via `/api/ga`) | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_DEFAULT_PROPERTY_ID` | Optionally pre-select a GA4 property | — |

---

## 5. Run it

**Redis**
```bash
redis-server            # or: sudo service redis-server start
```

**Backend**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev             # http://localhost:3030
```

Open http://localhost:3030:

1. **Connect an account** (optional) — *Connections* → connect Google/Meta →
   discover accessible properties → select → **Use selected in new site**. Or use
   **+ Add site** to enter IDs manually (GA4 Property ID + any platform IDs).
2. Pick a **date range** (presets incl. *Last month*, or custom start/end).
3. Each report renders as a month-over-month table. Use **⬇ CSV** per section, or
   **⬇ Export all → Google Sheet**, or build the **Slides** deck.
4. **Ask** a plain-English question about the site (needs `ANTHROPIC_API_KEY`).
5. Browse the **Platform** pages (GA4 / Merchant Center / Search Console) to see
   every site's status for that platform at a glance.
6. Switch sites anytime from the dropdown — no reconfiguration.

---

## Editing the reports

Edit `backend/report_defs.json` (seeded on first run). Each entry:

```json
{
  "key": "traffic-acquisition",
  "name": "Traffic Acquisition",
  "dimensions": ["{channelGroup}", "sessionSourceMedium"],
  "metrics": ["sessions", "totalUsers", "engagementRate"],
  "orderBy": "sessions",
  "limit": 100,
  "sheetTab": "Traffic Acquisition",
  "source": "ga4"
}
```

`"{channelGroup}"` is replaced per-site with that site's custom channel-group
dimension. `source` defaults to `"ga4"`; set `"moengage"` to pull that section
from MoEngage instead. Dimension/metric names are GA4 Data API names — see the
[GA4 API schema](https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema).

---

## API surface (backend)

All mounted under the FastAPI app and reached from the browser via `/api/ga/*`
(OAuth routes via `/oauth/*`).

| Prefix | Router | What it does |
|---|---|---|
| `/profiles` | `profiles` | CRUD for saved sites |
| `/reports` | `reports` | Run report sections (month-over-month) |
| `/insights` | `insights` | Generate/regenerate AI insights |
| `/export` | `export` | CSV / Google Sheets / Google Slides export |
| `/connections` + `/oauth/*` | `connections` | List/delete connections, OAuth login/callback, discovery |
| `/jobs` | `jobs` | CRUD for scheduled per-site jobs |
| `/ask` | `ask` | Free-text Q&A tool loop + history |
| `/health` | — | Liveness check |

---

## Scheduled cache & jobs

APScheduler runs in the backend process:

- **Cache warming** — re-runs the report template for every saved site every
  `REFRESH_INTERVAL_MIN` minutes so the dashboard loads instantly; live requests
  fall back to a fresh fetch on cache miss.
- **Jobs** — due `sheets_export` / `slides_export` / `insights_digest` jobs run on
  their schedule (daily / weekly on Mondays / monthly on the 1st, at the
  configured hour). A monthly job reports on the just-finished calendar month.

---

## Security notes

- Service-account keys and `*.json` state files are **git-ignored** — keep them
  out of version control (they contain credentials/tokens).
- OAuth connection tokens are **encrypted at rest**; pin `TOKEN_ENCRYPTION_KEY`
  in production so they survive restarts.
- MoEngage API keys are stored in plaintext inside `profiles.json` — treat that
  file as a secret.
# the_Ledger_marketing_automation_ai_tool
