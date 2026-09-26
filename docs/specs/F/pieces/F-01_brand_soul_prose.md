# F-01 — Brand Soul health check + long-form prose document

Depends on: —
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
A-D2 (CEO): many changes landed since Brand Soul was built — re-verify it end to end — and
the Brand Soul document (20 credits, `POST /api/soul/generate`, `app/main.py` ~L333)
must read as consolidated long-form prose, never as a JSON-like dump. The CEO asked for this
before and it never shipped.

## Files you may touch
- `app/tools/brand_soul/generator.py` (redaction prompt ~L331-380, in English; output English)
- `app/tools/brand_soul/template.py` (`build_soul_html` ~L157)
- `tests/test_brand_soul_f01_prose.py` (new); existing Brand Soul tests may be updated only where they assert the old layout.

## Behaviour
- Each of the 9 sections (diagnostico, brand_journey, charco, icp, contrarian, asociaciones,
  identidad, oferta, lead_magnet) renders as a titled chapter with 2-4 paragraphs of prose
  (150-350 words), English headings (e.g. "Diagnosis", "Brand Journey", "Your Pond",
  "Ideal Client", "Contrarian Take", "Associations", "Identity", "Offer", "Lead Magnet").
- No `{`, `}`, `":`, `key: value` lines, bullet dumps of raw fields, or snake_case keys in
  the visible document. Nested `content` objects are woven into sentences by the LLM; a
  deterministic fallback (no LLM) joins field values into sentences, never "field: value".
- Literal citations stay (existing `validate_citations_in_html` must still pass).
- An opening "Executive summary" (120-200 words) and a closing "How Brandy will use this".
- Price, caching and the confirmation flow stay the same.

## Health check (write it down as evidence)
With the network isolated, walk the Brand Soul path through `TestClient`: `/api/brain`
extract -> `/api/soul` 404 -> `/api/soul/generate` (LLM mocked) -> `/api/soul` 200 ->
regenerate. Record each status code.

## Done when
Tests assert: no JSON/key-value patterns in the text content, 9 chapters + summary present,
citations validated. Evidence = generated HTML (mocked LLM) + health-check table in
`docs/specs/evidence/F-01/`.
