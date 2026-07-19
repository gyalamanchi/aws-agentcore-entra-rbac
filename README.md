# AWS training sandbox — Bedrock · AgentCore · Strands

> **Sanitized public copy.** Identifiers are partially masked — real prefix, `xxxx` tail
> (e.g. account `21730xxxxxxx`, client `c1a0c3f8-xxxx-…`) — so structure is visible but the full
> values aren't. Screenshots have IP / name / email / full ids redacted. Substitute your own
> values; see `docs/architecture.md` for the full design + diagrams.


Isolated from the production infra: uses a dedicated **`aws-training`** IAM user + a **`training`** CLI
profile. Never uses the options-agent deployer credential.

## 1. Identity (done / to verify)
- IAM user **`aws-training`** — **programmatic access only** (access keys), **no console login**
  (you do console tasks as your admin identity).
- CLI profile: `aws configure --profile training` (region `us-east-1` or `us-west-2` — most Bedrock
  models). Keys live in `~/.aws/credentials`, **never in this repo** (see `.gitignore`).
- Run everything here with `export AWS_PROFILE=training` (or prefix each command).

## 2. Permissions — attach BOTH to the `aws-training` user
1. **AWS-managed:** `AmazonBedrockFullAccess` (Bedrock models / agents / knowledge bases).
2. **Custom:** `iam/training-policy.json` (Bedrock **AgentCore** + scoped `iam:PassRole` + CloudWatch
   Logs). Create it in the console: IAM → Policies → Create → JSON → paste → attach to the user.

> Note: this user can't create IAM roles (on purpose). When an agent needs an execution role, create
> it yourself as admin in the console; the training user only **passes** it to the service.

## 3. Enable model access (THE gotcha — do this or every invoke is AccessDenied)
Console → **Bedrock → Model access** → enable the models you want (Claude, Titan, …). Per-account,
per-region, usually instant. IAM perms alone are **not** enough.

## 4. Set a budget alarm (Bedrock + agents bill per token)
Billing → **Budgets** → a small monthly $ alert. Agent loops/tool calls burn tokens fast.

## 5. Run it
```bash
export AWS_PROFILE=training
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python bedrock_smoke.py        # step 1: lists the Claude models you can see (proves access)
#   → enable a model, put its id in the file, uncomment Step 2, re-run for a real inference
python strands_agent.py        # a tool-using Strands agent on Bedrock
```

## 6. Bedrock AgentCore — deploy the catalog agent + invoke it
`agentcore_agent.py` is the same style of Strands agent, wrapped in `BedrockAgentCoreApp` so it can
run on the managed **AgentCore Runtime**. It "selects" from an in-memory `CATALOG` dict via two tools.

**Two one-time ADMIN (console) steps first** — the `aws-training` user can't create IAM roles:
1. **Execution role** — IAM → Roles → Create role → **Custom trust policy** → paste
   `iam/agentcore-trust-policy.json`. On the permissions step, create an inline policy from
   `iam/agentcore-permissions-policy.json`. Name it `AgentCoreTrainingExecRole`, note its ARN.
   (Both files are pure ASCII with the account id pre-filled — paste as-is.)
2. **Re-attach `iam/training-policy.json`** — it now includes ECR push perms (for
   `deploy --local-build`). Update the attached policy in the console.

**Then, as the training user (local build → cloud runtime, no CodeBuild role needed):**
```bash
export AWS_PROFILE=training AWS_REGION=us-east-1
source venv/bin/activate
pip install -r requirements.txt
# NOTE: use the venv's `agentcore` (starter toolkit). An npm `agentcore` (CDK-based) may also be on
# PATH — the activated venv shadows it. Confirm: `which agentcore` → .../venv/bin/agentcore
python agentcore_agent.py    # optional local smoke test: curl -XPOST localhost:8080/invocations -d '{"prompt":"..."}'

agentcore configure -e agentcore_agent.py --execution-role arn:aws:iam::21730xxxxxxx:role/AgentCoreTrainingExecRole
#   (start Docker Desktop first — --local-build needs the daemon)
agentcore deploy --local-build     # builds ARM64 image, pushes to ECR, creates the runtime
agentcore status                   # → READY + the agentRuntimeArn
```

**Invoke it:**
- **Console:** Bedrock → AgentCore → Agent Runtime → your runtime → test/invoke panel, body `{"prompt":"how much is a cherry?"}`.
- **CLI:** `agentcore invoke '{"prompt":"list everything you sell"}'`
- **boto3:** `client("bedrock-agentcore").invoke_agent_runtime(agentRuntimeArn=..., runtimeSessionId="a"*40, payload=...)`

