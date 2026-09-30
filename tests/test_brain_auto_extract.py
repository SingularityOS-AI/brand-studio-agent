"""Auto-extraction safety net: parsing, filtering and never-raise behaviour (model mocked)."""
import asyncio
import json
import os

os.environ["TEST_MODE"] = "true"

from app.tools.brand_brain.auto_extract import auto_extract, build_prompt, parse_updates

FIELDS = [
    {"alias": "diagnostico.stage", "ask": "their stage", "filled": False},
    {"alias": "diagnostico.skill_to_unlock", "ask": "the one skill they need", "filled": True},
]


class _Resp:
    def __init__(self, text):
        self.text = text


class _Model:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.prompts = text, exc, []

    async def generate_content_async(self, prompt, generation_config=None):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return _Resp(self.text)


def _run(coro):
    return asyncio.run(coro)


def test_keeps_only_known_fields_and_trims():
    raw = json.dumps({"updates": [
        {"field": "diagnostico.stage", "value": "  stage one  "},
        {"field": "invented.field", "value": "x"},
        {"field": "diagnostico.stage", "value": "duplicate"},
        {"field": "diagnostico.skill_to_unlock", "value": ""},
    ]})
    out = parse_updates(raw, {"diagnostico.stage", "diagnostico.skill_to_unlock"})
    assert out == [{"field": "diagnostico.stage", "value": "stage one"}]


def test_bad_json_returns_empty():
    assert parse_updates("not json", {"diagnostico.stage"}) == []
    assert parse_updates('{"updates": "nope"}', {"diagnostico.stage"}) == []


def test_auto_extract_uses_model_and_marks_filled_fields():
    model = _Model(text=json.dumps({"updates": [{"field": "diagnostico.stage", "value": "1, just starting"}]}))
    out = _run(auto_extract("What stage are you?", "I would say 1, just starting.", "", FIELDS, model=model))
    assert out == [{"field": "diagnostico.stage", "value": "1, just starting"}]
    assert "[already filled]" in model.prompts[0]
    assert "I would say 1, just starting." in model.prompts[0]


def test_auto_extract_never_raises():
    assert _run(auto_extract("q", "an answer here", "", FIELDS, model=_Model(exc=RuntimeError("vertex down")))) == []
    assert _run(auto_extract("q", "   ", "", FIELDS, model=_Model(text="{}"))) == []


def test_prompt_forbids_inventing():
    p = build_prompt("q", "a", "", FIELDS)
    assert "Never invent" in p and "diagnostico.stage" in p
