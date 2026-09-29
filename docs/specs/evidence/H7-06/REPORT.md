# H7-06 — Fresh-account readiness (report only)

Base: `origin/main` @ 1d27219. No file under `app/`, `render_service/` or `app/static/` was changed.
Literal command output: `pytest_output.txt` (same folder). Walk + cost table come from
`tests/test_h7_06_fresh_user.py` (external APIs mocked, network locked by `tests/conftest.py`).

Environment of this run: Python 3.11 (AGENTS.md says 3.12), no `ffmpeg`, no Chromium, `playwright` pip
package installed only so test modules import. Guard ran in its in-memory mode (`SUPABASE_KEY` empty),
so Supabase-side behaviour (the `sessions` table, the `deduct_credits` RPC) was NOT exercised.

## 1. Seed / demo independence

Searched `app/` (py, js, html) for: `founder-001`, `seed`, `demo`, `fixture`, `sample`, `example.com`,
hard-coded tokens/UUIDs/JWTs/emails, `mock`, `tests/`, `cache/`, `localhost`. Only hits that touch runtime
behaviour are listed. There were no hits for `founder-001`, `demo`, `fixture`, hard-coded session tokens,
UUIDs, JWTs, emails or paths into `tests/`.

| file:line | What it is | Does a new user hit it? |
|---|---|---|
| `app/catalog/ideas.py:1096`, `:1164` | Catalog read/write to `cache/catalog/<session>.json` | Only when `_get_catalog_client()` is None (Supabase not configured; ideas.py:991). Otherwise the `catalogs` table is used |
| `app/scripting/scripts.py:367`, `:417`, `:458` | Script read/list/write to `cache/script/<session>/` | Same condition (`_get_script_client()`, scripts.py:240) |
| `app/audiovisual/storage.py:105`, `:130`, `:171`, `:206` | Local `cache/storage/` path and `https://local-storage.test/...mock_signed` / `mock_upload_token` URLs | Only when the storage client is None. If it ever were None in production, signed URLs would be fake |
| `app/audiovisual/motion_graphics.py:368` | Local `cache/storage/...` path | Same condition |
| `app/audiovisual/library/sfx.json`, `music.json` (`sfx.py:15`, `music.py:31`) | Bundled sound/music library; sfx entries carry `storage_path` into the storage bucket | Yes, every user. The bucket objects must exist in production; not verifiable here |
| `app/editing/catalog/catalog_v1.json` (`dressing.py:84`) | Bundled dressing catalog | Yes, every user (repo file, not seeded data) |
| `app/guard.py:255`, `:276` | Hard-coded `"payment_url": "https://example.com/upgrade"` in the 402 detail (Supabase mode) | Only when credits run out. Most endpoints re-wrap with `settings.payment_url`; the render 402 (`app/editing/router.py:~920`) re-raises `e.detail` unchanged |
| `app/config.py:73` | `PAYMENT_URL` default `https://example.com/upgrade` | Only if the env var is unset in production |
| `app/tools/brand_soul/template.py:143` | `"seed": "invisible"` (startup-stage name) | Not demo data: a stage mapping key |
| `app/editing/dressing.py:62,267…`, `app/editing/ir.py:624…` | `seed` = RNG seed per scene | Not demo data |
| `app/catalog/demand.py:642` | Comment "Sample title patterns" | Not demo data |

Result: no seeded founder, session, idea id or `tests/` path is read by `app/`. Fallbacks to disk/mock
storage exist and are selected by "Supabase not configured", not by user identity.

## 2. Fresh-session walk (TestClient, real in-memory guard, LLM/storage seams mocked)

New random user id, HS256 test JWT, no pre-created session. `initial_session_credits` = 500 (`app/config.py:68`).

| Step | Status | Credits after |
|---|---|---|
| GET `/api/session` | 200 | 500 |
| POST `/api/brain/extract` | 200 | 499 |
| POST `/api/soul/generate` | 200 | 479 |
| POST `/api/catalog/generate` | 200 | 464 |
| POST `/api/catalog/lock` | 200 | 464 |
| POST `/api/script/generate?idea_id=…` | 200 | 454 |
| POST `/api/script/{id}/lock` | 200 | 454 |
| GET `/api/audiovisual/{id}/estimate` (6 scenes: 3 a_roll, 2 stock, 1 motion_graphic) | 200 | 454 |
| GET `/api/editing/{id}` | 200 | 454 |

