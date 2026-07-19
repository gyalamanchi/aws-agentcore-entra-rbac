#!/usr/bin/env bash
# Serve the front-end over HTTPS on https://localhost:5173 (Entra corp tenants require https redirect URIs).
# Generates a self-signed cert on first run (browser will warn once — click "proceed to localhost").
# Register  https://localhost:5173  as the SPA redirect URI in Entra (App A).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f cert.pem ] || [ ! -f key.pem ]; then
  echo "Generating self-signed cert for localhost..."
  openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=localhost" 2>/dev/null
fi
echo "Serving https://localhost:5173  (Ctrl-C to stop)"
python3 - <<'PY'
import http.server, ssl
srv = http.server.HTTPServer(("localhost", 5173), http.server.SimpleHTTPRequestHandler)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain("cert.pem", "key.pem")
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
PY
