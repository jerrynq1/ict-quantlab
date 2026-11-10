# Static HTML deployment notes

The static site is rooted at `/index.html` and uses relative `assets/...` URLs, so it works both at a GitHub Pages project path and a custom domain. Hash navigation avoids server-side route rewrites.

For a private cTrader workspace, the browser stores only non-secret convenience settings (API URL, Client ID display value, redirect URI and environment). A short-lived API bearer token is held in `sessionStorage`. The cTrader Client Secret is never stored in web storage. It is submitted only to the configured HTTPS API endpoint, where the backend encrypts it.

If no API is configured, all screens remain browseable but live connection actions are unavailable. This is intentional: a static page cannot securely replace server-side credential storage or OAuth token exchange.
