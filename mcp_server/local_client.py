"""Local MCP client to smoke-test mcp_server.py before deploying.

    python mcp_server/mcp_server.py     # terminal 1
    python mcp_server/local_client.py   # terminal 2
"""
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    async with streamablehttp_client("http://localhost:8000/mcp", {}, timeout=30,
                                     terminate_on_close=False) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            result = await session.call_tool("get_weather", {"city": "seattle"})
            print("get_weather(seattle) ->", result.content[0].text)
            result = await session.call_tool("convert_currency",
                                             {"amount": 100, "from_currency": "usd", "to_currency": "eur"})
            print("convert_currency(100 usd->eur) ->", result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
