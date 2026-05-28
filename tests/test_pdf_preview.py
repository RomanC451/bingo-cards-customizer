from pathlib import Path
from unittest.mock import patch

from bingo_cards.pdf.preview import (
    detect_pdf_layout,
    extract_filtered_words,
    extract_first_card_matrix,
)
from tests.conftest import make_pdf_page


def test_extract_filtered_words_empty():
    page = make_pdf_page(words=[])
    assert extract_filtered_words(page) == []


def test_extract_filtered_words_skips_header():
    words = [
        {"text": "Card", "x0": 1, "top": 5},
        {"text": "Below", "x0": 10, "top": 50},
        {"text": "   ", "x0": 0, "top": 60},
    ]
    page = make_pdf_page(words=words)
    filtered = extract_filtered_words(page)
    assert len(filtered) == 1
    assert filtered[0]["text"] == "Below"


def test_detect_pdf_layout_from_sample(sample_pdf: Path):
    assert detect_pdf_layout(sample_pdf) == 5


def test_detect_pdf_layout_defaults_without_card_pages():
    page = make_pdf_page(text="no bingo here")
    with patch("bingo_cards.pdf.preview.pdfplumber.open") as open_mock:
        open_mock.return_value.__enter__.return_value.pages = [page]
        assert detect_pdf_layout(Path("x.pdf")) == 5


def test_extract_first_card_matrix(sample_pdf: Path):
    matrix = extract_first_card_matrix(sample_pdf, 5)
    assert matrix is not None
    assert len(matrix) == 5
    assert all(len(row) == 5 for row in matrix)


def test_extract_first_card_matrix_none_when_no_words():
    page = make_pdf_page(text="Card # 1", words=[])
    with patch("bingo_cards.pdf.preview.pdfplumber.open") as open_mock:
        open_mock.return_value.__enter__.return_value.pages = [page]
        assert extract_first_card_matrix(Path("x.pdf"), 3) is None
