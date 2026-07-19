"""tokentap — decode + pretty-print a JWT at every hop, so you can SEE tokens/headers end-to-end.

Stdlib only (no deps), so it works locally, in the DataPower shim, AND inside the deployed agent
container. It does NOT verify signatures — it's for *observing* the token, not trusting it (the
AgentCore authorizer does the real validation against Entra's keys).

    from common.tokentap import tap, claims
    tap("T1 (front-end -> shim)", bearer_token)      # prints header + key claims
    c = claims(bearer_token)                          # dict of the payload claims
"""
import base64
import json
from typing import Any


def _b64url(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _parts(token: str):
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:]
    header, payload, _sig = token.split(".")
    return json.loads(_b64url(header)), json.loads(_b64url(payload))


def claims(token: str) -> dict[str, Any]:
    """Return the JWT payload (claims) as a dict."""
    return _parts(token)[1]


# The claims most worth seeing for this exercise.
KEY = ["iss", "aud", "appid", "azp", "tid", "ver", "scp", "roles", "name",
       "preferred_username", "oid", "exp"]


def tap(label: str, token: str, *, full: bool = False) -> dict:
    """Pretty-print a token's header + key claims under `label`. Returns the claims dict."""
    try:
        header, payload = _parts(token)
    except Exception as e:  # noqa: BLE001
        print(f"\n=== {label} ===\n  <not a JWT: {e}>  raw[:40]={token[:40]!r}")
        return {}
    print(f"\n=== {label} ===")
    print(f"  header: alg={header.get('alg')} kid={header.get('kid','')[:12]} typ={header.get('typ')}")
    shown = payload if full else {k: payload[k] for k in KEY if k in payload}
    for k, v in shown.items():
        print(f"  {k}: {v}")
    # highlight the RBAC-relevant claims explicitly
    print(f"  --> scp (delegated scopes): {payload.get('scp', '(none)')}")
    print(f"  --> roles (app roles):      {payload.get('roles', '(none)')}")
    return payload


if __name__ == "__main__":  # quick self-test with a fake token
    import sys
    if len(sys.argv) > 1:
        tap("token", sys.argv[1], full=True)
