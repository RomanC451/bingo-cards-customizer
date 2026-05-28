"""Shared text normalization (no PDF or UI dependencies)."""


def normalize_cell_text(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = (
        cleaned.replace(" ,", ",")
        .replace(" .", ".")
        .replace(" ;", ";")
        .replace(" :", ":")
    )
    cleaned = cleaned.replace(" - ", " - ")
    return cleaned.strip()
