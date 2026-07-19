#!/usr/bin/env bash
# One-shot built-in evaluators against the deployed gateway_agent's recent sessions.
#
# Prereqs: CloudWatch Transaction Search enabled (Phase 0), the agent invoked a few times,
# and ~2-5 min elapsed so traces land in CloudWatch.
#
# Usage:
#   ./evals/run_evals.sh                 # evaluate the most recent session (toolkit picks it up)
#   ./evals/run_evals.sh <agent-id> <session-id>
set -euo pipefail
export AWS_PROFILE=training AWS_REGION=us-east-1 AGENTCORE_SUPPRESS_RECOMMENDATION=1
cd "$(dirname "$0")/.."
source venv/bin/activate

echo "=== available built-in evaluators ==="
agentcore eval evaluator list || true

EVALS=(--evaluator Builtin.Correctness --evaluator Builtin.Faithfulness --evaluator Builtin.ToolSelectionAccuracy)

mkdir -p evals
if [ "$#" -ge 2 ]; then
  agentcore eval run "${EVALS[@]}" --agent-id "$1" --session-id "$2" --output evals/results.json
else
  # Evaluate most recent session from config; --days widens the lookback if needed.
  agentcore eval run "${EVALS[@]}" --days 1 --output evals/results.json
fi

echo
echo "Results saved to evals/results.json"
echo "View in CloudWatch -> GenAI Observability -> Bedrock AgentCore -> <agent> -> Evaluations tab."
