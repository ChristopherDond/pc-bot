

import time

from .native import NativeLayer
from .pixel import PixelLayer
from .overlay import CursorOverlay

class AgentDesktop:
    def __init__(self, overlay: CursorOverlay | None = None, screenshots_dir="screenshots"):
        import os

        self._overlay = overlay
        self._native = NativeLayer(overlay=overlay)
        self._pixel = PixelLayer(overlay=overlay)
        self._screenshots_dir = screenshots_dir
        os.makedirs(screenshots_dir, exist_ok=True)

    def screenshot(self, name="screen"):
        path = f"{self._screenshots_dir}/{name}.png"
        img = self._pixel.screenshot(path=path)
        return {"path": path, "size": img.size}

    def get_state(self, limit_windows=15):
        """Resumo textual da tela: janelas abertas + plugins (se houver)."""
        windows = self._native.list_windows(limit=limit_windows)
        plugins = []
        try:
            from .plugins import list_plugins

            plugins = list_plugins()
        except Exception:
            pass
        return {"windows": windows, "plugins": plugins}

    def click(self, name=None, handle=None, x=None, y=None):
        if x is not None and y is not None:
            result = self._pixel.click(x, y)
            result["confidence"] = "C"
            return result
        result = self._native.click(name=name, handle=handle)
        if result.get("ok"):
            result["confidence"] = "A"
            return result
        result["confidence"] = "A"
        return result

    def type_text(self, text, name=None, handle=None, clear_first=False):
        if name or handle:
            result = self._native.type_text(text, name=name, handle=handle, clear_first=clear_first)
        else:
            result = self._pixel.type_text(text)
        result["confidence"] = "A" if result.get("ok") and (name or handle) else "C"
        return result

    def find(self, name=None, ctrl_type=None):
        return self._native.find(name=name, ctrl_type=ctrl_type)

    def open_app(self, app_path):
        """Abre um app pelo caminho, exe nome ou comando (via start)."""
        import os
        import subprocess
        import shlex

        try:
            if os.path.exists(app_path):
                os.startfile(app_path)
            else:
                subprocess.Popen(shlex.split(app_path), shell=True)
            time.sleep(1.2)
            return {"ok": True, "app": app_path}
        except Exception as exc:
            return {"error": str(exc)}

    def close(self):
        if self._overlay:
            self._overlay.close()