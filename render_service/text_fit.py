"""Card text fit: shrink-to-fit line breaking for overlay cards (piece E2-04).

Same rule family as caption layout (`render_service.ffmpeg_dress.layout_text`), but for
overlay cards, whose box has a fixed size and must never clip text top/bottom.

The JS twin lives in `app/static/editing_preview.js::fitCardText` and must return
identical `(lines, font_px)` for the same inputs (parity-tested).
"""

from __future__ import annotations

# Per-character width factors (fraction of font-size, bold weight). A flat K=0.58
# underestimates bold ASCII capitals and digits enough that Chromium's real layout
# wraps an extra line the formula never accounted for (measured in Chromium: bold
# capitals are ~0.70-0.74em in Inter/Montserrat). Values below carry ~70px of margin
# in the wrapped-line width check across the brand fonts.
CAP_DIGIT_K_FACTOR = 0.74
DIGIT_K_FACTOR = 0.64
K_FACTOR = 0.58
_CAP_AND_HEAVY_PUNCT = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ%$&@#")
_DIGITS = set("0123456789")

LINE_HEIGHT = 1.15
MAX_LINES = 3
MIN_FONT_PX = 28
SHRINK_STEP_PX = 2
PAD_W = 80
PAD_H = 60

DEFAULT_FONT_PX = {
    "card_stat": 110,
    "card_quote": 60,
    "card_list": 50,
    "card_lower_third": 44,
    "onscreen_text": 64,
}
FALLBACK_FONT_PX = 64


def _char_width_factor(ch: str) -> float:
    if ch in _CAP_AND_HEAVY_PUNCT:
        return CAP_DIGIT_K_FACTOR
    if ch in _DIGITS:
        return DIGIT_K_FACTOR
    return K_FACTOR


def _text_width(text: str, font_px: int) -> float:
    return sum(_char_width_factor(ch) for ch in text) * font_px


def _wrap(words: list[str], font_px: int, area_w: float) -> list[str]:
    """Greedy word-wrap into at most MAX_LINES lines; never splits a word.

    The last line absorbs every remaining word once MAX_LINES - 1 lines are full,
    so the result never exceeds MAX_LINES (same "absorb the rest" rule as frame_zero).
    """
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if len(lines) == MAX_LINES - 1:
            current.append(word)
            continue
        candidate = current + [word]
        candidate_str = " ".join(candidate)
        width = _text_width(candidate_str, font_px)
        if width <= area_w or not current:
            current = candidate
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def fit_card_text(
    text: str,
    kind: str,
    box_w: int,
    box_h: int,
) -> tuple[list[str], int]:
    """Line-breaks and shrinks `text` so it always fits inside a `box_w x box_h` card.

    Available area is `(box_w - 80) x (box_h - 60)`. Starts at the kind's default font
    size, shrinks 2px at a time (min 28px) until the wrapped lines (max 3, words never
    split) fit both the width and the height of the available area. Width uses a
    per-character factor (capitals/digits are wider than lowercase in bold brand
    fonts), not a single flat K, so the browser never wraps more lines than computed.
    """
    area_w = box_w - PAD_W
    area_h = box_h - PAD_H

    words = text.strip().split() if text else []
    start_font_px = DEFAULT_FONT_PX.get(kind, FALLBACK_FONT_PX)
    if not words:
        return ([], start_font_px)

    font_px = start_font_px
    lines = _wrap(words, font_px, area_w)
    while font_px > MIN_FONT_PX:
        total_h = len(lines) * font_px * LINE_HEIGHT
        max_line_w = max((_text_width(line, font_px) for line in lines), default=0)
        if total_h <= area_h and max_line_w <= area_w:
            break
        font_px = max(MIN_FONT_PX, font_px - SHRINK_STEP_PX)
        lines = _wrap(words, font_px, area_w)

    return (lines, font_px)


__all__ = [
    "CAP_DIGIT_K_FACTOR",
    "DEFAULT_FONT_PX",
    "DIGIT_K_FACTOR",
    "K_FACTOR",
    "LINE_HEIGHT",
    "MAX_LINES",
    "MIN_FONT_PX",
    "fit_card_text",
]
