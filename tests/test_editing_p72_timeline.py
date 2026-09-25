"""Unit tests for P72: Timeline construction, silence cutting, and brand style derivation."""

from __future__ import annotations

from app.editing.brand_style import derive_caption_style
from app.editing.config import FILLERS
from app.editing.timeline import build_timeline, cut_segments
from render_service.manifest import CaptionStyle, Timeline


def test_1_cut_segments():
    # 1. cut_segments test
    words = [
        {"text": "Hola", "start_ms": 50, "end_ms": 500},
        {"text": "eh,", "start_ms": 800, "end_ms": 1000},  # Filler
        {"text": "mundo", "start_ms": 1500, "end_ms": 2000},
    ]
    # 900 ms gap between w1 (500) and w3 (1500) -> 2 segments
    segs = cut_segments(words, take_duration_ms=3000, gap_ms=400, pad_ms=100, fillers=FILLERS)
    assert segs == [(0, 600), (1400, 2100)]

    # 300 ms gap -> 1 segment
    words_close = [
        {"text": "Hola", "start_ms": 50, "end_ms": 500},
        {"text": "mundo", "start_ms": 800, "end_ms": 1200},
    ]
    segs_close = cut_segments(words_close, take_duration_ms=3000, gap_ms=400, pad_ms=100, fillers=FILLERS)
    assert segs_close == [(0, 1300)]


def test_2_build_timeline_three_scenes():
    script = {
        "scenes": [
            {"n": 1, "phase": "hook", "asset_type": "a_roll"},
            {"n": 2, "phase": "body_1", "asset_type": "ai_image"},
            {"n": 3, "phase": "close_cta", "asset_type": "stock"},
        ],
        "frame_zero": {"on_screen_text": "HOOK ATENCION"},
    }

    jobs = [
        # Takes
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "created_at": "2026-09-25T10:00:00Z", "output": {"storage_path": "takes/t1.webm", "duration_s": 2.0}},
        {"id": "t2", "kind": "a_roll_take", "scene_n": 2, "status": "done", "created_at": "2026-09-25T10:00:00Z", "output": {"storage_path": "takes/t2.webm", "duration_s": 3.0}},
        {"id": "t3", "kind": "a_roll_take", "scene_n": 3, "status": "done", "created_at": "2026-09-25T10:00:00Z", "output": {"storage_path": "takes/t3.webm", "duration_s": 4.0}},
        # Transcripts
        {"kind": "transcript", "status": "done", "created_at": "2026-09-25T10:01:00Z", "input": {"take_job_id": "t1"}, "output": {"words": [{"text": "Uno", "start_ms": 100, "end_ms": 1500}]}},
        {"kind": "transcript", "status": "done", "created_at": "2026-09-25T10:01:00Z", "input": {"take_job_id": "t2"}, "output": {"words": [{"text": "Dos", "start_ms": 100, "end_ms": 2500}]}},
        {"kind": "transcript", "status": "done", "created_at": "2026-09-25T10:01:00Z", "input": {"take_job_id": "t3"}, "output": {"words": [{"text": "Tres", "start_ms": 100, "end_ms": 3500}]}},
        # B-rolls
        {"kind": "ai_image", "scene_n": 2, "status": "done", "created_at": "2026-09-25T10:02:00Z", "output": {"storage_path": "broll/img.png", "w": 1080, "h": 1920}},
        {"kind": "stock", "scene_n": 3, "status": "done", "created_at": "2026-09-25T10:02:00Z", "output": {"video_url": "https://pexels.com/video.mp4", "w": 1080, "h": 1920, "duration_s": 10.0}},
        # Music
        {"kind": "music", "scene_n": None, "status": "done", "created_at": "2026-09-25T10:03:00Z", "output": {"use_music": True, "volume": 0.2, "storage_path": "music/track.mp3"}},
    ]

    res = build_timeline(script, jobs, settings=None, edit_version=1)
    assert res["missing_takes"] == []
    tl_dict = res["timeline"]
    assert tl_dict is not None
    Timeline.model_validate(tl_dict)

    scenes = tl_dict["scenes"]
    assert len(scenes) == 3
    assert scenes[0]["n"] == 1
    assert scenes[1]["n"] == 2
    assert scenes[2]["n"] == 3

    # out_start_ms accumulation
    assert scenes[0]["out_start_ms"] == 0
    assert scenes[1]["out_start_ms"] == scenes[0]["out_end_ms"]
    assert scenes[2]["out_start_ms"] == scenes[1]["out_end_ms"]
    assert tl_dict["duration_ms"] == scenes[2]["out_end_ms"]

    inputs = res["inputs"]
    assert "take_s1" in inputs
    assert "take_s2" in inputs
    assert "take_s3" in inputs
    assert "broll_s2" in inputs
    assert inputs["broll_s2"]["kind"] == "image"
    assert "broll_s3" in inputs
    assert inputs["broll_s3"]["external_url"] == "https://pexels.com/video.mp4"
    assert "music" in inputs


