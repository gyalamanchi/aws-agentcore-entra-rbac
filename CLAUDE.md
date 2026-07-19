# CLAUDE.md — AWS training sandbox (Bedrock · AgentCore · Strands)

Context for any Claude Code agent working in this directory. This is a **learning/experimentation
sandbox** for AWS Bedrock, Bedrock **AgentCore**, and building **Strands agents**. The operator is
learning — favor explaining + small runnable examples over big builds; let them drive.

## Golden rules (read first)
1. **Credentials:** everything here uses the dedicated **`training`** AWS CLI profile
   (`export AWS_PROFILE=training`). **NEVER** use the `prod-deployer` / production credentials —
   this sandbox is deliberately isolated from the production infra (different IAM user: `aws-training`,
   programmatic-only, no console login).
2. **Never write credentials into the repo.** Keys live in `~/.aws/credentials`. `.gitignore` already
   excludes `.env`, `credentials`, `.aws/`, the CLI `.pkg`. Don't undo that.
3. **The `aws-training` user cannot create IAM roles** (by design). If an agent needs an execution
   role, ask the operator to create it in the console as admin; the training user only **passes** it
   (scoped `iam:PassRole` in `iam/training-policy.json`).
4. **Cost:** Bedrock + agents bill **per token**, and agent loops/tool-calls burn fast. Keep examples
   small, mention cost before anything token-heavy, and there's a Budgets alarm set.

## Environment facts
- **AWS CLI v2** (official bundled installer, not homebrew) — so the old `DYLD_LIBRARY_PATH=/opt/
  homebrew/opt/expat/lib` `pyexpat` workaround is **no longer needed** here. Plain `aws ...` works.
- **Region:** `us-east-1` or `us-west-2` (most Bedrock models, incl. Claude).
- Platform: macOS (Mac Studio). Python examples use a local `.venv`.

## THE gotcha (hit this before debugging IAM)
Bedrock requires **model access to be enabled in the console** (Bedrock → Model access) per-account,
per-region. IAM permissions alone are NOT enough — without it, every `InvokeModel`/`converse` returns
**AccessDenied**. If an invoke 403s, check model access FIRST.

## AWS_PROFILE not exported → silently uses the production `default` profile
If `AWS_PROFILE=training` isn't actually exported in the shell (e.g. you forgot it, or a new
terminal tab reset it), boto3/Strands silently falls back to the `[default]` profile in
`~/.aws/credentials` — which is `prod-deployer` (the production account) — instead of
erroring. Symptom: `AccessDeniedException` naming `prod-deployer` in the ARN, not
`aws-training`. Fix: `export AWS_PROFILE=training` before running any script, and check the ARN
in any AccessDenied error to confirm which identity actually made the call.

## Claude 4.5+ models need an inference-profile id, not the bare model id
Invoking `anthropic.claude-haiku-4-5-*` (or other 4.5+ Claude models) directly returns
`ValidationException: ... on-demand throughput isn't supported ... Retry with an inference
profile`. Use the cross-region inference profile id instead (e.g.
`us.anthropic.claude-haiku-4-5-20251001-v1:0`). Find the right one with:
```
aws bedrock list-inference-profiles --region us-east-1 --query \
  "inferenceProfileSummaries[?contains(inferenceProfileId, 'haiku-4-5')].[inferenceProfileId,inferenceProfileArn]"
```

## "Model use case details have not been submitted" (Anthropic models only)
Separate from the model-access gotcha above: even after enabling model access, invoking an
Anthropic model can return `ResourceNotFoundException: Model use case details have not been
submitted for this account. Fill out the Anthropic use case details form...`. This is a one-time,
per-account form (distinct from "Model access") that must be submitted by the operator in the
Bedrock console — the training IAM user can't do this via CLI. Submit it, then retry after ~15
min. Amazon Nova models (`amazon.nova-micro-v1:0`, etc.) don't require this form, so they're a
useful fallback for testing the pipeline while the form is pending.

