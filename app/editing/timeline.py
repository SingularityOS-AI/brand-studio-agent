"""Timeline construction, silence cutting, trim adjustments, visual choice, and inputs builder (Bloque E)."""

from __future__ import annotations

import re
from typing import Any

from app.editing.config import FILLERS, GAP_MS, PAD_MS
from render_service.manifest import (
    CaptionWord,
    Timeline,
    TimelineScene,
    Trim,
    timeline_hash,
)

_PUNCTUATION_STRIP = re.compile(r"^\W+|\W+$")


def _normalize_word(text: str) -> str:
    """Lowercase and strip punctuation from word edges."""
    if not text:
        return ""
    return _PUNCTUATION_STRIP.sub("", text.lower())


def current_take(jobs: list[dict], scene_n: int) -> dict | None:
    """Find the latest done a_roll_take job for scene_n."""
    matching = []
    for job in jobs:
        if job.get("kind") == "a_roll_take" and job.get("status") == "done":
            job_scene = job.get("scene_n")
            if job_scene is not None and int(job_scene) == int(scene_n):
                matching.append(job)
    if not matching:
        return None
    matching.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return matching[0]


def scene_words(jobs: list[dict], take_job_id: str) -> list[dict]:
    """Find words from the transcript job matching take_job_id."""
    matching = []
    for job in jobs:
        if job.get("kind") == "transcript" and job.get("status") == "done":
            inp = job.get("input") or {}
            if inp.get("take_job_id") == take_job_id:
                matching.append(job)
    if not matching:
        return []
    matching.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    out = matching[0].get("output") or {}
    return out.get("words") or []


