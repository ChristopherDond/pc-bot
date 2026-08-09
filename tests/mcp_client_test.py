import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command=r"C:\Users\user\pc-bot\.venv\Scripts\pcbot-mcp.exe",
        args=["--browser"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [getattr(t, "name", t) for t in tools.tools])
            result = await session.call_tool("get_state", {})
            print("get_state:", str(result)[:200])

asyncio.run(main())