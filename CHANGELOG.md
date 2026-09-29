# Changelog

What changed, when, and why. Newest first. Commit hashes point to `main`.

## 2026-09-29 — Block H7: hardening before the first-account production run

- **H7-01** Raw cuts no longer fail after upload: the render response contract carries the scene fallback list again, and the empty-scene warning reaches the editing state. Render engine `2026.09.29`.
- **H7-02** Test suite green on `main`: stale assertions updated for the agentic tools, a ghost test removed, UTF-8 output on Windows, tests no longer rewrite tracked evidence files.
- **H7-03** The render button shows the price that will actually be charged, also after a server restart.
- **H7-04** The production panel waits for sign-in and shows a friendly state when the audit table is not available.
- **H7-05** Repo hygiene: shortcut file untracked, ignore rules extended, `.env.example` lists every variable the code reads, README and changelog match what ships.
- **H7-06** Readiness check that a brand-new account can complete the full lap within the 500 free credits.

## Block F (2026-09) — Agentic Mode

- **F-01** Brand Soul rendered as prose from the 9-section brain.
- **F-02** `agent_actions` audit table (migration 014, RLS on, service-role access only).
- **F-03** Production panel: live audit trail as a card queue.
- **F-04** Action Registry: every agentic call stamped with `X-Agent-Action-Id` and logged.
- **F-05** Agentic Mode toggle, step-scoped Brandy, English orb states.
- **F-06** Confirmation engine: explicit phrase required, 45 s expiry, "yes" alone rejected.
- **F-07** Script voice tools: generate, review, iterate, lock.
- **F-08** Audiovisual voice tools: regenerate assets and B-roll.
- **F-09** Catalog and Brand Soul voice tools, with idea resolution.
- **F-10** Proactive announcements when a job finishes.
- **F-11** 14 editing voice tools in the action registry.

## Block E.2 (2026-09) — Editing

- **E2-01** Offline end-to-end test that renders a real MP4 with synthetic media.
- **E2-02** Chromium seek-capture for motion graphics: deterministic 30 fps frames.
- **E2-03** Empty-scene guard: a blank motion graphic falls back to the face take or an AI image, with a warning.
- **E2-04** Title cards shrink their text to fit the safe zone.
- **E2-05** Render pricing by engine version: first render 20 credits, later renders 5, free when only the engine changed.
- **E2-06** One caption style per script with a vertical position control.
- **E2-07** Overlays and captions no longer collide.
- **E2-08** Three-step editor in English: 1 Cut · 2 Auto-edit · 3 Export, with a loading screen.
- **E2-09** Draggable caption band with presets.
- **E2-10** Overlay controls: delete, edit text, switch on or off.
- **E2-11** Auto-edit looks: Clean, Standard, Bold, with free restyles.
- **E2-12** Recording guide silhouette for takes.
- **E2-13** Animated overlay library: 8 templates, identical in preview and MP4.

## 2026-09-24 — Audiovisual: the founder decides, and AI spend can't bankrupt us

- **Founders choose each scene's visual type** (camera, stock, motion graphic, AI image, AI video) with the price shown before spending. In 47 real scenes the script model never picked AI once, so AI assets were unreachable; now the script proposes and the founder decides. When a type needs a prompt the scene doesn't have, a text model writes it (async, 8 s timeout, deterministic fallback). `b6cdc93`
- **New prices:** AI video 150 credits, AI image 15, no base fee per video. `b6cdc93`
- **Monthly AI spend brake**, fail-closed, checked from the estimate down to the worker right before any paid call. The old spend cap setting was declared but never enforced. `b6cdc93`
- **Stripe price IDs from environment variables**, so going live needs no code change and a live key never pairs with a test price. `b6cdc93`
- **Screen:** 5-way type picker per scene, a real progress bar ("2 of 3 assets ready", AI video takes 1–3 min), listen-only soundtrack line and per-scene SFX chips, credits meter no longer pinned at 100%. `efcb92f`
- Docs: README rewritten to match what is actually built; internal deployment notes removed from the public repo.

## 2026-09-23 — Audiovisual block (record + generate)

- **CC0 music and SFX library** (14 tracks, 15 effects from Freesound) in a private bucket; two ambience recordings with people talking were replaced before shipping. `dfd64d0`
- Founders record **every** scene; each take is tagged on-camera or voice-over for Editing. `899cb51`
- **Generate assets** from the screen, with a credit confirmation, live status, persistence and per-scene regenerate; a double click can't charge twice. `41f7ba4`
- HyperFrames **motion graphics** in the strip; fixed the recording upload call. `273b8b2`
- **AI image and AI video** scenes, charged per asset on success. `563ccc9`
- **Stock B-roll** (Pexels/Pixabay), AI-chosen music, local SFX. `313f15a`
- **Teleprompter recording**, free retakes, real subtitles from AssemblyAI word timestamps. `ef5f3be`
- Foundations: private storage, resumable background jobs, cost estimate. `d52fd75`
- Brand Soul: the founder can reopen their Brand Soul document. `e372bc0`

## 2026-09-22 — Scripting block closed; pipeline rail

- **Pipeline rail**: five steps, done / in progress / locked with a way back to what is pending. `4ea3d1c`
- A freshly generated script can actually be locked (word budget fixed, one retry with the exact failures). `4d74858`
- Script = blueprint Audiovisual can consume; the lock enforces the critical rules; scene iteration with intent; review state. `557042d` `7278c3a` `fcd5d2b` `029265f`
- Regeneration can no longer erase a script or charge twice; the audit shows what it found. `7f18054` `949251a`
- Raw footage blocked before charging; English copy throughout. `7343bf8`
- Tests: `TEST_MODE` out of production, real secrets out of the tests, network lock for sync and async clients. `7e73ecf` `4e7952d`

## 2026-09-17 → 09-21 — Catalog to scripting

- Scripting block: script blueprint from a locked catalog idea, and the screen to reach it. `3bb3166` `07315f8`
- Catalog connected to scripting; founder's own ideas can be undone. `cc5ef60` `dec474d`
- Public repo cleanup (test output, debug scripts). `bdb41a1`

## 2026-09-14 → 09-16 — Catalog and billing

- Real demand signals instead of placeholders; 30-idea generation end to end; persisted in Supabase with founder ideas. `e9ba22b` `893d995` `f34541b`
- Billing: Stripe retries can't credit twice; XSS and webhook race closed; credits charged only after a successful catalog. `ec54812` `4b273e7` `37120b0`

## Before 2026-09-14 — Foundation

- AssemblyAI Voice Agent conversation with barge-in, secure token minting, WebAudio 24 kHz client, Brand Soul interview and brand brain, credits and Stripe checkout.
