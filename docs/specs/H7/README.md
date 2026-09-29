# Tanda 7 — Hardening before the fresh-account production run

Read first: `AGENTS.md`. Deadline: **2026-09-30 11:00 VET**. Goal: zero known bugs and a
green `main` before the CEO's end-to-end run from a brand-new account.

## Audit of `main` @ 440b638 (Capitán, 2026-09-28, full suite on Windows)
1,280 passed · **12 failed · 1 collection error**. Root causes:
| # | Finding | Severity | Piece |
|---|---|---|---|
| 1 | `RenderOk` (render_service/manifest.py ~L501, `extra="forbid"`) lost `scene_fallbacks` in `b4a7597`, but `render_service/app.py` ~L298 passes it → every raw render raises a ValidationError after uploading → HTTP 500. Probably live on Cloud Run engine `2026.09.28`. | **P0 — raw cut broken** | H7-01 |
| 2 | E2-03 warning never reaches the editing state (2 tests) even with #1 fixed | P0 | H7-01 |
| 3 | `tests/test_agent_f11.py` imports `app.models` / `app.agent.tools` (do not exist): ghost test. F-11 code itself exists (`tests/agent_editing.test.js` passes) | P0 (red main) | H7-02 |
| 4 | Stale asserts after F-07..F-11: `agent_actions.test.js` "exactly 5", `test_actions_f04.py` exact set, `test_editing_p82c_editing_js.py` (13 actions, literal `"delete"` op that editing.js maps to `overlay_delete` at L234, template-literal route) | P0 (red main) | H7-02 |
| 5 | `test_editing_e2_04_card_fit.py` parity reads Node stdout in cp1252 on Windows (emoji mojibake) | P1 | H7-02 |
| 6 | Tests overwrite **tracked** files in `docs/specs/evidence/` on every run (E2-03, E2-04, E2-06, E2-09, F-01) | P1 (dirty tree, noisy PRs) | H7-02 |
| 7 | Render label says `Render again · 5 credits` when the charge would be 0: the state uses `get_cached_engine_version()` (router.py ~L313), empty after every Render.com restart | P0 (price shown ≠ price charged) | H7-03 |
| 8 | `production_panel.js` ~L257-270 fetches before login → `Error: Not authenticated` in console; no friendly state when the audit table is missing | P1 | H7-04 |
| 9 | **Migration 014 (`agent_actions`) is NOT applied** in Supabase (last applied: 013) → the audit trail is empty in production | P0 — CEO action | CEO |
| 10 | `RUN - Shortcut.lnk` tracked; README/CHANGELOG/PR_SUMMARY out of date vs shipped features | P1 (judges read the repo) | H7-05 |
| 11 | No proof that a brand-new account runs the full lap without seeded data, nor that 500 initial credits cover it | P0 (tomorrow's run) | H7-06 |

Pricing rule (CEO, 2026-09-28): unchanged — first render of an idea 20, later renders 5,
free only when the previous render recorded an engine version and the only change is the engine.

## Order and parallelism (branches off the latest `main`; one PR per piece)
| Wave | Pieces (parallel inside a wave) | Why |
|---|---|---|
| 1 | **H7-01**, **H7-02**, **H7-04**, **H7-05**, **H7-06** | disjoint whitelists |
| 2 | **H7-03** (after H7-01 merges — both touch `app/editing/router.py`) | same file |
| CEO | apply migration 014 · redeploy Cloud Run after H7-01 (engine `2026.09.29`) · run PLAN_DE_PRUEBA_E2 + F in production | production gate |

Merge order inside wave 1: **H7-01 first**, then H7-02 (it turns `main` green), then the rest
(rebase on `main` before merging if GitHub says the branch is behind).

## Who
- **Implementers:** Claude Code **cloud** sessions (Sonnet), one per piece, branch `agent/<ID>`, PR to `main`.
  Local Claude Code sessions may also implement: use a **git worktree per session** (never two
  sessions in the same folder) and `gh pr create`.
- **Reviewer:** a **fresh** Sonnet session, READ-ONLY, one per PR (prompt below). For UI pieces
  (H7-04) the reviewer is a **local** Claude Code session so it can use Claude in Chrome on the
  running branch; cloud sessions have no browser.

## Reviewer prompt (paste in a fresh Sonnet session; change PR and ID)
```
You are the independent READ-ONLY reviewer for PR #<n> (piece <ID>) of SingularityOS-AI/brand-studio-agent.
Never edit, fix, commit or push anything. Spec: docs/specs/H7/pieces/<ID>_*.md, docs/specs/H7/README.md, AGENTS.md.
1. Anti-ghost: git fetch; git diff origin/main...origin/agent/<ID> --stat and the full diff of every
   source file in the whitelist. Tests/evidence without the promised source change = REJECT.
2. Scope: any changed file outside the piece's whitelist = REJECT (name it).
3. Run it yourself on the PR branch: python -m pytest -q -m "not e2e" -p no:cacheprovider (FULL suite),
   ruff check on touched .py, node --check on touched .js. Paste the literal tail of each output.
4. Check every "Done when" line against what you ran, not against the PR's evidence.
5. Checklist: error handling, no secrets, no Spanish UI strings, no price/charging change beyond the piece.
Verdict: MERGE or REJECT. If REJECT: a numbered ticket (file:line, the contract line violated,
what to change, how to verify) that the CEO pastes back to the implementer.
```

## Implementer prompt (paste in a Claude Code cloud session; change ID)
```
Repository SingularityOS-AI/brand-studio-agent, branch from the latest main.
Implement piece <ID> exactly as written in docs/specs/H7/pieces/<ID>_*.md.
Read AGENTS.md and docs/specs/H7/README.md first. If a file is missing, stop and say so.
Touch ONLY the files in the piece's whitelist. Branch agent/<ID>, one commit, open a PR to main.
Run the Done-when commands and save their literal output in docs/specs/evidence/<ID>/ (no verdicts).
Never read .env files, never call real external APIs, never deploy, never push to main.
```
