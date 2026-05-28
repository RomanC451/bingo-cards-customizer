import re

from bingo_cards.text_normalize import normalize_cell_text


def normalize_song_name(text: str) -> str:
    cleaned = (text or "").strip()
    while cleaned.startswith("-"):
        cleaned = cleaned[1:].lstrip()
    return cleaned


def canonical_music_name(text: str) -> str:
    return normalize_song_name(normalize_cell_text(text))


def song_identity_key(text: str) -> str:
    """Match the same track across cards even when PDF text includes artists differently."""
    base = canonical_music_name(text)
    if not base:
        return ""

    lowered = base.casefold()
    cut = len(base)
    for marker in (" (feat.", " (ft.", " (featuring ", " - "):
        index = lowered.find(marker)
        if index != -1:
            cut = min(cut, index)

    title = base[:cut].strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title.casefold() if title else lowered
