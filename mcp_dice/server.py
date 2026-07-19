"""Silly 'dice' MCP server — deployable to AgentCore Runtime (protocol=MCP).

Same pattern as mcp_server/mcp_server.py. Deployed with default IAM (SigV4) inbound so the Gateway
reaches it via SigV4; registered as Gateway target `diceTools` (camelCase, hyphen-free — Nova breaks
on hyphenated tool names, see CLAUDE.md).

Local test:  python mcp_dice/server.py   then a streamable-http MCP client on :8000/mcp
"""
import random

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

_8BALL = [
    "It is certain.", "Ask again later.", "Don't count on it.",
    "Yes, definitely.", "My reply is no.", "Outlook good.", "Very doubtful.",
]


@mcp.tool()
def roll_dice(sides: int = 6, count: int = 1) -> dict:
    """Roll `count` dice each with `sides` sides. Returns each roll and the total."""
    sides = max(2, min(int(sides), 1000))
    count = max(1, min(int(count), 100))
    rolls = [random.randint(1, sides) for _ in range(count)]
    return {"sides": sides, "count": count, "rolls": rolls, "total": sum(rolls)}


@mcp.tool()
def flip_coin() -> dict:
    """Flip a fair coin."""
    return {"result": random.choice(["heads", "tails"])}


@mcp.tool()
def magic_8ball(question: str) -> dict:
    """Ask the magic 8-ball a yes/no question (admin-gated in the RBAC demo)."""
    return {"question": question, "answer": random.choice(_8BALL)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
