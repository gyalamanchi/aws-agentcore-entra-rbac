#!/usr/bin/env bash
# Rebuild the FULL Entra-secured stack: 3 MCP servers + Entra-authorizer Gateway + RBAC agent.
# Persists across teardown: IAM roles/policies, Transaction Search, and your Entra app (entra/.env).
# Needs: Docker running, entra/.env filled.
#
# Usage:  ./rebuild_entra_stack.sh
set -euo pipefail
export AWS_PROFILE=training AWS_REGION=us-east-1 AGENTCORE_SUPPRESS_RECOMMENDATION=1
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"; source venv/bin/activate
ACCT=21730xxxxxxx
EXEC_ROLE="arn:aws:iam::${ACCT}:role/AgentCoreTrainingExecRole"
GATEWAY_ROLE="arn:aws:iam::${ACCT}:role/AgentCoreGatewayRole"
docker info >/dev/null 2>&1 || { echo "Start Docker Desktop first."; exit 1; }
[ -f entra/.env ] || { echo "entra/.env missing."; exit 1; }

arn_of() { aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 \
  --query "agentRuntimes[?agentRuntimeName=='$1'].agentRuntimeArn | [0]" --output text; }

deploy_mcp() {  # <dir> <entrypoint> <name>
  echo "===== MCP server: $3 ====="
  ( cd "$ROOT/$1" && agentcore configure -e "$2" --name "$3" --protocol MCP \
      --execution-role "$EXEC_ROLE" --region us-east-1 --disable-memory \
      --deployment-type container --non-interactive && agentcore deploy --local-build )
}

deploy_mcp mcp_server mcp_server.py mcp_server
deploy_mcp mcp_dice   server.py     mcp_dice
deploy_mcp mcp_fun    server.py     mcp_fun

export MCP_RUNTIME_ARN="$(arn_of mcp_server)"
export DICE_RUNTIME_ARN="$(arn_of mcp_dice)"
export FUN_RUNTIME_ARN="$(arn_of mcp_fun)"
echo "MCP ARNs: weather=$MCP_RUNTIME_ARN dice=$DICE_RUNTIME_ARN fun=$FUN_RUNTIME_ARN"

echo "===== Gateway (Entra authorizer) + targets ====="
export GATEWAY_ROLE_ARN="$GATEWAY_ROLE"
python gateway/setup_gateway.py create
sleep 10
python gateway/setup_gateway.py verify || echo "(verify warning — targets may still be syncing)"

echo "===== RBAC agent (Entra inbound authorizer) ====="
GATEWAY_URL="$(python -c "import json;print(json.load(open('gateway/gateway_info.json'))['gateway_url'])")"
AUTHZ="$(python -c "import json,importlib.util as u;s=u.spec_from_file_location('sg','gateway/setup_gateway.py');m=u.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.authorizer_config(m.entra())))")"
( cd "$ROOT/gateway" && agentcore configure -e gateway_agent.py --name gateway_agent \
    --execution-role "$EXEC_ROLE" --authorizer-config "$AUTHZ" --region us-east-1 \
    --disable-memory --deployment-type container --non-interactive \
  && agentcore deploy --local-build --env GATEWAY_URL="$GATEWAY_URL" )

echo
echo "Done. Agent ARN: $(arn_of gateway_agent)"
echo "Next: put that ARN in datapower/shim env (AGENT_ARN), run the shim + frontend, sign in."
