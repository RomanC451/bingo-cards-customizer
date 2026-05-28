from pathlib import Path

import pdfplumber

from bingo_cards.music.names import canonical_music_name
from bingo_cards.pdf.extraction import (
    closest_center_index,
    infer_grid_size,
    infer_grid_size_from_layout,
    kmeans_1d,
)


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
                    row_values.append(canonical_music_name(raw_name))
                matrix.append(row_values)
            return matrix
    return None
