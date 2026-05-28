import pytest

from bingo_cards.music.names import (
    canonical_music_name,
    normalize_song_name,
    song_identity_key,
)


def test_normalize_song_name_strips_leading_dashes():
    assert normalize_song_name("---  Track") == "Track"
    assert normalize_song_name("") == ""


def test_canonical_music_name():
    assert canonical_music_name("  Song  ,  Title ") == "Song, Title"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dancing Queen (feat. ABBA)", "dancing queen"),
        ("Hit Song - Artist Name", "hit song"),
        ("Plain Title", "plain title"),
        ("", ""),
    ],
)
def test_song_identity_key(text, expected):
    assert song_identity_key(text) == expected


def test_song_identity_key_featuring_marker():
    assert song_identity_key("Groove (featuring DJ X)") == "groove"
