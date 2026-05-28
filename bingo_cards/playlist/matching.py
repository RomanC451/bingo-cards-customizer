from __future__ import annotations

from difflib import SequenceMatcher

from bingo_cards.text_normalize import normalize_cell_text

MATCH_MIN_RATIO = 0.52


def format_playlist_track_label(track: dict, include_artist: bool) -> str:
    name = normalize_cell_text(str(track.get("name") or ""))
    if not name:
        return ""
    if not include_artist:
        return name
    artist = normalize_cell_text(str(track.get("artist") or ""))
    if artist:
        return f"{name} - {artist}"
    return name


def playlist_track_labels(tracks: list[dict], include_artist: bool) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for track in tracks:
        label = format_playlist_track_label(track, include_artist)
        if not label:
            continue
        folded = label.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        labels.append(label)
    return labels


def _comparison_text(text: str) -> str:
    return normalize_cell_text(text).casefold()


def _title_comparison_key(text: str) -> str:
    base = _comparison_text(text)
    if not base:
        return ""
    cut = len(base)
    for marker in (" (feat.", " (ft.", " (featuring ", " - "):
        index = base.find(marker)
        if index != -1:
            cut = min(cut, index)
    return base[:cut].strip()


def _match_score(cell: str, label: str) -> float:
    left = _comparison_text(cell)
    right = _comparison_text(label)
    if not left or not right:
        return 0.0

    scores = [SequenceMatcher(None, left, right).ratio()]
    if left in right or right in left:
        scores.append(0.92)

    left_title = _title_comparison_key(cell)
    right_title = _title_comparison_key(label)
    if left_title and right_title:
        scores.append(SequenceMatcher(None, left_title, right_title).ratio())
        if left_title in right_title or right_title in left_title:
            scores.append(0.9)

    return max(scores)


def match_cell_to_playlist_label(cell: str, labels: list[str]) -> str | None:
    if not cell or not labels:
        return None

    best_label: str | None = None
    best_score = 0.0
    for label in labels:
        score = _match_score(cell, label)
        if score > best_score:
            best_score = score
            best_label = label

    if best_label is None or best_score < MATCH_MIN_RATIO:
        return None
    return best_label
