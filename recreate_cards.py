import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np

TEMPLATE_PATH = Path("Carton-v1.png")
OUTPUT_JSON_PATH = Path("output.json")
OUTPUT_DIR = Path("output_cards")

# Configuration for grid detection
LINE_THRESHOLD = 100  # Threshold for line detection
MIN_LINE_LENGTH = 50  # Minimum line length to consider
MAX_LINE_GAP = 10  # Maximum gap in lines
FONT_SIZE = 26
TEXT_COLOR = (0, 0, 0)  # Black text
TEXT_Y_PADDING = 0  # Vertical padding to move text lower in each cell (in pixels)
FREE_IMAGE_PATH = Path("freee.png")
FREE_ICON_SIZE = 0.85  # Ratio of cell size used for FREE icon


def is_free_cell_text(text: str) -> bool:
    normalized = "".join(char for char in text.upper() if char.isalpha())
    return normalized == "FREE"


def get_grid_size(matrix):
    """Determine grid size from matrix"""
    return len(matrix)


def load_cards_from_json(json_path):
    """Load card data from JSON file"""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_template(template_path):
    """Load template image"""
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    return Image.open(template_path)


def detect_grid_cells(template_image, grid_size):
    """Detect grid cells by finding actual cell contours"""
    # Convert PIL image to OpenCV format
    cv_image = cv2.cvtColor(np.array(template_image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

    # Find grid lines using edge detection
    edges = cv2.Canny(gray, 80, 150)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    # Detect individual cells as rectangles
    cells_list = []
    min_cell_area = (
        15000  # Minimum area for a cell (increased to filter smaller contours)
    )
    max_cell_area = 80000  # Maximum area for a cell (reduced upper limit)

    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)

        # Look for 4-cornered rectangles (cells)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            area = w * h
            aspect_ratio = w / h if h != 0 else 0

            # Check if it's a reasonably-sized cell (more square-ish)
            if (
                min_cell_area < area < max_cell_area and 0.7 < aspect_ratio < 1.3
            ):  # More strict square requirement

                # Get the corners of the contour for better accuracy
                corners = approx.reshape(-1, 2)
                cells_list.append(
                    {
                        "contour": corners,
                        "x": x,
                        "y": y,
                        "w": w,
                        "h": h,
                        "area": area,
                        "center_x": x + w // 2,
                        "center_y": y + h // 2,
                    }
                )

    if len(cells_list) < grid_size * grid_size:
        print(
            f"Warning: Found {len(cells_list)} cells, expected {grid_size * grid_size}. Falling back to grid division."
        )
        # Fallback to original method
        return detect_grid_cells_fallback(template_image, grid_size)

    # Use fallback method for more reliable cell detection
    print("Using grid division method for cell detection...")
    return detect_grid_cells_fallback(template_image, grid_size)

    # Group cells by row (y position with tolerance)
    # Sort by y position first
    cells_list = sorted(cells_list, key=lambda c: c["y"])

    rows = []
    current_row = []
    row_tolerance = 30  # Cells within this y-distance are in the same row

    for cell_info in cells_list:
        if not current_row:
            current_row.append(cell_info)
        elif abs(cell_info["y"] - current_row[0]["y"]) <= row_tolerance:
            # Same row
            current_row.append(cell_info)
        else:
            # New row
            rows.append(current_row)
            current_row = [cell_info]

    if current_row:
        rows.append(current_row)

    print(f"Grouped into {len(rows)} rows")

    # Filter to match expected grid size - take only grid_size rows and grid_size cols per row
    # Also deduplicate cells with very similar coordinates
    deduplicated_rows = []

    for row_cells in rows[:grid_size]:  # Keep only first N rows
        row_cells = sorted(row_cells, key=lambda c: c["x"])
        # Deduplicate: remove cells that are too close to each other
        unique_cells = []
        for cell in row_cells:
            # Check if this cell is too close to an already-added cell
            is_duplicate = False
            for existing_cell in unique_cells:
                # If coordinates are within 20 pixels, consider it a duplicate
                if (
                    abs(cell["x"] - existing_cell["x"]) < 20
                    and abs(cell["y"] - existing_cell["y"]) < 20
                    and abs(cell["w"] - existing_cell["w"]) < 20
                    and abs(cell["h"] - existing_cell["h"]) < 20
                ):
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_cells.append(cell)

        deduplicated_rows.append(unique_cells[:grid_size])

    rows = deduplicated_rows

    # Organize into grid by row and column
    cells = []

    for row_idx, row_cells in enumerate(rows):
        # Sort cells in this row by x position (left to right)
        row_cells = sorted(row_cells, key=lambda c: c["x"])

        for col_idx, cell_info in enumerate(
            row_cells[:grid_size]
        ):  # Limit to grid_size columns
            cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "x1": cell_info["x"],
                    "y1": cell_info["y"],
                    "x2": cell_info["x"] + cell_info["w"],
                    "y2": cell_info["y"] + cell_info["h"],
                    "center_x": cell_info["center_x"],
                    "center_y": cell_info["center_y"],
                    "width": cell_info["w"],
                    "height": cell_info["h"],
                    "corners": cell_info["contour"],
                }
            )

    print(f"Detected {len(cells)} individual cells in {len(rows)}x{grid_size} grid")
    return cells


