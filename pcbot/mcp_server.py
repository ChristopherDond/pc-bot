

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import AgentDesktop
    from .browser import BrowserLayer

log = logging.getLogger("pcbot.mcp")


def create_server(agent: "AgentDesktop", browser: "BrowserLayer | None" = None):
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
    def click(name: str = "", x: int = -1, y: int = -1, confirmed: bool = False) -> str:
        """Clica num elemento pelo nome (UIA, camada A) ou por coordenada
        (fallback pixel, camada C). Cliques por coordenada exigem confirmed=true
        — sao o nivel de confianca mais baixo e nao devem ser disparados sem
        o usuario/agente confirmar explicitamente a acao."""
        if x >= 0 and y >= 0:
            result = agent.click(x=x, y=y, confirm=(lambda _r: confirmed))
        else:
            result = agent.click(name=name or None)
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
            """Clica num elemento pelo ref do DOM (camada B)."""
            result = agent.click(ref=ref) if agent is not None else browser.click(ref)
            return json.dumps(result, ensure_ascii=False)

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
    import threading

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="pc-bot MCP server")
    parser.add_argument("--browser", action="store_true", help="ativa a camada browser CDP")
    parser.add_argument("--channel", default="msedge", help="canal do navegador (msedge/chrome)")
    parser.add_argument("--verbose", action="store_true", help="logging em nivel DEBUG")
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger("pcbot").setLevel(logging.DEBUG)

    from .agent import AgentDesktop
    from .overlay import CursorOverlay

    overlay = CursorOverlay()
    state = {}

    def _init_worker():
        try:
            overlay.start()
            browser = None
            if args.browser:
                from .browser import BrowserLayer

                browser = BrowserLayer(channel=args.channel, overlay=overlay)
                start_result = browser.start()
                if not start_result.get("ok"):
                    log.error("camada browser nao pode ser iniciada: %s", start_result.get("error"))
                    browser = None
            state["agent"] = AgentDesktop(overlay=overlay, browser=browser)
            state["browser"] = browser
        except Exception:
            log.exception("falha ao inicializar o pc-bot")

    worker = threading.Thread(target=_init_worker, daemon=True)
    worker.start()
    worker.join(timeout=30)

    agent = state.get("agent")
    if agent is None:
        raise RuntimeError("falha ao inicializar o agente (veja o log acima para a causa)")
    browser = state.get("browser")

    mcp = create_server(agent, browser)
    try:
        mcp.run()
    finally:
        agent.close()


if __name__ == "__main__":
    main()