Estimate `credits_total` = 0. Editing state: `render_price` = 20, `render_price_kind` = `first`,
`missing_takes` = [1, 2, 3, 4, 5, 6]. Total charged in the walk: 46 = 1 + 20 + 15 + 10.

What the walk does not prove: the mocked seams were `extract_and_persist`, `generate_brand_soul`,
`get_or_generate_catalog`, `generate_script`, `lock_script`/`lock_catalog_session` and the editing script
lookup. Real LLM output, extractor validation, takes upload, `/generate`, raw cut and render were not run.

## 3. Cost of one lap vs 500 initial credits

Constants read from code: extract 1 (`main.py:2769`), Brand Soul 20 (`main.py:378`), catalog generate 15
(`app/catalog/ideas.py:144`), script 10 (`app/scripting/scripts.py:997`), audiovisual base 0 and stock /
motion_graphic / a_roll 0 (`app/audiovisual/pricing.py` `CREDITS_TABLE`), `ai_image` 15, render 20 and
re-render 5 (`app/editing/config.py:6-7`). Voice: `/api/voice/reserve` charges 8 per 60 s
(`main.py:246`, the path `app/static/app.js:351` uses); `settings.voice_credits_per_minute` = 7.5
(`app/config.py`). Both are shown.

Fixed part: 1 + 20 + 15 + 10 + 0 + 20 + 5 = **71** (+ B-roll assets).

| B-roll kind (2 B-roll + 1 motion) | Voice | Voice cost | Lap total | Left of 500 |
|---|---|---|---|---|
| stock (0 each) | 15 min @ 8/min | 120 | 191 | 309 |
| stock | 15 min @ 7.5/min | 112.5 | 183.5 | 316.5 |
| stock | 30 min @ 8/min | 240 | 311 | 189 |
| stock | 30 min @ 7.5/min | 225 | 296 | 204 |
| ai_image (15 each) | 15 min @ 8/min | 120 | 221 | 279 |
| ai_image | 15 min @ 7.5/min | 112.5 | 213.5 | 286.5 |
| ai_image | 30 min @ 8/min | 240 | 341 | 159 |
| ai_image | 30 min @ 7.5/min | 225 | 326 | 174 |

The lap fits in 500 credits in every combination computed; the tightest case leaves 159. Extras not in the
table: scene regenerate 2 (`scripts.py:998`), idea regenerate 3 (`main.py:2680`), redress 2
(`config.py:8`), `ai_video` 150 each. `/api/catalog/investigate` (25) and `/api/demand` (10) are not called
by the current frontend (`app.js:2682-2684` says the investigate UI was removed), so they are excluded.

## Findings for the Capitán (no fix applied)

1. **No blocker found for a fresh account in the modelled lap.** Credits cover it with 159+ to spare.
2. **Voice price mismatch:** the reserve endpoint bills 8/min while `voice_credits_per_minute` says 7.5; the
   websocket loop (`main.py:2974`, `guard.deduct_voice_credits`) would bill `int(7.5*10/60)` → 1 per 10 s = 6/min.
   Only the reserve path is used by the frontend today.
3. **`example.com` payment URL** at `guard.py:255`, `:276` and the `config.py:73` default. A founder who runs
   out of credits at render sees it unless `PAYMENT_URL` is set in Render.
4. **Not verified here (needs the production run):** Supabase `sessions` insert and `deduct_credits` RPC,
   storage-bucket objects for the sfx/music library, migration 014 (README finding 9, CEO action).
5. **Suite state on this box** (see `pytest_output.txt`): 16 failed, 2 errors on `main`, identical with my
   test file added; no new failures. The full-suite run also rewrote tracked
   `docs/specs/evidence/E2-09/javascript_summary.txt` and `F-01/extract_response.json` (README finding 6);
   both were restored with `git checkout` before committing. One connection to `trends.google.com` was denied
   by the sandbox proxy during the full-suite run; which test made it was not identified.
