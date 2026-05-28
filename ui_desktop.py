from pathlib import Path
import os
import json
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
import cv2
import numpy as np
import pdfplumber
from PIL import Image, ImageDraw, ImageFont, ImageTk

from main import extract_bingo_cards, infer_grid_size, infer_grid_size_from_layout
from recreate_cards import detect_grid_cells_fallback


SUPPORTED_GRID_SIZES = (3, 4, 5, 6)
FREE_IMAGE_PATH = Path("freee.png")
FREE_ICON_SIZE_DEFAULT = 0.85
APP_STATE_PATH = Path("ui_desktop_state.json")


def get_windows_work_area() -> tuple[int, int, int, int] | None:
    if os.name != "nt":
        return None
    rect = wintypes.RECT()
    SPI_GETWORKAREA = 0x0030
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
    )
    if not ok:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def is_free_cell_text(text: str) -> bool:
    normalized = "".join(char for char in text.upper() if char.isalpha())
    return normalized == "FREE"


def normalize_song_name(text: str) -> str:
    cleaned = (text or "").strip()
    while cleaned.startswith("-"):
        cleaned = cleaned[1:].lstrip()
    return cleaned


def kmeans_1d(values: list[float], k: int, iterations: int = 30) -> list[float]:
    if not values:
        return []

    sorted_values = sorted(values)
    minimum = sorted_values[0]
    maximum = sorted_values[-1]
    if k == 1:
        return [(minimum + maximum) / 2]

    centers = [minimum + (maximum - minimum) * i / (k - 1) for i in range(k)]

    for _ in range(iterations):
        groups = [[] for _ in range(k)]
        for value in sorted_values:
            closest_center = min(
                range(k), key=lambda i, target=value: abs(target - centers[i])
            )
            groups[closest_center].append(value)

        updated = [
            sum(group) / len(group) if group else centers[i]
            for i, group in enumerate(groups)
        ]
        if all(abs(old - new) < 1e-3 for old, new in zip(centers, updated)):
            break
        centers = updated

    return sorted(centers)


def nearest_center_distance(value: float, centers: list[float]) -> float:
    if not centers:
        return 0.0
    return min(abs(value - center) for center in centers)


def closest_center_index(value: float, centers: list[float]) -> int:
    return min(range(len(centers)), key=lambda idx: abs(value - centers[idx]))


def extract_filtered_words(page) -> list[dict]:
    words = page.extract_words(
        x_tolerance=1,
        y_tolerance=1,
        keep_blank_chars=False,
        use_text_flow=True,
    )
    if not words:
        return []

    card_word_tops = [
        word["top"] for word in words if word["text"].strip().lower() == "card"
    ]
    cutoff_top = min(card_word_tops) + 20 if card_word_tops else 0
    return [word for word in words if word["top"] > cutoff_top and word["text"].strip()]
    


def detect_main_grid_box(gray_image: np.ndarray) -> tuple[int, int, int, int] | None:
    edges = cv2.Canny(gray_image, 80, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    image_h, image_w = gray_image.shape[:2]
    image_area = image_w * image_h

    best_box = None
    best_area = 0

    for contour in contours:
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) < 4:
            continue

        x, y, w, h = cv2.boundingRect(approx)
        area = w * h
        aspect_ratio = w / h if h else 0
        if area < image_area * 0.08:
            continue
        if not (0.65 <= aspect_ratio <= 1.35):
            continue
        if area > best_area:
            best_area = area
            best_box = (x, y, w, h)

    return best_box


def cluster_line_positions(indices: np.ndarray, tolerance: int = 8) -> list[int]:
    if indices.size == 0:
        return []

    sorted_indices = sorted(int(value) for value in indices.tolist())
    groups: list[list[int]] = [[sorted_indices[0]]]
    for value in sorted_indices[1:]:
        if value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [int(round(sum(group) / len(group))) for group in groups]


def snap_to_expected_lines(line_positions: list[int], expected_count: int) -> list[int]:
    if not line_positions:
        return []
    line_positions = sorted(line_positions)
    if len(line_positions) == expected_count:
        return line_positions
    if len(line_positions) < 2:
        return line_positions

    left = line_positions[0]
    right = line_positions[-1]
    step = (right - left) / (expected_count - 1)
    snapped: list[int] = []
    for index in range(expected_count):
        target = left + (index * step)
        nearest = min(line_positions, key=lambda value, t=target: abs(value - t))
        if snapped and nearest <= snapped[-1]:
            nearest = snapped[-1] + max(1, int(step * 0.5))
        snapped.append(nearest)

    return snapped


