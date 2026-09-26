# F-03 — Right panel = audit trail / queue for every step

Depends on: F-02
Read first: `AGENTS.md`, `docs/specs/F/spec.md`, `docs/specs/F/plan.md` (§2 shared semantics).

## Goal
Spec "Panel": the right panel ("Production", `index.html` ~L1259, `#Prod-Jobs` ~L1282)
shows every action of the current idea, voice and button, in every step, the same way.

## Files you may touch
- `app/static/production_panel.js` (new), `app/static/index.html` (script tag + minimal markup)
- `app/static/app.js` only to call `BrandStudioPanel.refresh()` after the existing job
  refresh points and on step change (no other changes)
- `tests/test_panel_f03.py` (new, static + Node DOM)

## Behaviour
Card per action: icon voice/button, title, step, cost (`−2 credits`), status chip
(queued / running / done / failed / cancelled), relative time, link ("Open") to the result
when `result_ref` exists; voice cards expand to show `"You said: …"`, `"Brandy: …"`,
`"Confirmed: …"`. Refresh: on action start/finish events + every 5 s while anything is
queued/running. Keeps the existing jobs display working (merge, don't replace, if it shows
asset jobs today). Empty state in English. DOM built without `innerHTML` for data.

## Done when
DOM test renders a mixed list correctly and escapes a malicious utterance; evidence
screenshot/DOM text in `docs/specs/evidence/F-03/`.
