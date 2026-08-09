"""Integracao com o MCP: expoe o pc-bot como ferramentas para agentes.

Registra as acoes do AgentDesktop (click, type, find, screenshot, dom,
goto) como tools MCP, que qualquer agente com um client MCP pode chamar.
"""

import json
from .agent import AgentDesktop
from .overlay import CursorOverlay
from .browser import BrowserLayer


def create_server(agent: AgentDesktop, browser: BrowserLayer | None = None):
    """Monta um servidor MCP com as ferramentas do pc-bot."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("pc-bot")

    @mcp.tool()
    def screenshot(name: str = "screen") -> str:
        """Captura a tela atual e devolve o caminho da imagem."""
        result = agent.screenshot(name)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def get_state() -> str:
        """Lista janelas e plugins disponiveis no desktop."""
        return json.dumps(agent.get_state(), ensure_ascii=False)

    @mcp.tool()
    def click(name: str = "", x: int = -1, y: int = -1) -> str:
        """Clica num elemento pelo nome (UIA) ou por coordenada."""
        if x >= 0 and y >= 0:
            result = agent.click(x=x, y=y)
        else:
            result = agent.click(name=name)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def type_text(text: str, name: str = "") -> str:
        """Digita texto num campo (por nome UIA) ou na janela ativa."""
        result = agent.type_text(text, name=name or None)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def find(name: str = "", ctrl_type: str = "") -> str:
        """Busca elementos nativos por nome ou tipo."""
        result = agent.find(name=name or None, ctrl_type=ctrl_type or None)
        return json.dumps(result, ensure_ascii=False)

    if browser is not None:
        @mcp.tool()
        def browser_goto(url: str) -> str:
            """Navega o navegador para uma URL."""
            return json.dumps(browser.goto(url), ensure_ascii=False)

        @mcp.tool()
        def browser_dom() -> str:
            """Le a arvore DOM interativa da pagina atual."""
            return json.dumps(browser.get_dom(), ensure_ascii=False)

        @mcp.tool()
        def browser_click(ref: str) -> str:
            """Clica num elemento pelo ref do DOM."""
            return json.dumps(browser.click(ref), ensure_ascii=False)

        @mcp.tool()
        def browser_type(ref: str, text: str) -> str:
            """Digita texto num campo pelo ref do DOM."""
            return json.dumps(browser.type_text(ref, text), ensure_ascii=False)

        @mcp.tool()
        def browser_text() -> str:
            """Le o texto visivel da pagina atual."""
            return json.dumps(browser.get_text(), ensure_ascii=False)

    return mcp


def main():
    import argparse

    parser = argparse.ArgumentParser(description="pc-bot MCP server")
    parser.add_argument("--browser", action="store_true", help="ativa a camada browser CDP")
    parser.add_argument("--channel", default="msedge", help="canal do navegador (msedge/chrome)")
    args = parser.parse_args()

    overlay = CursorOverlay()
    overlay.start()
    agent = AgentDesktop(overlay=overlay)
    browser = None
    if args.browser:
        browser = BrowserLayer(channel=args.channel, overlay=overlay)
        browser.start()
    mcp = create_server(agent, browser)
    try:
        mcp.run()
    finally:
        browser.close() if browser else None
        agent.close()


if __name__ == "__main__":
    main()