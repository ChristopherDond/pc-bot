"""Gerador de arte do cursor overlay.

Cria um cursor PNG transparente (anel neon com glow radial) usando Pillow.
Desenha em 4x a resolucao final e reduz (supersampling) para o melhor
anti-aliasing possivel. Se o usuario colocar um arquivo em
assets/cursor.png, ele e usado no lugar do gerado.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
DEFAULT_CURSOR = ASSETS_DIR / "cursor.png"


def _glow_ring(size, color, radius, ring_width, glow_strength):
    """Anel neon com glow: desenha em supersampling e reduz."""
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = color

    # halo externo (glow) - camada de baixo
    halo_r = radius * ss * 1.9
    halo = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    dh = ImageDraw.Draw(halo)
    dh.ellipse(
        [big / 2 - halo_r, big / 2 - halo_r, big / 2 + halo_r, big / 2 + halo_r],
        fill=(c[0], c[1], c[2], int(70 * glow_strength)),
    )
    halo = halo.filter(ImageFilter.GaussianBlur(radius * ss * 0.55))
    img.alpha_composite(halo)

    # anel principal
    r0 = (radius - ring_width / 2) * ss
    r1 = (radius + ring_width / 2) * ss
    d.ellipse(
        [big / 2 - r1, big / 2 - r1, big / 2 + r1, big / 2 + r1],
        outline=(255, 255, 255, 255),
        width=max(1, int(ring_width * ss * 0.55)),
    )
    # segunda passada: cor com borda interna mais clara (efeito neon)
    d.ellipse(
        [big / 2 - r1, big / 2 - r1, big / 2 + r1, big / 2 + r1],
        outline=(c[0], c[1], c[2], 255),
        width=max(1, int(ring_width * ss * 0.35)),
    )
    d.ellipse(
        [big / 2 - r0, big / 2 - r0, big / 2 + r0, big / 2 + r0],
        outline=(min(255, c[0] + 80), min(255, c[1] + 80), min(255, c[2] + 80), 255),
        width=max(1, int(ring_width * ss * 0.18)),
    )

    img = img.resize((size, size), Image.LANCZOS)
    return img


def _cursor_with_tail(size, color, radius, ring_width, glow_strength):
    """Anel neon + seta/traco indicando direcao (estilo cursor de agente)."""
    base = _glow_ring(size, color, radius, ring_width, glow_strength)
    d = ImageDraw.Draw(base)
    c = color
    cx = cy = size / 2

    # ponta indicadora: linha do centro ate a borda + ponta
    ang = math.radians(-45)
    inner = radius * 0.45
    outer = radius + ring_width
    x0 = cx + math.cos(ang) * inner
    y0 = cy + math.sin(ang) * inner
    x1 = cx + math.cos(ang) * outer
    y1 = cy + math.sin(ang) * outer
    d.line([(x0, y0), (x1, y1)], fill=(c[0], c[1], c[2], 255), width=max(2, ring_width // 2))

    # triangulo na ponta
    perp = math.radians(-45 + 90)
    tip_x = cx + math.cos(ang) * (outer + ring_width * 0.9)
    tip_y = cy + math.sin(ang) * (outer + ring_width * 0.9)
    bx = cx + math.cos(ang) * (outer - ring_width * 0.2)
    by = cy + math.sin(ang) * (outer - ring_width * 0.2)
    w_ = ring_width * 0.8
    p1 = (bx + math.cos(perp) * w_, by + math.sin(perp) * w_)
    p2 = (bx - math.cos(perp) * w_, by - math.sin(perp) * w_)
    d.polygon([(tip_x, tip_y), p1, p2], fill=(c[0], c[1], c[2], 255))
    return base


def ensure_cursor(path=None, color=(0, 255, 200), radius=22, ring_width=5,
                  glow_strength=1.0, with_tail=True, force=False):
    """Garante um cursor PNG existir. Retorna (path, gerado_por_codigo)."""
    target = Path(path) if path else DEFAULT_CURSOR
    if target.exists() and not force:
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    size = (radius + ring_width + 6) * 2
    size = max(48, int(size))
    if with_tail:
        img = _cursor_with_tail(size, color, radius, ring_width, glow_strength)
    else:
        img = _glow_ring(size, color, radius, ring_width, glow_strength)
    img.save(target)
    return target, True


if __name__ == "__main__":
    p, generated = ensure_cursor(force=True)
    print(f"cursor em {p} (gerado={generated})")