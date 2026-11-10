# ICT QuantLab architecture

## Frontend
The frontend is plain static HTML, CSS and JavaScript at the repository root (`index.html`). It is hosted by GitHub Pages and uses hash navigation and relative asset URLs. No Node.js, Next.js, React, build pipeline or Actions workflow is required for the frontend.

## Backend
FastAPI remains under `apps/api`. It is a separate service required only for secure cTrader credentials, OAuth token exchange, persistent encrypted configuration and future market-data ingestion. GitHub Pages cannot run Python or safely store a Client Secret.

## Research pipeline
cTrader Open API -> account authorization -> symbol discovery -> M1 history -> validation/UTC normalization -> timeframe aggregation -> ICT Event Engine -> Statistics Engine -> Hybrid Forecast Engine -> research evaluation.

Raw OHLC is held in the session RAM cache only. Forecast audit records and encrypted cTrader configuration are separate persistence concerns.
