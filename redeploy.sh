#!/usr/bin/env bash
# One-shot (re)deploy of agentcore_agent.py to AgentCore Runtime.
#
# Prereqs that persist across teardowns (set up once, NOT recreated by this script):
#   - Execution role AgentCoreTrainingExecRole (iam/agentcore-{trust,permissions}-policy.json)
#   - Inline policies on the aws-training user (iam/training-policy.json)
#   - Docker Desktop running (for --local-build)
#
# Usage:  ./redeploy.sh
set -euo pipefail

export AWS_PROFILE=training
export AWS_REGION=us-east-1
export AGENTCORE_SUPPRESS_RECOMMENDATION=1

ROLE_ARN="arn:aws:iam::21730xxxxxxx:role/AgentCoreTrainingExecRole"
ENTRYPOINT="agentcore_agent.py"

cd "$(dirname "$0")"
source venv/bin/activate

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is down — start Docker Desktop first (needed for --local-build)." >&2
  exit 1
fi

agentcore configure -e "$ENTRYPOINT" \
  --execution-role "$ROLE_ARN" \
  --region "$AWS_REGION" --disable-memory --deployment-type container --non-interactive

agentcore deploy --local-build

echo
echo "Deployed. Test it with:"
echo "  agentcore invoke '{\"prompt\": \"what do you sell?\"}'"
