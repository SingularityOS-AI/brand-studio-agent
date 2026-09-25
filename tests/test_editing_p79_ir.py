"""Tests for P79 IR Stage 1 (frame zero + captions)."""

from app.editing.ir import build_ir_stage1
from render_service.manifest import RenderIR

SAMPLE_STYLE = {
    "font": "Montserrat",
    "text": "#FFFFFF",
    "accent": "#2B4CD8",
    "outline": "#000000",
}


def test_1_frame_zero_filters_early_words():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Antes", "start_ms": 500, "end_ms": 900},
        {"id": "s1w1", "scene_n": 1, "text": "Durante", "start_ms": 1200, "end_ms": 1400},
        {"id": "s1w2", "scene_n": 1, "text": "Despues", "start_ms": 1600, "end_ms": 1900},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text="MI HOOK POTENTE",
        style=SAMPLE_STYLE,
    )

    assert ir["frame_zero"] is not None
    assert ir["frame_zero"]["text"] == "MI HOOK POTENTE"
    assert ir["frame_zero"]["start_ms"] == 0
    assert ir["frame_zero"]["end_ms"] == 1500

    for event in ir["captions"]:
        for line in event["lines"]:
            for token in line:
                assert token["start_ms"] >= 1500
                assert token["text"] != "Antes"
                assert token["text"] != "Durante"

    assert len(ir["captions"]) == 1
    assert ir["captions"][0]["lines"][0][0]["text"] == "Despues"
    RenderIR.model_validate(ir)


def test_2_hero_events_between_1500_and_3000():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Uno", "start_ms": 1600, "end_ms": 1900},
        {"id": "s1w1", "scene_n": 1, "text": "Dos", "start_ms": 2200, "end_ms": 2500},
        {"id": "s1w2", "scene_n": 1, "text": "Tres", "start_ms": 3100, "end_ms": 3400},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text="HOOK",
        style=SAMPLE_STYLE,
    )

    hero_events = [ev for ev in ir["captions"] if ev["size"] == "hero"]
    assert len(hero_events) == 2
    assert hero_events[0]["lines"] == [[{"text": "Uno", "start_ms": 1600, "end_ms": 1900}]]
    assert hero_events[1]["lines"] == [[{"text": "Dos", "start_ms": 2200, "end_ms": 2500}]]

    block_events = [ev for ev in ir["captions"] if ev["size"] == "block"]
    assert len(block_events) == 1
    assert block_events[0]["lines"] == [[{"text": "Tres", "start_ms": 3100, "end_ms": 3400}]]

    RenderIR.model_validate(ir)


def test_3_block_splitting_on_punctuation_and_3_words():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Hola", "start_ms": 3100, "end_ms": 3300},
        {"id": "s1w1", "scene_n": 1, "text": "mundo.", "start_ms": 3400, "end_ms": 3700},
        {"id": "s1w2", "scene_n": 1, "text": "Esto", "start_ms": 3800, "end_ms": 4000},
        {"id": "s1w3", "scene_n": 1, "text": "es", "start_ms": 4100, "end_ms": 4200},
        {"id": "s1w4", "scene_n": 1, "text": "nuevo", "start_ms": 4300, "end_ms": 4500},
        {"id": "s1w5", "scene_n": 1, "text": "hoy", "start_ms": 4600, "end_ms": 4800},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )

    block_events = ir["captions"]
    assert len(block_events) == 3

    tokens_ev1 = [t["text"] for line in block_events[0]["lines"] for t in line]
    assert tokens_ev1 == ["Hola", "mundo."]

    tokens_ev2 = [t["text"] for line in block_events[1]["lines"] for t in line]
    assert tokens_ev2 == ["Esto", "es", "nuevo"]

    tokens_ev3 = [t["text"] for line in block_events[2]["lines"] for t in line]
    assert tokens_ev3 == ["hoy"]

    RenderIR.model_validate(ir)