def derive_grid_lines(binary_crop: np.ndarray, grid_size: int) -> tuple[list[int], list[int]]:
    crop_h, crop_w = binary_crop.shape[:2]
    vertical_projection = binary_crop.sum(axis=0) / 255.0
    horizontal_projection = binary_crop.sum(axis=1) / 255.0

    vertical_hits = np.nonzero(vertical_projection > (crop_h * 0.45))[0]
    horizontal_hits = np.nonzero(horizontal_projection > (crop_w * 0.45))[0]

    x_lines = cluster_line_positions(vertical_hits, tolerance=max(6, crop_w // 140))
    y_lines = cluster_line_positions(horizontal_hits, tolerance=max(6, crop_h // 140))

    expected = grid_size + 1
    x_lines = snap_to_expected_lines(x_lines, expected)
    y_lines = snap_to_expected_lines(y_lines, expected)

    # Keep detected outer lines, but nudge them slightly inward to avoid drawing
    # over rounded template borders.
    outer_inset_x = max(1, crop_w // 220)
    outer_inset_y = max(1, crop_h // 220)
    if len(x_lines) == expected:
        x_lines[0] = min(crop_w - 2, x_lines[0] + outer_inset_x)
        x_lines[-1] = max(1, x_lines[-1] - outer_inset_x)
    if len(y_lines) == expected:
        y_lines[0] = min(crop_h - 2, y_lines[0] + outer_inset_y)
        y_lines[-1] = max(1, y_lines[-1] - outer_inset_y)

    # Extra stabilization for right outer border: align to strongest long vertical line.
    if len(x_lines) == expected:
        strong_vertical = np.nonzero(vertical_projection > (crop_h * 0.6))[0]
        if strong_vertical.size > 0:
            right_candidate = int(strong_vertical[-1]) - outer_inset_x
            min_allowed = x_lines[-2] + max(6, crop_w // (grid_size * 6))
            x_lines[-1] = max(min_allowed, min(crop_w - 1, right_candidate))

        # If the last column width is an outlier (common right-edge overshoot),
        # snap it to the expected spacing pattern.
        x_steps = [x_lines[i + 1] - x_lines[i] for i in range(len(x_lines) - 1)]
        if len(x_steps) >= 3:
            median_step = int(np.median(x_steps[:-1]))
            if median_step > 0 and x_steps[-1] > int(median_step * 1.35):
                corrected_right = x_lines[0] + (median_step * grid_size)
                min_allowed = x_lines[-2] + max(4, median_step // 2)
                x_lines[-1] = max(min_allowed, min(crop_w - 1, corrected_right))
    return x_lines, y_lines


def detect_grid_cells_precise(template_image: Image.Image, grid_size: int) -> list[dict]:
    cv_image = cv2.cvtColor(np.array(template_image.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    grid_box = detect_main_grid_box(gray)
    if not grid_box:
        return detect_grid_cells_fallback(template_image, grid_size)

    x, y, w, h = grid_box
    crop = gray[y : y + h, x : x + w]
    binary = cv2.adaptiveThreshold(
        crop, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )
    x_lines, y_lines = derive_grid_lines(binary, grid_size)
    if len(x_lines) != grid_size + 1 or len(y_lines) != grid_size + 1:
        return detect_grid_cells_fallback(template_image, grid_size)

    x_lines = [x + value for value in x_lines]
    y_lines = [y + value for value in y_lines]

    cells: list[dict] = []
    for row in range(grid_size):
        for col in range(grid_size):
            x1 = x_lines[col]
            x2 = x_lines[col + 1]
            y1 = y_lines[row]
            y2 = y_lines[row + 1]
            cell_w = max(1, x2 - x1)
            cell_h = max(1, y2 - y1)
            cells.append(
                {
                    "row": row,
                    "col": col,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "center_x": x1 + (cell_w // 2),
                    "center_y": y1 + (cell_h // 2),
                    "width": cell_w,
                    "height": cell_h,
                }
            )
    return cells


def unique_positions(values: list[int], tolerance: int = 3) -> list[int]:
    if not values:
        return []
    sorted_values = sorted(values)
    groups: list[list[int]] = [[sorted_values[0]]]
    for value in sorted_values[1:]:
        if abs(value - groups[-1][-1]) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [int(round(sum(group) / len(group))) for group in groups]


def score_grid_alignment(edges: np.ndarray, cells: list[dict], size: int) -> float:
    if not cells:
        return -1.0
    x_lines = unique_positions(
        [cell["x1"] for cell in cells] + [cell["x2"] for cell in cells]
    )
    y_lines = unique_positions(
        [cell["y1"] for cell in cells] + [cell["y2"] for cell in cells]
    )
    if len(x_lines) != size + 1 or len(y_lines) != size + 1:
        return -1.0

    edge_h, edge_w = edges.shape[:2]
    band = 2
    values: list[float] = []

    for x in x_lines:
        x0 = max(0, x - band)
        x1 = min(edge_w, x + band + 1)
        if x1 > x0:
            values.append(float(edges[:, x0:x1].mean()))
    for y in y_lines:
        y0 = max(0, y - band)
        y1 = min(edge_h, y + band + 1)
        if y1 > y0:
            values.append(float(edges[y0:y1, :].mean()))

    return float(sum(values) / len(values)) if values else -1.0


def detect_template_layout(template_image: Image.Image) -> int:
    cv_image = cv2.cvtColor(np.array(template_image.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 150)

    best_size = 5
    best_score = -1.0
    for size in SUPPORTED_GRID_SIZES:
        cells = detect_grid_cells_fallback(template_image, size)
        score = score_grid_alignment(edges, cells, size)
        if score > best_score:
            best_score = score
            best_size = size

    return best_size


def detect_pdf_layout(pdf_path: Path) -> int:
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if "Card #" not in page_text:
                continue
            layout_size = infer_grid_size_from_layout(page)
            if layout_size:
                return layout_size
            filtered_words = extract_filtered_words(page)
            if filtered_words:
                return infer_grid_size(filtered_words)
    return 5


def extract_first_card_matrix(pdf_path: Path, grid_size: int) -> list[list[str]] | None:
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if "Card #" not in page_text:
                continue
            filtered_words = extract_filtered_words(page)
            if not filtered_words:
                continue

            x_centers = kmeans_1d([word["x0"] for word in filtered_words], grid_size)
            y_centers = kmeans_1d([word["top"] for word in filtered_words], grid_size)
            if len(x_centers) != grid_size or len(y_centers) != grid_size:
                continue

            cells = [[[] for _ in range(grid_size)] for _ in range(grid_size)]
            for word in filtered_words:
                col = closest_center_index(word["x0"], x_centers)
                row = closest_center_index(word["top"], y_centers)
                cells[row][col].append(word)

            matrix: list[list[str]] = []
            for row in range(grid_size):
                row_values = []
                for col in range(grid_size):
                    bucket = sorted(
                        cells[row][col], key=lambda word: (word["top"], word["x0"])
                    )
                    raw_name = " ".join(word["text"] for word in bucket).strip()
                    row_values.append(normalize_song_name(raw_name))
                matrix.append(row_values)
            return matrix
    return None


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
    paste_x = max(cell["x1"] + padding, min(paste_x, cell["x2"] - padding - badge.width))
    paste_y = max(cell["y1"] + padding, min(paste_y, cell["y2"] - padding - badge.height))
    image.paste(badge, (paste_x, paste_y), badge)


def get_placeholder_matrix(grid_size: int) -> list[list[str]]:
    return [
        [f"Sample {row + 1}-{col + 1}" for col in range(grid_size)]
        for row in range(grid_size)
    ]


def build_uniform_grid_cells(
    reference_cells: list[dict],
    grid_size: int,
    offset_x: int,
    offset_y: int,
    cell_width_adjust: int,
    cell_height_adjust: int,
) -> list[dict]:
    if not reference_cells:
        return []

    start_x = min(cell["x1"] for cell in reference_cells) + offset_x
    start_y = min(cell["y1"] for cell in reference_cells) + offset_y
    detected_widths = [cell["width"] for cell in reference_cells]
    detected_heights = [cell["height"] for cell in reference_cells]
    base_cell_width = int(round(float(np.median(detected_widths)))) if detected_widths else 120
    base_cell_height = int(round(float(np.median(detected_heights)))) if detected_heights else 120
    cell_width = max(20, base_cell_width + cell_width_adjust)
    cell_height = max(20, base_cell_height + cell_height_adjust)

    uniform_cells: list[dict] = []
    for row in range(grid_size):
        for col in range(grid_size):
            x1 = start_x + (col * cell_width)
            y1 = start_y + (row * cell_height)
            x2 = x1 + cell_width
            y2 = y1 + cell_height
            uniform_cells.append(
                {
                    "row": row,
                    "col": col,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "center_x": x1 + (cell_width // 2),
                    "center_y": y1 + (cell_height // 2),
                    "width": cell_width,
                    "height": cell_height,
                }
            )
    return uniform_cells


def build_preview(
    template_image: Image.Image,
    matrix: list[list[str]],
    grid_size: int,
    text_color_hex: str,
    font_size: int,
    text_offset_x: int,
    text_offset_y: int,
    free_icon_size: float,
    grid_offset_x: int,
    grid_offset_y: int,
    manual_cell_width: int,
    manual_cell_height: int,
    show_grid_overlay: bool,
    free_image_path: Path | None = None,
) -> Image.Image:
    preview = template_image.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    fill_color = tuple(int(text_color_hex[i : i + 2], 16) for i in (1, 3, 5))
    free_image = None
    candidate_path = free_image_path or FREE_IMAGE_PATH
    if candidate_path.exists():
        free_image = Image.open(candidate_path).convert("RGBA")
    cells = detect_grid_cells_precise(preview, grid_size)
    cells = sorted(cells, key=lambda c: (c["row"], c["col"]))
    cells = build_uniform_grid_cells(
        reference_cells=cells,
        grid_size=grid_size,
        offset_x=grid_offset_x,
        offset_y=grid_offset_y,
        cell_width_adjust=manual_cell_width,
        cell_height_adjust=manual_cell_height,
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


class BingoDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Bingo Card Designer")
        self.geometry("1380x900")
        self.minsize(1200, 780)
        self.after(0, lambda: self.state("zoomed"))

        self.template_path: Path | None = None
        self.pdf_path: Path | None = None
        self.template_image: Image.Image | None = None
        self.template_layout: int | None = None
        self.pdf_layout: int | None = None
        self.output_dir: Path | None = None
        self.free_icon_path: Path | None = None
        self.preview_photo = None
        self.preview_base_image: Image.Image | None = None
        self.preview_image_id: int | None = None
        self.preview_zoom = 1.0
        self.preview_zoom_label_var = tk.StringVar(value="100%")
        self._pending_fit_zoom = False
        self._preview_h_scroll_visible = True
        self._preview_v_scroll_visible = True
        self.cached_pdf_cards: list[dict] | None = None
        self.music_name_overrides: dict[str, str] = {}
        self.tutorial_seen = False
        self._tutorial_tooltip: ctk.CTkToplevel | None = None
        self._tutorial_target_widget = None
        self._tutorial_target_restore: dict[str, object] | None = None
        self._tutorial_steps: list[dict] = []
        self._tutorial_step_index = 0

        self.text_color_var = tk.StringVar(value="#000000")
        self.font_size_var = tk.IntVar(value=26)
        self.text_offset_x_var = tk.IntVar(value=0)
        self.text_offset_y_var = tk.IntVar(value=0)
        self.free_icon_size_var = tk.DoubleVar(value=FREE_ICON_SIZE_DEFAULT)
        self.grid_offset_x_var = tk.IntVar(value=0)
        self.grid_offset_y_var = tk.IntVar(value=0)
        self.manual_cell_width_var = tk.IntVar(value=0)
        self.manual_cell_height_var = tk.IntVar(value=0)
        self.show_grid_overlay_var = tk.BooleanVar(value=True)
        self.grid_settings_expanded = False
        self.text_settings_expanded = False
        self._loading_state = False

        self._build_layout()
        self._load_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(450, self._show_tutorial_if_needed)

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        controls = ctk.CTkScrollableFrame(self, corner_radius=12, width=380)
        controls.grid(row=0, column=0, sticky="nsw", padx=(16, 8), pady=16)
        controls.grid_columnconfigure(0, weight=1)
        self.controls_scrollable = controls

        ctk.CTkLabel(
            controls,
            text="Bingo Card Designer",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        ctk.CTkLabel(
            controls,
            text="Source",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=1, column=0, padx=16, pady=(8, 6), sticky="w")

        self.select_template_button = ctk.CTkButton(
            controls,
            text="Select Template Image",
            command=self._select_template,
            height=36,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.select_template_button.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="ew")

        self.template_layout_label = ctk.CTkLabel(
            controls, text="Template layout: -", anchor="w"
        )
        self.template_layout_label.grid(
            row=3, column=0, padx=16, pady=(0, 14), sticky="ew"
        )

        self.import_pdf_button = ctk.CTkButton(
            controls,
            text="Import Cards PDF",
            command=self._select_pdf,
            height=36,
            fg_color="#0ea5e9",
            hover_color="#0284c7",
        )
        self.import_pdf_button.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="ew")

        self.pdf_layout_label = ctk.CTkLabel(controls, text="PDF layout: -", anchor="w")
        self.pdf_layout_label.grid(row=5, column=0, padx=16, pady=(0, 14), sticky="ew")
        self.edit_music_button = ctk.CTkButton(
            controls,
            text="Edit Music Names",
            command=self._open_music_name_editor,
            height=34,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            state="disabled",
        )
        self.edit_music_button.grid(row=6, column=0, padx=16, pady=(0, 12), sticky="ew")

        ctk.CTkFrame(controls, height=2, fg_color="#6b7280", corner_radius=0).grid(
            row=7, column=0, padx=16, pady=(4, 12), sticky="ew"
        )
        ctk.CTkLabel(
            controls,
            text="Customize",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=8, column=0, padx=16, pady=(0, 6), sticky="w")

        self.text_settings_toggle_button = ctk.CTkButton(
            controls,
            text="▶ Text Settings",
            command=self._toggle_text_settings,
            height=32,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        self.text_settings_toggle_button.grid(
            row=9, column=0, padx=16, pady=(0, 10), sticky="ew"
        )

        self.text_settings_frame = ctk.CTkFrame(controls, corner_radius=8)
        self.text_settings_frame.grid_columnconfigure(0, weight=1)

        color_row = ctk.CTkFrame(self.text_settings_frame, fg_color="transparent")
        color_row.grid(row=0, column=0, padx=10, pady=(10, 8), sticky="ew")
        color_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(color_row, text="Text Color (#RRGGBB)").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        ctk.CTkEntry(color_row, textvariable=self.text_color_var, width=110).grid(
            row=0, column=1, padx=(0, 6), sticky="e"
        )
        ctk.CTkButton(
            color_row,
            text="Pick",
            width=60,
            command=self._pick_text_color,
        ).grid(row=0, column=2, sticky="e")

        self.color_swatch = ctk.CTkLabel(
            self.text_settings_frame,
            text="",
            height=18,
            corner_radius=6,
            fg_color=self.text_color_var.get(),
        )
        self.color_swatch.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")

        self.font_size_value_label = self._create_stepper_row(
            self.text_settings_frame,
            row=2,
            label="Font Size",
            variable=self.font_size_var,
            minimum=10,
            maximum=64,
        )
        self.text_offset_x_value_label = self._create_stepper_row(
            self.text_settings_frame,
            row=3,
            label="Text Offset X",
            variable=self.text_offset_x_var,
            minimum=-120,
            maximum=120,
        )
        self.text_offset_y_value_label = self._create_stepper_row(
            self.text_settings_frame,
            row=4,
            label="Text Offset Y",
            variable=self.text_offset_y_var,
            minimum=-120,
            maximum=120,
        )
        self.free_icon_size_value_label = self._create_float_stepper_row(
            self.text_settings_frame,
            row=5,
            label="Free Icon Size",
            variable=self.free_icon_size_var,
            minimum=0.30,
            maximum=1.00,
            step=0.05,
            decimals=2,
        )
        free_icon_row = ctk.CTkFrame(self.text_settings_frame, fg_color="transparent")
        free_icon_row.grid(row=6, column=0, padx=10, pady=(0, 10), sticky="ew")
        free_icon_row.grid_columnconfigure(0, weight=1)
        self.free_icon_path_label = ctk.CTkLabel(
            free_icon_row,
            text=self._format_free_icon_label(),
            anchor="w",
            text_color="#9ca3af",
        )
        self.free_icon_path_label.grid(row=0, column=0, padx=(0, 8), sticky="w")
        ctk.CTkButton(
            free_icon_row,
            text="Select FREE Icon",
            width=140,
            command=self._select_free_icon,
            fg_color="#6b7280",
            hover_color="#4b5563",
        ).grid(row=0, column=1, sticky="e")

        self.grid_settings_toggle_button = ctk.CTkButton(
            controls,
            text="▶ Grid Settings",
            command=self._toggle_grid_settings,
            height=32,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        self.grid_settings_toggle_button.grid(
            row=11, column=0, padx=16, pady=(0, 12), sticky="ew"
        )

        self.grid_settings_frame = ctk.CTkFrame(controls, corner_radius=8)
        self.grid_settings_frame.grid_columnconfigure(0, weight=1)

        grid_overlay_row = ctk.CTkFrame(self.grid_settings_frame, fg_color="transparent")
        grid_overlay_row.grid(row=0, column=0, padx=10, pady=(10, 8), sticky="ew")
        grid_overlay_row.grid_columnconfigure(0, weight=1)
        grid_overlay_row.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(grid_overlay_row, text="Show Preview Grid").grid(
            row=0, column=0, sticky="w"
        )

        overlay_controls = ctk.CTkFrame(
            grid_overlay_row, fg_color="transparent", width=136, height=30
        )
        overlay_controls.grid(row=0, column=1, sticky="e")
        overlay_controls.grid_propagate(False)
        overlay_controls.grid_columnconfigure(0, weight=1)

        self.grid_overlay_switch = ctk.CTkSwitch(
            overlay_controls,
            text="",
            width=46,
            switch_width=36,
            variable=self.show_grid_overlay_var,
            command=self._refresh_preview,
        )
        self.grid_overlay_switch.grid(row=0, column=0, sticky="e")

        self.grid_offset_x_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=1,
            label="Grid Offset X",
            variable=self.grid_offset_x_var,
            minimum=-300,
            maximum=300,
        )
        self.grid_offset_y_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=2,
            label="Grid Offset Y",
            variable=self.grid_offset_y_var,
            minimum=-300,
            maximum=300,
        )
        self.manual_cell_width_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=3,
            label="Cell Width Adjust",
            variable=self.manual_cell_width_var,
            minimum=-120,
            maximum=120,
        )
        self.manual_cell_height_value_label = self._create_stepper_row(
            self.grid_settings_frame,
            row=4,
            label="Cell Height Adjust",
            variable=self.manual_cell_height_var,
            minimum=-120,
            maximum=120,
        )
        ctk.CTkButton(
            controls,
            text="Reset Configs",
            command=self._reset_configs,
            height=34,
            fg_color="#6b7280",
            hover_color="#4b5563",
        ).grid(row=13, column=0, padx=16, pady=(10, 12), sticky="ew")

        ctk.CTkFrame(controls, height=2, fg_color="#6b7280", corner_radius=0).grid(
            row=14, column=0, padx=16, pady=(2, 12), sticky="ew"
        )
        ctk.CTkLabel(
            controls,
            text="Output",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=15, column=0, padx=16, pady=(0, 6), sticky="w")
        self.output_folder_button = ctk.CTkButton(
            controls,
            text=self._format_output_button_text(),
            command=self._select_output_folder,
            height=36,
            fg_color="#0891b2",
            hover_color="#0e7490",
        )
        self.output_folder_button.grid(row=16, column=0, padx=16, pady=(0, 10), sticky="ew")
        ctk.CTkButton(
            controls,
            text="Open Generated Folder",
            command=self._open_output_folder,
            height=34,
            fg_color="#475569",
            hover_color="#334155",
        ).grid(row=17, column=0, padx=16, pady=(0, 12), sticky="ew")

        ctk.CTkFrame(controls, height=2, fg_color="#6b7280", corner_radius=0).grid(
            row=18, column=0, padx=16, pady=(2, 12), sticky="ew"
        )
        ctk.CTkLabel(
            controls,
            text="Run",
            text_color="#9ca3af",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=19, column=0, padx=16, pady=(0, 6), sticky="w")

        self.generate_button = ctk.CTkButton(
            controls,
            text="Generate Cards",
            command=self._generate_cards,
            fg_color="#16a34a",
            hover_color="#15803d",
            height=38,
        )
        self.generate_button.grid(row=20, column=0, padx=16, pady=(0, 10), sticky="ew")
        self.generate_progress = ctk.CTkProgressBar(controls)
        self.generate_progress.set(0)
        self.generate_progress.grid(row=21, column=0, padx=16, pady=(0, 4), sticky="ew")
        self.generate_status_label = ctk.CTkLabel(
            controls, text="Generation status: idle", anchor="w", text_color="#9ca3af"
        )
        self.generate_status_label.grid(row=22, column=0, padx=16, pady=(0, 16), sticky="ew")
        self.tutorial_button = ctk.CTkButton(
            controls,
            text="Start Tutorial Tour",
            command=self._start_tutorial,
            height=34,
            fg_color="#4f46e5",
            hover_color="#4338ca",
        )
        self.tutorial_button.grid(row=23, column=0, padx=16, pady=(0, 14), sticky="ew")

        preview_frame = ctk.CTkFrame(self, corner_radius=12)
        preview_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            preview_frame,
            text="Live Preview",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, padx=18, pady=(16, 10), sticky="w")

        preview_toolbar = ctk.CTkFrame(preview_frame, fg_color="transparent")
        preview_toolbar.grid(row=0, column=0, padx=18, pady=(16, 10), sticky="e")
        ctk.CTkButton(
            preview_toolbar,
            text="-",
            width=30,
            command=self._zoom_out,
        ).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(
            preview_toolbar,
            textvariable=self.preview_zoom_label_var,
            width=56,
            anchor="center",
        ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            preview_toolbar,
            text="+",
            width=30,
            command=self._zoom_in,
        ).grid(row=0, column=2, padx=(0, 6))
        ctk.CTkButton(
            preview_toolbar,
            text="Reset",
            width=64,
            command=self._zoom_reset,
        ).grid(row=0, column=3)

        preview_viewport = ctk.CTkFrame(preview_frame, corner_radius=8)
        preview_viewport.grid(row=1, column=0, padx=18, pady=(0, 18), sticky="nsew")
        preview_viewport.grid_rowconfigure(0, weight=1)
        preview_viewport.grid_columnconfigure(0, weight=1)

        self.preview_canvas = tk.Canvas(
            preview_viewport,
            bg="#2b2b2b",
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.preview_v_scroll = ctk.CTkScrollbar(
            preview_viewport, orientation="vertical", command=self.preview_canvas.yview
        )
        self.preview_v_scroll.grid(row=0, column=1, sticky="ns")
        self.preview_h_scroll = ctk.CTkScrollbar(
            preview_viewport, orientation="horizontal", command=self.preview_canvas.xview
        )
        self.preview_h_scroll.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.configure(
            xscrollcommand=self.preview_h_scroll.set,
            yscrollcommand=self.preview_v_scroll.set,
        )
        self.preview_canvas.bind("<Control-MouseWheel>", self._on_preview_ctrl_wheel)
        self.preview_canvas.bind("<MouseWheel>", self._on_preview_scroll)
        self.preview_canvas.bind("<Shift-MouseWheel>", self._on_preview_shift_scroll)
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_configure)
        self._show_preview_warning("Select a template image to start.")

        self.text_color_var.trace_add("write", lambda *_args: self._refresh_preview())
        self.font_size_var.trace_add("write", lambda *_args: self._refresh_preview())
        self.text_offset_x_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.text_offset_y_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.free_icon_size_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.grid_offset_x_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.grid_offset_y_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.manual_cell_width_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.manual_cell_height_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )
        self.show_grid_overlay_var.trace_add(
            "write", lambda *_args: self._refresh_preview()
        )

    def _toggle_text_settings(self):
        self.text_settings_expanded = not self.text_settings_expanded
        if self.text_settings_expanded:
            self.text_settings_toggle_button.configure(text="▼ Text Settings")
            self.text_settings_frame.grid(
                row=10, column=0, padx=16, pady=(0, 12), sticky="ew"
            )
        else:
            self.text_settings_toggle_button.configure(text="▶ Text Settings")
            self.text_settings_frame.grid_forget()
        self._save_state()

    def _toggle_grid_settings(self):
        self.grid_settings_expanded = not self.grid_settings_expanded
        if self.grid_settings_expanded:
            self.grid_settings_toggle_button.configure(text="▼ Grid Settings")
            self.grid_settings_frame.grid(
                row=12, column=0, padx=16, pady=(0, 12), sticky="ew"
            )
        else:
            self.grid_settings_toggle_button.configure(text="▶ Grid Settings")
            self.grid_settings_frame.grid_forget()
        self._save_state()

    def _show_tutorial_if_needed(self):
        if not self.tutorial_seen:
            self._start_tutorial()

    def _start_tutorial(self):
        if self._tutorial_tooltip and self._tutorial_tooltip.winfo_exists():
            self._tutorial_position_tooltip()
            self._tutorial_tooltip.lift()
            return

        self._tutorial_steps = [
            {
                "title": "Welcome to Bingo Card Designer",
                "body": (
                    "This tour highlights the main controls directly in the app. "
                    "Use Next/Back below and follow the highlighted element each step."
                ),
                "target": lambda: self.tutorial_button,
                "action": None,
            },
            {
                "title": "Step 1: Select a template image",
                "body": (
                    "Use 'Select Template Image' in Source. This imports the bingo card design where "
                    "text should be drawn. The app detects the template grid layout automatically."
                ),
                "target": lambda: self.select_template_button,
                "action": None,
            },
            {
                "title": "Step 2: Import your cards PDF",
                "body": (
                    "Click 'Import Cards PDF'. This imports your bingo cards and loads all song values "
                    "from the PDF. "
                    "After import, the music-name editor becomes available."
                ),
                "target": lambda: self.import_pdf_button,
                "action": None,
            },
            {
                "title": "Step 3: Edit music names",
                "body": (
                    "Use 'Edit Music Names' to fix OCR inconsistencies or rename entries. "
                    "These overrides are saved and used in preview and final generated cards."
                ),
                "target": lambda: self.edit_music_button,
                "action": None,
            },
            {
                "title": "Step 4: Adjust text settings",
                "body": (
                    "Open 'Text Settings' to control text color, font size, offsets, and FREE icon size. "
                    "All changes are visible immediately in Live Preview."
                ),
                "target": lambda: self.text_settings_toggle_button,
                "action": self._expand_text_settings,
            },
            {
                "title": "Step 5: Align the grid if needed",
                "body": (
                    "Open 'Grid Settings' only if text placement needs correction. "
                    "Use grid offsets and cell width/height adjust to align content to your template."
                ),
                "target": lambda: self.grid_settings_toggle_button,
                "action": self._expand_grid_settings,
            },
            {
                "title": "Step 6: Choose output and generate",
                "body": (
                    "Choose an output folder using the Output button. "
                    "This is where generated bingo cards will be saved."
                ),
                "target": lambda: self.output_folder_button,
                "action": None,
            },
            {
                "title": "Step 7: Generate cards",
                "body": (
                    "Press 'Generate Cards' to create your final PNG bingo cards. "
                    "When complete, use 'Open Generated Folder' to review exports."
                ),
                "target": lambda: self.generate_button,
                "action": None,
            },
        ]
        tooltip = ctk.CTkToplevel(self)
        tooltip.title("Tutorial")
        tooltip.geometry("420x240")
        tooltip.attributes("-topmost", True)
        tooltip.transient(self)
        tooltip.protocol("WM_DELETE_WINDOW", self._close_tutorial)
        tooltip.grid_columnconfigure(0, weight=1)
        tooltip.grid_rowconfigure(1, weight=1)
        self._tutorial_tooltip = tooltip

        self._tutorial_title_label = ctk.CTkLabel(
            tooltip,
            text="",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
            justify="left",
        )
        self._tutorial_title_label.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        self._tutorial_body_label = ctk.CTkLabel(
            tooltip,
            text="",
            anchor="nw",
            justify="left",
            wraplength=390,
        )
        self._tutorial_body_label.grid(row=1, column=0, padx=14, pady=(0, 8), sticky="nsew")

        footer = ctk.CTkFrame(tooltip, fg_color="transparent")
        footer.grid(row=2, column=0, padx=14, pady=(2, 12), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)
        self._tutorial_back_button = ctk.CTkButton(
            footer, text="Back", width=86, command=self._tutorial_prev
        )
        self._tutorial_back_button.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self._tutorial_progress_label = ctk.CTkLabel(
            footer, text="", text_color="#9ca3af", anchor="w"
        )
        self._tutorial_progress_label.grid(row=0, column=1, sticky="w")
        self._tutorial_next_button = ctk.CTkButton(
            footer,
            text="Next",
            width=96,
            command=self._tutorial_next,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self._tutorial_next_button.grid(row=0, column=2, padx=(8, 0), sticky="e")

        self._tutorial_step_index = 0
        self._render_tutorial_step()

    def _expand_text_settings(self):
        if not self.text_settings_expanded:
            self._toggle_text_settings()

    def _expand_grid_settings(self):
        if not self.grid_settings_expanded:
            self._toggle_grid_settings()

    def _render_tutorial_step(self):
        if not self._tutorial_steps:
            return
        self._tutorial_step_index = max(
            0, min(self._tutorial_step_index, len(self._tutorial_steps) - 1)
        )
        current = self._tutorial_steps[self._tutorial_step_index]
        action = current.get("action")
        if callable(action):
            action()
        target_getter = current.get("target")
        target_widget = target_getter() if callable(target_getter) else None
        self._tutorial_ensure_widget_visible(target_widget)
        self._tutorial_highlight_widget(target_widget)
        self._tutorial_title_label.configure(text=current["title"])
        self._tutorial_body_label.configure(text=current["body"])
        self._tutorial_progress_label.configure(
            text=f"Step {self._tutorial_step_index + 1} of {len(self._tutorial_steps)}"
        )
        self._tutorial_position_tooltip()

        if self._tutorial_step_index >= len(self._tutorial_steps) - 1:
            self._tutorial_next_button.configure(text="Finish")
        else:
            self._tutorial_next_button.configure(text="Next")
        self._tutorial_back_button.configure(
            state="normal" if self._tutorial_step_index > 0 else "disabled"
        )

    def _tutorial_position_tooltip(self):
        if not (self._tutorial_tooltip and self._tutorial_tooltip.winfo_exists()):
            return
        self.update_idletasks()
        target = self._tutorial_target_widget
        if not target or not target.winfo_exists():
            return
        self._tutorial_tooltip.update_idletasks()
        work_area = get_windows_work_area()
        if work_area:
            screen_x, screen_y, screen_right, screen_bottom = work_area
            screen_w = screen_right - screen_x
            screen_h = screen_bottom - screen_y
        else:
            screen_x = self.winfo_vrootx()
            screen_y = self.winfo_vrooty()
            screen_w = self.winfo_vrootwidth()
            screen_h = self.winfo_vrootheight()
        target_x = target.winfo_rootx()
        target_y = target.winfo_rooty()
        target_w = target.winfo_width()
        target_h = target.winfo_height()
        tip_w = self._tutorial_tooltip.winfo_width()
        tip_h = self._tutorial_tooltip.winfo_height()
        gap = 14
        margin = 12

        x = target_x + target_w + gap
        y = target_y
        if x + tip_w > (screen_x + screen_w - margin):
            x = target_x - tip_w - gap
        if y + tip_h > (screen_y + screen_h - margin):
            y = target_y + target_h - tip_h

        max_x = (screen_x + screen_w) - tip_w - margin
        max_y = (screen_y + screen_h) - tip_h - margin
        x = max(screen_x + margin, min(x, max_x))
        y = max(screen_y + margin, min(y, max_y))
        self._tutorial_tooltip.geometry(f"+{x}+{y}")

    def _tutorial_ensure_widget_visible(self, widget):
        if widget is None or not widget.winfo_exists():
            return
        self.update_idletasks()
        scrollable = getattr(self, "controls_scrollable", None)
        if scrollable is None:
            return
        canvas = getattr(scrollable, "_parent_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return

        canvas_top = canvas.winfo_rooty()
        canvas_bottom = canvas_top + canvas.winfo_height()
        widget_top = widget.winfo_rooty()
        widget_bottom = widget_top + widget.winfo_height()
        margin = 18
        if widget_top >= canvas_top + margin and widget_bottom <= canvas_bottom - margin:
            return

        try:
            _, content_bottom = canvas.bbox("all")[1], canvas.bbox("all")[3]
            content_height = max(1, content_bottom)
            current_fraction = canvas.yview()[0]
            current_offset = current_fraction * content_height
            delta = 0
            if widget_bottom > canvas_bottom - margin:
                delta = widget_bottom - (canvas_bottom - margin)
            elif widget_top < canvas_top + margin:
                delta = widget_top - (canvas_top + margin)
            target_offset = max(0, min(content_height, current_offset + delta))
            canvas.yview_moveto(target_offset / content_height)
            self.update_idletasks()
        except Exception:
            pass

    def _tutorial_highlight_widget(self, widget):
        self._clear_tutorial_highlight()
        if widget is None or not widget.winfo_exists():
            self._tutorial_target_widget = None
            return
        self._tutorial_target_widget = widget
        restore: dict[str, object] = {}
        try:
            restore["border_width"] = widget.cget("border_width")
            restore["border_color"] = widget.cget("border_color")
            widget.configure(border_width=3, border_color="#f59e0b")
        except Exception:
            try:
                restore["highlightthickness"] = widget.cget("highlightthickness")
                restore["highlightbackground"] = widget.cget("highlightbackground")
                widget.configure(highlightthickness=3, highlightbackground="#f59e0b")
            except Exception:
                pass
        self._tutorial_target_restore = restore

    def _clear_tutorial_highlight(self):
        if (
            self._tutorial_target_widget
            and self._tutorial_target_widget.winfo_exists()
            and self._tutorial_target_restore
        ):
            try:
                if "border_width" in self._tutorial_target_restore:
                    self._tutorial_target_widget.configure(
                        border_width=self._tutorial_target_restore["border_width"],
                        border_color=self._tutorial_target_restore["border_color"],
                    )
                elif "highlightthickness" in self._tutorial_target_restore:
                    self._tutorial_target_widget.configure(
                        highlightthickness=self._tutorial_target_restore["highlightthickness"],
                        highlightbackground=self._tutorial_target_restore["highlightbackground"],
                    )
            except Exception:
                pass
        self._tutorial_target_widget = None
        self._tutorial_target_restore = None

    def _tutorial_next(self):
        if self._tutorial_step_index >= len(self._tutorial_steps) - 1:
            self._close_tutorial(mark_seen=True)
            return
        self._tutorial_step_index += 1
        self._render_tutorial_step()

    def _tutorial_prev(self):
        if self._tutorial_step_index <= 0:
            return
        self._tutorial_step_index -= 1
        self._render_tutorial_step()

    def _close_tutorial(self, mark_seen: bool = True):
        if mark_seen:
            self.tutorial_seen = True
            self._save_state()
        self._clear_tutorial_highlight()
        if self._tutorial_tooltip and self._tutorial_tooltip.winfo_exists():
            self._tutorial_tooltip.destroy()
        self._tutorial_tooltip = None

    def _step_int_var(self, variable: tk.IntVar, delta: int, minimum: int, maximum: int):
        current = int(variable.get())
        variable.set(max(minimum, min(maximum, current + delta)))

    def _create_stepper_row(
        self,
        parent,
        row: int,
        label: str,
        variable: tk.IntVar,
        minimum: int,
        maximum: int,
    ):
        stepper = ctk.CTkFrame(parent, fg_color="transparent")
        stepper.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="ew")
        stepper.grid_columnconfigure(0, weight=1)
        button_width = 32
        value_width = 60

        ctk.CTkLabel(stepper, text=label).grid(row=0, column=0, sticky="w")
        controls = ctk.CTkFrame(stepper, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")
        controls.grid_columnconfigure(0, minsize=button_width)
        controls.grid_columnconfigure(1, minsize=value_width)
        controls.grid_columnconfigure(2, minsize=button_width)

        ctk.CTkButton(
            controls,
            text="-",
            width=button_width,
            command=lambda: self._step_int_var(variable, -1, minimum, maximum),
        ).grid(row=0, column=0, padx=(0, 6))
        value_label = ctk.CTkLabel(controls, text=str(int(variable.get())), width=value_width)
        value_label.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            controls,
            text="+",
            width=button_width,
            command=lambda: self._step_int_var(variable, 1, minimum, maximum),
        ).grid(row=0, column=2)

        return value_label

    def _step_float_var(
        self, variable: tk.DoubleVar, delta: float, minimum: float, maximum: float
    ):
        current = float(variable.get())
        new_value = max(minimum, min(maximum, current + delta))
        variable.set(round(new_value, 2))

    def _create_float_stepper_row(
        self,
        parent,
        row: int,
        label: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
    ):
        stepper = ctk.CTkFrame(parent, fg_color="transparent")
        stepper.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="ew")
        stepper.grid_columnconfigure(0, weight=1)
        button_width = 32
        value_width = 60

        ctk.CTkLabel(stepper, text=label).grid(row=0, column=0, sticky="w")
        controls = ctk.CTkFrame(stepper, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")
        controls.grid_columnconfigure(0, minsize=button_width)
        controls.grid_columnconfigure(1, minsize=value_width)
        controls.grid_columnconfigure(2, minsize=button_width)

        ctk.CTkButton(
            controls,
            text="-",
            width=button_width,
            command=lambda: self._step_float_var(variable, -step, minimum, maximum),
        ).grid(row=0, column=0, padx=(0, 6))
        value_label = ctk.CTkLabel(
            controls, text=f"{float(variable.get()):.{decimals}f}", width=value_width
        )
        value_label.grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            controls,
            text="+",
            width=button_width,
            command=lambda: self._step_float_var(variable, step, minimum, maximum),
        ).grid(row=0, column=2)

        return value_label

    def _select_template(self):
        file_path = filedialog.askopenfilename(
            title="Select template image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        self._load_template_file(Path(file_path), show_error=True)

    def _select_pdf(self):
        file_path = filedialog.askopenfilename(
            title="Select cards PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not file_path:
            return
        self._load_pdf_file(Path(file_path), show_error=True)

    def _effective_grid_size(self) -> int:
        if self.pdf_layout:
            return self.pdf_layout
        if self.template_layout:
            return self.template_layout
        return 5

    def _format_output_button_text(self) -> str:
        if self.output_dir is None:
            return "Browse Output Folder"
        path_text = str(self.output_dir)
        max_len = 38
        if len(path_text) > max_len:
            path_text = f"...{path_text[-(max_len - 3):]}"
        return f"Output: {path_text}"

    def _select_output_folder(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if not folder:
            return
        self.output_dir = Path(folder)
        self.output_folder_button.configure(text=self._format_output_button_text())
        self._save_state()

    def _format_free_icon_label(self) -> str:
        icon_path = self.free_icon_path or FREE_IMAGE_PATH
        if self.free_icon_path:
            label_prefix = "FREE Icon:"
        else:
            label_prefix = "FREE Icon (default):"
        name = icon_path.name
        if len(name) > 24:
            name = f"{name[:10]}...{name[-10:]}"
        return f"{label_prefix} {name}"

    def _select_free_icon(self):
        file_path = filedialog.askopenfilename(
            title="Select FREE icon image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        selected = Path(file_path)
        try:
            Image.open(selected).verify()
        except Exception:
            messagebox.showerror("Invalid Image", "Could not read the selected icon image.")
            return
        self.free_icon_path = selected
        self.free_icon_path_label.configure(text=self._format_free_icon_label())
        self._refresh_preview()

    def _open_output_folder(self):
        if self.output_dir is None:
            messagebox.showwarning(
                "Missing Output Folder", "Please choose an output folder first."
            )
            return
        if not self.output_dir.exists():
            messagebox.showwarning(
                "Missing Folder", f"Output folder does not exist:\n{self.output_dir}"
            )
            return
        os.startfile(self.output_dir)

    def _reset_configs(self):
        self.text_color_var.set("#000000")
        self.font_size_var.set(26)
        self.text_offset_x_var.set(0)
        self.text_offset_y_var.set(0)
        self.free_icon_size_var.set(FREE_ICON_SIZE_DEFAULT)
        self.free_icon_path = None
        self.free_icon_path_label.configure(text=self._format_free_icon_label())
        self.grid_offset_x_var.set(0)
        self.grid_offset_y_var.set(0)
        self.manual_cell_width_var.set(0)
        self.manual_cell_height_var.set(0)
        self.show_grid_overlay_var.set(True)
        self.generate_progress.set(0)
        self.generate_status_label.configure(text="Generation status: idle")
        self._refresh_preview()

    def _generate_cards(self):
        if self.template_image is None or self.template_path is None:
            messagebox.showwarning("Missing Template", "Please select a template image first.")
            return
        if self.pdf_path is None:
            messagebox.showwarning("Missing PDF", "Please import the cards PDF first.")
            return
        if self.output_dir is None:
            messagebox.showwarning(
                "Missing Output Folder", "Please choose an output folder first."
            )
            return
        if (
            self.template_layout
            and self.pdf_layout
            and self.template_layout != self.pdf_layout
        ):
            messagebox.showwarning(
                "Layout Mismatch",
                (
                    f"Template is {self.template_layout}x{self.template_layout} but "
                    f"PDF is {self.pdf_layout}x{self.pdf_layout}.\n"
                    "Use matching layouts before generating cards."
                ),
            )
            return

        self.generate_button.configure(state="disabled")
        self.generate_progress.set(0)
        self.generate_status_label.configure(text="Generation status: preparing...")
        self.update_idletasks()

        try:
            cards = self._get_cached_valid_cards(force_reload=True)
            if not cards:
                self.generate_status_label.configure(text="Generation status: no cards found")
                messagebox.showwarning("No Cards Found", "No cards were extracted from the PDF.")
                return

            total_cards = len(cards)
            if total_cards == 0:
                self.generate_status_label.configure(text="Generation status: no valid cards")
                messagebox.showwarning(
                    "No Cards Found", "No cards with song matrices were extracted."
                )
                return

            generated_count = 0
            for index, card in enumerate(cards, start=1):
                matrix = self._apply_music_name_overrides(card.get("songs_matrix", []))
                grid_size = len(matrix)
                image = build_preview(
                    template_image=self.template_image,
                    matrix=matrix,
                    grid_size=grid_size,
                    text_color_hex=self._normalize_color(self.text_color_var.get()),
                    font_size=int(self.font_size_var.get()),
                    text_offset_x=int(self.text_offset_x_var.get()),
                    text_offset_y=int(self.text_offset_y_var.get()),
                    free_icon_size=float(self.free_icon_size_var.get()),
                    grid_offset_x=int(self.grid_offset_x_var.get()),
                    grid_offset_y=int(self.grid_offset_y_var.get()),
                    manual_cell_width=int(self.manual_cell_width_var.get()),
                    manual_cell_height=int(self.manual_cell_height_var.get()),
                    show_grid_overlay=False,
                    free_image_path=self.free_icon_path,
                )
                card_number = int(card.get("card_number", generated_count + 1))
                output_path = self.output_dir / f"card_{card_number:02d}.png"
                image.save(output_path)
                generated_count += 1
                self.generate_progress.set(index / total_cards)
                self.generate_status_label.configure(
                    text=f"Generation status: {index}/{total_cards}"
                )
                self.update_idletasks()

            self.generate_status_label.configure(
                text=f"Generation status: done ({generated_count}/{total_cards})"
            )
            messagebox.showinfo(
                "Generation Complete",
                f"Generated {generated_count} cards in:\n{self.output_dir}",
            )
        except Exception as error:
            self.generate_status_label.configure(text="Generation status: failed")
            messagebox.showerror("Generation Error", f"Could not generate cards:\n{error}")
        finally:
            self.generate_button.configure(state="normal")

    def _show_preview_warning(self, message: str):
        self.preview_base_image = None
        self.preview_photo = None
        self.preview_image_id = None
        self.preview_canvas.delete("all")
        canvas_w = max(200, self.preview_canvas.winfo_width())
        canvas_h = max(150, self.preview_canvas.winfo_height())
        self.preview_canvas.create_text(
            canvas_w // 2,
            canvas_h // 2,
            text=message,
            fill="#f59e0b",
            anchor="center",
            width=max(180, canvas_w - 40),
        )
        self.preview_canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))
        self._set_preview_scrollbars_visibility(show_horizontal=False, show_vertical=False)

    def _set_preview_scrollbars_visibility(
        self, show_horizontal: bool, show_vertical: bool
    ):
        if show_horizontal != self._preview_h_scroll_visible:
            if show_horizontal:
                self.preview_h_scroll.grid(row=1, column=0, sticky="ew")
            else:
                self.preview_h_scroll.grid_remove()
            self._preview_h_scroll_visible = show_horizontal
        if show_vertical != self._preview_v_scroll_visible:
            if show_vertical:
                self.preview_v_scroll.grid(row=0, column=1, sticky="ns")
            else:
                self.preview_v_scroll.grid_remove()
            self._preview_v_scroll_visible = show_vertical

    def _preview_layout(self, render_w: int, render_h: int) -> dict[str, int]:
        canvas_w = max(1, self.preview_canvas.winfo_width())
        canvas_h = max(1, self.preview_canvas.winfo_height())
        origin_x = max(0, (canvas_w - render_w) // 2)
        origin_y = max(0, (canvas_h - render_h) // 2)
        scroll_w = max(canvas_w, render_w)
        scroll_h = max(canvas_h, render_h)
        return {
            "canvas_w": canvas_w,
            "canvas_h": canvas_h,
            "origin_x": origin_x,
            "origin_y": origin_y,
            "scroll_w": scroll_w,
            "scroll_h": scroll_h,
        }

    def _set_preview_zoom(
        self,
        zoom_value: float,
        anchor_canvas_x: int | None = None,
        anchor_canvas_y: int | None = None,
    ):
        old_zoom = self.preview_zoom
        base_x: float | None = None
        base_y: float | None = None
        pointer_x = anchor_canvas_x
        pointer_y = anchor_canvas_y

        if (
            self.preview_base_image is not None
            and old_zoom > 0
            and anchor_canvas_x is not None
            and anchor_canvas_y is not None
        ):
            base_w, base_h = self.preview_base_image.size
            old_render_w = max(1, int(round(base_w * old_zoom)))
            old_render_h = max(1, int(round(base_h * old_zoom)))
            old_layout = self._preview_layout(old_render_w, old_render_h)
            world_x = self.preview_canvas.canvasx(anchor_canvas_x)
            world_y = self.preview_canvas.canvasy(anchor_canvas_y)
            base_x = (world_x - old_layout["origin_x"]) / old_zoom
            base_y = (world_y - old_layout["origin_y"]) / old_zoom

        self.preview_zoom = max(0.25, min(4.0, zoom_value))
        self.preview_zoom_label_var.set(f"{int(round(self.preview_zoom * 100))}%")
        self._render_preview_image()

        if (
            self.preview_base_image is None
            or base_x is None
            or base_y is None
            or pointer_x is None
            or pointer_y is None
        ):
            return

        base_w, base_h = self.preview_base_image.size
        new_render_w = max(1, int(round(base_w * self.preview_zoom)))
        new_render_h = max(1, int(round(base_h * self.preview_zoom)))
        new_layout = self._preview_layout(new_render_w, new_render_h)

        new_world_x = new_layout["origin_x"] + (base_x * self.preview_zoom)
        new_world_y = new_layout["origin_y"] + (base_y * self.preview_zoom)

        max_x_scroll = max(0, new_layout["scroll_w"] - new_layout["canvas_w"])
        max_y_scroll = max(0, new_layout["scroll_h"] - new_layout["canvas_h"])

        desired_left = new_world_x - pointer_x
        desired_top = new_world_y - pointer_y

        if max_x_scroll > 0:
            clamped_left = max(0, min(max_x_scroll, desired_left))
            self.preview_canvas.xview_moveto(clamped_left / new_layout["scroll_w"])
        else:
            self.preview_canvas.xview_moveto(0)
        if max_y_scroll > 0:
            clamped_top = max(0, min(max_y_scroll, desired_top))
            self.preview_canvas.yview_moveto(clamped_top / new_layout["scroll_h"])
        else:
            self.preview_canvas.yview_moveto(0)

    def _calculate_fit_zoom(self) -> float:
        if self.preview_base_image is None:
            return 1.0
        image_w, image_h = self.preview_base_image.size
        if image_w <= 0 or image_h <= 0:
            return 1.0
        canvas_w = max(1, self.preview_canvas.winfo_width())
        canvas_h = max(1, self.preview_canvas.winfo_height())
        fit_zoom = min(canvas_w / image_w, canvas_h / image_h)
        return max(0.25, min(4.0, fit_zoom))

    def _zoom_in(self):
        self._set_preview_zoom(self.preview_zoom * 1.1)

    def _zoom_out(self):
        self._set_preview_zoom(self.preview_zoom / 1.1)

    def _zoom_reset(self):
        self._set_preview_zoom(self._calculate_fit_zoom())

    def _on_preview_ctrl_wheel(self, event):
        if event.delta > 0:
            self._set_preview_zoom(self.preview_zoom * 1.1, event.x, event.y)
        else:
            self._set_preview_zoom(self.preview_zoom / 1.1, event.x, event.y)

    def _on_preview_scroll(self, event):
        if event.delta == 0:
            return
        self.preview_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_preview_shift_scroll(self, event):
        if event.delta == 0:
            return
        self.preview_canvas.xview_scroll(int(-event.delta / 120), "units")

    def _on_preview_canvas_configure(self, _event):
        if self._pending_fit_zoom and self.preview_base_image is not None:
            self._pending_fit_zoom = False
            self._set_preview_zoom(self._calculate_fit_zoom())
            return
        self._render_preview_image()

    def _render_preview_image(self):
        if self.preview_base_image is None:
            return
        base_w, base_h = self.preview_base_image.size
        render_w = max(1, int(round(base_w * self.preview_zoom)))
        render_h = max(1, int(round(base_h * self.preview_zoom)))
        rendered = self.preview_base_image.resize(
            (render_w, render_h), Image.Resampling.LANCZOS
        )
        self.preview_photo = ImageTk.PhotoImage(rendered)
        self.preview_canvas.delete("all")
        layout = self._preview_layout(render_w, render_h)
        origin_x = layout["origin_x"]
        origin_y = layout["origin_y"]
        self.preview_image_id = self.preview_canvas.create_image(
            origin_x, origin_y, anchor="nw", image=self.preview_photo
        )
        scroll_w = layout["scroll_w"]
        scroll_h = layout["scroll_h"]
        self.preview_canvas.configure(scrollregion=(0, 0, scroll_w, scroll_h))
        self._set_preview_scrollbars_visibility(
            show_horizontal=render_w > layout["canvas_w"],
            show_vertical=render_h > layout["canvas_h"],
        )

    def _pick_text_color(self):
        initial_color = self._normalize_color(self.text_color_var.get())
        selected, hex_color = colorchooser.askcolor(
            color=initial_color, title="Choose text color"
        )
        if selected is None or not hex_color:
            return
        self.text_color_var.set(hex_color.lower())
        self._refresh_preview()

    def _normalize_color(self, value: str) -> str:
        if not value:
            return "#000000"
        color = value.strip()
        if not color.startswith("#"):
            color = f"#{color}"
        if len(color) != 7:
            return "#000000"
        try:
            int(color[1:], 16)
        except ValueError:
            return "#000000"
        return color.lower()

    def _refresh_preview(self):
        self.font_size_value_label.configure(text=str(int(self.font_size_var.get())))
        self.text_offset_x_value_label.configure(text=str(int(self.text_offset_x_var.get())))
        self.text_offset_y_value_label.configure(text=str(int(self.text_offset_y_var.get())))
        self.free_icon_size_value_label.configure(
            text=f"{float(self.free_icon_size_var.get()):.2f}"
        )
        self.grid_offset_x_value_label.configure(text=str(int(self.grid_offset_x_var.get())))
        self.grid_offset_y_value_label.configure(text=str(int(self.grid_offset_y_var.get())))
        self.manual_cell_width_value_label.configure(
            text=str(int(self.manual_cell_width_var.get()))
        )
        self.manual_cell_height_value_label.configure(
            text=str(int(self.manual_cell_height_var.get()))
        )

        if self.template_image is None:
            return
        if (
            self.template_layout
            and self.pdf_layout
            and self.template_layout != self.pdf_layout
        ):
            self._show_preview_warning(
                (
                    f"Layout mismatch detected.\n"
                    f"Template: {self.template_layout}x{self.template_layout}\n"
                    f"PDF: {self.pdf_layout}x{self.pdf_layout}\n\n"
                    f"Please use matching layouts to preview."
                )
            )
            return

        grid_size = self._effective_grid_size()
        matrix = get_placeholder_matrix(grid_size)

        if self.pdf_path:
            try:
                extracted = extract_first_card_matrix(self.pdf_path, grid_size)
                if extracted and len(extracted) == grid_size:
                    matrix = self._apply_music_name_overrides(extracted)
            except Exception:
                pass

        color_value = self._normalize_color(self.text_color_var.get())
        if color_value != self.text_color_var.get().strip().lower():
            self.text_color_var.set(color_value)
            return

        self.color_swatch.configure(fg_color=color_value)

        preview = build_preview(
            template_image=self.template_image,
            matrix=matrix,
            grid_size=grid_size,
            text_color_hex=color_value,
            font_size=int(self.font_size_var.get()),
            text_offset_x=int(self.text_offset_x_var.get()),
            text_offset_y=int(self.text_offset_y_var.get()),
            free_icon_size=float(self.free_icon_size_var.get()),
            grid_offset_x=int(self.grid_offset_x_var.get()),
            grid_offset_y=int(self.grid_offset_y_var.get()),
            manual_cell_width=int(self.manual_cell_width_var.get()),
            manual_cell_height=int(self.manual_cell_height_var.get()),
            show_grid_overlay=bool(self.show_grid_overlay_var.get()),
            free_image_path=self.free_icon_path,
        )

        should_fit_preview = (
            self.preview_base_image is None
            or self.preview_base_image.size != preview.size
        )
        self.preview_base_image = preview
        if should_fit_preview:
            self._pending_fit_zoom = True
            self._render_preview_image()
        else:
            self._render_preview_image()
        self._save_state()

    def _load_template_file(self, path: Path, show_error: bool):
        self.template_path = path
        try:
            self.template_image = Image.open(self.template_path).convert("RGB")
            self.template_layout = detect_template_layout(self.template_image)
            self.template_layout_label.configure(
                text=f"Template layout: {self.template_layout}x{self.template_layout}"
            )
            self._refresh_preview()
            return True
        except Exception as error:
            self.template_path = None
            self.template_image = None
            self.template_layout = None
            self.template_layout_label.configure(text="Template layout: -")
            if show_error:
                messagebox.showerror("Template Error", f"Could not read template:\n{error}")
            return False

    def _load_pdf_file(self, path: Path, show_error: bool):
        self.pdf_path = path
        self.cached_pdf_cards = None
        self.music_name_overrides = {}
        try:
            self.pdf_layout = detect_pdf_layout(self.pdf_path)
            self.pdf_layout_label.configure(
                text=f"PDF layout: {self.pdf_layout}x{self.pdf_layout}"
            )
            self.edit_music_button.configure(state="normal")
            self._refresh_preview()
            return True
        except Exception as error:
            self.pdf_path = None
            self.pdf_layout = None
            self.cached_pdf_cards = None
            self.music_name_overrides = {}
            self.pdf_layout_label.configure(text="PDF layout: -")
            self.edit_music_button.configure(state="disabled")
            if show_error:
                messagebox.showerror("PDF Error", f"Could not read PDF:\n{error}")
            return False

    def _get_cached_valid_cards(self, force_reload: bool = False) -> list[dict]:
        if self.pdf_path is None:
            return []
        if self.cached_pdf_cards is not None and not force_reload:
            return self.cached_pdf_cards
        cards = extract_bingo_cards(self.pdf_path)
        valid_cards: list[dict] = []
        for card in cards:
            matrix = card.get("songs_matrix")
            if not matrix:
                continue
            normalized_matrix = [
                [normalize_song_name(cell) for cell in row]
                for row in matrix
            ]
            normalized_card = dict(card)
            normalized_card["songs_matrix"] = normalized_matrix
            valid_cards.append(normalized_card)
        self.cached_pdf_cards = valid_cards
        return self.cached_pdf_cards

    def _apply_music_name_overrides(self, matrix: list[list[str]]) -> list[list[str]]:
        if not self.music_name_overrides:
            return matrix
        return [
            [self.music_name_overrides.get(cell, cell) for cell in row]
            for row in matrix
        ]

    def _collect_music_names(self, cards: list[dict]) -> list[str]:
        unique_names: dict[str, None] = {}
        for card in cards:
            matrix = card.get("songs_matrix") or []
            for row in matrix:
                for song_name in row:
                    cleaned = (song_name or "").strip()
                    if cleaned and not is_free_cell_text(cleaned):
                        unique_names.setdefault(cleaned, None)
        return sorted(unique_names.keys(), key=str.casefold)

    def _open_music_name_editor(self):
        if self.pdf_path is None:
            messagebox.showwarning("Missing PDF", "Please import the cards PDF first.")
            return
        try:
            cards = self._get_cached_valid_cards()
        except Exception as error:
            messagebox.showerror("PDF Error", f"Could not parse songs from PDF:\n{error}")
            return
        if not cards:
            messagebox.showwarning("No Songs Found", "No songs were extracted from the PDF.")
            return

        names = self._collect_music_names(cards)
        if not names:
            messagebox.showwarning("No Songs Found", "No songs were extracted from the PDF.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Music Names")
        dialog.geometry("920x700")
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            dialog,
            text="Update song names before generating cards",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        scroll = ctk.CTkScrollableFrame(dialog, corner_radius=10)
        scroll.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        scroll.grid_columnconfigure(1, weight=1)

        entry_vars: dict[str, tk.StringVar] = {}
        for index, original_name in enumerate(names):
            ctk.CTkLabel(
                scroll,
                text=original_name,
                anchor="w",
                wraplength=360,
            ).grid(row=index, column=0, padx=(8, 8), pady=4, sticky="ew")
            current_value = self.music_name_overrides.get(original_name, original_name)
            value_var = tk.StringVar(value=current_value)
            entry_vars[original_name] = value_var
            ctk.CTkEntry(scroll, textvariable=value_var).grid(
                row=index, column=1, padx=(8, 8), pady=4, sticky="ew"
            )

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        actions.grid_columnconfigure(2, weight=1)

        def reset_changes():
            for original_name, value_var in entry_vars.items():
                value_var.set(original_name)

        def save_changes():
            updated_overrides: dict[str, str] = {}
            for original_name, value_var in entry_vars.items():
                updated_name = value_var.get().strip()
                if not updated_name:
                    updated_name = original_name
                if updated_name != original_name:
                    updated_overrides[original_name] = updated_name
            self.music_name_overrides = updated_overrides
            dialog.destroy()
            self._refresh_preview()
            messagebox.showinfo(
                "Music Names Updated",
                f"Saved {len(updated_overrides)} replacement(s).",
            )

        ctk.CTkButton(
            actions,
            text="Reset",
            command=reset_changes,
            fg_color="#6b7280",
            hover_color="#4b5563",
            width=140,
        ).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Cancel",
            command=dialog.destroy,
            fg_color="#374151",
            hover_color="#4b5563",
            width=140,
        ).grid(row=0, column=1, padx=4, sticky="ew")
        ctk.CTkButton(
            actions,
            text="Apply",
            command=save_changes,
            fg_color="#16a34a",
            hover_color="#15803d",
            width=140,
        ).grid(row=0, column=2, padx=(8, 0), sticky="ew")

    def _serialize_state(self) -> dict:
        return {
            "template_path": str(self.template_path) if self.template_path else None,
            "pdf_path": str(self.pdf_path) if self.pdf_path else None,
            "output_dir": str(self.output_dir) if self.output_dir else None,
            "text_color": self.text_color_var.get(),
            "font_size": int(self.font_size_var.get()),
            "text_offset_x": int(self.text_offset_x_var.get()),
            "text_offset_y": int(self.text_offset_y_var.get()),
            "free_icon_size": float(self.free_icon_size_var.get()),
            "free_icon_path": str(self.free_icon_path) if self.free_icon_path else None,
            "grid_offset_x": int(self.grid_offset_x_var.get()),
            "grid_offset_y": int(self.grid_offset_y_var.get()),
            "manual_cell_width": int(self.manual_cell_width_var.get()),
            "manual_cell_height": int(self.manual_cell_height_var.get()),
            "show_grid_overlay": bool(self.show_grid_overlay_var.get()),
            "music_name_overrides": dict(self.music_name_overrides),
            "text_settings_expanded": bool(self.text_settings_expanded),
            "grid_settings_expanded": bool(self.grid_settings_expanded),
            "tutorial_seen": bool(self.tutorial_seen),
        }

    def _save_state(self):
        if self._loading_state:
            return
        try:
            APP_STATE_PATH.write_text(
                json.dumps(self._serialize_state(), indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_state(self):
        if not APP_STATE_PATH.exists():
            return
        try:
            state = json.loads(APP_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return

        self._loading_state = True
        try:
            self.text_color_var.set(state.get("text_color", "#000000"))
            self.font_size_var.set(int(state.get("font_size", 26)))
            text_offset_y = int(state.get("text_offset_y", state.get("text_y_padding", 0)))
            self.text_offset_x_var.set(int(state.get("text_offset_x", 0)))
            self.text_offset_y_var.set(text_offset_y)
            self.free_icon_size_var.set(float(state.get("free_icon_size", FREE_ICON_SIZE_DEFAULT)))
            free_icon_path = state.get("free_icon_path")
            if free_icon_path and Path(free_icon_path).exists():
                self.free_icon_path = Path(free_icon_path)
            else:
                self.free_icon_path = None
            self.free_icon_path_label.configure(text=self._format_free_icon_label())
            self.grid_offset_x_var.set(int(state.get("grid_offset_x", 0)))
            self.grid_offset_y_var.set(int(state.get("grid_offset_y", 0)))
            self.manual_cell_width_var.set(int(state.get("manual_cell_width", 0)))
            self.manual_cell_height_var.set(int(state.get("manual_cell_height", 0)))
            self.show_grid_overlay_var.set(bool(state.get("show_grid_overlay", True)))
            saved_overrides = state.get("music_name_overrides", {})
            if isinstance(saved_overrides, dict):
                self.music_name_overrides = {
                    str(original): str(updated)
                    for original, updated in saved_overrides.items()
                    if str(original).strip() and str(updated).strip()
                }
            else:
                self.music_name_overrides = {}

            output_dir = state.get("output_dir")
            if output_dir:
                output_path = Path(output_dir)
                self.output_dir = output_path
            self.output_folder_button.configure(text=self._format_output_button_text())

            if state.get("text_settings_expanded"):
                self.text_settings_expanded = False
                self._toggle_text_settings()

            if state.get("grid_settings_expanded"):
                self.grid_settings_expanded = False
                self._toggle_grid_settings()
            self.tutorial_seen = bool(state.get("tutorial_seen", False))

            template_path = state.get("template_path")
            if template_path and Path(template_path).exists():
                self._load_template_file(Path(template_path), show_error=False)

            pdf_path = state.get("pdf_path")
            if pdf_path and Path(pdf_path).exists():
                self._load_pdf_file(Path(pdf_path), show_error=False)
                saved_overrides = state.get("music_name_overrides", {})
                if isinstance(saved_overrides, dict):
                    self.music_name_overrides = {
                        str(original): str(updated)
                        for original, updated in saved_overrides.items()
                        if str(original).strip() and str(updated).strip()
                    }
        finally:
            self._loading_state = False

        self._refresh_preview()

    def _on_close(self):
        self._save_state()
        self.destroy()


if __name__ == "__main__":
    app = BingoDesktopApp()
    app.mainloop()
