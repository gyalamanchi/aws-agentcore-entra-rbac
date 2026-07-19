#!/usr/bin/env bash
# Serve the front-end + DataPower shim on one HTTPS origin: https://localhost:5173
# (matches the Entra SPA redirect URI; no CORS / mixed content). The shim proxies to the deployed
# Entra-authenticated agent, doing token exchange (MODE=exchange) or passthrough.
#
# Usage:  MODE=exchange ./run_frontend.sh      (MODE defaults to exchange; use passthrough to compare)
set -euo pipefail
cd "$(dirname "$0")"
source venv/bin/activate

# self-signed cert (first run). Browser warns once; accept it.
if [ ! -f frontend/cert.pem ]; then
  openssl req -x509 -newkey rsa:2048 -keyout frontend/key.pem -out frontend/cert.pem -days 365 -nodes -subj "/CN=localhost" 2>/dev/null
fi

# Entra values for the OBO shim (secret stays local).
set -a; source entra/.env; set +a
export AWS_PROFILE=training AWS_REGION=us-east-1
export AGENT_ARN="$(aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 \
  --query "agentRuntimes[?agentRuntimeName=='gateway_agent'].agentRuntimeArn | [0]" --output text)"
export MODE="${MODE:-exchange}"

echo "AGENT_ARN = $AGENT_ARN"
echo "MODE      = $MODE"
echo
echo ">>> Open  https://localhost:5173   (accept the self-signed cert once), then click 'Sign in with Microsoft'."
echo ">>> Watch this terminal for the T1/T2 token prints at each hop."
echo
exec uvicorn datapower.shim:app --host localhost --port 5173 \
  --ssl-keyfile frontend/key.pem --ssl-certfile frontend/cert.pem
