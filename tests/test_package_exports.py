import bingo_cards
import bingo_cards.grid
import bingo_cards.music
import bingo_cards.pdf
import bingo_cards.playlist
import bingo_cards.render
import bingo_cards.ui


def test_package_docstring():
    assert "bingo" in bingo_cards.__doc__.lower()


def test_pdf_public_exports():
    from bingo_cards.pdf import (
        STOP_MARKER,
        detect_pdf_layout,
        extract_bingo_cards,
        kmeans_1d,
        normalize_cell_text,
    )

    assert STOP_MARKER
    assert callable(detect_pdf_layout)
    assert callable(extract_bingo_cards)
    assert callable(kmeans_1d)
    assert callable(normalize_cell_text)


def test_subpackages_importable():
    assert bingo_cards.grid
    assert bingo_cards.music
    assert bingo_cards.playlist
    assert bingo_cards.render
    assert bingo_cards.ui