def test_3_readjusted_caption_times():
    script = {"scenes": [{"n": 1, "phase": "body_1", "asset_type": "a_roll"}]}
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "takes/t1.webm", "duration_s": 4.0}},
        {
            "kind": "transcript",
            "status": "done",
            "input": {"take_job_id": "t1"},
            "output": {
                "words": [
                    {"text": "Hola", "start_ms": 100, "end_ms": 500},
                    {"text": "a", "start_ms": 600, "end_ms": 800},
                    # 700 ms gap (800 to 1500) -> cut silences removes 500 ms gap (from 900 to 1400)
                    {"text": "todos", "start_ms": 1500, "end_ms": 2000},
                ]
            },
        },
    ]
    res = build_timeline(script, jobs, settings=None, edit_version=1)
    words = res["captions_words"]
    assert len(words) == 3

    # seg0: in_ms=0, out_ms=900 (duration=900, out_start_ms=0)
    # seg1: in_ms=1400, out_ms=2100 (duration=700, out_start_ms=900)
    # "todos" in original transcript is 1500-2000 (offset inside seg1 is 100-600)
    # So "todos" output start_ms should be 900 + (1500 - 1400) = 1000
    assert words[2]["text"] == "todos"
    assert words[2]["start_ms"] == 1000
    assert words[2]["end_ms"] == 1500


def test_4_missing_take_scene_2():
    script = {
        "scenes": [
            {"n": 1, "phase": "hook", "asset_type": "a_roll"},
            {"n": 2, "phase": "body_1", "asset_type": "a_roll"},
        ]
    }
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "t1.webm", "duration_s": 2.0}},
    ]
    res = build_timeline(script, jobs, settings=None, edit_version=1)
    assert res["timeline"] is None
    assert res["missing_takes"] == [2]


def test_5_cancelled_take_and_new_done_take():
    script = {"scenes": [{"n": 1, "phase": "hook", "asset_type": "a_roll"}]}
    jobs = [
        {"id": "t1_old", "kind": "a_roll_take", "scene_n": 1, "status": "cancelled", "created_at": "2026-09-25T10:00:00Z", "output": {"storage_path": "old.webm", "duration_s": 2.0}},
        {"id": "t1_new", "kind": "a_roll_take", "scene_n": 1, "status": "done", "created_at": "2026-09-25T10:05:00Z", "output": {"storage_path": "new.webm", "duration_s": 3.0}},
        {"kind": "transcript", "status": "done", "created_at": "2026-09-25T10:01:00Z", "input": {"take_job_id": "t1_old"}, "output": {"words": [{"text": "Viejo", "start_ms": 100, "end_ms": 500}]}},
        {"kind": "transcript", "status": "done", "created_at": "2026-09-25T10:06:00Z", "input": {"take_job_id": "t1_new"}, "output": {"words": [{"text": "Nuevo", "start_ms": 100, "end_ms": 500}]}},
    ]
    res = build_timeline(script, jobs, settings=None, edit_version=1)
    assert res["timeline"] is not None
    assert res["timeline"]["scenes"][0]["take_job_id"] == "t1_new"
    assert len(res["captions_words"]) == 1
    assert res["captions_words"][0]["text"] == "Nuevo"


