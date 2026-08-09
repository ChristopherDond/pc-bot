

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_overlay():
    from pcbot.overlay import CursorOverlay

    o = CursorOverlay()
    o.start()
    o.teleport_to(300, 200)
    o.move_to(400, 300)
    time.sleep(0.3)
    o.hide()
    o.close()
    print("✔ overlay OK")

def test_native():
    from pcbot.agent import AgentDesktop

    a = AgentDesktop()
    state = a.get_state(limit_windows=5)
    assert len(state["windows"]) > 0, "nenhuma janela encontrada"
    print(f"✔ nativa OK ({len(state['windows'])} janelas)")

def test_pixel():
    from pcbot.pixel import PixelLayer

    p = PixelLayer()
    img = p.screenshot(path="screenshots/smoke.png")
    assert img is not None
    print(f"✔ pixel OK (screenshot {img.size})")

def test_browser():
    from pcbot.browser import BrowserLayer

    b = BrowserLayer(channel="msedge", headless=True)
    start = b.start()
    assert start.get("ok"), f"start falhou: {start.get('error')}"
    nav = b.goto("https://example.com")
    assert nav.get("ok"), f"goto falhou: {nav.get('error')}"
    dom = b.get_dom(max_elements=20)
    assert dom.get("ok"), f"get_dom falhou: {dom.get('error')}"
    assert len(dom.get("elements", [])) > 0
    b.close()
    print("✔ browser OK")

def test_plugins():
    from pcbot.plugins import list_plugins, PLUGINS_DIR

    assert os.path.isdir(PLUGINS_DIR), f"PLUGINS_DIR nao existe: {PLUGINS_DIR}"
    list_plugins()  # so garante que nao lanca
    print(f"✔ plugins OK (dir={PLUGINS_DIR})")

def main():
    test_overlay()
    test_native()
    test_pixel()
    test_browser()
    test_plugins()
    print("Todos os smoke tests passaram!")

if __name__ == "__main__":
    main()