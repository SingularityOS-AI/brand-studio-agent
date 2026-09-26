# F-09 — Catalog + Brand Soul tools

Depends on: F-08
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Files you may touch
`app/static/agent.js`, `app/static/actions.js`, `app/static/app.js` (only to expose Catalog
handlers through `window.BrandStudio`), `tests/agent_catalog.test.js`, `tests/test_agent_f09.py`.

## Tools
Catalog: `catalog_research_demand` (confirm, its price) · `catalog_generate_ideas` (confirm) ·
`catalog_regenerate_idea {idea}` (confirm, 3) · `catalog_add_idea {text}` (free) ·
`catalog_accept {idea}` (free) · `catalog_discard {idea}` (confirm, discards) ·
`catalog_explain_demand {idea}` (free) · `catalog_lock` (confirm).
Brand Soul: `soul_generate` (confirm, 20) · `soul_regenerate` (confirm, 20).
Ideas are referenced by position ("idea 4") or title words; ambiguous -> ask, never guess.

## Done when
Harness covers each tool + the ambiguity path. Evidence in `docs/specs/evidence/F-09/`.
