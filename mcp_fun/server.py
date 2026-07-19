"""Silly 'fun' MCP server — deployable to AgentCore Runtime (protocol=MCP).

Registered as Gateway target `funTools`. See mcp_dice/server.py for the pattern/notes.

Local test:  python mcp_fun/server.py
"""
import random

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

_FACTS = [
    "Honey never spoils.", "Octopuses have three hearts.",
    "Bananas are berries; strawberries are not.", "A group of flamingos is a 'flamboyance'.",
    "Wombat poop is cube-shaped.",
]


@mcp.tool()
def to_pig_latin(text: str) -> dict:
    """Translate text to Pig Latin."""
    out = []
    for w in text.split():
        if not w.isalpha():
            out.append(w); continue
        if w[0].lower() in "aeiou":
            out.append(w + "way")
        else:
            i = next((k for k, c in enumerate(w) if c.lower() in "aeiou"), len(w))
            out.append(w[i:] + w[:i] + "ay")
    return {"input": text, "pig_latin": " ".join(out)}


@mcp.tool()
def mock_case(text: str) -> dict:
    """SpOnGeBoB-style alternating case."""
    return {"mocked": "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))}


@mcp.tool()
def random_fact() -> dict:
    """Return a random fun fact."""
    return {"fact": random.choice(_FACTS)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
