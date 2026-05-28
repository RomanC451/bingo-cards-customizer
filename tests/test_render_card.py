from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bingo_cards.render.card import (
    build_preview,
    draw_free_image_in_cell,
    draw_text_in_cell,
    get_placeholder_matrix,
    is_free_cell_text,
    wrap_text,
)
from bingo_cards.grid.placement import build_uniform_grid_cells


def test_is_free_cell_text():
    assert is_free_cell_text("FREE")
    assert is_free_cell_text("  f r e e  ")
    assert not is_free_cell_text("FREEDOM")


def test_get_placeholder_matrix():
    matrix = get_placeholder_matrix(3)
    assert matrix[0][0] == "Sample 1-1"
    assert len(matrix) == 3


def test_wrap_text_empty():
    image = Image.new("RGB", (100, 100))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    assert wrap_text("", 50, font, draw) == []


def test_wrap_text_splits_long_word():
    image = Image.new("RGB", (200, 200))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    lines = wrap_text("supercalifragilisticexpialidocious word", 10, font, draw)
    assert lines


def test_draw_text_in_cell_skips_blank():
    image = Image.new("RGB", (100, 100))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    cell = build_uniform_grid_cells(1, 0, 0, 80, 80)[0]
    draw_text_in_cell(draw, "   ", cell, font, (0, 0, 0), 0, 0)


def test_draw_free_image_in_cell_no_image():
    image = Image.new("RGB", (100, 100))
    cell = build_uniform_grid_cells(1, 0, 0, 80, 80)[0]
    draw_free_image_in_cell(image, cell, None, 0, 0, 1.0)


def test_build_preview_with_text_and_overlay(tiny_rgb_image, tiny_rgba_icon):
    matrix = [["Song A", "FREE"], ["Song B", "Song C"]]
    preview = build_preview(
        template_image=tiny_rgb_image,
        matrix=matrix,
        grid_size=2,
        text_color_hex="#ff0000",
        font_size=12,
        text_offset_x=0,
        text_offset_y=0,
        free_icon_size=0.8,
        grid_x=10,
        grid_y=10,
        cell_width=80,
        cell_height=80,
        show_grid_overlay=True,
        free_image_path=tiny_rgba_icon,
    )
    assert preview.size == tiny_rgb_image.size


def test_build_preview_uses_default_font_when_arial_missing(
    tiny_rgb_image, monkeypatch
):
    matrix = get_placeholder_matrix(2)

    original_truetype = ImageFont.truetype

    def selective_truetype(font, size, *args, **kwargs):
        if "arial" in str(font).lower():
            raise OSError("no arial")
        return original_truetype(font, size, *args, **kwargs)

    monkeypatch.setattr(ImageFont, "truetype", selective_truetype)
    preview = build_preview(
        template_image=tiny_rgb_image,
        matrix=matrix,
        grid_size=2,
        text_color_hex="#000000",
        font_size=14,
        text_offset_x=0,
        text_offset_y=0,
        free_icon_size=0.5,
        grid_x=0,
        grid_y=0,
        cell_width=50,
        cell_height=50,
        show_grid_overlay=False,
        free_image_path=Path("missing.png"),
    )
    assert preview.mode == "RGB"
