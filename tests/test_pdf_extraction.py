from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bingo_cards.pdf.extraction import (
    CARD_NUMBER_PATTERN,
    STOP_MARKER,
    closest_center_index,
    extract_bingo_cards,
    extract_card_from_page,
    infer_grid_size,
    infer_grid_size_from_layout,
    kmeans_1d,
    nearest_center_distance,
    pick_input_pdf,
)
from tests.conftest import make_pdf_page


def test_kmeans_1d_empty():
    assert kmeans_1d([], 3) == []


def test_kmeans_1d_single_cluster():
    assert kmeans_1d([1.0, 2.0, 3.0], 1) == [2.0]


def test_kmeans_1d_converges():
    values = [10.0, 11.0, 50.0, 51.0, 52.0]
    centers = kmeans_1d(values, 2, iterations=50)
    assert len(centers) == 2
    assert centers[0] < centers[1]


def test_nearest_center_distance_empty():
    assert nearest_center_distance(5.0, []) == 0.0


def test_nearest_center_distance():
    assert nearest_center_distance(5.0, [1.0, 10.0]) == 4.0


def test_closest_center_index():
    assert closest_center_index(5.5, [1.0, 10.0]) == 0
    assert closest_center_index(9.0, [1.0, 10.0]) == 1


def test_card_number_pattern():
    assert CARD_NUMBER_PATTERN.search("Card # 12")
    assert CARD_NUMBER_PATTERN.search("card#3")


def test_infer_grid_size_from_layout_block_count():
    layout = "Card # 1\n" + "\n\n\n".join(f"block{i}" for i in range(5))
    page = make_pdf_page(layout_text=layout)
    assert infer_grid_size_from_layout(page) == 5


def test_infer_grid_size_from_layout_no_card_line():
    page = make_pdf_page(layout_text="no card here")
    assert infer_grid_size_from_layout(page) is None


def test_infer_grid_size_from_layout_unsupported_block_count():
    layout = "Card # 1\n" + "\n\n".join("x" for _ in range(7))
    page = make_pdf_page(layout_text=layout)
    assert infer_grid_size_from_layout(page) is None


def test_infer_grid_size_empty_words_defaults_to_five():
    assert infer_grid_size([]) == 5


def test_infer_grid_size_with_clustered_words():
    words = []
    for row in range(5):
        for col in range(5):
            words.append({"x0": col * 100.0, "top": row * 100.0})
    assert infer_grid_size(words) == 5


def test_extract_card_from_page_none_without_card_number():
    page = make_pdf_page(text="no card")
    assert extract_card_from_page(page) is None


def test_extract_card_from_page_none_without_words():
    page = make_pdf_page(text="Card # 1")
    assert extract_card_from_page(page) is None


def test_extract_card_from_page_success():
    words = []
    for row in range(3):
        for col in range(3):
            words.append(
                {
                    "text": f"R{row}C{col}",
                    "x0": 50 + col * 80,
                    "top": 100 + row * 40,
                }
            )
    page = make_pdf_page(text="Card # 7", words=words)
    card = extract_card_from_page(page, forced_grid_size=3)
    assert card is not None
    assert card["card_number"] == 7
    assert len(card["songs_matrix"]) == 3


def test_extract_card_from_page_filters_header_card_word():
    words = [
        {"text": "Card", "x0": 10, "top": 10},
        {"text": "Song", "x0": 50, "top": 100},
    ]
    page = make_pdf_page(text="Card # 2", words=words)
    card = extract_card_from_page(page, forced_grid_size=1)
    assert card is not None
    assert card["songs_matrix"][0][0] == "Song"


def test_extract_bingo_cards_stops_at_cheat_sheet(sample_pdf: Path):
    cards = extract_bingo_cards(sample_pdf)
    assert cards
    assert all("card_number" in card and "songs_matrix" in card for card in cards)


def test_extract_bingo_cards_detects_grid_size(sample_pdf: Path):
    cards = extract_bingo_cards(sample_pdf)
    first = cards[0]["songs_matrix"]
    assert len(first) == len(first[0])


def test_pick_input_pdf_cli_path(tmp_path: Path):
    pdf = tmp_path / "chosen.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert pick_input_pdf(str(pdf)) == pdf


def test_pick_input_pdf_first_in_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"%PDF")
    second.write_bytes(b"%PDF")
    assert pick_input_pdf().resolve() == first.resolve()


def test_pick_input_pdf_raises_when_missing(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="No PDF files"):
        pick_input_pdf()


def test_extract_bingo_cards_with_mocked_pdf():
    page = MagicMock()
    page.extract_text.return_value = "Card # 1\nsongs"
    page.extract_words.return_value = [
        {"text": "Card", "x0": 1, "top": 1},
        {"text": "Hi", "x0": 50, "top": 80},
    ]
    cheat_page = MagicMock()
    cheat_page.extract_text.return_value = STOP_MARKER

    mock_pdf = MagicMock()
    mock_pdf.pages = [page, cheat_page]
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.__exit__.return_value = False

    with patch("bingo_cards.pdf.extraction.pdfplumber.open", return_value=mock_pdf):
        with patch(
            "bingo_cards.pdf.extraction.extract_card_from_page",
            return_value={"card_number": 1, "songs_matrix": [["Hi"]]},
        ):
            cards = extract_bingo_cards("fake.pdf")
    assert len(cards) == 1
