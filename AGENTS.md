# AGENTS.md — rules for every coding agent (Jules, Antigravity, Claude Code, Codex…)

Brand Studio Agent is a live product (FastAPI on Render.com, Supabase, a render
service on Cloud Run). Real founders pay credits here. Read this before touching code.

## 1. Where the work is defined
- Build specs live in `docs/specs/`. Start at `docs/specs/README.md`.
- You work on **one piece** (`docs/specs/<block>/pieces/<ID>_*.md`) at a time. The piece
  lists the files you may touch. Touching other files = the PR is rejected.
- If the piece is ambiguous, write the question in the PR description and implement
  the most conservative reading. Never invent product behaviour.

## 2. Git
- Branch: `agent/<piece-id>` (e.g. `agent/E2-03`). One piece = one PR = one commit
  (squash is fine). Never push to `main`. Never force-push someone else's branch.
- Commit message: `type(scope): what changes for the founder` + a body explaining **why**.
- Stage explicit paths. Never `git add -A` / `git add .`.

## 3. Secrets and data (hard rules)
- Never read, print, copy or create `.env` files, keys, tokens or service URLs with
  credentials. Tests must never call real APIs (Supabase, Gemini, AssemblyAI, Stripe,
  Pexels, Cloud Run). Mock them. `tests/conftest.py` already isolates the network.
- No patient data, no real founder data in fixtures, evidence or logs.

## 4. Product rules that bind every piece
- **English UI.** Every string the founder sees is English. No new Spanish text in
  `app/static/*` or in API messages. (Brandy may *speak* the founder's language.)
- **Same function as the button.** Voice/agent actions call the exact same frontend
  functions and backend endpoints as the buttons. No parallel backend.
- **Preview = MP4.** Anything that changes the final video goes through the RenderIR
  (`render_service/manifest.py`). The browser preview (`app/static/editing_preview.js`)
  and FFmpeg (`render_service/ffmpeg_dress.py`) only draw what the IR says, with the
  same numbers. A change that only exists in one of them is a bug.
- **Contract order.** If you add a field to the render contract, make it optional with
  a default equal to today's behaviour, so the backend and the render service can be
  deployed in any order.
- **Credits.** Never change prices or charging code unless the piece says so. Charge
  only on success paths already defined; every failure path refunds.

## 5. Definition of done (paste the literal output in the PR)
```
python -m pytest -q                      # full suite, 0 failures
ruff check <every .py you touched>       # clean
node --check <every .js you touched>     # clean
```
Plus the piece's own evidence (frames, screenshots, DOM text) saved under
`docs/specs/evidence/<piece-id>/`. **Evidence is literal output, never a verdict.**
Do not write "PASS", "works", "verified". The reviewer decides.

## 6. Environment notes
- Python 3.12, `pip install -r requirements.txt`; the render service has its own
  `render_service/requirements.txt`.
- Render tests need `ffmpeg` (with libass) and Chromium on PATH, or `CHROME_PATH`.
- `tests/test_render_e2e_offline.py` (piece E2-01) renders a real MP4 with synthetic
  media and no network: use it to prove any render change.
- Windows dev box: never `uvicorn --reload`. Never kill processes you did not start.
