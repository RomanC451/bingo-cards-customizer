from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bingo_cards.config import FREE_IMAGE_PATH
from bingo_cards.grid.placement import build_uniform_grid_cells


def is_free_cell_text(text: str) -> bool:
    normalized = "".join(char for char in text.upper() if char.isalpha())
    return normalized == "FREE"


def wrap_text(
    text: str, max_width: int, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw
):
    words = text.split()
    if not words:
        return []

    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] > max_width:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
        else:
            current_line.append(word)
    if current_line:
        lines.append(" ".join(current_line))
    return lines


def draw_text_in_cell(
    draw: ImageDraw.ImageDraw,
    text: str,
    cell: dict,
    font: ImageFont.FreeTypeFont,
    fill_color: tuple[int, int, int],
    text_offset_x: int,
    text_offset_y: int,
):
    if not text.strip():
        return

    padding = 15
    max_width = cell["width"] - (padding * 2)
    lines = wrap_text(text, max_width, font, draw)
    if not lines:
        return

    line_height = font.size + 4
    total_height = len(lines) * line_height
    content_top = cell["y1"] + padding
    content_bottom = cell["y2"] - padding
    available_height = content_bottom - content_top
    start_y = content_top + (available_height - total_height) // 2
    start_y = max(content_top, min(start_y, content_bottom - total_height))
    start_y += text_offset_y

    for index, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        line_x = (cell["center_x"] - text_width // 2) + text_offset_x
        line_x = max(
            cell["x1"] + padding, min(line_x, cell["x2"] - padding - text_width)
        )
        line_y = start_y + index * line_height
        draw.text((line_x, line_y), line, font=font, fill=fill_color)


def draw_free_image_in_cell(
    image: Image.Image,
    cell: dict,
    free_image: Image.Image,
    text_offset_x: int,
    text_offset_y: int,
    icon_size_ratio: float,
):
    if free_image is None:
        return

    padding = 8
    base_max_width = max(1, cell["width"] - (padding * 2))
    base_max_height = max(1, cell["height"] - (padding * 2))
    max_width = max(1, int(base_max_width * icon_size_ratio))
    max_height = max(1, int(base_max_height * icon_size_ratio))

    badge = free_image.copy()
    badge.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    paste_x = (cell["center_x"] - badge.width // 2) + text_offset_x
    paste_y = (cell["center_y"] - badge.height // 2) + text_offset_y
    paste_x = max(
        cell["x1"] + padding, min(paste_x, cell["x2"] - padding - badge.width)
    )
    paste_y = max(
        cell["y1"] + padding, min(paste_y, cell["y2"] - padding - badge.height)
    )
    image.paste(badge, (paste_x, paste_y), badge)


def get_placeholder_matrix(grid_size: int) -> list[list[str]]:
    return [
        [f"Sample {row + 1}-{col + 1}" for col in range(grid_size)]
        for row in range(grid_size)
    ]


def build_preview(
    template_image: Image.Image,
    matrix: list[list[str]],
    grid_size: int,
    text_color_hex: str,
    font_size: int,
    text_offset_x: int,
    text_offset_y: int,
    free_icon_size: float,
    grid_x: int,
    grid_y: int,
    cell_width: int,
    cell_height: int,
    show_grid_overlay: bool,
    free_image_path: Path | None = None,
    free_image: Image.Image | None = None,
) -> Image.Image:
    preview = template_image.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    fill_color = tuple(int(text_color_hex[i : i + 2], 16) for i in (1, 3, 5))
    if free_image is None:
        candidate_path = free_image_path or FREE_IMAGE_PATH
        if candidate_path.exists():
            free_image = Image.open(candidate_path).convert("RGBA")
    cells = build_uniform_grid_cells(
        grid_size=grid_size,
        grid_x=grid_x,
        grid_y=grid_y,
        cell_width=cell_width,
        cell_height=cell_height,
    )

    for cell in cells:
        row, col = cell["row"], cell["col"]
        if row < len(matrix) and col < len(matrix[row]):
            cell_text = matrix[row][col]
            if is_free_cell_text(cell_text) and free_image is not None:
                draw_free_image_in_cell(
                    preview,
                    cell,
                    free_image,
                    text_offset_x=text_offset_x,
                    text_offset_y=text_offset_y,
                    icon_size_ratio=free_icon_size,
                )
            else:
                draw_text_in_cell(
                    draw=draw,
                    text=cell_text,
                    cell=cell,
                    font=font,
                    fill_color=fill_color,
                    text_offset_x=text_offset_x,
                    text_offset_y=text_offset_y,
                )

    if show_grid_overlay:
        for cell in cells:
            draw.rectangle(
                [(cell["x1"], cell["y1"]), (cell["x2"], cell["y2"])],
                outline=(255, 0, 0),
                width=2,
            )
    return preview
