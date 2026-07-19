"""Sample MCP server, deployable to AgentCore Runtime (protocol=MCP).

AgentCore Runtime serves MCP servers at 0.0.0.0:8000/mcp (the FastMCP default). Deployed with
default IAM (SigV4) inbound auth — no OAuth authorizer — so the AgentCore Gateway can invoke it
outbound via SigV4.

Local test:
    python mcp_server/mcp_server.py            # serves http://localhost:8000/mcp
    python mcp_server/local_client.py          # lists + calls the tools

Deploy (see README section 7):
    cd mcp_server
    agentcore configure -e mcp_server.py --protocol MCP \
      --execution-role arn:aws:iam::21730xxxxxxx:role/AgentCoreTrainingExecRole \
      --region us-east-1 --disable-memory --deployment-type container --non-interactive
    agentcore deploy --local-build
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

# A tiny fake weather DB so tool calls are deterministic (good for eval Correctness/Groundedness).
_WEATHER = {
    "seattle": {"tempC": 14, "sky": "rain"},
    "phoenix": {"tempC": 39, "sky": "clear"},
    "denver":  {"tempC": 22, "sky": "partly cloudy"},
}
_RATES_TO_USD = {"usd": 1.0, "eur": 1.08, "gbp": 1.27, "jpy": 0.0064}


@mcp.tool()
def get_weather(city: str) -> dict:
    """Get current weather for a supported city (seattle, phoenix, denver)."""
    return _WEATHER.get(city.lower().strip(), {"error": f"no weather for '{city}'"})


@mcp.tool()
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert an amount between currencies (usd, eur, gbp, jpy)."""
    f, t = from_currency.lower().strip(), to_currency.lower().strip()
    if f not in _RATES_TO_USD or t not in _RATES_TO_USD:
        return {"error": "supported: usd, eur, gbp, jpy"}
    usd = amount * _RATES_TO_USD[f]
    return {"amount": round(usd / _RATES_TO_USD[t], 4), "currency": t.upper()}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