def detect_grid_cells_fallback(template_image, grid_size):
    """Fallback grid detection using simple bounding box division"""
    # Convert PIL image to OpenCV format
    cv_image = cv2.cvtColor(np.array(template_image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

    # Find grid lines using edge detection
    edges = cv2.Canny(gray, 80, 150)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    # Find the bounding box of the main grid (largest rectangular contour)
    grid_box = None
    max_area = 0

    for contour in contours:
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) >= 4:
            x, y, w, h = cv2.boundingRect(approx)
            area = w * h
            # Look for a large rectangular region (the grid)
            if area > max_area and w > 300 and h > 300:
                max_area = area
                grid_box = (x, y, w, h)

    if grid_box is None:
        print("Warning: Could not find grid boundaries.")
        # Use entire image as fallback
        h, w = template_image.size[::-1]
        grid_box = (50, 50, w - 100, h - 100)

    x, y, w, h = grid_box
    print(f"Grid bounding box: x={x}, y={y}, width={w}, height={h}")

    # Divide grid into cells based on grid_size
    cell_width = w // grid_size
    cell_height = h // grid_size

    cells = []
    for row in range(grid_size):
        for col in range(grid_size):
            cell_x1 = x + col * cell_width
            cell_y1 = y + row * cell_height
            cell_x2 = cell_x1 + cell_width
            cell_y2 = cell_y1 + cell_height

            cells.append(
                {
                    "row": row,
                    "col": col,
                    "x1": cell_x1,
                    "y1": cell_y1,
                    "x2": cell_x2,
                    "y2": cell_y2,
                    "center_x": (cell_x1 + cell_x2) // 2,
                    "center_y": (cell_y1 + cell_y2) // 2,
                    "width": cell_width,
                    "height": cell_height,
                }
            )

    print(f"Detected {len(cells)} cells in a {grid_size}x{grid_size} grid")
    return cells


def wrap_text(text, max_width, font, draw):
    """Wrap text to fit within max width"""
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


def draw_text_in_cell(draw, text, cell, font, fill_color=TEXT_COLOR):
    """Draw text centered in a cell with word wrapping and padding"""
    if not text or text.strip() == "":
        return

    # Add significant padding from cell borders
    padding = 15
    max_width = cell["width"] - (padding * 2)

    lines = wrap_text(text, max_width, font, draw)

    if not lines:
        return

    # Calculate dimensions for centering
    line_height = font.size + 4
    total_height = len(lines) * line_height

    # Calculate vertical bounds with padding
    content_top = cell["y1"] + padding
    content_bottom = cell["y2"] - padding
    available_height = content_bottom - content_top

    # Vertical centering: position so text block is centered within padded area
    start_y = content_top + (available_height - total_height) // 2

    # Clamp start_y to prevent overflow
    start_y = max(content_top, min(start_y, content_bottom - total_height))

    # Apply vertical padding offset to move text lower
    start_y = start_y + TEXT_Y_PADDING

    for i, line in enumerate(lines):
        # Get accurate text dimensions
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]

        # Horizontal centering within cell (with padding)
        line_x = cell["center_x"] - text_width // 2
        # Clamp horizontal position
        line_x = max(
            cell["x1"] + padding, min(line_x, cell["x2"] - padding - text_width)
        )

        # Vertical position for this line
        line_y = start_y + i * line_height

        draw.text((line_x, line_y), line, font=font, fill=fill_color)


