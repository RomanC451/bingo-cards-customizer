"""Load toolbar icons from icons/ (PNG preferred) for the preview toolbar."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from bingo_cards.config import ICONS_DIR

TOOLBAR_ICON_COLOR = (229, 231, 235)
TOOLBAR_ICON_DISABLED_COLOR = (107, 114, 128)
ICON_CANDIDATES: dict[str, list[str]] = {
    "undo": ["undo-2.png", "undo.png", "undo.svg"],
    "redo": ["redo-2.png", "redo.png", "redo.svg"],
    "reset": ["rotate-ccw.png", "rotate-ccw.svg"],
    "fit": ["expand.png", "expand (1).png", "expand.svg"],
    "plus": ["plus.png", "plus.svg"],
    "minus": ["minus.png", "minus.svg"],
}


def _resolve_icon_path(kind: str) -> Path:
    for file_name in ICON_CANDIDATES.get(kind, []):
        path = ICONS_DIR / file_name
        if path.exists():
            return path
    raise FileNotFoundError(f"No icon file found for '{kind}' in {ICONS_DIR}")


def _tint_icon(image: Image.Image, color: tuple[int, int, int] = TOOLBAR_ICON_COLOR) -> Image.Image:
    _red, _green, _blue, alpha = image.convert("RGBA").split()
    return Image.merge(
        "RGBA",
        (
            Image.new("L", image.size, color[0]),
            Image.new("L", image.size, color[1]),
            Image.new("L", image.size, color[2]),
            alpha,
        ),
    )


def _load_png(path: Path, size: int) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    image = _tint_icon(image)
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image


def _load_svg(path: Path, size: int) -> Image.Image:
    import skia

    svg_bytes = path.read_bytes()
    stream = skia.MemoryStream(svg_bytes)
    dom = skia.SVGDOM.MakeFromStream(stream)
    if dom is None:
        raise ValueError(f"Could not parse SVG icon: {path}")

    render_px = max(size * 4, 96)
    surface = skia.Surface(render_px, render_px)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    dom.setContainerSize(skia.ISize(render_px, render_px))
    dom.render(canvas)

    png_data = surface.makeImageSnapshot().encodeToData()
    image = Image.open(io.BytesIO(bytes(png_data))).convert("RGBA")
    image = _tint_icon(image)
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image


def dim_toolbar_icon(image: Image.Image) -> Image.Image:
    dimmed = _tint_icon(image.convert("RGBA"), TOOLBAR_ICON_DISABLED_COLOR)
    red, green, blue, alpha = dimmed.split()
    faded_alpha = alpha.point(lambda value: int(value * 0.45))
    return Image.merge("RGBA", (red, green, blue, faded_alpha))


def load_toolbar_icon(
    kind: str,
    size: int = 24,
    *,
    enabled: bool = True,
) -> Image.Image:
    path = _resolve_icon_path(kind)
    if path.suffix.lower() == ".png":
        image = _load_png(path, size)
    else:
        image = _load_svg(path, size)

    if enabled:
        return image
    return dim_toolbar_icon(image)
