"""Overlay cursor: anel visual que mostra onde o agente esta agindo.

Janela em toda a tela (WS_EX_LAYERED + WS_EX_TRANSPARENT + WS_EX_NOACTIVATE)
renderizada via UpdateLayeredWindow com alpha por pixel: o fundo e 100%
transparente (nao cobre nada, nao rouba foco) e o anel colorido e 100%
opaco, com anti-aliasing na borda. Animado a ~60fps, deslizando ate o alvo.
"""

import ctypes
import math
import threading
import time

import win32api
import win32con
import win32gui

from . import enable_dpi_awareness

AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x02
SM_CXSCREEN = win32con.SM_CXSCREEN
SM_CYSCREEN = win32con.SM_CYSCREEN


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


_gdi32 = ctypes.windll.gdi32
_user32 = ctypes.windll.user32


class CursorOverlay:
    """Anel colorido em tela cheia que segue as acoes do agente."""

    def __init__(self, color=(0, 255, 200), radius=18, ring_width=4):
        enable_dpi_awareness()
        self._color = color
        self._radius = radius
        self._ring_width = ring_width
        self._hwnd = None
        self._running = False
        self._thread = None
        self._pos = None
        self._target = None
        self._lock = threading.Lock()
        self._buffer = None
        self._stride = 0

    # ------------------------------------------------------------------
    # janela + superficie
    # ------------------------------------------------------------------
    def _create_window(self):
        hinst = win32api.GetModuleHandle(None)
        wnd_class = win32gui.RegisterClass(
            {
                "lpfnWndProc": win32gui.DefWindowProc,
                "lpszClassName": "PCBotOverlayCursor",
                "hInstance": hinst,
                "hCursor": 0,
                "hbrBackground": 0,
            }
        )
        width = win32api.GetSystemMetrics(SM_CXSCREEN)
        height = win32api.GetSystemMetrics(SM_CYSCREEN)
        self._hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOOLWINDOW
            | win32con.WS_EX_NOACTIVATE,
            wnd_class,
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
        self._width = width
        self._height = height
        self._init_surface()

    def _init_surface(self):
        hdc_screen = _user32.GetDC(0)
        try:
            bmi = _BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = self._width
            bmi.bmiHeader.biHeight = -self._height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            bits = ctypes.c_void_p()
            self._hbmp = _gdi32.CreateDIBSection(
                hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
            )
            self._bits_addr = bits.value
            self._stride = self._width * 4
            self._buffer = bytearray(self._stride * self._height)
            self._mem_dc = _gdi32.CreateCompatibleDC(hdc_screen)
            _gdi32.SelectObject(self._mem_dc, self._hbmp)
        finally:
            _user32.ReleaseDC(0, hdc_screen)

    # ------------------------------------------------------------------
    # rasterizacao do anel (BGRA premultiplied, alpha por pixel)
    # ------------------------------------------------------------------
    def _coverage(self, dist):
        r = self._radius
        w = self._ring_width
        inner = r - w / 2 - 0.5
        outer = r + w / 2 + 0.5
        if dist <= inner or dist >= outer:
            return 0.0
        return min(1.0, min(dist - inner, outer - dist))

    def _render_ring(self, cx, cy):
        r = self._radius
        w = self._ring_width
        pad = r + w + 2
        x0 = max(0, int(cx - pad))
        x1 = min(self._width - 1, int(cx + pad))
        y0 = max(0, int(cy - pad))
        y1 = min(self._height - 1, int(cy + pad))
        r2 = (r - 0.5) ** 2
        c0, c1, c2 = self._color
        buf = self._buffer
        stride = self._stride
        for y in range(y0, y1 + 1):
            dy = y - cy
            row = y * stride
            for x in range(x0, x1 + 1):
                dx = x - cx
                d2 = dx * dx + dy * dy
                if d2 > (pad + 1) ** 2:
                    continue
                d = math.sqrt(d2)
                cov = self._coverage(d)
                if cov <= 0.0:
                    continue
                idx = row + x * 4
                a = int(255 * cov)
                buf[idx] = c0 * a // 255
                buf[idx + 1] = c1 * a // 255
                buf[idx + 2] = c2 * a // 255
                buf[idx + 3] = a

    def _clear_buffer(self):
        buf = self._buffer
        for i in range(0, len(buf), 4096):
            buf[i : i + 4096] = b"\x00" * min(4096, len(buf) - i)

    def _present(self):
        if not self._hwnd:
            return
        ctypes.memmove(self._bits_addr, self._buffer, len(self._buffer))
        hdc_screen = _user32.GetDC(0)
        try:
            blend = _BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
            pos = _POINT(0, 0)
            size = _SIZE(self._width, self._height)
            src = _POINT(0, 0)
            _user32.UpdateLayeredWindow(
                self._hwnd, hdc_screen, ctypes.byref(pos), ctypes.byref(size),
                self._mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
            )
        finally:
            _user32.ReleaseDC(0, hdc_screen)

    def _paint(self):
        self._clear_buffer()
        pos = self._pos
        if pos is not None:
            self._render_ring(int(pos[0]), int(pos[1]))
        self._present()

    # ------------------------------------------------------------------
    # loop de animacao
    # ------------------------------------------------------------------
    def _anim_loop(self):
        while self._running:
            now = time.time()
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
                self._paint()
            elif target and pos is None:
                with self._lock:
                    self._pos = self._target
                    self._target = None
                self._paint()
            time.sleep(1 / 60)

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        self._running = True
        self._create_window()
        self._thread = threading.Thread(target=self._anim_loop, daemon=True)
        self._thread.start()
        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)

    def move_to(self, x, y):
        with self._lock:
            self._target = (int(x), int(y))
            if self._pos is None:
                self._pos = (int(x), int(y))

    def teleport_to(self, x, y):
        with self._lock:
            self._pos = (int(x), int(y))
            self._target = None
            self._paint()

    def hide(self):
        with self._lock:
            self._target = None
            self._pos = None
        self._paint()

    def close(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._hwnd:
            win32gui.DestroyWindow(self._hwnd)
            self._hwnd = None
        if getattr(self, "_hbmp", None):
            _gdi32.DeleteObject(self._hbmp)
        if getattr(self, "_mem_dc", None):
            _gdi32.DeleteDC(self._mem_dc)