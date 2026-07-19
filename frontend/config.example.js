// Copy to config.js and fill from Entra. These are PUBLIC-client values (client id / tenant / scope) —
// not secrets — so config.js is safe, but it's gitignored anyway to keep your ids out of the repo.
window.APP_CONFIG = {
  tenantId:    "4b7f45a9-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  spaClientId: "c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  // The delegated scope your SPA requests (Expose an API > Scopes on the API app):
  apiScope:    "api://c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx/mcp.invoke",
  // Where the DataPower shim listens:
  shimUrl:     "http://localhost:8080/invoke",
};
