

import logging
import time

from pywinauto import Desktop, ElementNotFoundError
from pywinauto.timings import TimeoutError as PywinautoTimeoutError

from .overlay import CursorOverlay

log = logging.getLogger("pcbot.native")


def _describe(elem):
    """Descreve um elemento UIA com seguranca — elementos ficam 'stale' com
    frequencia (janela fechou, DOM mudou) e chamadas na COM podem lancar."""
    try:
        name = (elem.window_text() or "").strip()
    except Exception:
        return None
    ctrl_type = ""
    auto_id = ""
    try:
        ctrl_type = getattr(elem, "friendly_class_name", lambda: "")()
        auto_id = elem.element_info.automation_id or ""
        if hasattr(elem.element_info, "control_type"):
            ctrl_type = elem.element_info.control_type
    except Exception:
        pass
    if not name and not auto_id:
        return None
    try:
        r = elem.rectangle()
        rect = (int(r.left), int(r.top), int(r.right), int(r.bottom))
        handle = int(elem.handle)
    except Exception:
        return None
    return {"name": name, "type": ctrl_type, "automation_id": auto_id, "rect": rect, "handle": handle}


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

    def list_windows(self, limit=30):
        out = []
        try:
            windows = self._desktop.windows()
        except Exception as exc:
            log.exception("falha ao enumerar janelas")
            return []
        for win in windows:
            info = _describe(win)
            if info and info["name"]:
                out.append(info)
            if len(out) >= limit:
                break
        return out

    def find(self, name=None, ctrl_type=None, top_n=20, timeout=5):
        """Busca elementos na arvore UIA (descendentes de todas as janelas)
        por nome/tipo. Um unico passe — sem pre-filtro redundante."""
        matches = []
        try:
            windows = self._desktop.windows()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        for win in windows:
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
                log.debug("descendants() falhou para uma janela, pulando", exc_info=True)
                continue
        return matches[:top_n]

    def click(self, name=None, handle=None, timeout=5):
        """Clica em um elemento pelo nome ou handle."""
        if handle:
            try:
                elem = self._desktop.window(handle=handle)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        else:
            try:
                elem = self._desktop.window(title=name).wait("exists", timeout)
            except (ElementNotFoundError, PywinautoTimeoutError):
                return {"ok": False, "error": f"elemento '{name}' nao encontrado"}
        try:
            result = self._click_element(elem)
            return {"ok": True, **result}
        except Exception as exc:
            log.exception("falha ao clicar em name=%r handle=%r", name, handle)
            return {"ok": False, "error": str(exc)}

    def type_text(self, text, name=None, handle=None, timeout=5, clear_first=False):
        """Digita texto num campo de edicao."""
        if not name and not handle:
            return {"ok": False, "error": "informe name ou handle"}
        try:
            if handle:
                elem = self._desktop.window(handle=handle)
            else:
                elem = self._desktop.window(title=name).wait("exists", timeout)
            rect = elem.rectangle()
            cx, cy = rect.mid_point()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
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
            log.exception("falha ao digitar em name=%r handle=%r", name, handle)
            return {"ok": False, "error": str(exc)}

    def get_window(self, name=None, handle=None):
        """Le o texto visivel de uma janela (para extracao de conteudo)."""
        try:
            if handle:
                elem = self._desktop.window(handle=handle)
            else:
                elem = self._desktop.window(title=name)
            return {"ok": True, "title": elem.window_text(), "text": elem.window_text()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
