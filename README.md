# ICT QuantLab

Dark Quant Terminal for ICT-oriented quantitative research. The frontend is a static HTML/CSS/Vanilla JavaScript site for GitHub Pages. A separate FastAPI service handles authentication, cTrader OAuth/Protobuf, RAM-only OHLC caching, analytics, forecast audit records and research notes.

> This project is a research platform, not an execution terminal. ICT concepts have multiple practitioner definitions. Mechanical proxies are identified in the UI/API and should be validated per broker, instrument and timeframe.

## Architecture

```text
Browser (GitHub Pages)
  index.html + assets/styles.css + assets/app.js
            | HTTPS / Bearer session / CORS
            v
FastAPI backend (Render / Railway / VPS)
  Admin login · cTrader OAuth · Protobuf SDK · Engines
  Encrypted SQLite settings · Forecast audit · Research notes
            |
            v
cTrader Open API (Demo or Live account, read-only accounts scope)
```

GitHub Pages cannot run Python/FastAPI, store a backend database, or protect the cTrader Client Secret. Never put Client Secret, access token, refresh token, Fernet key, admin password, or session secret in HTML, JavaScript, GitHub Actions variables used by the public frontend, or localStorage.

## 1. Publish the frontend on GitHub Pages

1. Put the contents of this repository at the root of your GitHub repository. `index.html`, `.nojekyll`, `assets/` and `.github/workflows/deploy-pages.yml` must be at the root.
2. Open **Settings → Pages → Build and deployment** and select **GitHub Actions**.
3. Push to the `main` branch, or run **Actions → Validate and deploy ICT QuantLab to GitHub Pages → Run workflow**. The workflow first runs the backend tests and static frontend checks; Pages only deploys if validation succeeds.
4. Open `https://GITHUB_USERNAME.github.io/REPOSITORY_NAME/`.

The workflow publishes only `index.html`, `.nojekyll` and `assets/`. It does not publish the backend folder as part of the Pages artifact.

## 2. Deploy the backend

Create a Docker Web Service from this repository (Render, Railway, or a VPS with Docker):

| Setting | Value |
|---|---|
| Root directory | `apps/api` |
| Runtime | Docker |
| Dockerfile path | `Dockerfile` |
| Health check | `/api/v1/system/health` |
| Persistent volume mount | `/data` |

A persistent volume is required when using SQLite so encrypted cTrader settings, sessions, forecast audit records and research notes survive container replacement. The in-memory M1 cache is intentionally transient and is not persisted.

Set the following backend environment variables in the hosting provider's secret/environment settings. Do not commit a real `.env` file.

| Variable | Example / purpose |
|---|---|
| `ICTQL_ENVIRONMENT` | `production` |
| `ICTQL_DATABASE_PATH` | `/data/ict_quantlab.sqlite3` |
| `ICTQL_ADMIN_USERNAME` | A private admin username |
| `ICTQL_ADMIN_PASSWORD` | A long unique password |
| `ICTQL_SESSION_SECRET` | Random secret, 48+ bytes |
| `ICTQL_ENCRYPTION_KEY` | Valid Fernet key |
| `ICTQL_PUBLIC_APP_URL` | Full GitHub Pages URL including repository path, no trailing slash |
| `ICTQL_PUBLIC_API_URL` | Backend HTTPS origin, no trailing slash |
| `ICTQL_CORS_ORIGINS` | `https://GITHUB_USERNAME.github.io` (origin only, no repository path) |
| `ICTQL_TRUSTED_HOSTS` | Backend hostname only, e.g. `my-api.onrender.com` |
| `ICTQL_MAX_BARS_PER_SYMBOL` | `2000000` |

Generate secrets locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use the first output for `ICTQL_ENCRYPTION_KEY`, and the second for `ICTQL_SESSION_SECRET`. Preserve both values permanently. Changing the Fernet key makes stored credentials/tokens undecryptable. Changing the session secret invalidates existing session tokens.

After deployment, check:

```text
https://YOUR_BACKEND_HOST/api/v1/system/health
https://YOUR_BACKEND_HOST/api/v1/system/readiness
```

The frontend login screen or **Settings → Backend endpoint** takes the backend base URL, e.g. `https://my-api.onrender.com`.

## 3. Configure cTrader Open API

1. Create an Open API application in the cTrader Open API portal.
2. Set the application redirect URI to the exact callback URL:
   `https://YOUR_BACKEND_HOST/api/v1/ctrader/oauth/callback`
3. In QuantLab → Data Center → cTrader, enter Client ID, Client Secret, Demo/Live environment and the same redirect URI, then save.
4. Choose the `accounts` scope (read-only) unless you explicitly need trading permissions; this product does not place trades.
5. Click **Authorize cTrader**, approve the app, refresh the account list, and select the target account.
6. Load the symbol list, select a symbol and download M1 history.

The Client Secret and OAuth tokens are encrypted by the backend before being saved in SQLite. The API returns only whether a secret is saved, never the secret itself. Use Demo first when validating a new integration. The app's OAuth callback must be HTTPS and must exactly match the URI registered with cTrader.

## 4. Research modules

### Phase 1 core statistics