## Gatekeeper killing pyenv's Python (exit 137, no error output)
If a script (e.g. `bedrock_smoke.py`) just dies silently — no traceback, no output, exit code
**137 (SIGKILL)** — it's not a boto3/network issue. It's macOS Gatekeeper rejecting the pyenv-built
Python binary at launch, before the interpreter can even print `--version`. Confirm with:
```
spctl -a -vv ~/.pyenv/versions/<version>/bin/python3.13   # "rejected" = confirmed
```
Fix (harmless, standard for ad-hoc-signed dev tools):
```
codesign --sign - --force --deep ~/.pyenv/versions/<version>/bin/python3.13
```
This can recur after pyenv reinstalls that Python version or after a macOS update re-evaluates
signatures. `/usr/bin/python3` (Apple's system Python) is unaffected — only pyenv-built interpreters
(and venvs symlinked to them) hit this.

## AgentCore deploy: use `deploy --local-build`, NOT the default CodeBuild path
The training user **can't create IAM roles**, which fights the auto-provisioning deploy tools:
- The **npm** `agentcore` CLI (`@aws/agentcore`, may be on PATH via nvm) deploys via **CDK** → needs
  `cdk bootstrap` (creates roles/stacks) → blocked. **Avoid it.**
- The **pip** `bedrock-agentcore-starter-toolkit` gives a venv-local `agentcore` (`configure` /
  `deploy` (formerly `launch`) / `invoke` / `status` / `destroy`) that lets you **pass** a pre-made
  role via `--execution-role`. The activated venv's `agentcore` shadows the npm one — confirm with
  `which agentcore`.
- Even the toolkit's **default** `deploy` (CodeBuild) auto-creates a *CodeBuild* service role → also
  blocked. Use **`agentcore deploy --local-build`**: builds the ARM64 image with local Docker, pushes
  to ECR, and creates the runtime directly (no CodeBuild role). Needs: Docker daemon running + ECR
  push perms (now in `training-policy.json`, Sid `EcrForAgentImagePushLocalBuild`) + the
  admin-created runtime execution role (`iam/agentcore-trust-policy.json` for the trust relationship +
`iam/agentcore-permissions-policy.json` inline — both pure ASCII; a wrapper file with a `_README`
em-dash previously tripped the console's "printable ASCII only" check on the trust policy).

IAM the training user needs for the deploy (all now in `iam/training-policy.json`), learned the hard
way — each surfaced as a separate `AccessDeniedException`:
- `bedrock-agentcore:*` — for `CreateAgentRuntime` (NOT covered by `AmazonBedrockFullAccess`; that's
  `bedrock:*`, a different service prefix).
- `iam:PassRole` to `bedrock-agentcore.amazonaws.com` — to hand the execution role to the runtime.
- ECR push (Sid `EcrForAgentImagePushLocalBuild`) — for `--local-build`.
- `iam:CreateServiceLinkedRole` scoped to `bedrock-agentcore.amazonaws.com` — the FIRST
  `CreateAgentRuntime` in an account auto-creates an AgentCore service-linked role. Scoped SLR
  creation is safe (AWS-predefined, non-escalating), so it's OK despite the no-role-creation rule.
- OPTIONAL, not added: `logs:PutResourcePolicy` + `logs:PutDeliverySource` enable full X-Ray
  "Transaction Search" GenAI-observability traces. Without them deploy still succeeds and basic
  CloudWatch logs work — you just get a non-fatal warning and no trace dashboard.

Two paste gotchas when creating these in the console: (1) IAM identity policies reject a top-level
`"Comment"` key — `training-policy.json` had one and it silently blocked the paste (removed now).
(2) The training user has no IAM read/console login, so add these as **inline policies** on the user.

Working recipe (verified 2026-07, deployed runtime `agentcore_agent-q7lyFLBY8y`): local test with
`python agentcore_agent.py` + curl
`localhost:8080/invocations`; then `agentcore configure -e agentcore_agent.py --execution-role <arn>`
→ `agentcore deploy --local-build` → `agentcore status`. Entry point import is
`from bedrock_agentcore.runtime import BedrockAgentCoreApp`. Terraform equivalent
(`aws_bedrockagentcore_agent_runtime`) lives in `terraform/` and **reuses** the toolkit's ECR image
(Terraform can't build containers).

## Gateway + MCP-server-on-Runtime + Evaluations (verified 2026-07, the hard way)
End-to-end stack that works: MCP server on Runtime  ← (SigV4) ←  Gateway  ← (Cognito OAuth) ←  Strands
agent. Files: `mcp_server/`, `gateway/{setup_gateway.py,gateway_agent.py}`, `evals/run_evals.sh`.
Gotchas that each cost a round-trip — check these FIRST:
- **Nova breaks on hyphens in tool names.** `mcp-runtime-target___get_weather` → `modelStreamError:
  Model produced invalid sequence as part of ToolUse`; `mcpRuntime___get_weather` works. Gateway
  namespaces tools as `{targetName}___{tool}`, and the target-name regex `([0-9a-zA-Z][-]?){1,100}`
  forbids underscores — so use a single-word camelCase target name (e.g. `mcpRuntime`), never hyphens.
- **nova-micro can't tool-use reliably** (same invalid-ToolUse error even with one tool). Use
  **nova-lite**+ for any real tool calling; keep micro only for trivial/no-tool agents. Also broaden
  the exec role's bedrock resource to `foundation-model/amazon.nova-*` or it AccessDenies the new model.
- **A deployable agent's `__main__` MUST call `app.run()` when run with no args.** The container runs
  `python agent.py` (no args); if `__main__` does a local CLI test and exits, the server never starts →
  `RuntimeClientError: error when starting the runtime` (and stale success logs mislead you).
- **MCP server on Runtime:** `agentcore configure --protocol MCP` (default IAM inbound, no OAuth).
  Add it to the Gateway with **boto3** `create_gateway_target` (the toolkit helper only does
  lambda/openApi/smithy): `targetConfiguration.mcp.mcpServer.endpoint` = the runtime MCP invocation URL,
  `credentialProviderConfigurations=[{credentialProviderType: GATEWAY_IAM_ROLE, ...iamCredentialProvider}]`.
- **Gateway inbound auth = Cognito**, auto-provisioned by `GatewayClient.create_oauth_authorizer_with_cognito`
  (needs `cognito-idp:*` on the user). The deployed agent mints its own token via **client-credentials**
  (scope `<resourceServer>/invoke`) from env vars — see `gateway_agent.py`.
- **Evaluations** (`agentcore eval run --evaluator Builtin.Correctness|Faithfulness|ToolSelectionAccuracy`)
  read spans from CloudWatch. Prereqs: enable **Transaction Search** (console, account-level) + grant the
  user `logs:StartQuery`/`StopQuery`/`GetQueryResults` on `aws/spans`. The per-deploy
  "Access Denied for this Delivery Destination" / `xray:UpdateTraceSegmentDestination` warnings are
  **non-fatal** — spans still land via account-level Transaction Search.
- Admin (can't-create-roles) additions this needed: a **Gateway service role** (`iam/gateway-*.json`),
  broadened exec-role model resource, and several user-policy grants (Cognito, log delivery, span query)
  — all now in `iam/training-policy.json`. Inline policies cap at 2048 non-ws chars → use a **managed**
  policy (6144); a top-level `"Comment"` key makes IAM reject the paste.

## Entra ID OAuth + RBAC across the stack (verified 2026-07, MANY round-trips)
Full flow that works: front-end (MSAL) → DataPower shim → Agent on Runtime → Gateway → 3 MCP servers,
all Entra-JWT-secured, with role/scope RBAC. Files: `frontend/`, `datapower/shim.py`, `gateway/`,
`entra/.env`, `run_frontend.sh`, `rebuild_entra_stack.sh`. Every gotcha below cost a round-trip:

- **One Entra app can be BOTH the SPA client and the API resource** (SPA_CLIENT_ID == API_CLIENT_ID).
  Expose an API (`mcp.invoke` scope) + App roles (`Tools.Reader`/`Tools.Admin`) + a client secret + SPA
  redirect `https://localhost:5173` all on one registration. Assign yourself the role via **Enterprise
  applications → Users and groups** (App registrations only *defines* roles; assignment is separate).
- **This app issues v1.0 tokens** (`iss=sts.windows.net/4b7f45a9-xxxx-xxxx-xxxx-xxxxxxxxxxxx/`, `aud=api://c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, `ver:1.0`) even
  with the v2 manifest flag — so use the **v1 discovery URL** (`.../4b7f45a9-xxxx-xxxx-xxxx-xxxxxxxxxxxx/.well-known/openid-configuration`,
  NO `/v2.0`) and `allowedAudience=[api://c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx, c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx]`.
- **DO NOT set `allowedClients` with Entra v1 tokens.** The authorizer validates it against a `client_id`
  claim, but Entra v1 puts the client in **`appid`** (no `client_id`) → Runtime rejects with 401
  "Claim 'client_id' value mismatch"; Gateway rejects with 403 **"insufficient_scope"** (same cause,
  misleading label). Validate on `allowedAudience` (+ `allowedScopes`) only.
- **`allowedScopes` DOES work** (reads the `scp` claim, short name e.g. `["mcp.invoke"]`). Layered RBAC:
  **Gateway** gates on audience+scope (coarse "may use gateway"); the **agent** gates on the `roles`
  claim (fine, per-tool — the admin-only `magic_8ball`). Enforced in code (`gateway_agent.py::_rbac`).
- **The Runtime STRIPS the `Authorization` header** after the JWT authorizer validates it — the container
  never sees the bearer token. So the shim passes the token **in the request body** (`_user_token`) and
  the agent reads it from `payload` (with a `context.request_headers` fallback) for RBAC + forwarding.
- **Container build context = the entrypoint's own dir.** `from common.tokentap import …` → 
  `ModuleNotFoundError` → "error when starting the runtime". Inline helpers into the agent file.
- **`UpdateGateway` can change the authorizer in place** (keeps URL + targets, no agent redeploy) — pass
  `name, roleArn, authorizerType=CUSTOM_JWT, authorizerConfiguration, protocolType, protocolConfiguration`.
- **OBO / DataPower exchange (works single-app, with the right scope)**: OBO-to-self needs three things,
  each of which fails loudly if wrong: (1) the **GUID** resource, not the `api://` URI (AADSTS90009);
  (2) **admin consent** on the app's API permissions (else AADSTS65001); (3) request the **specific
  scope** `c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx/mcp.invoke` — NOT `c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx/.default`, because `.default` resolves to the app's
  Graph `User.Read` perm and the exchanged T2 then fails the gateway's `allowedScopes:[mcp.invoke]` gate
  (403). With `c1a0c3f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx/mcp.invoke` the T2 carries `scp:"User.Read mcp.invoke"` (aud=GUID,
  `appidacr:1` = confidential) and the gateway accepts it → `MODE=exchange` works end-to-end. Real
  DataPower exchanges for a *different downstream audience*; a second Entra app is cleaner but the
  single-app self-exchange demonstrates the two-token flow fine. `MODE=passthrough` forwards T1 unchanged.
- **Front-end gotchas**: the MSAL CDN is often blocked on corp nets (404) → **bundle it locally**
  (`frontend/msal-browser.min.js`). Corp tenants require **https** redirect URIs → serve over TLS.
  **Safari** fights self-signed certs + fetch — use **Chrome/Edge**. Serve the SPA *from the shim* on one
  https origin (`run_frontend.sh`, port 5173) → no CORS, no mixed content, matches the redirect URI.
- **Device-code flow won't work** here (the app has a secret → confidential client → AADSTS7000218). Use
  the SPA + PKCE browser flow (public client, no secret needed).

## Permissions (attached to `aws-training`)
- AWS-managed **`AmazonBedrockFullAccess`** (models / agents / knowledge bases).
- Custom **`iam/training-policy.json`** — `bedrock-agentcore:*`, scoped `iam:PassRole` (to
  bedrock/agentcore/lambda only), CloudWatch Logs.

## Files
| file | what |
|---|---|
| `README.md` | operator-facing setup guide (identity → policies → model access → budget → run) |
| `iam/training-policy.json` | the custom IAM policy to attach |
| `bedrock_smoke.py` | `AWS_PROFILE=training python bedrock_smoke.py` — lists models (access check) + a Converse example |
| `strands_agent.py` | minimal tool-using Strands agent on Bedrock (`from strands import Agent, tool`) |
| `agentcore_agent.py` | same agent wrapped in `BedrockAgentCoreApp` — deployable to AgentCore Runtime |
| `iam/agentcore-trust-policy.json` + `iam/agentcore-permissions-policy.json` | the admin-created runtime execution role (trust + inline perms; pure ASCII) |
| `terraform/` | the runtime as IaC (`aws_bedrockagentcore_agent_runtime`, reuses the toolkit's image) |
| `requirements.txt` | `boto3`, `strands-agents`, `strands-agents-tools`, `bedrock-agentcore(+starter-toolkit)` |

## Working notes for the agent
- **Strands** reads `AWS_PROFILE` for its Bedrock backend (no extra creds). Docs:
  https://strandsagents.com — APIs evolve; verify current signatures + **model IDs** (they change) via
  `aws bedrock list-foundation-models` rather than trusting a hardcoded id.
- **AgentCore** (`bedrock-agentcore`) is the managed agent runtime (Runtime / Memory / Gateway /
  Identity / Tools); it's new + moving fast — lean on current AWS docs for deploy flows.
- Use the **Converse API** (model-agnostic) over raw `invoke_model` unless a feature needs otherwise.
- This is a git-safe dir but **not necessarily a git repo yet** — check before assuming; if you
  `git init`, the `.gitignore` already protects secrets.
- Keep this file current: if you learn a gotcha, a working model id, or an AgentCore deploy recipe,
  add it here so the next agent doesn't rediscover it.
