# Block E.2 — Editing polish (signed spec, 2026-09-25)

Signed by the CEO "with changes" on 2026-09-25. Source document: the CEO's
`SPEC_EDITING_PULIDO.html` (local). This file is the dump agents read. Deadline for the
whole product: **2026-09-30 11:00 VET** (UTC-4).

## Why
The CEO produced the first real MP4 with Brand Studio (51 s, English, B2B medical
interpretation pitch). Verdict: cuts, silence removal, B-roll placement and SFX are
excellent and faster than CapCut. The workflow to MP4 is **validated**. E.2 is polish,
not a rebuild.

## Findings from that video (frame by frame)
| Time | What | Verdict |
|---|---|---|
| 0:00–0:01 | Frame zero text cut off the screen | Old bug, already fixed (P92). Re-render returned the old MP4 → B3 |
| 0:02–0:05, 0:08, 0:14–0:16 | Overlay card competes with / sits **on top of** captions | F2 |
| whole video | Caption band fixed at y=1250/1920 → covers mouth on close framing | F1 |
| 0:29–0:41 | **11 s of empty dark screen**: a motion-graphic scene rendered blank | B2 (root cause below) |
| 0:36–0:40 | Card "reduces wait" with top and bottom lines clipped | B1 |
| 0:02 vs rest | Captions change style (hook = giant single word in another look) | F6 |
| whole video | Too many cards for a sober B2B video | F4 |
| 0:12–0:22 | B-roll generic, not what is said | Out: fixed in Audiovisual via agentic "regenerate one" |
| whole video | Very tight framing, glare on glasses | F5 (recording guide) |

**B2 root cause (verified in code):** motion-graphic templates
(`app/audiovisual/motion_templates/*.html`) build a **paused GSAP timeline**
(`window.__timelines[...]`). `render_service/motion.py::convert_html` renders them with
HyperFrames under a 120 s timeout and 1 worker (HyperFrames measured ~8 min per 60 s),
so an 11 s scene times out and falls back to a Chromium screenshot taken with the
timeline at t=0 — every element still at `opacity: 0` → blank dark frame.

## In scope
| ID | What | Type |
|---|---|---|
| B1 | Card text always fits its box (line-break + shrink, same rule family as captions) — preview and MP4 | Bug |
| B2 | No MP4 ever ships an empty scene: fix the MG root cause + empty-scene guard (fallback to the scene's AI image or the founder's face, and tell the founder in English) | Bug |
| B3 | Render engine version is part of the render key; re-render after an engine update produces a new MP4 | Bug |
| P1 | **Pricing of renders** (CEO asked the Capitán to propose): first final render of an idea = **20 credits**; every later render of the same idea = **5 credits**; a re-render whose only difference is the engine version = **free**. Raw cut download stays free. *Capitán proposal — CEO confirms in the E.2 test plan.* | Pricing |
| F1 | Caption position: drag the caption band in the preview + 3 presets (Top · Middle · Bottom); one value for the whole video; the MP4 uses the same height (±20 px) | Feature |
| F2 | No-collision rule: an overlay is placed in the free zone away from the captions; if no zone fits, captions hide only while that overlay is on screen | Feature |
| F3 | Overlay controls: delete a card, edit its text (free), global "Overlays" on/off switch. Deleting/hiding never discards the paid auto-edit | Feature |
| F3b | **Animated overlays** (CEO addition): Brandy can place *animated* motion-graphic overlays, not only static text cards — chosen and filled by the LLM from a closed library of animated templates (stat counter, checklist, arrow callout, lower third, quote reveal, icon pop, progress bar, keyword highlight). Same animation in preview and MP4 | Feature |
| F4 | Auto-edit styles **Clean / Standard / Bold** (density of zooms, cards, transitions). Changing style re-runs auto-edit for free up to 3 times per raw cut | Feature |
| F5 | Recording guide in the recording studio: head-and-shoulders silhouette over the camera + one tip ("Light at 45°, not straight at your glasses") | Feature |
| F6 | **One caption style per video**, derived from the Brand Soul. Captions never switch look mid-video (no giant "hero" word in another style). Big animated words are overlays (F3b), not captions | Feature |
| F7 | **Simpler, English Editing.** "Vestir" is gone: the studio reads as 3 steps — **1 Cut** (automatic) · **2 Auto-edit** (Brandy adds captions, zooms, transitions, overlays, SFX; pick Clean/Standard/Bold) · **3 Export**. Every string in English | UX |
| F8 | Editing gets a loading screen consistent with the other steps (same pattern, same look) | UX |
| O1 | `docs/specs/` + `AGENTS.md` + an offline end-to-end MP4 test that runs with no credentials (synthetic media) | Ops |

Principles: everything that changes the video goes through the RenderIR; new controls are
free and never destroy what was paid for.

## Out of scope
- Face detection to place captions automatically.
- CapCut-style free editing: keyframes, dragging cards by hand, new layers.
- Colour/light/glare correction or reframing in post. Video filters: post-hackathon.
- Free-form LLM-written HTML/JS animations (only the closed animated template library).
- New caption fonts/animations beyond "one Brand Soul style".
- Formats other than 9:16, new music, languages other than English/Spanish.
- Changing any price except P1.
- Agentic mode (block F has its own spec).

## Data (no SQL migration expected)
- `edit.settings.caption_y` (int, 1080×1920 canvas, default = today's band)
- `edit.settings.overlays_enabled` (bool, default true)
- `edit.settings.overlays` → `{ "<overlay_id>": { "deleted": true } | { "text": "..." } }`
- `edit.dressing.style` (`clean|standard|bold`, default `standard`), `edit.dressing.free_restyles_used` (int, per raw cut)
- RenderIR: optional `layout.caption_y`; overlays may carry `anim` template id + params;
  captions may be suppressed by the IR in collision windows (renderers only draw).
- Render service: `ENGINE_VERSION` exposed by `/health`, included in the render key.

## Acceptance (the CEO's test plan checks these literally)
1. Same idea re-rendered: frame zero readable in full; no clipped card text.
2. Captions dragged to the top: preview and MP4 at the same height (≤20 px apart).
3. Not a single MP4 frame where a card box intersects the caption box.
4. No MP4 scene is near-uniform colour for >1 s; a failed MG scene shows the AI image
   or the face, and the app says so in English.
5. Deleting a card / turning overlays off: gone from preview and MP4, free, rest intact.
6. Clean has fewer zooms and cards than Standard; restyle free until the 4th time.
7. After a render-engine redeploy, Render makes a new MP4 at the P1 price.
8. Captions keep one style for the whole video; animated overlays animate the same in
   preview and MP4.
9. Editing shows a loading screen; no Spanish anywhere in the Editing UI.
