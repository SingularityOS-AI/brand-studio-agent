# Tanda 8 — Production patches (Capitán's live test, 2026-09-29)

Read first: `AGENTS.md`. Deadline **2026-09-30 11:00 VET**; video recording needs these merged by
**2026-09-30 06:00 VET**. Every finding below was reproduced in production (Chrome, the CEO's account,
Supabase rows) — file:line and evidence are in each piece.

| ID | Finding | Priority | Files (disjoint → all 5 run in parallel) |
|---|---|---|---|
| H8-01 | No-collision (E2-07) never acts: stage 2 reads `caption_y` from `timeline.settings` (absent) → always 1250 | P0 | `app/editing/ir.py` |
| H8-02 | Brand Soul "Regenerate · 20 credits" ignores `regenerate` and serves the cached doc; any failure after charging keeps the 20 credits | P0 money | `app/main.py` (soul handler only), `app/tools/brand_soul/generator.py` |
| H8-03 | Raw cut reused across engine versions → a blank motion graphic from an old engine can never be rebuilt | P0 | `app/editing/router.py`, `app/editing/timeline.py` |
| H8-04 | Async jobs (render, assets) stay `queued` forever in the audit trail; panel doesn't refresh after in-step actions; credits never recorded | P0 (visible in the demo) | `app/agent/*`, `app/editing/dispatch.py`, `app/audiovisual/worker.py`, `app/static/production_panel.js` |
| H8-05 | E2-10/E2-11 UI never shipped: no Overlays list/switch, no Clean/Standard/Bold selector, no Overlays track | P1 | `app/static/editing.js` |

Merge order: any. Rebase on `main` if GitHub says behind. After H8-01/H8-03 merge no Cloud Run
redeploy is needed (backend only, Render.com auto-deploys).

## Implementer prompt (Claude Code cloud, Sonnet — change the ID)
```
Repository SingularityOS-AI/brand-studio-agent, branch from the latest main.
Implement piece <ID> exactly as written in docs/specs/H8/pieces/<ID>_*.md.
Read AGENTS.md and docs/specs/H8/README.md first. If a file is missing, stop and say so.
Touch ONLY the files in the piece's whitelist. Branch agent/<ID>, one commit, open a PR to main (not draft).
Run the Done-when commands and save their literal output in docs/specs/evidence/<ID>/ (no verdicts).
Never read .env files, never call real external APIs, never deploy, never push to main.
```

## Reviewer prompt (fresh local Sonnet session, read-only — change PR and ID)
```
You are the independent READ-ONLY reviewer of PR #<N> (piece <ID>) in SingularityOS-AI/brand-studio-agent.
Never edit, fix, commit, push, merge or comment on GitHub. Spec: docs/specs/H8/pieces/<ID>_*.md, docs/specs/H8/README.md, AGENTS.md.
Work in ONE worktree, foreground, one command at a time, never -x:
repo: C:\Users\gabri\Desktop\SINGULARITYOS\_PROYECTOS_SUELTOS_SIN_CLASIFICAR\hackaton lablab assemly IA voice agent\brand-studio-agent
1. git fetch origin; gh pr view <N> --json headRefName; git worktree add C:\Users\gabri\AppData\Local\Temp\claude\wt\h8-<N> origin/<headRefName>
2. Anti-ghost + scope: git diff origin/main...HEAD --stat and the full diff. File outside the whitelist or missing source change = REJECT.
3. python -m pytest -q -m "not e2e" -p no:cacheprovider 2>&1 | tail -30   (main is green: ANY failure = REJECT, except
   test_guard_jwt.py x2 and test_fonts_and_sources_hashes, which fail only inside worktrees because of CRLF/local config).
4. ruff check / node --check on touched files. 5. Check every "Done when" line yourself.
6. Cleanup: git checkout -- docs/specs/evidence ; cd .. ; git worktree remove --force <worktree>
Answer: VERDICT MERGE or REJECT, suite tail, new failures, scope, Done-when lines, and a numbered ticket if REJECT.
```
