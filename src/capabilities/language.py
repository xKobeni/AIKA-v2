"""Harmless normalization shared by bounded user-intent recognizers."""

import re


def natural_text(prompt: str) -> str:
    text = " ".join(prompt.replace("’", "'").split()).strip()
    text = re.sub(r"^(?:hey\s+)?aika[, :]\s*", "", text, flags=re.I)
    return re.sub(r"^(?:(?:please|can you|could you|would you)\s+)+", "", text, flags=re.I).rstrip(",.?!").strip()
