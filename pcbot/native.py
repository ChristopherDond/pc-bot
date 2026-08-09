"""Camada nativa Windows via UI Automation (pywinauto).

Inspeciona a arvore de acessibilidade do Windows (a mesma usada por
leitores de tela) e executa acoes por elemento — muito mais confiavel
que clicar em pixel, porque o alvo e identificado por propriedades
reais (nome, tipo, automation_id).
"""

import time

from pywinauto import Desktop, ElementNotFoundError
from pywinauto.timings import TimeoutError as PywinautoTimeoutError

from .overlay import CursorOverlay


def _describe(elem, depth=0):
    name = (elem.window_text() or "").strip()
    ctrl_type = getattr(elem, "friendly_class_name", lambda: "")()
    auto_id = ""
    try:
        auto_id = elem.element_info.automation_id or ""
        if hasattr(elem.element_info, "control_type"):
            ctrl_type = elem.element_info.control_type
    except Exception:
        pass
    if not name and not auto_id:
        return None
    return {
        "name": name,
        "type": ctrl_type,
        "automation_id": auto_id,
        "rect": (int(r.left), int(r.top), int(r.right), int(r.bottom)) if (r := elem.rectangle()) else None,
        "handle": int(elem.handle),
    }


class NativeLayer:
    """Opera sobre a arvore UIA do desktop inteiro."""

    def __init__(self, overlay: CursorOverlay | None = None):
        self._overlay = overlay
        self._desktop = Desktop(backend="uia")

    def _click_element(self, elem):
        rect = elem.rectangle()
        cx, cy = rect.mid_point()
        if self._overlay:
            self._overlay.teleport_to(cx, cy)
            time.sleep(0.05)
        elem.click_input()
        if self._overlay:
            self._overlay.hide()
        return {"x": cx, "y": cy, "handle": int(elem.handle)}

    # ------------------------------------------------------------------
    # inspecao
    # ------------------------------------------------------------------
    def list_windows(self, limit=30):
        out = []
        for win in self._desktop.windows():
            info = _describe(win)
            if info and info["name"]:
                out.append(info)
            if len(out) >= limit:
                break
        return out

    def find(self, name=None, ctrl_type=None, top_n=20, timeout=5):
        """Busca elementos na arvore UIA por nome/tipo."""
        try:
            if name:
                matches = [
                    _describe(e)
                    for e in self._desktop.windows()
                    if name.lower() in (e.window_text() or "").lower()
                ]
            else:
                matches = []
            for win in self._desktop.windows():
                try:
                    for e in win.descendants():
                        info = _describe(e)
                        if not info:
                            continue
                        if ctrl_type and ctrl_type.lower() not in info["type"].lower():
                            continue
                        if name and name.lower() not in info["name"].lower():
                            continue
                        matches.append(info)
                        if len(matches) >= top_n:
                            return matches[:top_n]
                except Exception:
                    continue
            return matches[:top_n]
        except Exception as exc:
            return {"error": str(exc)}

    def click(self, name=None, handle=None, timeout=5):
        """Clica em um elemento pelo nome ou handle."""
        if handle:
            try:
                from pywinauto.controls.uiawrapper import UIAWrapper

                elem = UIAWrapper(handle)
            except Exception as exc:
                return {"error": str(exc)}
        else:
            try:
                elem = self._desktop.window(title=name).wait("exists", timeout)
            except (ElementNotFoundError, PywinautoTimeoutError):
                return {"error": f"elemento '{name}' nao encontrado"}
        try:
            result = self._click_element(elem)
            return {"ok": True, **result}
        except Exception as exc:
            return {"error": str(exc)}

    def type_text(self, text, name=None, handle=None, timeout=5, clear_first=False):
        """Digita texto num campo de edicao."""
        try:
            if handle:
                from pywinauto.controls.uiawrapper import UIAWrapper

                elem = UIAWrapper(handle)
            else:
                elem = self._desktop.window(title=name).wait("exists", timeout)
            rect = elem.rectangle()
            cx, cy = rect.mid_point()
        except Exception as exc:
            return {"error": str(exc)}
        try:
            if self._overlay:
                self._overlay.teleport_to(cx, cy)
                time.sleep(0.05)
            elem.set_focus()
            if clear_first:
                elem.select()
            elem.type_keys(text, with_spaces=True)
            if self._overlay:
                self._overlay.hide()
            return {"ok": True, "text": text[:80]}
        except Exception as exc:
            return {"error": str(exc)}

    def get_window(self, name=None, handle=None):
        """Le o texto visivel de uma janela (para extracao de conteudo)."""
        try:
            if handle:
                from pywinauto.controls.uiawrapper import UIAWrapper

                elem = UIAWrapper(handle)
            else:
                elem = self._desktop.window(title=name)
            return {"title": elem.window_text(), "text": elem.window_text()}
        except Exception as exc:
            return {"error": str(exc)}