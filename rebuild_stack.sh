#!/usr/bin/env bash
# Rebuild the full Gateway + MCP + agent stack from scratch after a teardown.
# The IAM roles/policies + Transaction Search persist across teardowns, so this needs NO console work.
#
# Prereqs (one-time, already done): AgentCoreTrainingExecRole, AgentCoreGatewayRole, managed policy
# aws-training-agentcore, Transaction Search enabled. Plus Docker Desktop running.
#
# Usage:  ./rebuild_stack.sh
set -euo pipefail
export AWS_PROFILE=training AWS_REGION=us-east-1 AGENTCORE_SUPPRESS_RECOMMENDATION=1
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"; source venv/bin/activate
ACCT=21730xxxxxxx
EXEC_ROLE="arn:aws:iam::${ACCT}:role/AgentCoreTrainingExecRole"
GATEWAY_ROLE="arn:aws:iam::${ACCT}:role/AgentCoreGatewayRole"

docker info >/dev/null 2>&1 || { echo "Start Docker Desktop first (needed for --local-build)."; exit 1; }

echo "===== 1/3  MCP server on Runtime ====="
cd "$ROOT/mcp_server"
agentcore configure -e mcp_server.py --protocol MCP --execution-role "$EXEC_ROLE" \
  --region us-east-1 --disable-memory --deployment-type container --non-interactive
agentcore deploy --local-build
cd "$ROOT"
MCP_ARN=$(aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 \
  --query "agentRuntimes[?agentRuntimeName=='mcp_server'].agentRuntimeArn | [0]" --output text)
echo "MCP runtime ARN: $MCP_ARN"
[ -n "$MCP_ARN" ] && [ "$MCP_ARN" != "None" ] || { echo "Could not find MCP runtime ARN"; exit 1; }

echo "===== 2/3  Gateway + Cognito + MCP-server target ====="
GATEWAY_ROLE_ARN="$GATEWAY_ROLE" MCP_RUNTIME_ARN="$MCP_ARN" python gateway/setup_gateway.py create
sleep 10  # let the target finish syncing
python gateway/setup_gateway.py verify

echo "===== 3/3  Gateway agent (deployed, with fresh Cognito creds) ====="
cd "$ROOT/gateway"
eval "$(python - <<'PY'
import json
i=json.load(open("gateway_info.json")); ci=i["cognito"]["client_info"]
print(f'GW={i["gateway_url"]!r}');  print(f'TOK={ci["token_endpoint"]!r}')
print(f'CID={ci["client_id"]!r}');  print(f'SEC={ci["client_secret"]!r}');  print(f'SCOPE={ci["scope"]!r}')
PY
)"
agentcore configure -e gateway_agent.py --execution-role "$EXEC_ROLE" \
  --region us-east-1 --disable-memory --deployment-type container --non-interactive
agentcore deploy --local-build \
  --env GATEWAY_URL="$GW" --env COGNITO_TOKEN_URL="$TOK" --env COGNITO_CLIENT_ID="$CID" \
  --env COGNITO_CLIENT_SECRET="$SEC" --env COGNITO_SCOPE="$SCOPE"

echo
echo "Done. Test with:"
echo "  cd gateway && agentcore invoke '{\"prompt\":\"weather in denver and price of a banana?\"}'"
