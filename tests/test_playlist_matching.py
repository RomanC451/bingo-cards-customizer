from bingo_cards.playlist.matching import (
    MATCH_MIN_RATIO,
    format_playlist_track_label,
    match_cell_to_playlist_label,
    playlist_track_labels,
)


def test_format_playlist_track_label_name_only():
    track = {"name": "  Song  ", "artist": "Artist"}
    assert format_playlist_track_label(track, include_artist=False) == "Song"


def test_format_playlist_track_label_with_artist():
    track = {"name": "Song", "artist": "Artist"}
    assert format_playlist_track_label(track, True) == "Song - Artist"


def test_format_playlist_track_label_empty_name():
    assert format_playlist_track_label({"name": ""}, False) == ""


def test_playlist_track_labels_deduplicates_case_insensitive():
    tracks = [
        {"name": "Same", "artist": "A"},
        {"name": "same", "artist": "B"},
        {"name": "Other", "artist": ""},
    ]
    labels = playlist_track_labels(tracks, include_artist=False)
    assert labels == ["Same", "Other"]


def test_match_cell_to_playlist_label_exact_enough():
    labels = ["Dancing Queen - ABBA"]
    assert match_cell_to_playlist_label("Dancing Queen", labels) == labels[0]


def test_match_cell_to_playlist_label_below_threshold_returns_none():
    labels = ["Completely Different Song Title"]
    assert match_cell_to_playlist_label("xyz", labels) is None


def test_match_cell_to_playlist_label_empty_inputs():
    assert match_cell_to_playlist_label("", ["a"]) is None
    assert match_cell_to_playlist_label("a", []) is None


def test_match_min_ratio_constant():
    assert 0 < MATCH_MIN_RATIO < 1


def test_match_score_substring_boost():
    from bingo_cards.playlist.matching import _match_score

    assert _match_score("abc", "xx abc yy") >= 0.9


def test_title_comparison_key_empty():
    from bingo_cards.playlist.matching import _title_comparison_key

    assert _title_comparison_key("") == ""


def test_format_playlist_track_label_no_artist():
    assert format_playlist_track_label({"name": "Only"}, True) == "Only"
