# cTrader credential and deployment security

## Credential model
Client ID is an identifier; Client Secret, authorization code, access token and refresh token are
sensitive. Send them only to FastAPI over HTTPS. The API encrypts secrets/tokens with Fernet before
writing SQLite. The encryption key is supplied independently through the deployment secret store.
The database never contains plaintext secrets. GET config returns only Client ID, redirect URI,
environment and booleans/status; it never returns the secret or bearer tokens. Blank Secret on update
means preserve the saved encrypted Secret.

## Static frontend authentication
GitHub Pages and a separately hosted API are commonly cross-site, and browser third-party cookie
blocking can make an HttpOnly cookie unreliable. This build issues an 8-hour signed bearer session
held in `sessionStorage` (not localStorage), sends it in the Authorization header, and checks exact
allowed Origins for state-changing requests. OAuth callback uses a random, one-use, 10-minute state
value created by an authenticated request; no cross-site login cookie is required for the callback.
The bearer token is readable by JavaScript, so this is intended for a private single-owner workspace.
For stronger isolation use same-site custom domains plus a backend-for-frontend with HttpOnly cookies.

## Persistence / reload
Encrypted credentials and OAuth tokens persist in the server database across browser reloads. The
frontend never receives the Secret. The short-lived login bearer token survives reload in the same
tab via sessionStorage. Production database must be on a persistent volume.

## Operational safety
- HTTPS only in production. Never log bodies, authorization codes, tokens or secrets.
- Keep encryption key outside the database and back it up separately.
- Restrict CORS to the exact frontend origin. Do not use wildcard origins.
- Keep Client Secret out of GitHub Pages environment variables; those are build-time public values.
- Rotate credentials if exposed. Losing encryption key makes stored credentials unrecoverable.
- Current auth is single-workspace; do not expose as multi-tenant SaaS without per-user isolation,
  audit logging, stronger session revocation and security review.


## Static HTML frontend
GitHub Pages stores only public UI files. The browser must never persist Client Secret, access token or refresh token in localStorage/sessionStorage. The static client sends Client Secret only to the HTTPS API endpoint after workspace authentication; the backend encrypts it before database persistence. The short-lived workspace bearer token is held in sessionStorage for the active tab and cleared on sign-out/expiry.