def cut_segments(
    words: list[dict],
    take_duration_ms: int,
    gap_ms: int = GAP_MS,
    pad_ms: int = PAD_MS,
    fillers: frozenset[str] = FILLERS,
) -> list[tuple[int, int]]:
    """Cut silences and fillers, returning list of (in_ms, out_ms) intervals."""
    take_duration_ms = max(0, take_duration_ms)

    kept_words = []
    for w in words:
        norm = _normalize_word(w.get("text", ""))
        if norm and norm in fillers:
            continue
        kept_words.append(w)

    if not kept_words:
        if take_duration_ms > 0:
            return [(0, take_duration_ms)]
        return [(0, 0)]

    kept_words.sort(key=lambda w: w.get("start_ms", 0))

    groups: list[list[dict]] = []
    current_group: list[dict] = [kept_words[0]]

    for prev_w, curr_w in zip(kept_words[:-1], kept_words[1:]):
        prev_end = prev_w.get("end_ms", 0)
        curr_start = curr_w.get("start_ms", 0)
        gap = curr_start - prev_end
        if gap > gap_ms:
            groups.append(current_group)
            current_group = [curr_w]
        else:
            current_group.append(curr_w)
    groups.append(current_group)

    raw_segments: list[tuple[int, int]] = []
    for g in groups:
        start = max(0, g[0].get("start_ms", 0) - pad_ms)
        end = min(take_duration_ms, g[-1].get("end_ms", 0) + pad_ms)
        if end > start:
            raw_segments.append((start, end))

    if not raw_segments:
        if take_duration_ms > 0:
            return [(0, take_duration_ms)]
        return [(0, 0)]

    merged: list[tuple[int, int]] = []
    cur_start, cur_end = raw_segments[0]

    for next_start, next_end in raw_segments[1:]:
        if next_start <= cur_end:
            cur_end = max(cur_end, next_end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = next_start, next_end
    merged.append((cur_start, cur_end))

    return merged


def raw_content_hash(timeline_dict: dict) -> str:
    """Hash of what the raw MP4 is made of, and nothing else.

    edit_version is left out because it rises on every save (a caption fix, a
    dressing, the worker recording the finished raw), and sfx_enabled because
    sound effects are added in the final render, not in the raw cut. Including
    either made a finished raw look stale and forced a pointless re-render.
    """
    content = {k: v for k, v in timeline_dict.items() if k not in ("hash", "edit_version")}
    settings = dict(content.get("settings") or {})
    settings.pop("sfx_enabled", None)
    content["settings"] = settings
    return timeline_hash(content)


def _get_setting_val(settings: dict | None, key: str, scene_n: int) -> Any:
    """Fetch setting for a scene supporting string and integer keys."""
    if not settings:
        return None
    d = settings.get(key)
    if not isinstance(d, dict):
        return None
    if str(scene_n) in d:
        return d[str(scene_n)]
    if scene_n in d:
        return d[scene_n]
    return None


def build_timeline(
    script: dict, jobs: list[dict], settings: dict | None, edit_version: int
) -> dict:
    """Devuelve {"timeline": dict|None, "captions_words": list[dict], "missing_takes": list[int],
    "inputs": dict[str, dict], "warnings": list[str]}"""
    script_scenes = sorted(script.get("scenes", []), key=lambda s: s.get("n", 0))

    missing_takes = []
    for s in script_scenes:
        n = s.get("n")
        if n is not None:
            take = current_take(jobs, n)
            if not take:
                missing_takes.append(int(n))

    if missing_takes:
        missing_takes.sort()
        return {
            "timeline": None,
            "captions_words": [],
            "missing_takes": missing_takes,
            "inputs": {},
            "warnings": [f"Missing takes for scenes: {missing_takes}"],
        }

    gap_val = int((settings or {}).get("gap_ms", GAP_MS))
    pad_val = int((settings or {}).get("pad_ms", PAD_MS))
    sfx_val = bool((settings or {}).get("sfx_enabled", True))
    music_muted = bool((settings or {}).get("music_muted", False))
    music_vol_setting = (settings or {}).get("music_volume")

    warnings: list[str] = []
    inputs: dict[str, dict] = {}
    captions_words: list[dict] = []
    timeline_scenes: list[dict] = []

    current_out_start_ms = 0

    for s in script_scenes:
        n = int(s["n"])
        take = current_take(jobs, n)
        assert take is not None  # Guaranteed by missing_takes check above
        take_id = take["id"]
        take_out = take.get("output") or {}
        take_dur_ms = take_out.get("duration_ms")
        if take_dur_ms is None:
            take_dur_ms = int(float(take_out.get("duration_s") or 0) * 1000)

        take_input_id = f"take_s{n}"
        inputs[take_input_id] = {
            "storage_path": take_out.get("storage_path", ""),
            "kind": "video",
        }
        if "duration_s" in take_out or "duration_ms" in take_out:
            inputs[take_input_id]["duration_ms"] = take_dur_ms

        w_list = scene_words(jobs, take_id)
        if take_dur_ms <= 0 and w_list:
            # Take saved without a duration: the last spoken word bounds it.
            take_dur_ms = max(int(w.get("end_ms", 0)) for w in w_list) + pad_val
            inputs[take_input_id]["duration_ms"] = take_dur_ms
        if not w_list:
            warnings.append(f"scene {n}: no transcript, not cut")
            segs = [(0, take_dur_ms)] if take_dur_ms > 0 else [(0, 300)]
        else:
            segs = cut_segments(w_list, take_dur_ms, gap_val, pad_val, FILLERS)

        trim_dict = _get_setting_val(settings, "trim", n) or {}
        raw_start_trim = int(trim_dict.get("start_ms", 0))
        raw_end_trim = int(trim_dict.get("end_ms", 0))
        start_trim = max(-500, min(500, raw_start_trim))
        end_trim = max(-500, min(500, raw_end_trim))
        trim_obj = Trim(start_ms=start_trim, end_ms=end_trim)

        if segs:
            f_in, f_out = segs[0]
            f_in = max(0, min(take_dur_ms, f_in + start_trim))
            segs[0] = (f_in, f_out)

            l_in, l_out = segs[-1]
            l_out = max(0, min(take_dur_ms, l_out - end_trim))
            segs[-1] = (l_in, l_out)

            valid_segs = [(i, o) for (i, o) in segs if o > i]
            if not valid_segs:
                warnings.append(
                    f"scene {n}: trim left no segments, reset to 300ms min"
                )
                valid_segs = [(0, min(take_dur_ms, 300) if take_dur_ms > 0 else 300)]
            segs = valid_segs

        scene_segments_objs = []
        scene_start_out_ms = current_out_start_ms
        for in_ms, out_ms in segs:
            dur = out_ms - in_ms
            seg_out_start = current_out_start_ms
            scene_segments_objs.append(
                {"in_ms": in_ms, "out_ms": out_ms, "out_start_ms": seg_out_start}
            )
            current_out_start_ms += dur
        scene_end_out_ms = current_out_start_ms

        for i, w in enumerate(w_list):
            w_text = w.get("text", "")
            if _normalize_word(w_text) in FILLERS:
                continue
            w_in = w.get("start_ms", 0)
            w_out = w.get("end_ms", 0)
            for seg_dict in scene_segments_objs:
                seg_in = seg_dict["in_ms"]
                seg_out = seg_dict["out_ms"]
                seg_out_start = seg_dict["out_start_ms"]
                if w_in < seg_out and w_out > seg_in:
                    b_in = max(seg_in, w_in)
                    b_out = min(seg_out, w_out)
                    if b_out >= b_in:
                        word_out_start = seg_out_start + (b_in - seg_in)
                        word_out_end = seg_out_start + (b_out - seg_in)
                        cw_dict = {
                            "id": f"s{n}w{i}",
                            "scene_n": n,
                            "text": w_text[:40],
                            "edited_text": None,
                            "start_ms": word_out_start,
                            "end_ms": word_out_end,
                        }
                        CaptionWord.model_validate(cw_dict)
                        captions_words.append(cw_dict)
                        break

        asset_type = s.get("asset_type")
        broll_kinds = {"stock", "ai_image", "ai_video", "motion_graphic"}
        broll_jobs = [
            j
            for j in jobs
            if j.get("kind") in broll_kinds
            and j.get("status") == "done"
            and j.get("scene_n") is not None
            and int(j.get("scene_n")) == n
        ]
        if asset_type in broll_kinds:
            matching_kind = [j for j in broll_jobs if j.get("kind") == asset_type]
            if matching_kind:
                broll_jobs = matching_kind

        broll_jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        broll_job = broll_jobs[0] if broll_jobs else None

        face_setting = _get_setting_val(settings, "face", n)
        if face_setting is True:
            desired_visual = "face"
        elif face_setting is False:
            desired_visual = "broll"
        else:
            desired_visual = "face" if asset_type == "a_roll" else "broll"

        final_visual = desired_visual
        if desired_visual == "broll" and not broll_job:
            final_visual = "face"
            warnings.append(f"scene {n}: no b-roll ready, showing face")

        # Only a scene that SHOWS its b-roll ships it to the render service:
        # a face scene would otherwise download stock (up to 4K) nobody sees.
        if broll_job and final_visual == "broll":
            broll_input_id = f"broll_s{n}"
            b_kind = broll_job.get("kind", asset_type)
            b_out = broll_job.get("output") or {}
            if b_kind == "stock":
                v_url = b_out.get("video_url") or b_out.get("external_url", "")
                inp_entry: dict[str, Any] = {"external_url": v_url, "kind": "video"}
            elif b_kind == "ai_image":
                inp_entry = {
                    "storage_path": b_out.get("storage_path", ""),
                    "kind": "image",
                }
            elif b_kind == "ai_video":
                inp_entry = {
                    "storage_path": b_out.get("storage_path", ""),
                    "kind": "video",
                }
            elif b_kind == "motion_graphic":
                inp_entry = {
                    "storage_path": b_out.get("storage_path", ""),
                    "kind": "html",
                    "convert": True,
                }
            else:
                inp_entry = {
                    "storage_path": b_out.get("storage_path", ""),
                    "kind": "video",
                }

            w_val = b_out.get("width") or b_out.get("w")
            h_val = b_out.get("height") or b_out.get("h")
            dur_s = b_out.get("duration_s")
            b_dur_ms = (
                b_out.get("duration_ms")
                if b_out.get("duration_ms") is not None
                else (int(dur_s * 1000) if dur_s is not None else None)
            )

            if w_val is not None:
                inp_entry["w"] = int(w_val)
            if h_val is not None:
                inp_entry["h"] = int(h_val)
            if b_dur_ms is not None:
                inp_entry["duration_ms"] = int(b_dur_ms)

            inputs[broll_input_id] = inp_entry
            broll_obj: dict[str, Any] | None = {
                "kind": b_kind,
                "input_id": broll_input_id,
                "w": int(w_val) if w_val is not None else None,
                "h": int(h_val) if h_val is not None else None,
                "duration_ms": int(b_dur_ms) if b_dur_ms is not None else None,
            }
        else:
            broll_obj = None

        scene_dict = {
            "n": n,
            "phase": s.get("phase", ""),
            "visual": final_visual,
            "take_job_id": take_id,
            "take_input": take_input_id,
            "broll": broll_obj,
            "segments": scene_segments_objs,
            "trim": trim_obj.model_dump(),
            "out_start_ms": scene_start_out_ms,
            "out_end_ms": scene_end_out_ms,
        }
        TimelineScene.model_validate(scene_dict)
        timeline_scenes.append(scene_dict)

    music_jobs = [
        j
        for j in jobs
        if j.get("kind") == "music"
        and j.get("status") == "done"
        and j.get("scene_n") is None
    ]
    music_jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    music_job = music_jobs[0] if music_jobs else None

    if music_job:
        m_out = music_job.get("output") or {}
        use_music = m_out.get("use_music", False)
        m_path = m_out.get("storage_path", "")
        default_vol = float(m_out.get("volume", 0.1))
        m_vol = (
            float(music_vol_setting) if music_vol_setting is not None else default_vol
        )
        m_vol = max(0.0, min(1.0, m_vol))
    else:
        use_music = False
        m_path = ""
        m_vol = float(music_vol_setting) if music_vol_setting is not None else 0.1
        m_vol = max(0.0, min(1.0, m_vol))

    if use_music and m_path and not music_muted:
        inputs["music"] = {"storage_path": m_path, "kind": "audio"}
        music_obj = {"input_id": "music", "volume": m_vol}
    else:
        music_obj = None

    settings_obj = {
        "gap_ms": gap_val,
        "pad_ms": pad_val,
        "music_volume": m_vol,
        "music_muted": music_muted,
        "sfx_enabled": sfx_val,
    }

    timeline_dict = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": edit_version,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": settings_obj,
        "scenes": timeline_scenes,
        "music": music_obj,
        "duration_ms": current_out_start_ms,
        "hash": "",
    }
    timeline_dict["hash"] = raw_content_hash(timeline_dict)
    Timeline.model_validate(timeline_dict)

    return {
        "timeline": timeline_dict,
        "captions_words": captions_words,
        "missing_takes": [],
        "inputs": inputs,
        "warnings": warnings,
    }
