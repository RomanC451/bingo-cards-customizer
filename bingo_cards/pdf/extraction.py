import re
from collections import defaultdict
from pathlib import Path

import pdfplumber

from bingo_cards.config import SUPPORTED_GRID_SIZES
from bingo_cards.text_normalize import normalize_cell_text

STOP_MARKER = "BINGO MASTER CHEAT SHEET"
CARD_NUMBER_PATTERN = re.compile(r"Card\s*#\s*(\d+)", re.IGNORECASE)


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
            closest_center = min(range(k), key=lambda i: abs(value - centers[i]))
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


def infer_grid_size_from_layout(page) -> int | None:
    layout_text = page.extract_text(layout=True) or ""
    lines = layout_text.splitlines()

    card_line_index = None
    for index, line in enumerate(lines):
        if CARD_NUMBER_PATTERN.search(line):
            card_line_index = index
            break

    if card_line_index is None:
        return None

    content_lines = lines[card_line_index + 1 :]
    blocks: list[list[str]] = []
    current: list[str] = []
    empty_streak = 0

    for line in content_lines:
        if line.strip():
            current.append(line)
            empty_streak = 0
            continue

        empty_streak += 1
        if empty_streak >= 2 and current:
            blocks.append(current)
            current = []

    if current:
        blocks.append(current)

    block_count = len(blocks)
    if block_count in SUPPORTED_GRID_SIZES:
        return block_count

    return None


def infer_grid_size(
    words: list[dict], candidates: tuple[int, ...] = SUPPORTED_GRID_SIZES
) -> int:
    x_values = [word["x0"] for word in words]
    y_values = [word["top"] for word in words]
    if not x_values or not y_values:
        return 5

    best_size = 5
    best_score = float("inf")

    for size in candidates:
        x_centers = kmeans_1d(x_values, size)
        y_centers = kmeans_1d(y_values, size)

        cells: defaultdict[tuple[int, int], int] = defaultdict(int)
        for word in words:
            col = min(range(size), key=lambda i: abs(word["x0"] - x_centers[i]))
            row = min(range(size), key=lambda i: abs(word["top"] - y_centers[i]))
            cells[(row, col)] += 1

        non_empty_cells = sum(1 for value in cells.values() if value > 0)
        empty_ratio = 1 - (non_empty_cells / (size * size))

        x_span = max(x_values) - min(x_values) if len(x_values) > 1 else 1
        y_span = max(y_values) - min(y_values) if len(y_values) > 1 else 1
        x_compactness = sum(
            nearest_center_distance(value, x_centers) for value in x_values
        ) / (len(x_values) * x_span)
        y_compactness = sum(
            nearest_center_distance(value, y_centers) for value in y_values
        ) / (len(y_values) * y_span)

        score = x_compactness + y_compactness + (empty_ratio * 1.2)
        if score < best_score:
            best_score = score
            best_size = size

    return best_size


def extract_card_from_page(page, forced_grid_size: int | None = None) -> dict | None:
    page_text = page.extract_text() or ""
    card_match = CARD_NUMBER_PATTERN.search(page_text)
    if not card_match:
        return None

    words = page.extract_words(
        x_tolerance=1,
        y_tolerance=1,
        keep_blank_chars=False,
        use_text_flow=True,
    )
    if not words:
        return None

    card_word_tops = [
        word["top"] for word in words if word["text"].strip().lower() == "card"
    ]
    cutoff_top = min(card_word_tops) + 20 if card_word_tops else 0
    filtered_words = [
        word for word in words if word["top"] > cutoff_top and word["text"].strip()
    ]
    if not filtered_words:
        return None

    grid_size = (
        forced_grid_size
        or infer_grid_size_from_layout(page)
        or infer_grid_size(filtered_words)
    )
    column_centers = kmeans_1d([word["x0"] for word in filtered_words], grid_size)
    row_centers = kmeans_1d([word["top"] for word in filtered_words], grid_size)
    if len(column_centers) != grid_size or len(row_centers) != grid_size:
        return None

    cells: defaultdict[tuple[int, int], list[dict]] = defaultdict(list)
    for word in filtered_words:
        col = min(range(grid_size), key=lambda i: abs(word["x0"] - column_centers[i]))
        row = min(range(grid_size), key=lambda i: abs(word["top"] - row_centers[i]))
        cells[(row, col)].append(word)

    matrix: list[list[str]] = []
    for row in range(grid_size):
        matrix_row: list[str] = []
        for col in range(grid_size):
            bucket = sorted(
                cells[(row, col)], key=lambda word: (word["top"], word["x0"])
            )
            cell_text = normalize_cell_text(" ".join(word["text"] for word in bucket))
            matrix_row.append(cell_text)
        matrix.append(matrix_row)

    return {
        "card_number": int(card_match.group(1)),
        "songs_matrix": matrix,
    }


def extract_bingo_cards(pdf_path: str | Path) -> list[dict]:
    cards: list[dict] = []
    detected_grid_size: int | None = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if STOP_MARKER in page_text:
                break

            if detected_grid_size is None and CARD_NUMBER_PATTERN.search(page_text):
                words = page.extract_words(
                    x_tolerance=1,
                    y_tolerance=1,
                    keep_blank_chars=False,
                    use_text_flow=True,
                )
                card_word_tops = [
                    word["top"]
                    for word in words
                    if word["text"].strip().lower() == "card"
                ]
                cutoff_top = min(card_word_tops) + 20 if card_word_tops else 0
                filtered_words = [
                    word
                    for word in words
                    if word["top"] > cutoff_top and word["text"].strip()
                ]
                detected_grid_size = infer_grid_size_from_layout(
                    page
                ) or infer_grid_size(filtered_words)

            card = extract_card_from_page(page, forced_grid_size=detected_grid_size)
            if card:
                cards.append(card)

    return cards


def pick_input_pdf(cli_path: str | None = None) -> Path:
    if cli_path:
        return Path(cli_path)

    pdf_files = sorted(Path(".").glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError("No PDF files found in current directory.")

    return pdf_files[0]
