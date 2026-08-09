import ctypes
import math
import threading
import time
from pathlib import Path

import numpy as np
import win32api
import win32con
import win32gui
from PIL import Image

from . import enable_dpi_awareness

AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x02
_WM_RENDER = 0x8000 + 1

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

class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_size_t),
        ("time", ctypes.c_uint),
        ("pt", ctypes.c_long * 2),
    ]

_gdi32 = ctypes.windll.gdi32
_user32 = ctypes.windll.user32

def _load_cursor_bgra(path, color=None):
    """Carrega o cursor e devolve um array HxWx4 (BGRA, alpha pre-multiplicado).
    `color`, se dado (r, g, b) 0-255, tinge o cursor multiplicando o canal RGB
    original (mantendo o alpha/forma do PNG original)."""
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    arr = np.asarray(img, dtype=np.float32)  # H,W,4 em RGBA
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    if color is not None:
        cr, cg, cb = color
        r, g, b = r * (cr / 255.0), g * (cg / 255.0), b * (cb / 255.0)
    fa = a / 255.0
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0] = (b * fa).astype(np.uint8)
    out[..., 1] = (g * fa).astype(np.uint8)
    out[..., 2] = (r * fa).astype(np.uint8)
    out[..., 3] = a.astype(np.uint8)
    return out, w, h

class _WindowThread:
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
                win32gui.ValidateRect(hwnd, None)
                return 0
            if msg == _WM_RENDER:
                owner._present_in_thread(hwnd)
                return 0
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
        self._ready.set()

        owner._init_surface()

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
    def __init__(self, image=None, hotspot=None, color=None):
        enable_dpi_awareness()
        default = Path(__file__).resolve().parent.parent / "assets" / "cursor.png"
        self._image_path = Path(image) if image else default
        self._color = color
        self._hwnd = None
        self._running = False
        self._anim_thread = None
        self._pos = None
        self._target = None
        self._lock = threading.Lock()
        self._buffer = None
        self._bits_addr = None
        self._mem_dc = None
        self._hbmp = None
        self._stride = 0
        self._surface_lock = threading.Lock()
        self._cursor_bgra = None
        self._cursor_w = 0
        self._cursor_h = 0
        self._hotspot = hotspot
        self._load_cursor()

    def _load_cursor(self):
        if not self._image_path.exists():
            raise FileNotFoundError(f"Cursor nao encontrado: {self._image_path}")
        self._cursor_bgra, self._cursor_w, self._cursor_h = _load_cursor_bgra(
            self._image_path, color=self._color
        )
        if self._hotspot is None:
            self._hotspot = (self._cursor_w // 2, self._cursor_h // 2)

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
            with self._surface_lock:
                self._buffer = np.zeros((self._height, self._width, 4), dtype=np.uint8)
            self._mem_dc = _gdi32.CreateCompatibleDC(hdc_screen)
            _gdi32.SelectObject(self._mem_dc, self._hbmp)
        finally:
            _user32.ReleaseDC(0, hdc_screen)

    def _blit_cursor_locked(self, cx, cy):
        """Alpha blend vetorizado (numpy) do cursor sobre self._buffer.
        Chamador deve segurar self._surface_lock."""
        w, h = self._cursor_w, self._cursor_h
        hx, hy = self._hotspot
        x0, y0 = cx - hx, cy - hy

        src_x0 = max(0, -x0)
        src_y0 = max(0, -y0)
        dst_x0 = max(0, x0)
        dst_y0 = max(0, y0)
        dst_x1 = min(dst_x0 + (w - src_x0), self._width)
        dst_y1 = min(dst_y0 + (h - src_y0), self._height)
        if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
            return
        cw, ch = dst_x1 - dst_x0, dst_y1 - dst_y0

        src = self._cursor_bgra[src_y0:src_y0 + ch, src_x0:src_x0 + cw].astype(np.float32)
        dst = self._buffer[dst_y0:dst_y1, dst_x0:dst_x1].astype(np.float32)

        sa = src[..., 3:4] / 255.0
        da = dst[..., 3:4] / 255.0
        out_a = sa + da * (1.0 - sa)
        denom = np.maximum(out_a, 1e-6)
        out_rgb = (src[..., :3] * sa + dst[..., :3] * da * (1.0 - sa)) / denom

        blended = np.empty_like(dst)
        blended[..., :3] = out_rgb
        blended[..., 3:4] = out_a * 255.0
        self._buffer[dst_y0:dst_y1, dst_x0:dst_x1] = blended.astype(np.uint8)

    def _paint(self):
        with self._lock:
            pos = self._pos
        with self._surface_lock:
            if self._buffer is None:
                return
            self._buffer.fill(0)
            if pos is not None:
                self._blit_cursor_locked(int(pos[0]), int(pos[1]))
        self._present()

    def _present(self):
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, _WM_RENDER, 0, 0)

    def _present_in_thread(self, hwnd):
        with self._surface_lock:
            if self._bits_addr is None or self._buffer is None:
                return
            buf = np.ascontiguousarray(self._buffer)
            ctypes.memmove(self._bits_addr, buf.ctypes.data, buf.nbytes)
            hdc_screen = _user32.GetDC(0)
            try:
                blend = _BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
                pos = _POINT(0, 0)
                size = _SIZE(self._width, self._height)
                src = _POINT(0, 0)
                _user32.UpdateLayeredWindow(
                    hwnd, hdc_screen, ctypes.byref(pos), ctypes.byref(size),
                    self._mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
                )
            finally:
                _user32.ReleaseDC(0, hdc_screen)

    def start(self):
        if self._running:
            return
        self._running = True
        self._window_thread = _WindowThread(self)
        self._hwnd = self._window_thread.start()
        if not self._hwnd:
            raise RuntimeError("falha ao criar a janela do overlay")
        self._width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        self._height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        for _ in range(100):
            if self._buffer is not None:
                break
            time.sleep(0.05)
        self._paint()
        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)
        self._paint()
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
                self._paint()
                last_key = key

    def move_to(self, x, y):
        with self._lock:
            self._target = (int(x), int(y))
            if self._pos is None:
                self._pos = (int(x), int(y))
        self._paint()

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
        if self._anim_thread:
            self._anim_thread.join(timeout=1.0)
        if self._hwnd:
            try:
                win32gui.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
        if self._hbmp:
            _gdi32.DeleteObject(self._hbmp)
        if self._mem_dc:
            _gdi32.DeleteDC(self._mem_dc)
        self._hbmp = None
        self._mem_dc = None