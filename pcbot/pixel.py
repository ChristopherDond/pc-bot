

import logging
import time

from PIL import ImageGrab

from .overlay import CursorOverlay

log = logging.getLogger("pcbot.pixel")


class PixelLayer:
    def __init__(self, overlay: CursorOverlay | None = None):
        self._overlay = overlay

    def screenshot(self, region=None, path=None):
        img = ImageGrab.grab(region, all_screens=True)
        if path:
            img.save(path)
        return img

    def click(self, x, y, button="left", clicks=1):
        try:
            import pyautogui

            if self._overlay:
                self._overlay.move_to(x, y)
                time.sleep(0.08)
            pyautogui.click(x, y, clicks=clicks, button=button)
            if self._overlay:
                self._overlay.hide()
            return {"ok": True, "x": x, "y": y, "button": button}
        except Exception as exc:
            log.exception("falha no clique por pixel (x=%s y=%s)", x, y)
            return {"ok": False, "error": str(exc)}

    def double_click(self, x, y):
        return self.click(x, y, clicks=2)

    def type_text(self, text, interval=0.02):
        try:
            import pyautogui

            pyautogui.typewrite(text, interval=interval)
            return {"ok": True, "text": text[:80]}
        except Exception as exc:
            log.exception("falha ao digitar via pixel")
            return {"ok": False, "error": str(exc)}

    def find_template(self, template_path, threshold=0.8, screenshot=None):
        """Procura uma imagem de referencia na tela e devolve o centro."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return {"ok": False, "error": "opencv-python e numpy necessarios para template matching"}
        img = screenshot or self.screenshot()
        img_rgb = np.array(img.convert("RGB"))
        template = cv2.imread(template_path)
        if template is None:
            return {"ok": False, "error": f"template nao carregou: {template_path}"}
        h, w = template.shape[:2]
        result = cv2.matchTemplate(img_rgb, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold:
            return {"ok": True, "found": False, "confidence": float(max_val)}
        cx, cy = max_loc[0] + w // 2, max_loc[1] + h // 2
        return {"ok": True, "found": True, "x": cx, "y": cy, "confidence": float(max_val), "size": (w, h)}

    def click_template(self, template_path, threshold=0.8):
        match = self.find_template(template_path, threshold)
        if not match.get("found"):
            return {"ok": False, "error": "template nao encontrado", "confidence": match.get("confidence")}
        return self.click(match["x"], match["y"])
