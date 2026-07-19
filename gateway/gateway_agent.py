"""Strands agent on AgentCore Runtime — Entra-authenticated, RBAC-enforcing.

Inbound: the Runtime's JWT authorizer (Microsoft Entra) validates the caller's token before this
code runs. Here we ALSO read that token from the request context to:
  1. print its claims (so you can see aud/scp/roles at this hop), and
  2. enforce RBAC — filter which tools the agent may use based on scopes/roles, and
  3. forward the SAME token to the Gateway (whose authorizer is also Entra).

RBAC model (matches the Entra app):
  - scope `mcp.invoke` OR role `Tools.Reader`/`Tools.Admin`  -> may use read tools
  - role `Tools.Admin`                                       -> may ALSO use the admin tool (magic_8ball)

Env (set at deploy): GATEWAY_URL. Local test: pass a token file via TOKEN_FILE + gateway_info.json.
"""
import base64
import json
import os
import sys

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client


# Inlined JWT decode (no signature verify — the Runtime authorizer already validated the token).
# Kept self-contained so the container build context (gateway/) needs no ../common.
def claims(token: str) -> dict:
    try:
        t = token[7:] if token.lower().startswith("bearer ") else token
        seg = t.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    except Exception:  # noqa: BLE001
        return {}


def tap(label: str, token: str) -> dict:
    c = claims(token)
    print(f"\n=== {label} ===")
    for k in ("iss", "aud", "appid", "scp", "roles", "name", "exp"):
        if k in c:
            print(f"  {k}: {c[k]}")
    return c

REGION = os.environ.get("AWS_REGION", "us-east-1")
INFO_PATH = os.path.join(os.path.dirname(__file__), "gateway_info.json")
ADMIN_TOOL_MARKER = "magic_8ball"   # the one tool gated behind Tools.Admin


# ---- local tool (kept, to show local + gateway tools mixed) ----
@tool
def catalog_price(item: str) -> dict:
    """Look up a local catalog item's price."""
    return {"apple": 0.50, "banana": 0.25, "cherry": 2.00}.get(item.lower().strip(), {"error": "not in catalog"})


def _rbac(c: dict) -> dict:
    """Decide access from token claims."""
    scp = set((c.get("scp") or "").split())
    roles = set(c.get("roles") or [])
    can_read = bool({"mcp.invoke"} & scp) or bool({"Tools.Reader", "Tools.Admin"} & roles)
    can_admin = "Tools.Admin" in roles
    return {"scp": sorted(scp), "roles": sorted(roles), "can_read": can_read, "can_admin": can_admin}


def _gateway_url() -> str:
    return os.environ.get("GATEWAY_URL") or json.load(open(INFO_PATH))["gateway_url"]


def _answer(prompt: str, token: str) -> dict:
    c = claims(token) if token else {}
    tap("AGENT hop — token received from shim/front-end", token or "(none)")
    rb = _rbac(c)
    print(f"RBAC decision: {rb}")

    if not rb["can_read"]:
        return {"denied": True, "reason": "token lacks scope 'mcp.invoke' or a Tools.* role", "claims": rb}

    # Forward the SAME Entra token to the Gateway (its authorizer is also Entra).
    mcp_client = MCPClient(lambda: streamablehttp_client(_gateway_url(),
                                                         headers={"Authorization": f"Bearer {token}"}))
    with mcp_client:
        gateway_tools = mcp_client.list_tools_sync()
        allowed = []
        for t in gateway_tools:
            name = getattr(t, "tool_name", "")
            if "x_amz_bedrock_agentcore_search" in name:
                continue                                   # gateway's search tool trips up Nova
            if ADMIN_TOOL_MARKER in name and not rb["can_admin"]:
                continue                                   # RBAC: hide admin tool from non-admins
            allowed.append(t)
        print(f"Tools exposed to model ({len(allowed)}): {[getattr(t,'tool_name','') for t in allowed]}")

        agent = Agent(
            model=BedrockModel(model_id="amazon.nova-lite-v1:0"),
            tools=[catalog_price, *allowed],
            system_prompt=("You are an assistant with local + gateway tools. Use tools, be concise. "
                           "If asked to do something you have no tool for, say you're not permitted."),
        )
        return {"denied": False, "claims": rb, "result": str(agent(prompt))}


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    # The Runtime authorizer validates the bearer token but strips the Authorization header before the
    # container, so we read the token from the body (the shim puts it there). Header is a fallback.
    token = payload.get("_user_token", "")
    if not token:
        headers = getattr(context, "request_headers", None) or {}
        auth = headers.get("Authorization") or headers.get("authorization") or ""
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
    return _answer(payload.get("prompt", "what can you do?"), token)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Local test: token from TOKEN_FILE env (a saved Entra access token), prompt from argv.
        tok = open(os.environ["TOKEN_FILE"]).read().strip() if os.environ.get("TOKEN_FILE") else ""
        print(json.dumps(_answer(sys.argv[1], tok), indent=2))
    else:
        app.run()
