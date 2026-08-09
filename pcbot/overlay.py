"""Overlay cursor: anel colorido que mostra onde o agente esta agindo.

Tecnica: janela WS_EX_LAYERED + LWA_COLORKEY (magenta transparente) com
o anel desenhado via GDI no WM_PAINT. O UpdateLayeredWindow/DIB falha
silenciosamente na composicao em alguns ambientes; a abordagem colorkey
+GDI e comprovadamente composta pelo DWM. A janela e criada numa thread
dedicada com message pump, para que WM_PAINT seja entregue de verdade.
"""

import ctypes
import math
import threading
import time

import win32api
import win32con
import win32gui

from . import enable_dpi_awareness

# Cor usada como "chave de transparencia" no LWA_COLORKEY
COLORKEY_RGB = (255, 0, 255)  # magenta puro


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_size_t),
        ("time", ctypes.c_uint),
        ("pt", ctypes.c_long * 2),
    ]


class _WindowThread:
    """Thread que cria a janela do overlay e roda o message pump."""

    def __init__(self, owner):
        self._owner = owner
        self._hwnd = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        enable_dpi_awareness()
        hinst = win32api.GetModuleHandle(None)
        owner = self._owner

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            if msg == win32con.WM_PAINT:
                owner._draw_gdi(hwnd)
                return 0
            if msg == win32con.WM_ERASEBKGND:
                return 1
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = wnd_proc
        wc.lpszClassName = "PCBotOverlayCursor"
        wc.hInstance = hinst
        wc.hCursor = 0
        wc.hbrBackground = 0
        win32gui.RegisterClass(wc)

        width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        self._hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOOLWINDOW
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TOPMOST,
            "PCBotOverlayCursor",
            "PCBotOverlay",
            win32con.WS_POPUP,
            0,
            0,
            width,
            height,
            0,
            0,
            hinst,
            None,
        )
        win32gui.SetLayeredWindowAttributes(
            self._hwnd, win32api.RGB(*COLORKEY_RGB), 0, win32con.LWA_COLORKEY
        )
        self._ready.set()

        # Message pump com ctypes
        user32 = ctypes.windll.user32
        msg = _MSG()
        r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
        while r > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)

    def start(self):
        self._thread.start()
        self._ready.wait(timeout=5)
        return self._hwnd


class CursorOverlay:
    """Anel colorido em tela cheia que segue as acoes do agente."""

    def __init__(self, color=(0, 255, 200), radius=18, ring_width=4):
        enable_dpi_awareness()
        self._color = color
        self._radius = radius
        self._ring_width = ring_width
        self._hwnd = None
        self._running = False
        self._anim_thread = None
        self._pos = None
        self._target = None
        self._lock = threading.Lock()
        self._pens = {}

    # ------------------------------------------------------------------
    # desenho GDI (WM_PAINT, na thread da janela)
    # ------------------------------------------------------------------
    def _draw_gdi(self, hwnd):
        hdc, ps = win32gui.BeginPaint(hwnd)
        try:
            with self._lock:
                pos = self._pos
                color = self._color
                radius = self._radius
                ring_width = self._ring_width
            # pinta o fundo inteiro de colorkey (transparente)
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("l", ctypes.c_long),
                    ("t", ctypes.c_long),
                    ("r", ctypes.c_long),
                    ("b", ctypes.c_long),
                ]

            r = RECT(0, 0, 65536, 65536)
            brush_bg = ctypes.windll.gdi32.CreateSolidBrush(
                win32api.RGB(*COLORKEY_RGB)
            )
            ctypes.windll.user32.FillRect(hdc, ctypes.byref(r), brush_bg)
            ctypes.windll.gdi32.DeleteObject(brush_bg)

            if pos is not None:
                x, y = int(pos[0]), int(pos[1])
                cap = win32con.PS_SOLID
                pen_key = (color, radius, ring_width, cap)
                pen = self._pens.get(pen_key)
                if pen is None:
                    pen = win32gui.CreatePen(cap, ring_width, win32api.RGB(*color))
                    self._pens[pen_key] = pen
                old_pen = win32gui.SelectObject(hdc, pen)
                old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(5))  # NULL_BRUSH
                win32gui.Ellipse(
                    hdc, x - radius, y - radius, x + radius, y + radius
                )
                win32gui.SelectObject(hdc, old_pen)
                win32gui.SelectObject(hdc, old_brush)
        finally:
            win32gui.EndPaint(hwnd, ps)

    def _invalidate(self):
        if self._hwnd:
            win32gui.InvalidateRect(self._hwnd, None, True)

    # ------------------------------------------------------------------
    # inicio / loop de animacao
    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._window_thread = _WindowThread(self)
        self._hwnd = self._window_thread.start()
        if not self._hwnd:
            raise RuntimeError("falha ao criar a janela do overlay")
        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)
        self._invalidate()
        self._anim_thread = threading.Thread(target=self._anim_loop, daemon=True)
        self._anim_thread.start()

    def _anim_loop(self):
        last_key = None
        while self._running:
            time.sleep(1 / 60)
            with self._lock:
                target = self._target
                pos = self._pos
            if target and pos:
                dx, dy = target[0] - pos[0], target[1] - pos[1]
                dist = math.hypot(dx, dy)
                step = max(14.0, dist * 0.28)
                if dist <= step:
                    with self._lock:
                        self._pos = self._target
                        self._target = None
                else:
                    with self._lock:
                        self._pos = (pos[0] + dx / dist * step, pos[1] + dy / dist * step)
            key = (self._pos, self._target)
            if key != last_key:
                self._invalidate()
                last_key = key

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def move_to(self, x, y):
        with self._lock:
            self._target = (int(x), int(y))
            if self._pos is None:
                self._pos = (int(x), int(y))
        self._invalidate()

    def teleport_to(self, x, y):
        with self._lock:
            self._pos = (int(x), int(y))
            self._target = None
        self._invalidate()

    def hide(self):
        with self._lock:
            self._target = None
            self._pos = None
        self._invalidate()

    def close(self):
        self._running = False
        if self._anim_thread:
            self._anim_thread.join(timeout=1.0)
        if self._hwnd:
            try:
                win32gui.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
        for pen in self._pens.values():
            try:
                win32gui.DeleteObject(pen)
            except Exception:
                pass
        self._pens = {}