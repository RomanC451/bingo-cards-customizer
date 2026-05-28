from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from bingo_cards.ui import toolbar_icons as icons


def test_resolve_icon_path_finds_undo():
    path = icons._resolve_icon_path("undo")
    assert path.exists()
    assert path.suffix.lower() == ".png"


def test_resolve_icon_path_missing_kind():
    with patch.dict(icons.ICON_CANDIDATES, {"missing": ["nope.png"]}, clear=False):
        with pytest.raises(FileNotFoundError, match="No icon file"):
            icons._resolve_icon_path("missing")


def test_tint_icon():
    base = Image.new("RGBA", (8, 8), color=(0, 0, 0, 255))
    tinted = icons._tint_icon(base, (10, 20, 30))
    assert tinted.mode == "RGBA"
    assert tinted.getpixel((0, 0))[:3] == (10, 20, 30)


def test_load_toolbar_icon_png_enabled():
    image = icons.load_toolbar_icon("plus", size=16, enabled=True)
    assert image.size == (16, 16)


def test_load_toolbar_icon_disabled():
    image = icons.load_toolbar_icon("minus", size=16, enabled=False)
    assert image.size == (16, 16)


def test_dim_toolbar_icon():
    base = icons.load_toolbar_icon("fit", size=12, enabled=True)
    dimmed = icons.dim_toolbar_icon(base)
    assert dimmed.mode == "RGBA"


def test_load_svg_icon_when_only_svg(tmp_path: Path, monkeypatch):
    svg = tmp_path / "test.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<rect width="10" height="10" fill="black"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setitem(icons.ICON_CANDIDATES, "testkind", ["test.svg"])
    monkeypatch.setattr(icons, "ICONS_DIR", tmp_path)
    image = icons._load_svg(svg, 16)
    assert image.size == (16, 16)


def test_load_svg_invalid_raises(tmp_path: Path):
    bad = tmp_path / "bad.svg"
    bad.write_bytes(b"not svg")
    with pytest.raises(ValueError, match="Could not parse SVG"):
        icons._load_svg(bad, 16)