**Cost:** runtime bills only while actively processing a request (idle ≈ free); tiny standing floor
for the ECR image + logs; each invoke also bills nova tokens. See the Budgets alarm (§4).

### 6b. Terraform (same runtime as IaC — learning exercise)
`terraform/` recreates the runtime with `aws_bedrockagentcore_agent_runtime`, **reusing** the image
the toolkit already pushed (Terraform can't build containers). It makes a *second* runtime
(`catalog_agent_tf`) so it won't collide. `cp terraform.tfvars.example terraform.tfvars`, fill in the
role ARN + `container_uri` (from `agentcore status`), then `terraform init && terraform apply`.

## 7. Gateway + MCP server + built-in evaluators (the full stack)
Topology: **agent → (Cognito OAuth) → Gateway → (IAM SigV4) → MCP server on Runtime.** The agent mixes
a local tool with tools proxied from the MCP server through the Gateway; then AgentCore's built-in
evaluators score the deployed agent's traces.

**Admin (console) prereqs** — the training user can't create roles / enable account features:
1. **Gateway service role** `AgentCoreGatewayRole` from `iam/gateway-trust-policy.json` +
   `iam/gateway-permissions-policy.json`.
2. **Managed policy** `aws-training-agentcore` = full `iam/training-policy.json` (attach; it has the
   Cognito, log-delivery, and span-query grants). Broaden `AgentCoreTrainingExecRole`'s model resource
   to `amazon.nova-*` (`iam/agentcore-permissions-policy.json`).
3. **Enable CloudWatch Transaction Search** (CloudWatch → Application Signals → Transaction Search).

**Run it:**
```bash
export AWS_PROFILE=training AWS_REGION=us-east-1 && source venv/bin/activate
# 1) MCP server on Runtime
cd mcp_server && agentcore configure -e mcp_server.py --protocol MCP \
  --execution-role arn:aws:iam::21730xxxxxxx:role/AgentCoreTrainingExecRole \
  --region us-east-1 --disable-memory --deployment-type container --non-interactive && \
  agentcore deploy --local-build && cd ..
# 2) Gateway + Cognito + MCP-server target (set MCP_RUNTIME_ARN from `agentcore status`)
export GATEWAY_ROLE_ARN=arn:aws:iam::21730xxxxxxx:role/AgentCoreGatewayRole
export MCP_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:21730xxxxxxx:runtime/mcp_server-XXXX
python gateway/setup_gateway.py create && python gateway/setup_gateway.py verify
# 3) Agent: local, then deploy (see gateway_agent.py header for the --env COGNITO_*/GATEWAY_URL flags)
python gateway/gateway_agent.py "weather in denver and price of a banana?"
# 4) Evaluate (after invoking the deployed agent a few times + ~3 min)
./evals/run_evals.sh
```
Uses **nova-lite** (micro can't tool-use). Tool names must be hyphen-free — the target is named
`mcpRuntime` so tools surface as `mcpRuntime___get_weather`. See CLAUDE.md for the full gotcha list.
View eval scores: CloudWatch → GenAI Observability → Bedrock AgentCore → your agent → Evaluations.

## Files
| file | what |
|---|---|
| `iam/training-policy.json` | custom IAM policy (AgentCore + PassRole + Logs + ECR push) to attach |
| `iam/agentcore-trust-policy.json` | paste into the role's **Custom trust policy** (pure ASCII, acct pre-filled) |
| `iam/agentcore-permissions-policy.json` | the role's inline **permissions** policy (Bedrock invoke + ECR pull + logs) |
| `requirements.txt` | boto3 + strands-agents + bedrock-agentcore(+starter-toolkit) |
| `bedrock_smoke.py` | list models (access check) + a Converse inference example |
| `strands_agent.py` | minimal tool-using Strands agent on Bedrock (local only) |
| `agentcore_agent.py` | the same agent wrapped for AgentCore Runtime (deployable) |
| `terraform/` | the runtime expressed as IaC (reuses the toolkit's ECR image) |
| **`docs/architecture.md`** | **full design doc with diagrams** — Entra auth, RBAC, token exchange, gateway + MCP scoping, agent internals |
| `frontend/` · `datapower/` · `gateway/` · `mcp_*/` | the Entra + RBAC + MCP stack (see `docs/architecture.md`) |
| `.gitignore` | keeps credentials / deploy artifacts / tfstate out of git |