def test_6_settings_face_toggle():
    script = {
        "scenes": [
            {"n": 1, "phase": "hook", "asset_type": "a_roll"},
            {"n": 2, "phase": "body_1", "asset_type": "a_roll"},
        ]
    }
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "t1.webm", "duration_s": 2.0}},
        {"id": "t2", "kind": "a_roll_take", "scene_n": 2, "status": "done", "output": {"storage_path": "t2.webm", "duration_s": 2.0}},
        {"kind": "ai_image", "scene_n": 1, "status": "done", "output": {"storage_path": "b1.png"}},
    ]
    # Scene 1 has B-roll ready; scene 2 has no B-roll.
    settings = {"face": {"1": False, "2": False}}
    res = build_timeline(script, jobs, settings, edit_version=1)
    scenes = res["timeline"]["scenes"]
    assert scenes[0]["visual"] == "broll"
    assert scenes[1]["visual"] == "face"
    assert any("scene 2: no b-roll ready, showing face" in w for w in res["warnings"])


def test_7_trim_adjustments():
    script = {"scenes": [{"n": 1, "phase": "hook", "asset_type": "a_roll"}]}
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "t1.webm", "duration_s": 3.0}},
        {"kind": "transcript", "status": "done", "input": {"take_job_id": "t1"}, "output": {"words": [{"text": "Hola", "start_ms": 100, "end_ms": 2500}]}},
    ]

    # start_ms = 300 -> trims 300 ms from start
    settings_trim_300 = {"trim": {"1": {"start_ms": 300, "end_ms": 0}}}
    res1 = build_timeline(script, jobs, settings_trim_300, edit_version=1)
    seg1 = res1["timeline"]["scenes"][0]["segments"][0]
    # Original segment: in_ms=0 (100 - 100), out_ms=2600.
    # Trim +300 -> in_ms becomes 300.
    assert seg1["in_ms"] == 300

    # start_ms = -800 -> bounded to -500, but in_ms cannot go below 0
    settings_trim_neg800 = {"trim": {"1": {"start_ms": -800, "end_ms": 0}}}
    res2 = build_timeline(script, jobs, settings_trim_neg800, edit_version=1)
    seg2 = res2["timeline"]["scenes"][0]["segments"][0]
    assert seg2["in_ms"] == 0


def test_8_no_transcript_fallback():
    script = {"scenes": [{"n": 1, "phase": "hook", "asset_type": "a_roll"}]}
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "t1.webm", "duration_s": 2.5}},
    ]
    res = build_timeline(script, jobs, settings=None, edit_version=1)
    scenes = res["timeline"]["scenes"]
    assert len(scenes[0]["segments"]) == 1
    assert scenes[0]["segments"][0]["in_ms"] == 0
    assert scenes[0]["segments"][0]["out_ms"] == 2500
    assert any("scene 1: no transcript, not cut" in w for w in res["warnings"])


def test_9_music_muted():
    script = {"scenes": [{"n": 1, "phase": "hook", "asset_type": "a_roll"}]}
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "t1.webm", "duration_s": 2.0}},
        {"kind": "music", "scene_n": None, "status": "done", "output": {"use_music": True, "volume": 0.2, "storage_path": "music/m.mp3"}},
    ]
    settings = {"music_muted": True}
    res = build_timeline(script, jobs, settings, edit_version=1)
    assert res["timeline"]["music"] is None
    assert "music" not in res["inputs"]


