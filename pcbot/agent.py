

import logging
import os
import subprocess
import time

from .native import NativeLayer
from .pixel import PixelLayer
from .overlay import CursorOverlay

log = logging.getLogger("pcbot.agent")


class AgentDesktop:
    """Orquestra as camadas A (UIA) / B (browser CDP, opcional) / C (pixel),
    caindo para a proxima apenas quando a atual falha."""

    def __init__(self, overlay: CursorOverlay | None = None, screenshots_dir="screenshots", browser=None):
        self._overlay = overlay
        self._native = NativeLayer(overlay=overlay)
        self._pixel = PixelLayer(overlay=overlay)
        self._browser = browser  # BrowserLayer | None — injetado, ja iniciado
        self._screenshots_dir = screenshots_dir
        os.makedirs(screenshots_dir, exist_ok=True)

    def screenshot(self, name="screen"):
        path = f"{self._screenshots_dir}/{name}.png"
        img = self._pixel.screenshot(path=path)
        return {"ok": True, "path": path, "size": img.size}

    def get_state(self, limit_windows=15):
        """Resumo textual da tela: janelas abertas + plugins (se houver)."""
        windows = self._native.list_windows(limit=limit_windows)
        plugins = []
        try:
            from .plugins import list_plugins

            plugins = list_plugins()
        except Exception:
            log.exception("falha ao listar plugins")
        return {"windows": windows, "plugins": plugins}

    def click(self, name=None, handle=None, x=None, y=None, ref=None, require_confirmation_below="B", confirm=None):
        """Clica cascateando pelas camadas disponiveis (A -> B -> C).

        - name/handle: tenta camada A (UIA).
        - ref: tenta camada B (browser DOM), se `self._browser` estiver configurado.
        - x/y: pula direto pra camada C.
        Se nenhum identificador especifico for dado (so x/y) o cascateamento nao
        ocorre — a chamada ja pede explicitamente o nivel C.

        `require_confirmation_below`: nivel minimo (A/B/C, em ordem decrescente de
        confianca) que dispensa confirmacao. Cliques que so tem sucesso num nivel
        pior que esse chamam `confirm(result)` antes de retornar; se `confirm`
        nao for passado ou devolver False, o clique e revertido para um resultado
        de erro em vez de reportar sucesso silencioso.
        """
        attempts = []

        if x is not None and y is not None and name is None and handle is None and ref is None:
            result = self._pixel.click(x, y)
            result["confidence"] = "C"
            return self._gate_confidence(result, "C", require_confirmation_below, confirm)

        if name is not None or handle is not None:
            result = self._native.click(name=name, handle=handle)
            attempts.append(("A", result))
            if result.get("ok"):
                result["confidence"] = "A"
                return result
            log.info("camada A falhou (name=%r handle=%r): %s", name, handle, result.get("error"))

        if ref is not None and self._browser is not None:
            result = self._browser.click(ref)
            attempts.append(("B", result))
            if result.get("ok"):
                result["confidence"] = "B"
                return result
            log.info("camada B falhou (ref=%r): %s", ref, result.get("error"))

        if x is not None and y is not None:
            result = self._pixel.click(x, y)
            attempts.append(("C", result))
            result["confidence"] = "C"
            if result.get("ok"):
                return self._gate_confidence(result, "C", require_confirmation_below, confirm)
            log.info("camada C falhou (x=%r y=%r): %s", x, y, result.get("error"))

        return {
            "ok": False,
            "error": "todas as camadas disponiveis falharam",
            "attempts": [{"confidence": c, **r} for c, r in attempts],
        }

    def _gate_confidence(self, result, level, threshold, confirm):
        order = {"A": 0, "B": 1, "C": 2}
        if order[level] <= order.get(threshold, 2):
            return result
        if confirm is None or not confirm(result):
            return {
                "ok": False,
                "error": f"clique de confianca {level} exige confirmacao explicita (confirm=...)",
                "attempted": result,
            }
        result["confirmed"] = True
        return result

    def type_text(self, text, name=None, handle=None, clear_first=False, ref=None):
        if name is not None or handle is not None:
            result = self._native.type_text(text, name=name, handle=handle, clear_first=clear_first)
            result["confidence"] = "A"
            if result.get("ok"):
                return result
            log.info("digitacao camada A falhou: %s", result.get("error"))

        if ref is not None and self._browser is not None:
            result = self._browser.type_text(ref, text, clear_first=clear_first)
            result["confidence"] = "B"
            if result.get("ok"):
                return result
            log.info("digitacao camada B falhou: %s", result.get("error"))

        result = self._pixel.type_text(text)
        result["confidence"] = "C"
        return result

    def find(self, name=None, ctrl_type=None):
        return self._native.find(name=name, ctrl_type=ctrl_type)

    def open_app(self, app_path):
        """Abre um app pelo caminho, exe nome ou comando (via shell do SO)."""
        try:
            if os.path.exists(app_path):
                os.startfile(app_path)
            else:
                # shell=True no Windows espera uma string (repassada ao cmd.exe),
                # nao uma lista — nao usar shlex.split (parser POSIX) aqui.
                subprocess.Popen(app_path, shell=True)
            time.sleep(1.2)
            return {"ok": True, "app": app_path}
        except Exception as exc:
            log.exception("falha ao abrir app %r", app_path)
            return {"ok": False, "error": str(exc)}

    def close(self):
        if self._overlay:
            self._overlay.close()
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                log.exception("falha ao fechar browser")
