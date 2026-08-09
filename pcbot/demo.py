

import os
import time

def run(demo_dir="screenshots/demo"):
    os.makedirs(demo_dir, exist_ok=True)

    print("== Demo pc-bot ==")
    print("1/4 Captura de estado (janelas) e screenshot...")
    from pcbot.agent import AgentDesktop
    from pcbot.overlay import CursorOverlay

    overlay = CursorOverlay(color=(0, 255, 200))
    overlay.start()
    agent = AgentDesktop(overlay=overlay, screenshots_dir=demo_dir)

    state = agent.get_state(limit_windows=8)
    print(f"   {len(state['windows'])} janelas encontradas")
    shot = agent.screenshot("1_estado")
    print(f"   screenshot -> {shot['path']}")

    print("2/4 Camada nativa (UIA): clique por elemento...")
    docs = agent.find(ctrl_type="Document")
    if docs and isinstance(docs, list) and len(docs) > 0:
        handle = docs[0]["handle"]
        click = agent.click(handle=handle)
        print(f"   clique A: {click}")
        typed = agent.type_text("pc-bot demo", handle=handle)
        print(f"   texto A: {typed}")
    else:
        print("   (nenhum campo Document aberto; pulando)")

    print("3/4 Camada browser (CDP): navegar + ler DOM...")
    try:
        from pcbot.browser import BrowserLayer

        browser = BrowserLayer(channel="msedge", headless=True, overlay=overlay)
        browser.start()
        browser.goto("https://example.com")
        dom = browser.get_dom(max_elements=20)
        print(f"   DOM: {len(dom.get('elements', []))} elementos interativos")
        browser.close()
    except Exception as exc:
        print(f"   browser indisponivel: {exc}")

    print("4/4 Camada pixel (fallback): clique por coordenada...")
    px = agent._pixel
    print(f"   click C: {px.click(640, 512)}")

    agent.screenshot("2_final")
    overlay.close()
    print(f"Done! Screenshots em {demo_dir}")

if __name__ == "__main__":
    run()