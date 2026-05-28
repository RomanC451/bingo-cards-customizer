from pathlib import Path
from unittest.mock import patch

from bingo_cards.pdf.preview import detect_pdf_layout, extract_first_card_matrix
from tests.conftest import make_pdf_page


def test_detect_pdf_layout_uses_layout_inference():
    page = make_pdf_page(
        text="Card # 1",
        layout_text="Card # 1\n" + "\n\n\n".join(f"b{i}" for i in range(4)),
    )
    with patch("bingo_cards.pdf.preview.pdfplumber.open") as open_mock:
        open_mock.return_value.__enter__.return_value.pages = [page]
        assert detect_pdf_layout(Path("x.pdf")) == 4


def test_extract_first_card_matrix_skips_bad_center_count():
    words = [{"text": "Song", "x0": 10, "top": 80}]
    page = make_pdf_page(text="Card # 1", words=words)
    with patch("bingo_cards.pdf.preview.kmeans_1d", return_value=[1.0, 2.0]):
        with patch("bingo_cards.pdf.preview.pdfplumber.open") as open_mock:
            open_mock.return_value.__enter__.return_value.pages = [page]
            assert extract_first_card_matrix(Path("x.pdf"), 3) is None
