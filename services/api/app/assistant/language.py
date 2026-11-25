"""Script-level language detection with hysteresis (§14.2).

This is a lightweight first pass. Romanized Telugu/Hindi cannot be told apart from English by script, so the
reasoning model handles those; native-speaker evaluation (§16) decides whether a dedicated classifier is needed.
"""

from __future__ import annotations

TELUGU = (0x0C00, 0x0C7F)
DEVANAGARI = (0x0900, 0x097F)


def detect_script_language(text: str) -> str | None:
    te = hi = latin = 0
    for ch in text:
        o = ord(ch)
        if TELUGU[0] <= o <= TELUGU[1]:
            te += 1
        elif DEVANAGARI[0] <= o <= DEVANAGARI[1]:
            hi += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    total = te + hi + latin
    if total == 0:
        return None
    if te / total >= 0.3:
        return "te-IN"
    if hi / total >= 0.3:
        return "hi-IN"
    return "en-IN" if latin / total >= 0.7 else None


def next_language(current: str, recent_detected: list[str | None], explicit: str | None = None) -> str:
    """Honor explicit requests; otherwise switch only after two consecutive utterances agree (hysteresis)."""
    if explicit and explicit != "auto":
        return explicit
    tail = [d for d in recent_detected[-2:] if d]
    if len(tail) == 2 and tail[0] == tail[1] and tail[0] != current:
        return tail[0]
    if current == "auto" and tail:
        return tail[-1]
    return current
