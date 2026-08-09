"""Overlay cursor: renderiza um cursor PNG com transparencia real na tela.

Tecnica: janela WS_EX_LAYERED fullscreen + UpdateLayeredWindow com DIB de
32 bits (BGRA premultiplied, alpha por pixel). Isso permite desenhar
qualquer arte com transparencia suave (anti-aliasing, glow, sombras) —
como um PNG baixado da internet ou o cursor neon gerado por cursor_art.

A janela e criada numa thread dedicada com message pump (GetMessageW via
ctypes) e o UpdateLayeredWindow roda NA thread da janela via PostMessage,
porque o DWM exige que o hDC da surface pertenca a mesma thread da janela.

DETALHE CRITICO: o buffer do DIBSection e BGRA (Blue, Green, Red, Alpha).
Escrever RGBA direto resulta em cores trocadas (ex.: ciano vira amarelo).
A conversao RGBA->BGRA e feita na carga do PNG, com premultiplicacao de
alpha obrigatoria para o flag AC_SRC_ALPHA.
"""

import ctypes
import math
import threading
import time
from pathlib import Path

import win32api
import win32con
import win32gui
from PIL import Image

from . import enable_dpi_awareness
from .cursor_art import DEFAULT_CURSOR, ensure_cursor

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


def _load_cursor_bgra(path):
    """Carrega um PNG RGBA e devolve (bytes BGRA premultiplied, w, h, hot_x, hot_y).

    Premultiplicacao e obrigatoria para AC_SRC_ALPHA: cada canal de cor e
    multiplicado por alpha/255 antes de ir pro buffer.
    """
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    px = img.load()
    buf = bytearray(w * h * 4)
    for y in range(h):
        row = y * w * 4
        for x in range(w):
            r, g, b, a = px[x, y]
            fa = a / 255.0
            i = row + x * 4
            buf[i] = int(b * fa)      # Blue
            buf[i + 1] = int(g * fa)  # Green
            buf[i + 2] = int(r * fa)  # Red
            buf[i + 3] = a            # Alpha
    # hot spot: centro do anel
    return bytes(buf), w, h


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

        # Surface criada na thread da janela (o DWM exige hDC da mesma thread)
        owner._init_surface()

        # Message pump
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
    """Cursor PNG em tela cheia que segue as acoes do agente."""

    def __init__(self, image=None, color=(0, 255, 200), radius=22, ring_width=5,
                 glow_strength=1.0, with_tail=True):
        enable_dpi_awareness()
        self._image_path = Path(image) if image else DEFAULT_CURSOR
        self._color = color
        self._radius = radius
        self._ring_width = ring_width
        self._glow_strength = glow_strength
        self._with_tail = with_tail
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
        self._load_cursor()

    def _load_cursor(self):
        if not self._image_path.exists():
            ensure_cursor(
                self._image_path,
                color=self._color,
                radius=self._radius,
                ring_width=self._ring_width,
                glow_strength=self._glow_strength,
                with_tail=self._with_tail,
            )
        self._cursor_bgra, self._cursor_w, self._cursor_h = _load_cursor_bgra(
            self._image_path
        )

    # ------------------------------------------------------------------
    # superficie DIB
    # ------------------------------------------------------------------
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
    # composicao do cursor no buffer
    # ------------------------------------------------------------------
    def _blit_cursor(self, cx, cy):
        w, h = self._cursor_w, self._cursor_h
        buf = self._buffer
        stride = self._stride
        x0 = cx - w // 2
        y0 = cy - h // 2
        for yy in range(h):
            sy = y0 + yy
            if sy < 0 or sy >= self._height:
                continue
            row_src = yy * w * 4
            row_dst = sy * stride + x0 * 4
            for xx in range(w):
                sx = x0 + xx
                if sx < 0 or sx >= self._width:
                    continue
                sa = self._cursor_bgra[row_src + xx * 4 + 3]
                if sa == 0:
                    continue
                i = row_dst + xx * 4
                da = buf[i + 3]
                out_a = sa + da * (255 - sa) // 255
                if out_a == 0:
                    continue
                for ch in range(3):
                    sc = self._cursor_bgra[row_src + xx * 4 + ch]
                    dc = buf[i + ch]
                    buf[i + ch] = (sc * sa + dc * da * (255 - sa) // 255) // out_a
                buf[i + 3] = out_a

    def _clear_buffer(self):
        buf = self._buffer
        if buf is None:
            return
        for i in range(0, len(buf), 4096):
            buf[i : i + 4096] = b"\x00" * min(4096, len(buf) - i)

    def _paint(self):
        self._clear_buffer()
        with self._lock:
            pos = self._pos
        if pos is not None:
            self._blit_cursor(int(pos[0]), int(pos[1]))
        self._present()

    def _present(self):
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, _WM_RENDER, 0, 0)

    def _present_in_thread(self, hwnd):
        with self._surface_lock:
            if self._bits_addr is None or self._buffer is None:
                return
            ctypes.memmove(self._bits_addr, bytes(self._buffer), len(self._buffer))
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

    # ------------------------------------------------------------------
    # ciclo de vida
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
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