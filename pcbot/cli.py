"""CLI do pc-bot: inspecao, acoes e demo do cursor overlay."""

import argparse
import sys
import time


def _make_overlay_and_agent(no_overlay=False):
    from .agent import AgentDesktop
    from .overlay import CursorOverlay

    overlay = None
    if not no_overlay:
        overlay = CursorOverlay()
        overlay.start()
    return AgentDesktop(overlay=overlay)


def cmd_state(args):
    agent = _make_overlay_and_agent(no_overlay=True)
    state = agent.get_state(limit_windows=args.limit)
    for win in state["windows"]:
        print(f"[{win['type']}] {win['name']}  rect={win['rect']} handle={win['handle']}")
    print(f"\n{len(state['windows'])} janelas, {len(state['plugins'])} plugins")
    agent.close()


def cmd_find(args):
    agent = _make_overlay_and_agent(no_overlay=True)
    result = agent.find(name=args.name, ctrl_type=args.type)
    if isinstance(result, dict) and "error" in result:
        print(result["error"])
        sys.exit(1)
    for item in result:
        print(f"[{item['type']}] {item['name']}  rect={item['rect']} handle={item['handle']}")
    agent.close()


def cmd_click(args):
    agent = _make_overlay_and_agent()
    result = agent.click(name=args.name, x=args.x, y=args.y)
    print(result)
    agent.close()


def cmd_type(args):
    agent = _make_overlay_and_agent()
    result = agent.type_text(args.text, name=args.name or None)
    print(result)
    agent.close()


def cmd_screenshot(args):
    agent = _make_overlay_and_agent(no_overlay=True)
    result = agent.screenshot(name=args.name)
    print(result.get("path"))
    agent.close()


def cmd_demo(args):
    from .overlay import CursorOverlay

    overlay = CursorOverlay(color=(0, 255, 200))
    overlay.start()
    print("Demo do cursor overlay — movendo por 5 segundos...")
    w = 10
    for i in range(60):
        x = 100 + (i * 20) % 1000
        y = 100 + (i * 15) % 500
        overlay.teleport_to(x, y)
        time.sleep(0.1)
    overlay.close()
    print("Fim da demo.")


def main():
    parser = argparse.ArgumentParser(prog="pcbot", description="pc-bot: agentes de IA controlando o Windows")
    sub = parser.add_subparsers(dest="cmd")

    p_state = sub.add_parser("state", help="lista janelas abertas")
    p_state.add_argument("--limit", type=int, default=15)
    p_state.set_defaults(func=cmd_state)

    p_find = sub.add_parser("find", help="busca elementos nativos")
    p_find.add_argument("--name", default="")
    p_find.add_argument("--type", default="")
    p_find.set_defaults(func=cmd_find)

    p_click = sub.add_parser("click", help="clica em elemento por nome ou coordenada")
    p_click.add_argument("--name", default="")
    p_click.add_argument("--x", type=int, default=-1)
    p_click.add_argument("--y", type=int, default=-1)
    p_click.set_defaults(func=cmd_click)

    p_type = sub.add_parser("type", help="digita texto")
    p_type.add_argument("text")
    p_type.add_argument("--name", default="")
    p_type.set_defaults(func=cmd_type)

    p_shot = sub.add_parser("screenshot", help="captura a tela")
    p_shot.add_argument("--name", default="screen")
    p_shot.set_defaults(func=cmd_screenshot)

    p_demo = sub.add_parser("demo", help="mostra o cursor overlay animado")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()