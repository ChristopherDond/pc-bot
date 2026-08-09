"""Camada browser via CDP (Playwright).

Conecta no Edge/Chrome do usuario com um perfil persistente dedicado
(pc-bot-profile) ou reutiliza um perfil existente via --profile. Expõe a
arvore DOM como uma lista de elementos com refs, clica em um ref,
digita, navega e le o conteudo — a forma mais confiavel de agir na web.
"""

import os
import time

_profile_dir = os.path.join(os.path.expanduser("~"), ".pc-bot", "profile")


class BrowserLayer:
    def __init__(self, channel="msedge", profile=None, headless=False, overlay=None):
        self._channel = channel
        self._profile = profile or _profile_dir
        self._headless = headless
        self._overlay = overlay
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # ciclo de vida
    # ------------------------------------------------------------------
    def start(self):
        from playwright.sync_api import sync_playwright

        os.makedirs(self._profile, exist_ok=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch_persistent_context(
            user_data_dir=self._profile,
            channel=self._channel,
            headless=self._headless,
            accept_downloads=True,
            viewport={"width": 1280, "height": 800},
        )
        self._context = self._browser
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return {"ok": True, "channel": self._channel}

    def close(self):
        try:
            self._browser.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # navegacao
    # ------------------------------------------------------------------
    def goto(self, url, timeout=30000):
        self._page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        time.sleep(0.4)
        return {"url": self._page.url, "title": self._page.title()}

    # ------------------------------------------------------------------
    # arvore DOM
    # ------------------------------------------------------------------
    def get_dom(self, max_elements=60):
        """Extrai elementos interativos com refs (button, a, input, etc)."""
        js_refs = """
        () => {
          const want = ['button','a','input','textarea','select','[role=button]','[role=link]','[role=textbox]','[role=checkbox]','[role=menuitem]','label'];
          const seen = new Set();
          let i = 0;
          for (const sel of want) {
            for (const el of document.querySelectorAll(sel)) {
              if (seen.has(el)) continue;
              seen.add(el);
              const r = el.getBoundingClientRect();
              if (r.width > 2 && r.height > 2 && getComputedStyle(el).visibility !== 'hidden') {
                el.dataset.pcbotRef = 'pcbot-' + i;
                i++;
              }
            }
          }
        }
        """
        js = """
        () => {
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
          return out.slice(0, %s);
        }
        """ % max_elements
        try:
            self._page.evaluate(js_refs, [])
        except Exception:
            pass
        try:
            elements = self._page.evaluate(js)
        except Exception as exc:
            return {"error": str(exc)}

        return {"url": self._page.url, "title": self._page.title(), "elements": elements}

    # ------------------------------------------------------------------
    # acoes
    # ------------------------------------------------------------------
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
            return {"error": str(exc)}

    def type_text(self, ref, text, clear_first=True):
        loc = self._locator_for(ref)
        try:
            if clear_first:
                loc.fill("")
            loc.fill(text, timeout=5000)
            return {"ok": True, "ref": ref}
        except Exception as exc:
            return {"error": str(exc)}

    def press(self, key):
        self._page.keyboard.press(key)
        return {"ok": True, "key": key}

    def get_text(self):
        try:
            return {"text": self._page.inner_text("body")[:8000]}
        except Exception as exc:
            return {"error": str(exc)}