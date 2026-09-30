"""
Brand Brain auto-extraction (voice interview safety net).

The voice agent is SUPPOSED to call extract_brand_brain after every founder fact, but
in live tests it often only said it was saving ("Saving that skill.") without emitting
the tool call, so nothing reached the screen or the database. AssemblyAI's own guidance
is to not rely on the voice LLM for extraction: collect the transcript and run a
separate LLM call. This module does exactly that for ONE founder answer.

It only PROPOSES field values. Persistence still goes through /api/brain/extract, which
keeps every invariant (citation = the founder's literal words, found in the transcript;
"confirmado" only after an explicit yes).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_VALUE_CHARS = 200
MAX_UPDATES = 4


def build_prompt(question: str, answer: str, context: str, fields: list[dict[str, Any]]) -> str:
    lines = []
    for f in fields:
        alias = str(f.get("alias", "")).strip()
        if not alias:
            continue
        ask = str(f.get("ask", "")).strip()
        mark = " [already filled]" if f.get("filled") else ""
        lines.append(f"- {alias}: {ask}{mark}")
    field_list = "\n".join(lines)
    return (
        "You extract facts from ONE answer in a spoken brand interview.\n"
        "The interviewer (Brandy) asked or said:\n"
        f"\"{question.strip()}\"\n\n"
        "The founder answered:\n"
        f"\"{answer.strip()}\"\n\n"
        "Earlier conversation (context only):\n"
        f"{context.strip()}\n\n"
        "Brand fields (alias: what it captures):\n"
        f"{field_list}\n\n"
        "Return JSON: {\"updates\": [{\"field\": \"<alias from the list>\", \"value\": \"<short phrase>\"}]}\n"
        "Rules:\n"
        "- Only facts the founder states in THIS answer, or a proposal from Brandy that the founder explicitly accepts in this answer (then the value is Brandy's proposal).\n"
        "- Prefer the field Brandy's question was about. A fact that clearly belongs to another field goes there.\n"
        "- Use the founder's own words, at most 15 words per value. Never invent or embellish.\n"
        "- Return {\"updates\": []} for greetings, filler, questions back to Brandy, 'I don't know', or a bare yes/no with no new fact.\n"
        f"- At most {MAX_UPDATES} updates."
    )


def parse_updates(raw_text: str, allowed_aliases: set[str]) -> list[dict[str, str]]:
    """Parses the model output and keeps only well-formed updates for known fields."""
    try:
        data = json.loads(raw_text or "{}")
    except (TypeError, ValueError):
        return []
    items = data.get("updates") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        alias = str(item.get("field", "")).strip()
        value = str(item.get("value", "")).strip()
        if alias not in allowed_aliases or not value or alias in seen:
            continue
        seen.add(alias)
        out.append({"field": alias, "value": value[:MAX_VALUE_CHARS]})
        if len(out) >= MAX_UPDATES:
            break
    return out


async def auto_extract(question: str, answer: str, context: str, fields: list[dict[str, Any]],
                       model: Any = None) -> list[dict[str, str]]:
    """Returns [{field, value}] proposed from one founder answer. Never raises."""
    if not answer or not answer.strip():
        return []
    allowed = {str(f.get("alias", "")).strip() for f in fields if f.get("alias")}
    if not allowed:
        return []
    try:
        if model is None:
            from app.tools.brand_soul.generator import _get_vertex_ai_client
            model = _get_vertex_ai_client()
        if model is None:
            return []
        response = await model.generate_content_async(
            build_prompt(question or "", answer, context or "", fields),
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 512,
                "response_mime_type": "application/json",
            },
        )
        return parse_updates(getattr(response, "text", "") or "", allowed)
    except Exception as exc:  # noqa: BLE001 - the interview must never break on this
        logger.warning(f"[auto_extract] failed: {exc}")
        return []