1. Gap Statistics — NDOG/NWOG, progressive 25/50/75/100% fill, censoring and reaction windows.
2. Liquidity Statistics — Asia High/Low, PDH/PDL, PWH/PWL, probe/sweep/breakout/reclaim.
3. Session Statistics — session ranges, direction, continuation/reversal and formation times.
4. Time Statistics — high/low timing, reversal candidates and hourly distribution.
5. Market Structure — confirmed pivots, BOS/MSS, MFE/MAE, target attainment and ambiguity handling.
6. Daily & Weekly — direction, range and high/low formation time; incomplete edge periods are labelled/excluded from complete-period baselines.
7. Liquidity → MSS — conditional response after a sweep at 5/15/30/60-minute horizons.

FVG fill statistics are not in Phase 1. FVG formation/mitigation is part of the Advanced ICT Lab.

### Advanced ICT research

FVG, EQH/EQL, OB/Breaker, Premium/Discount and rolling dealing-range context, ADR 5/20/50, IPDA-style ranges, CBDR, Silver Bullet window matches, PO3/AMD, Judas Swing, CISD, Three Drives, SMT, Quarterly profile/shift candidates and Confluence heuristic scores.

The Advanced ICT Lab uses explicit mechanical proxies. Heuristic candidate labels are not calibrated probabilities or trade recommendations. Confluence is a weighted evidence score, never a probability.

### Hybrid Forecast

Live and historical replay combine event forecasts and price distribution forecasts. The available baseline uses empirical historical analogues with exclusive scenarios, Laplace smoothing, Wilson intervals, quantile price ranges and an explicit minimum sample threshold. Historical analogue labels require a fully observed continuous forward horizon and are drawn only from examples whose labels had matured before the selected forecast timestamp. Forecast audit records are stored separately from the transient M1 cache. Evaluation requires the entire future horizon with continuous bar coverage; Brier score, top-scenario accuracy, multi-class precision/recall, confusion matrix and top-class reliability bins are reported only for eligible outcomes. Forecast minute horizons must be an exact multiple of the selected timeframe; incompatible choices are disabled in the UI and rejected by the API.

HMM/Markov switching, GARCH, survival models, XGBoost, quantile regression and sequence models are research roadmap items; they are not claimed to be trained/active in this build. Compare any future model against the baseline with walk-forward and out-of-sample testing.

## 5. Data and time contracts

- cTrader M1 is the source series. Higher chart intervals are aggregated from M1 on UTC-aligned buckets.
- All internal timestamps are UTC milliseconds; display and date/session filters use `America/New_York`, automatically following EST/EDT.
- Forex trading-day default starts at 17:00 New York. This is a profile assumption, not universal for every instrument or broker.
- Session defaults: Asia 20:00–00:00, London 02:00–05:00, NY AM 07:00–10:00, London Close 10:00–12:00, NY PM 13:00–16:00 New York time. All are editable.
- The RAM cache is partitioned by browser-run ID, account and symbol. Reload starts a new logical run and cache partition. A wider date request reuses successfully loaded ranges and requests only missing ranges.
- Failed data requests are not marked as loaded. Suspect OHLC rows are retained for audit/chart display but excluded from analytics. Higher-timeframe buckets are usable only when every source M1 minute is present and usable.
- The cTrader Open API historical request rate is limited to 5 requests per second per connection. The implementation chunks history requests and inserts a conservative delay.
- Historical OHLC is not stored permanently. SQLite stores credentials/configuration, auth sessions, forecast runs/outcomes and research notes.

## 6. Local development and tests

```bash
cd apps/api
python -m venv .venv
# activate the environment, then:
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
# Replace the placeholder admin password, session secret and Fernet key in .env.
uvicorn app.main:app --reload
```

Run tests from repository root:

```bash
PYTHONPATH=apps/api pytest -q apps/api/tests
node --check assets/app.js
python -m compileall -q apps/api/app
```

A real cTrader integration test requires a registered application, correct redirect URI, valid Client ID/Secret and an authorized demo/live account. Never share those credentials in chat or commit them to the repository.

## 7. Implementation status and validation

- Frontend is static HTML/CSS/Vanilla JavaScript and is deployable through the included GitHub Pages Actions workflow; no Node.js build is required for the site. The FastAPI backend remains a separate Docker service.
- Automated backend test suite: run `cd apps/api && pytest -q` (35 tests in the current build). JavaScript syntax check: `node --check assets/app.js`. Python compile check: `python -m compileall -q apps/api/app`. The GitHub Actions workflow runs backend tests, JavaScript syntax and DOM-ID checks before publishing the Pages artifact.
- The automated test suite covers New York DST/trading periods, data cache isolation, source-bar decoding/quality, incomplete timeframe/session handling, gap censoring, opening-gap liquidity classification, structure look-ahead, Liquidity→MSS horizon completeness, historical replay leakage, forecast diagnostics and advanced ICT candidate definitions.
- A passing local suite does not prove a live cTrader account connection. Production verification still requires a registered Open API app, exact HTTPS OAuth redirect URI, valid Client ID/Secret, an authorized account and a persistent backend database volume. No real market result or forecast should be inferred from the empty workspace before that connection and historical data load.
