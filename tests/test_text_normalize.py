from bingo_cards.text_normalize import normalize_cell_text


def test_normalize_cell_text_collapses_whitespace():
    assert normalize_cell_text("  hello   world  ") == "hello world"


def test_normalize_cell_text_fixes_punctuation_spacing():
    assert normalize_cell_text("song , title . end ; ok : yes") == (
        "song, title. end; ok: yes"
    )


def test_normalize_cell_text_preserves_hyphenated_phrase():
    assert normalize_cell_text("artist - song") == "artist - song"


def test_normalize_cell_text_empty():
    assert normalize_cell_text("") == ""
    assert normalize_cell_text("   ") == ""
