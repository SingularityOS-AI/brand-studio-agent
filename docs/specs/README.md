# Build specs — Brand Studio Agent

Coding agents start here. Rules: `/AGENTS.md`. Deadline: **2026-09-30 11:00 VET (UTC-4)**.

| Block | What | Spec | Plan | Pieces |
|---|---|---|---|---|
| E.2 | Editing polish after the first real video | `E2/spec.md` | `E2/plan.md` | `E2/pieces/` (13) |
| F | Agentic Mode: Brandy runs the pipeline by voice | `F/spec.md` | `F/plan.md` | `F/pieces/` (11) |

Evidence for every piece: `evidence/<piece-id>/` (literal outputs only, no verdicts).

## Calendar (two lanes, in parallel; they touch different files)
| Day (VET) | Lane A — Editing E.2 | Lane B — Agentic F |
|---|---|---|
| Fri 26 | E2-01 → E2-02, E2-04, E2-05 (parallel after E2-01) | F-01, F-02 (parallel) → F-04 |
| Sat 27 | E2-03, E2-06 → E2-07, E2-08 | F-03, F-05 → F-06 |
| Sun 28 | E2-09, E2-10, E2-11, E2-12 · E2-13 spike (cut line 20:00: any P0 open → E2-13 out) | F-07 → F-08 |
| Mon 29 | E2-13 (if alive) · Render redeploy · CEO test plan E.2 | F-09, F-10 · cut line 12:00 · F-11 · CEO test plan F |
| Tue 30 | 09:00 freeze (fixes only) · 11:00 submit | same |

A piece may start only when its "Depends on" pieces are **merged**. `app/static/app.js`:
one open PR at a time across both lanes.

## Who does what
- **Antigravity 2.0** (the CEO pastes the prompt): pieces that need a real browser,
  Chromium or a local UI (E2-02, E2-06, E2-08, E2-09, E2-12, E2-13, F-03, F-04, F-05, F-07+).
- **Jules** / **Claude Code cloud** (repo only): pure backend / pure JS module pieces
  (E2-01, E2-03, E2-04, E2-05, E2-07, E2-10, E2-11, F-01, F-02, F-06, F-10 spike).
- **Reviewer** (the Capitán, or a *fresh* Claude Code cloud session that did not write the
  piece): reruns the Definition of Done, reads the whole diff, checks evidence against
  "Done when", and writes PASS/FAIL with reasons on the PR. Nobody reviews their own work.
- **CEO**: merges after a PASS, applies migration 014, runs the Cloud Run redeploy, and runs
  the live test plans (`PLAN_DE_PRUEBA_E2` / `PLAN_DE_PRUEBA_F`). A block is closed only when
  its plan is 100 % PASS.

## Prompt to paste (same for every agent; change the piece id)
```
Repository: SingularityOS-AI/brand-studio-agent (branch from main).
Implement piece <ID> exactly as written in docs/specs/<E2|F>/pieces/<ID>_*.md.
Before coding read AGENTS.md, docs/specs/<E2|F>/spec.md and plan.md.
Only touch the files the piece lists. Work on branch agent/<ID>, one commit, open a PR.
Put literal outputs (pytest -q, ruff check, node --check, and the piece's own evidence)
in docs/specs/evidence/<ID>/ and paste them in the PR. Do not write verdicts.
Never read .env files, never call real external APIs, never push to main, never deploy.
```

## Review prompt (fresh Claude Code cloud session)
```
You are the independent reviewer. Review PR #<n> for piece <ID> against
docs/specs/<block>/pieces/<ID>_*.md, spec.md and AGENTS.md. Re-run the Definition of Done
yourself (do not trust the PR's outputs). Read the full diff: flag any file outside the
piece's list, any price/charging change not in the piece, any Spanish UI string, any
preview-vs-MP4 divergence. Answer PASS or FAIL with a numbered list of reasons and
file:line references. Do not fix the code.
```
