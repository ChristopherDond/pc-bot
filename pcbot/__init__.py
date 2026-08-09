import sys

__version__ = "0.1.0"

if sys.platform != "win32":
    raise RuntimeError(
        "pc-bot depende de APIs nativas do Windows (UIA, win32gui, ctypes.windll) "
        "e so funciona em sys.platform == 'win32'."
    )

import ctypes

def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
