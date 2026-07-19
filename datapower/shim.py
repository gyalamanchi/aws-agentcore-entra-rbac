"""Local stand-in for the DataPower token-exchange gateway.

Sits inline: front-end -> THIS SHIM -> Agent on AgentCore Runtime. It receives the user's Entra token
(T1), optionally exchanges it for a downstream token (T2) via Entra On-Behalf-Of, and forwards the
request to the deployed agent's Runtime invocation URL. It prints BOTH tokens so you can see exactly
what DataPower would do.

MODE (env, default = exchange):
  exchange     -> real Entra OBO: swap T1 (aud=API app) for T2 (a fresh Entra-signed token). This is
                  the two-token pattern DataPower performs. At $WORK, point OBO at the real downstream
                  audience; here we reuse the API app so the Gateway/Runtime still validate T2.
  passthrough  -> forward T1 unchanged (DataPower as a no-op proxy).

Run:  (fill entra/.env + set AGENT_ARN after the agent is deployed)
  export $(grep -v '^#' entra/.env | xargs) && export AGENT_ARN=arn:aws:bedrock-agentcore:...:runtime/gateway_agent-XXXX
  uvicorn datapower.shim:app --port 8080 --reload
"""
import json
import os
import sys
import urllib.parse

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.tokentap import tap, claims  # noqa: E402

MODE = os.environ.get("MODE", "exchange")            # DEFAULT: exchange
REGION = os.environ.get("AWS_REGION", "us-east-1")
TENANT = os.environ.get("TENANT_ID", "")
API_CLIENT_ID = os.environ.get("API_CLIENT_ID", "")
API_CLIENT_SECRET = os.environ.get("API_CLIENT_SECRET", "")
# OBO target scope: request the SPECIFIC mcp.invoke scope (not .default, which resolves to the app's
# Graph User.Read perm and fails the gateway's scope gate). Use the GUID app-id (NOT the api:// URI) —
# Entra only allows a token-for-itself exchange with the GUID-based identifier (AADSTS90009).
OBO_SCOPE = os.environ.get("OBO_SCOPE", f"{API_CLIENT_ID}/mcp.invoke")
AGENT_ARN = os.environ.get("AGENT_ARN", "")
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"

app = FastAPI(title="DataPower shim")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _agent_url() -> str:
    enc = AGENT_ARN.replace(":", "%3A").replace("/", "%2F")
    return f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{enc}/invocations?qualifier=DEFAULT"


async def _obo_exchange(user_token: str) -> dict:
    """Entra On-Behalf-Of: exchange the user's token for a downstream token (T2)."""
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "client_id": API_CLIENT_ID,
        "client_secret": API_CLIENT_SECRET,
        "assertion": user_token,
        "scope": OBO_SCOPE,
        "requested_token_use": "on_behalf_of",
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data=data)
    return {"status": r.status_code, "body": r.json()}


def _probe_gateway(token: str) -> dict:
    """DIAGNOSTIC: call the gateway directly with the token to capture its raw accept/reject."""
    try:
        gw_url = json.load(open(os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                             "gateway", "gateway_info.json")))["gateway_url"]
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "probe", "version": "1"}}})
        r = httpx.post(gw_url, content=body, timeout=30, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
        return {"gateway_status": r.status_code,
                "www_authenticate": r.headers.get("www-authenticate"), "body": r.text[:400]}
    except Exception as e:  # noqa: BLE001
        return {"probe_error": str(e)}


@app.get("/health")
def health():
    return {"mode": MODE, "agent_configured": bool(AGENT_ARN)}


@app.post("/invoke")
async def invoke(request: Request):
    body = await request.body()
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return JSONResponse({"error": "missing bearer token"}, status_code=401)
    t1 = auth[7:]

    print("\n" + "#" * 70 + f"\n# DataPower shim  (MODE={MODE})\n" + "#" * 70)
    tap("T1  front-end -> shim", t1)

    forward_token = t1
    exchanged = None
    if MODE == "exchange":
        res = await _obo_exchange(t1)
        if res["status"] == 200 and "access_token" in res["body"]:
            t2 = res["body"]["access_token"]
            tap("T2  shim -> agent (after Entra OBO)", t2)
            forward_token = t2
            exchanged = {"t2_claims": claims(t2)}
        else:
            # Surface Entra's error so you can see exactly what OBO needs (permissions/consent/aud).
            print("\n!!! OBO exchange failed — forwarding T1. Entra said:")
            print("   ", res["body"])
            exchanged = {"obo_error": res["body"]}

    if not AGENT_ARN:
        return JSONResponse({"note": "AGENT_ARN not set — token dance only",
                             "mode": MODE, "t1_claims": claims(t1), **(exchanged or {})})

    # The Runtime authorizer validates (and strips) the Authorization header, so it never reaches the
    # container. Also pass the token IN THE BODY so the agent can read claims for RBAC + forward it.
    try:
        fwd = json.loads(body) if body else {}
    except Exception:  # noqa: BLE001
        fwd = {}
    fwd["_user_token"] = forward_token
    fwd_body = json.dumps(fwd).encode()

    print(f"\n--> forwarding to agent: {_agent_url()}\n    Authorization: Bearer <{'T2' if forward_token!=t1 else 'T1'}> (+ token in body for the app)")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(_agent_url(), content=fwd_body,
                         headers={"Authorization": f"Bearer {forward_token}",
                                  "Content-Type": "application/json"})
    try:
        agent_resp = r.json()
    except Exception:  # noqa: BLE001
        agent_resp = {"raw": r.text}
    probe = _probe_gateway(forward_token)   # DIAGNOSTIC: show how the gateway sees this exact token
    print(f"\n[gateway probe] {probe}")
    return JSONResponse({"mode": MODE, "agent_status": r.status_code, "gateway_probe": probe,
                         "t1_claims": claims(t1), **(exchanged or {}), "agent_response": agent_resp})


# Serve the front-end from this same origin (https://localhost:5173) so there's no CORS / mixed-content
# and it matches the Entra SPA redirect URI. Mounted LAST so /invoke + /health take precedence.
_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