def test_4_scene_change_closes_block():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Hola", "start_ms": 3100, "end_ms": 3300},
        {"id": "s2w0", "scene_n": 2, "text": "amigo", "start_ms": 3400, "end_ms": 3700},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )

    events = ir["captions"]
    assert len(events) == 2
    tokens_ev1 = [t["text"] for line in events[0]["lines"] for t in line]
    tokens_ev2 = [t["text"] for line in events[1]["lines"] for t in line]

    assert tokens_ev1 == ["Hola"]
    assert tokens_ev2 == ["amigo"]
    RenderIR.model_validate(ir)


def test_5_long_block_splits_into_two_lines():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "extraordinariamente", "start_ms": 3100, "end_ms": 3500},
        {"id": "s1w1", "scene_n": 1, "text": "complicado", "start_ms": 3600, "end_ms": 3900},
        {"id": "s1w2", "scene_n": 1, "text": "ejemplo", "start_ms": 4000, "end_ms": 4300},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )

    events = ir["captions"]
    assert len(events) == 1
    lines = events[0]["lines"]
    assert len(lines) == 2
    assert len(lines[0]) >= 1
    assert len(lines[1]) >= 1
    assert [t["text"] for t in lines[0]] == ["extraordinariamente"]
    assert [t["text"] for t in lines[1]] == ["complicado", "ejemplo"]

    RenderIR.model_validate(ir)


def test_6_event_end_ms_handling_and_silence():
    timeline = {"duration_ms": 7000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Uno", "start_ms": 3000, "end_ms": 3500},
        {"id": "s1w1", "scene_n": 1, "text": "Dos", "start_ms": 5500, "end_ms": 6000},
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )

    events = ir["captions"]
    assert len(events) == 2

    assert events[0]["start_ms"] == 3000
    assert events[0]["end_ms"] == 3900

    assert events[1]["start_ms"] == 5500
    assert events[1]["end_ms"] == 6400
    assert events[1]["end_ms"] <= timeline["duration_ms"]

    RenderIR.model_validate(ir)


def test_7_edited_text_replaces_text_keeps_times():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {
            "id": "s1w0",
            "scene_n": 1,
            "text": "Original",
            "edited_text": "Editado",
            "start_ms": 3100,
            "end_ms": 3400,
        }
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text=None,
        style=SAMPLE_STYLE,
    )

    events = ir["captions"]
    assert len(events) == 1
    token = events[0]["lines"][0][0]
    assert token["text"] == "Editado"
    assert token["start_ms"] == 3100
    assert token["end_ms"] == 3400

    RenderIR.model_validate(ir)


def test_8_no_frame_zero_starts_hook_at_0():
    timeline = {"duration_ms": 10000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Primera", "start_ms": 200, "end_ms": 500},
        {"id": "s1w1", "scene_n": 1, "text": "Segunda", "start_ms": 600, "end_ms": 900},
    ]

    for fz_input in [None, "", "   "]:
        ir = build_ir_stage1(
            timeline=timeline,
            captions_words=captions_words,
            frame_zero_text=fz_input,
            style=SAMPLE_STYLE,
        )

        assert ir["frame_zero"] is None
        events = ir["captions"]
        assert len(events) == 2
        assert events[0]["size"] == "hero"
        assert events[0]["lines"][0][0]["text"] == "Primera"
        assert events[1]["size"] == "hero"
        assert events[1]["lines"][0][0]["text"] == "Segunda"

        RenderIR.model_validate(ir)


def test_9_always_validates_render_ir():
    timeline = {"duration_ms": 12000}
    captions_words = [
        {"id": "s1w0", "scene_n": 1, "text": "Probando", "start_ms": 1600, "end_ms": 2000}
    ]
    ir = build_ir_stage1(
        timeline=timeline,
        captions_words=captions_words,
        frame_zero_text="Test validation",
        style=SAMPLE_STYLE,
    )

    validated = RenderIR.model_validate(ir)
    assert validated.schema == "brandstudio.ir.v1"
    assert validated.duration_ms == 12000
    assert validated.frame_zero is not None
    assert validated.frame_zero.text == "Test validation"
