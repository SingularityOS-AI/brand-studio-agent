# E2-04 — Card text always fits its box (Python + JS parity)

Depends on: E2-01
Read first: `AGENTS.md`, `docs/specs/E2/spec.md`, `docs/specs/E2/plan.md` (§2 shared semantics).

## Goal
Bug B1: card "reduces wait" rendered with top and bottom lines clipped.
`render_service/cards.py::card_html` uses a fixed font size per kind with a fixed box
height (`ov.h`), so long text overflows.

## Files you may touch
- `render_service/text_fit.py` (new) and `render_service/cards.py`
- `app/static/editing_preview.js` (card drawing: add `fitCardText`, export it for Node)
- `tests/test_editing_e2_04_card_fit.py` (new; Node parity like `tests/test_editing_p94_rebote.py`)

## Behaviour (plan §2 "Card text fit")
`fit_card_text(text, kind, box_w, box_h) -> (lines, font_px)`: area `box_w-80 x box_h-60`,
start at the kind's current size, char width K=0.58, line height 1.15, max 3 lines, shrink
2 px at a time until it fits, min 28 px, never split a word. Cards render the lines with
explicit `<br>` and the size. The JS twin returns identical output.

## Done when
- Parity: 10 strings (short, 80 chars, one 30-char word, emoji) -> Python == JS.
- Offline E2E with a 70-char `card_stat`: in the MP4 frame no text pixels in the card's
  top/bottom 20 px (measure). Evidence crop in `docs/specs/evidence/E2-04/`.
