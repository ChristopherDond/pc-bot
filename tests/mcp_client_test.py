import asyncio
import shutil
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # resolve o executavel instalado no venv ativo em vez de um path fixo
    # de uma maquina especifica (o hardcoded C:\Users\user\... so funcionava
    # pra quem instalou exatamente nesse caminho).
    command = shutil.which("pcbot-mcp") or sys.executable
    args = [] if shutil.which("pcbot-mcp") else ["-m", "pcbot.mcp_server"]
    args += ["--browser"]
    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [getattr(t, "name", t) for t in tools.tools])
            result = await session.call_tool("get_state", {})
            print("get_state:", str(result)[:200])

asyncio.run(main())