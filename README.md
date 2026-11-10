# ICT QuantLab — Static HTML Edition

This edition uses **plain HTML, CSS and JavaScript**. No Node.js, Next.js, React, Docker or build step is needed to publish the frontend on GitHub Pages.

## Publish on GitHub Pages
1. Upload the contents of this repository to the **root** of your GitHub repository. `index.html` must be visible in the repository's top-level Code view.
2. Open **Settings → Pages**.
3. Under **Build and deployment → Source**, choose **Deploy from a branch**.
4. Select branch `main` and folder `/(root)`, then click **Save**.
5. Wait for the Pages deployment and open the URL shown on the Pages settings page. For a project repo it is normally `https://OWNER.github.io/REPOSITORY/`.

There is no Actions workflow and no `NEXT_PUBLIC_API_BASE_URL` variable needed for the static page itself.

## cTrader connection and security
GitHub Pages is static hosting. It cannot run FastAPI, exchange OAuth codes using a private Client Secret, or store credentials securely on the server.

The Data Center screen can store the public API URL, Client ID, redirect URI and Demo/Live choice in browser local storage. **Client Secret is deliberately not stored in the browser.** To save it persistently, enter it while signed in and send it over HTTPS to the separate FastAPI backend, which encrypts it before database persistence. The saved Secret is never returned to JavaScript.

Therefore:
- To preview and use the dashboard shell, GitHub Pages alone is enough.
- To save credentials and use cTrader OAuth, deploy `apps/api` to a separate HTTPS backend and configure CORS to allow your exact GitHub Pages origin.
- The API callback URL must be registered in cTrader and point to the backend, not GitHub Pages.
- Keep the backend encryption key and database on persistent server storage. Never put Client Secret, API passwords, tokens or encryption keys in this GitHub repository.

## API backend
The existing FastAPI source is retained in `apps/api`. Configure the backend environment variables according to `../.env.example` and `docs/CTRADER_SECURITY.md`. Set `ICTQL_PUBLIC_APP_URL` to the exact GitHub Pages URL including the repository path and trailing slash, e.g. `https://OWNER.github.io/REPOSITORY/`. Set `ICTQL_CORS_ORIGINS` to the origin only, e.g. `https://OWNER.github.io`.

The cTrader OAuth callback URL registered in cTrader should be:
`https://YOUR_API_HOST/api/v1/integrations/ctrader/callback`

## Research scope
The logic and event definitions are documented in `docs/`. The cTrader Protobuf transport, account authorization, dynamic symbol discovery, M1 history ingestion, statistics calculations and trained/validated Forecast models remain implementation work. The interface intentionally does not fabricate prices or probabilities.
