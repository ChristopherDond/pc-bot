

import logging
import os
import time

log = logging.getLogger("pcbot.browser")

_profile_dir = os.path.join(os.path.expanduser("~"), ".pc-bot", "profile")

_JS_TAG_REFS = """
() => {
  if (!window.__pcbotRefCounter) window.__pcbotRefCounter = 0;
  const want = ['button','a','input','textarea','select','[role=button]','[role=link]','[role=textbox]','[role=checkbox]','[role=menuitem]','label'];
  const seen = new Set();
  for (const sel of want) {
    for (const el of document.querySelectorAll(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      const r = el.getBoundingClientRect();
      if (r.width > 2 && r.height > 2 && getComputedStyle(el).visibility !== 'hidden') {
        if (!el.dataset.pcbotRef) {
          el.dataset.pcbotRef = 'pcbot-' + (window.__pcbotRefCounter++);
        }
      }
    }
  }
}
"""

_JS_COLLECT = """
(maxElements) => {
  const seen = new Set();
  const out = [];
  const want = ['button','a','input','textarea','select','[role=button]','[role=link]','[role=textbox]','[role=checkbox]','[role=menuitem]','label'];
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  for (const sel of want) {
    for (const el of q(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      const r = el.getBoundingClientRect();
      const isVisible = r.width > 2 && r.height > 2 && getComputedStyle(el).visibility !== 'hidden';
      if (!isVisible) continue;
      const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim().slice(0, 120);
      out.push({
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        text: text,
        type: el.getAttribute('type') || '',
        placeholder: el.getAttribute('placeholder') || '',
        aria: el.getAttribute('aria-label') || '',
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
        ref: el.dataset.pcbotRef || ''
      });
    }
  }
  return out.slice(0, maxElements);
}
"""


class BrowserLayer:
    def __init__(self, channel="msedge", profile=None, headless=False, overlay=None, executable_path=None):
        self._channel = channel
        self._profile = profile or _profile_dir
        self._headless = headless
        self._overlay = overlay
        self._executable_path = executable_path
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def start(self):
        from playwright.sync_api import sync_playwright

        try:
            os.makedirs(self._profile, exist_ok=True)
            self._pw = sync_playwright().start()
            kwargs = dict(
                user_data_dir=self._profile,
                channel=self._channel,
                headless=self._headless,
                accept_downloads=True,
                viewport={"width": 1280, "height": 800},
            )
            if self._executable_path:
                kwargs["executable_path"] = self._executable_path
            self._browser = self._pw.chromium.launch_persistent_context(**kwargs)
            self._context = self._browser
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return {"ok": True, "channel": self._channel}
        except Exception as exc:
            log.exception("falha ao iniciar o browser (channel=%s)", self._channel)
            return {"ok": False, "error": str(exc)}

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            log.exception("falha ao fechar o browser")
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                log.exception("falha ao parar playwright")

    def goto(self, url, timeout=30000):
        try:
            self._page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            time.sleep(0.4)
            return {"ok": True, "url": self._page.url, "title": self._page.title()}
        except Exception as exc:
            log.exception("falha ao navegar para %r", url)
            return {"ok": False, "error": str(exc)}

    def get_dom(self, max_elements=60):
        """Extrai elementos interativos com refs estaveis (button, a, input, etc)."""
        try:
            self._page.evaluate(_JS_TAG_REFS)
            elements = self._page.evaluate(_JS_COLLECT, max_elements)
        except Exception as exc:
            log.exception("falha ao ler o DOM")
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "url": self._page.url, "title": self._page.title(), "elements": elements}

    def _locator_for(self, ref):
        return self._page.locator(f"[data-pcbot-ref='{ref}']")

    def click(self, ref):
        loc = self._locator_for(ref)
        try:
            box = loc.bounding_box()
            if box and self._overlay:
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                self._overlay.teleport_to(cx, cy)
                time.sleep(0.05)
            loc.click(timeout=5000)
            if self._overlay:
                self._overlay.hide()
            return {"ok": True, "ref": ref}
        except Exception as exc:
            log.exception("falha ao clicar ref=%r", ref)
            return {"ok": False, "error": str(exc)}

    def type_text(self, ref, text, clear_first=True):
        loc = self._locator_for(ref)
        try:
            if clear_first:
                loc.fill("")
            loc.fill(text, timeout=5000)
            return {"ok": True, "ref": ref}
        except Exception as exc:
            log.exception("falha ao digitar ref=%r", ref)
            return {"ok": False, "error": str(exc)}

    def press(self, key):
        try:
            self._page.keyboard.press(key)
            return {"ok": True, "key": key}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_text(self):
        try:
            return {"ok": True, "text": self._page.inner_text("body")[:8000]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
