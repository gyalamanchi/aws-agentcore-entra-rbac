"""Create an AgentCore Gateway secured by Microsoft Entra ID, fronting our MCP servers on Runtime.

Inbound auth  = Entra custom JWT (discoveryUrl + allowedAudience + allowedClients from entra/.env)
Outbound auth = IAM SigV4 (gateway role) to each MCP-server-on-Runtime target

Usage:
  export AWS_PROFILE=training AWS_REGION=us-east-1
  export GATEWAY_ROLE_ARN=arn:aws:iam::21730xxxxxxx:role/AgentCoreGatewayRole
  # target runtime ARNs (from `agentcore status` in each server dir):
  export MCP_RUNTIME_ARN=...   DICE_RUNTIME_ARN=...   FUN_RUNTIME_ARN=...
  python gateway/setup_gateway.py create
  python gateway/setup_gateway.py verify      # uses a client-credentials app token to list tools
  python gateway/setup_gateway.py teardown
"""
import json
import os
import sys
from pathlib import Path

import boto3
import httpx
from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient

REGION = os.environ.get("AWS_REGION", "us-east-1")
INFO_PATH = Path(__file__).with_name("gateway_info.json")
ENV_PATH = Path(__file__).resolve().parent.parent / "entra" / ".env"

# Target name -> env var holding that MCP server's runtime ARN. Names are camelCase (hyphen-free) so
# gateway-namespaced tool names like `mcpRuntime___get_weather` don't break Nova (see CLAUDE.md).
TARGETS = {"mcpRuntime": "MCP_RUNTIME_ARN", "diceTools": "DICE_RUNTIME_ARN", "funTools": "FUN_RUNTIME_ARN"}


def entra() -> dict:
    d = {}
    for line in ENV_PATH.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            d[k.strip()] = v.split("#", 1)[0].strip()
    return d


def authorizer_config(e: dict) -> dict:
    # This Entra app issues v1.0 tokens (iss=sts.windows.net, aud=App ID URI). Use the v1 discovery URL
    # and accept the App ID URI as audience. To switch to v2.0: set the app's requestedAccessTokenVersion
    # to 2 (Manifest), then use discoveryUrl .../v2.0/... + allowedAudience=[API_CLIENT_ID].
    aud = list(dict.fromkeys([e["API_APP_ID_URI"], e["API_CLIENT_ID"]]))
    # NOTE: no allowedClients. The Runtime authorizer checks a `client_id` claim, but Entra v1 tokens
    # carry the client in `appid` (no client_id claim) -> "client_id value mismatch" 401. Validating on
    # audience alone already proves the token was minted for THIS app. (For v2 tokens with an `azp`
    # claim you could re-add allowedClients=[SPA_CLIENT_ID, API_CLIENT_ID].)
    # allowedScopes = the SHORT scope name as it appears in the Entra `scp` claim (e.g. "mcp.invoke",
    # not the full api:// URI). This is the coarse "may use the gateway at all" gate; fine-grained
    # per-tool RBAC is enforced in the agent via the `roles` claim.
    scope_short = e["API_SCOPE"].split("/")[-1]
    return {"customJWTAuthorizer": {
        "discoveryUrl": f"https://login.microsoftonline.com/{e['TENANT_ID']}/.well-known/openid-configuration",
        "allowedAudience": aud,
        "allowedScopes": [scope_short],
    }}


def _mcp_url(arn: str) -> str:
    enc = arn.replace(":", "%3A").replace("/", "%2F")
    return f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{enc}/invocations?qualifier=DEFAULT"


def _add_target(cp, gateway_id, name, arn):
    return cp.create_gateway_target(
        gatewayIdentifier=gateway_id, name=name,
        targetConfiguration={"mcp": {"mcpServer": {"endpoint": _mcp_url(arn), "listingMode": "DEFAULT"}}},
        credentialProviderConfigurations=[{
            "credentialProviderType": "GATEWAY_IAM_ROLE",
            "credentialProvider": {"iamCredentialProvider": {"service": "bedrock-agentcore", "region": REGION}}}],
    )["targetId"]


def create():
    e = entra()
    role_arn = os.environ["GATEWAY_ROLE_ARN"]
    gw = GatewayClient(region_name=REGION)

    print("Creating Entra-secured gateway...")
    gateway = gw.create_mcp_gateway(name="entra-gateway", role_arn=role_arn,
                                    authorizer_config=authorizer_config(e), enable_semantic_search=True)
    gid, url = gateway["gatewayId"], gateway["gatewayUrl"]

    cp = boto3.client("bedrock-agentcore-control", region_name=REGION)
    targets = {}
    for name, env_var in TARGETS.items():
        arn = os.environ.get(env_var)
        if not arn:
            print(f"  skip {name}: {env_var} not set"); continue
        targets[name] = _add_target(cp, gid, name, arn)
        print(f"  added target {name} -> {arn.split('/')[-1]}")

    INFO_PATH.write_text(json.dumps({"gateway_id": gid, "gateway_url": url, "targets": targets,
                                     "tenant_id": e["TENANT_ID"], "api_client_id": e["API_CLIENT_ID"]}, indent=2))
    print(f"\nSaved {INFO_PATH}\nGateway URL: {url}")


def app_token(e: dict) -> str:
    """Client-credentials (app-only) token for verification — has aud=API app + app roles, no scp."""
    r = httpx.post(f"https://login.microsoftonline.com/{e['TENANT_ID']}/oauth2/v2.0/token", data={
        "grant_type": "client_credentials", "client_id": e["API_CLIENT_ID"],
        "client_secret": e["API_CLIENT_SECRET"], "scope": f"api://{e['API_CLIENT_ID']}/.default"}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def verify():
    import asyncio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    sys.path.insert(0, str(ENV_PATH.parent.parent))
    from common.tokentap import tap

    e = entra()
    info = json.loads(INFO_PATH.read_text())
    token = app_token(e)
    tap("verify: client-credentials app token -> gateway", token)

    async def run():
        async with streamablehttp_client(info["gateway_url"], {"Authorization": f"Bearer {token}"},
                                         timeout=60, terminate_on_close=False) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                print("Tools via gateway:", [t.name for t in tools.tools])
    asyncio.run(run())


def teardown():
    info = json.loads(INFO_PATH.read_text())
    gw = GatewayClient(region_name=REGION)
    cp = boto3.client("bedrock-agentcore-control", region_name=REGION)
    for name, tid in info.get("targets", {}).items():
        try:
            cp.delete_gateway_target(gatewayIdentifier=info["gateway_id"], targetId=tid); print("deleted target", name)
        except Exception as ex:  # noqa: BLE001
            print("target delete:", ex)
    try:
        gw.delete_gateway(gateway_identifier=info["gateway_id"], skip_resource_in_use=True); print("deleted gateway")
    except Exception as ex:  # noqa: BLE001
        print("gateway delete:", ex)


if __name__ == "__main__":
    {"create": create, "verify": verify, "teardown": teardown}[sys.argv[1] if len(sys.argv) > 1 else "create"]()
