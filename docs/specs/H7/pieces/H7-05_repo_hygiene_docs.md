# H7-05 — Repo hygiene + README/CHANGELOG match what ships (judges read this)

Depends on: —
Read first: `AGENTS.md`, `docs/specs/H7/README.md`.
Priority: P1 · Branch: `agent/H7-05`

## Goal
Finding #10 and the hackathon submission rules (public repo, MIT, README with Mermaid
architecture, `.env.example`, install steps, public demo URL).

## Files you may touch   (Scope Whitelist)
- `.gitignore` (add: `*.lnk`, `temp_render/`, `output/`, `*.log` if missing, `.pytest_cache/`, `__pycache__/`, `.env.*` except `.env.example`; keep the `/specs/` and `.claude/` rules)
- `git rm --cached "RUN - Shortcut.lnk"` (untrack only)
- `README.md`, `CHANGELOG.md`, `PR_SUMMARY.md`
- `.env.example` (add every variable read with `os.getenv`/`os.environ` in `app/` and `render_service/`, with empty values and a one-line comment; **never a real value**)

## Behaviour
- README top: what Brand Studio does in 3 lines, the live demo URL `https://brand-studio-agent.onrender.com`,
  how a judge tries it (Google sign-in, 500 free credits), and a "What ships" table: Brand Soul (voice
  interview, AssemblyAI Voice Agent API), Catalog, Script, Audiovisual, Editing (1 Cut · 2 Auto-edit · 3 Export,
  FFmpeg render service on Cloud Run engine `2026.09.29`), Agentic Mode (voice tools with explicit two-turn
  confirmation, audit trail). Keep the existing Mermaid diagram and extend it with the render service and
  the agentic tool pipeline.
- CHANGELOG: one entry per block (E.2, F, H7) listing pieces by ID; no internal process talk, no Spanish.
- PR_SUMMARY: either updated to the current state or deleted if redundant with CHANGELOG (say which in the PR).

## Out of scope
Any code. No secrets, no internal paths, no service account names, no Supabase project ids.

## Done when
```
git ls-files | grep -iE "\.lnk$|__pycache__|\.pyc$|\.log$" → empty
grep -rnE "(sk-|AIza|eyJhbGci|service_role)" README.md CHANGELOG.md PR_SUMMARY.md .env.example → empty
python -m pytest -q -m "not e2e" -p no:cacheprovider    # unchanged vs main
```
Plus: every env var found by `grep -rhoE "os\.(getenv|environ\.get)\(\"[A-Z_]+" app render_service | sort -u` appears in `.env.example`.

## Evidence   (`docs/specs/evidence/H7-05/`)
`ls_files_check.txt`, `secret_scan.txt`, `env_vars_diff.txt`, `README.md`.
