from unittest.mock import patch

from bingo_cards.pdf.extraction import extract_card_from_page, infer_grid_size_from_layout
from tests.conftest import make_pdf_page


def test_infer_grid_size_from_layout_trailing_block():
    layout = "Card # 1\n" + "\n\n\n".join(["a", "b", "c"])
    page = make_pdf_page(layout_text=layout)
    assert infer_grid_size_from_layout(page) == 3


def test_extract_card_from_page_center_mismatch():
    page = make_pdf_page(
        text="Card # 3",
        words=[{"text": "x", "x0": 1, "top": 50}],
    )

    with patch(
        "bingo_cards.pdf.extraction.kmeans_1d",
        side_effect=[[1.0, 2.0], [1.0, 2.0, 3.0]],
    ):
        assert extract_card_from_page(page, forced_grid_size=3) is None


def test_extract_card_from_page_no_filtered_words_after_header():
    words = [{"text": "Card", "x0": 1, "top": 10}]
    page = make_pdf_page(text="Card # 1", words=words)
    assert extract_card_from_page(page) is None