def draw_free_image_in_cell(
    image, cell, free_image, text_y_padding=TEXT_Y_PADDING, icon_size_ratio=FREE_ICON_SIZE
):
    """Draw FREE badge image centered in a cell."""
    if free_image is None:
        return

    padding = 8
    base_max_width = max(1, cell["width"] - (padding * 2))
    base_max_height = max(1, cell["height"] - (padding * 2))
    max_width = max(1, int(base_max_width * icon_size_ratio))
    max_height = max(1, int(base_max_height * icon_size_ratio))

    badge = free_image.copy()
    badge.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    paste_x = cell["center_x"] - badge.width // 2
    paste_y = (cell["center_y"] - badge.height // 2) + text_y_padding
    paste_y = max(cell["y1"] + padding, min(paste_y, cell["y2"] - padding - badge.height))
    image.paste(badge, (paste_x, paste_y), badge)


def clear_cell_content(image, cell):
    """Clear existing content in a cell by filling with white"""
    draw = ImageDraw.Draw(image)
    # Add small padding to avoid clearing the border
    padding = 2
    draw.rectangle(
        [
            cell["x1"] + padding,
            cell["y1"] + padding,
            cell["x2"] - padding,
            cell["y2"] - padding,
        ],
        fill=(255, 255, 255),  # White
        outline=None,
    )


def create_card_image(template, card_data, cells, font):
    """Create a card image by placing song names in detected cells"""
    image = template.copy()
    matrix = card_data["songs_matrix"]
    free_image = None
    if FREE_IMAGE_PATH.exists():
        free_image = Image.open(FREE_IMAGE_PATH).convert("RGBA")

    # Sort cells by row and column
    cells = sorted(cells, key=lambda c: (c["row"], c["col"]))

    # Place text in cells
    for cell in cells:
        row = cell["row"]
        col = cell["col"]

        # Add song text if available
        if row < len(matrix) and col < len(matrix[row]):
            song_text = matrix[row][col]
            if is_free_cell_text(song_text) and free_image is not None:
                draw_free_image_in_cell(
                    image,
                    cell,
                    free_image,
                    text_y_padding=TEXT_Y_PADDING,
                    icon_size_ratio=FREE_ICON_SIZE,
                )
            else:
                draw = ImageDraw.Draw(image)
                draw_text_in_cell(draw, song_text, cell, font)

    return image


def recreate_cards_from_json():
    """Main function to recreate cards from JSON"""
    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Load template
    print(f"Loading template from {TEMPLATE_PATH}...")
    template = load_template(TEMPLATE_PATH)

    # Load cards from JSON first to get grid size
    print(f"Loading cards from {OUTPUT_JSON_PATH}...")
    cards = load_cards_from_json(OUTPUT_JSON_PATH)

    if not cards:
        print("Error: No cards found in JSON")
        return

    # Get grid size from first card
    grid_size = len(cards[0]["songs_matrix"])
    print(f"Grid size: {grid_size}x{grid_size}")

    # Detect grid cells in template
    print("Detecting grid cells in template...")
    cells = detect_grid_cells(template, grid_size)
    if cells is None:
        print("Error: Could not detect grid cells. Exiting.")
        return

    # Try to load a font, fall back to default if not available
    try:
        font = ImageFont.truetype("arial.ttf", FONT_SIZE)
    except (OSError, IOError):
        print("Warning: Arial font not found, using default font")
        font = ImageFont.load_default()

    # Process each card
    for card_data in cards:
        card_number = card_data["card_number"]
        matrix = card_data["songs_matrix"]

        print(f"Processing card #{card_number}...")

        # Create card image
        card_image = create_card_image(template, card_data, cells, font)

        # Save card
        output_path = OUTPUT_DIR / f"card_{card_number:02d}.png"
        card_image.save(output_path)
        print(f"  Saved to {output_path}")

    print(f"\nAll {len(cards)} cards have been recreated and saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    try:
        recreate_cards_from_json()
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {OUTPUT_JSON_PATH}")
    except Exception as e:
        print(f"Unexpected error: {e}")