def test_10_timeline_hash_behavior():
    script = {"scenes": [{"n": 1, "phase": "hook", "asset_type": "a_roll"}]}
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "output": {"storage_path": "t1.webm", "duration_s": 3.0}},
    ]
    s1 = {"trim": {"1": {"start_ms": 100, "end_ms": 0}}, "sfx_enabled": True}
    s2 = {"sfx_enabled": True, "trim": {"1": {"start_ms": 100, "end_ms": 0}}}
    s3 = {"trim": {"1": {"start_ms": 200, "end_ms": 0}}, "sfx_enabled": True}

    res1 = build_timeline(script, jobs, s1, edit_version=1)
    res2 = build_timeline(script, jobs, s2, edit_version=1)
    res3 = build_timeline(script, jobs, s3, edit_version=1)

    assert res1["timeline"]["hash"] == res2["timeline"]["hash"]
    assert res1["timeline"]["hash"] != res3["timeline"]["hash"]


def test_11_derive_caption_style():
    # 1. Hex color
    bb1 = {"identidad": {"colores": "azul y #FF6600", "tipografias": "Montserrat"}}
    st1 = derive_caption_style(bb1)
    assert st1["accent"] == "#FF6600"
    CaptionStyle.model_validate(st1)

    # 2. Named color from dictionary ("Azul marino") -> lightened hex
    bb2 = {"identidad": {"colores": "Azul marino", "tipografias": "Inter"}}
    st2 = derive_caption_style(bb2)
    assert st2["accent"] != "#1E3A8A"  # Dark blue lightened
    CaptionStyle.model_validate(st2)

    # 3. None -> Cool Paper lightened
    st3 = derive_caption_style(None)
    assert st3["accent"] == "#8094E8"
    CaptionStyle.model_validate(st3)

    # 4. Font keyword & explicit font
    bb4 = {"identidad": {"colores": "verde", "tipografias": "Bebas Neue para títulos"}}
    st4 = derive_caption_style(bb4)
    assert st4["font"] == "Bebas Neue"
    CaptionStyle.model_validate(st4)

    bb5 = {"identidad": {"colores": "rojo", "tipografias": "algo condensado"}}
    st5 = derive_caption_style(bb5)
    assert st5["font"] == "Anton"
    CaptionStyle.model_validate(st5)


def test_capitan_face_scene_does_not_ship_its_broll_and_null_duration_is_bounded():
    """QA del Capitán: una escena con cara no manda su B-roll al servicio; una toma sin duración usa la última palabra."""
    from app.editing.timeline import build_timeline

    script = {"scenes": [{"n": 1, "phase": "hook", "asset_type": "stock"}]}
    jobs = [
        {"id": "t1", "kind": "a_roll_take", "scene_n": 1, "status": "done", "created_at": "2026-09-25T10:00:00",
         "output": {"storage_path": "x/idea/1/take.webm", "duration_s": None}},
        {"id": "tr1", "kind": "transcript", "scene_n": 1, "status": "done", "created_at": "2026-09-25T10:01:00",
         "input": {"take_job_id": "t1"},
         "output": {"words": [{"text": "Hola", "start_ms": 200, "end_ms": 600}, {"text": "mundo.", "start_ms": 650, "end_ms": 1100}]}},
        {"id": "s1", "kind": "stock", "scene_n": 1, "status": "done", "created_at": "2026-09-25T10:02:00",
         "output": {"video_url": "https://videos.pexels.com/v.mp4", "width": 3840, "height": 2160, "duration_s": 12}},
    ]
    face = build_timeline(script, jobs, {"face": {"1": True}}, edit_version=1)
    assert face["timeline"]["scenes"][0]["visual"] == "face"
    assert face["timeline"]["scenes"][0]["broll"] is None
    assert "broll_s1" not in face["inputs"]
    assert face["timeline"]["duration_ms"] > 300  # bounded by the last word, not the 300 ms fallback

    broll = build_timeline(script, jobs, None, edit_version=1)
    assert broll["timeline"]["scenes"][0]["visual"] == "broll"
    assert broll["inputs"]["broll_s1"]["external_url"] == "https://videos.pexels.com/v.mp4"
