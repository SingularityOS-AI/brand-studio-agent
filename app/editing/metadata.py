"""
Publication metadata generation per platform (Piece 88A - Block E).

Generates platform-specific title, description, hashtags, and first comment
for LinkedIn, Instagram, and TikTok using Gemini LLM with a deterministic fallback.
"""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from typing import Any

from app.audiovisual.genai_client import get_genai_client
from app.config import settings

PLATFORMS = ("linkedin", "instagram", "tiktok")

LIMITS = {
    "linkedin": {"title": 100, "description": 1300},
    "instagram": {"title": 100, "description": 2200},
    "tiktok": {"title": 100, "description": 2200},
}

DEFAULT_HASHTAGS = ["#marcapersonal", "#founders", "#emprendimiento", "#contenido", "#shorts"]
LLM_TIMEOUT_META = 15.0

TAG_CONTENT_PATTERN = re.compile(r"^[A-Za-z0-9_áéíóúñÁÉÍÓÚÑ]{1,30}$")


def sanitize_text(text: Any, max_len: int) -> str:
    """
    Sanitize text: string, no control characters (except newline \n),
    no '<' or '>', sliced to max_len.
    """
    if text is None:
        return ""
    s = str(text)
    s = s.replace("<", "").replace(">", "")
    cleaned = []
    for char in s:
        if char == "\n" or (ord(char) >= 32 and ord(char) != 127 and unicodedata.category(char) != "Cc"):
            cleaned.append(char)
    result = "".join(cleaned)
    return result[:max_len]


def sanitize_hashtags(tags: Any) -> list[str]:
    """
    Sanitize hashtags: returns exactly 5 hashtags, each formatted as '#' + [A-Za-z0-9_áéíóúñÁÉÍÓÚÑ]{1,30}.
    Deduplicated case-insensitively. If fewer than 5 valid tags, completed with DEFAULT_HASHTAGS.
    """
    candidates: list[str] = []
    if isinstance(tags, str):
        candidates = tags.replace(",", " ").split()
    elif isinstance(tags, (list, tuple, set)):
        for item in tags:
            if isinstance(item, str):
                candidates.extend(item.replace(",", " ").split())
            elif item is not None:
                candidates.append(str(item))

    valid_tags: list[str] = []
    seen_lower: set[str] = set()

    for token in candidates:
        token_str = token.strip()
        if not token_str:
            continue
        if token_str.startswith("#"):
            body = token_str[1:]
        else:
            body = token_str

        if TAG_CONTENT_PATTERN.fullmatch(body):
            lower_tag = f"#{body.lower()}"
            if lower_tag not in seen_lower:
                seen_lower.add(lower_tag)
                valid_tags.append(f"#{body}")
                if len(valid_tags) == 5:
                    break

    if len(valid_tags) < 5:
        for default_tag in DEFAULT_HASHTAGS:
            lower_tag = default_tag.lower()
            if lower_tag not in seen_lower:
                seen_lower.add(lower_tag)
                valid_tags.append(default_tag)
                if len(valid_tags) == 5:
                    break

    return valid_tags[:5]


def _extract_script_data(script: dict | Any) -> tuple[str, str, str, str, str]:
    """Extracts (title, angle, frame_zero_text, body_text, cta_text) from script object or dict."""
    def get_val(obj: Any, key: str, default: Any = "") -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    title = str(get_val(script, "title", "") or "")
    angle = str(get_val(script, "angle", "") or "")

    fz = get_val(script, "frame_zero", None)
    fz_text = ""
    if isinstance(fz, dict):
        fz_text = fz.get("on_screen_text") or fz.get("visual") or ""
    elif fz is not None:
        fz_text = getattr(fz, "on_screen_text", "") or getattr(fz, "visual", "") or str(fz)
    fz_text = str(fz_text)

    scenes = get_val(script, "scenes", []) or []
    body_text = ""
    cta_text = ""

    for sc in scenes:
        phase = str(get_val(sc, "phase", "") or "").lower()
        spoken = str(get_val(sc, "spoken_text", "") or get_val(sc, "on_screen_text", "") or "")

        if not body_text and (phase in ("body_1", "body_2", "body") or phase.startswith("body")):
            body_text = spoken

        if phase == "close_cta":
            cta_text = spoken

    if not body_text and len(scenes) > 1:
        body_text = str(get_val(scenes[1], "spoken_text", "") or "")
    elif not body_text and scenes:
        body_text = str(get_val(scenes[0], "spoken_text", "") or "")

    if not cta_text and scenes:
        cta_text = str(get_val(scenes[-1], "spoken_text", "") or "")

    return title, angle, fz_text, body_text, cta_text


def fallback_metadata(script: dict | Any, brand_brain: dict | None) -> dict:
    """
    Deterministic fallback metadata generator when LLM is unavailable or times out.
    """
    title, angle, fz_text, body_text, cta_text = _extract_script_data(script)

    desc_parts = [p for p in [fz_text, body_text, cta_text] if p.strip()]
    raw_desc = "\n\n".join(desc_parts) if desc_parts else title

    raw_first_comment = cta_text.strip() if cta_text.strip() else "¿Qué opinas? Te leo en los comentarios."

    words = re.findall(r"[A-Za-z0-9_áéíóúñÁÉÍÓÚÑ]+", f"{title} {angle}")
    long_words = [w.lower() for w in words if len(w) >= 4]
    derived_tags = [f"#{w}" for w in long_words]
    clean_hashtags = sanitize_hashtags(derived_tags)

    platforms_res = {}
    for p in PLATFORMS:
        limit_t = LIMITS[p]["title"]
        limit_d = LIMITS[p]["description"]
        platforms_res[p] = {
            "title": sanitize_text(title, limit_t),
            "description": sanitize_text(raw_desc, limit_d),
            "hashtags": clean_hashtags,
            "first_comment": sanitize_text(raw_first_comment, 300),
        }

    return {
        "source": "fallback",
        "platforms": platforms_res,
    }


async def generate_metadata(
    script: dict | Any,
    brand_brain: dict | None,
    *,
    timeout_s: float | None = None,
) -> dict:
    """
    Generates platform publication metadata using Gemini LLM.
    Falls back to deterministic metadata on failure, timeout or invalid output.
    """
    fb = fallback_metadata(script, brand_brain)
    fb_platforms = fb["platforms"]

    try:
        from google.genai import types

        title, angle, fz_text, body_text, cta_text = _extract_script_data(script)
        scenes = script.get("scenes", []) if isinstance(script, dict) else getattr(script, "scenes", [])
        scenes_summary = []
        for sc in scenes:
            ph = sc.get("phase", "") if isinstance(sc, dict) else getattr(sc, "phase", "")
            sp = sc.get("spoken_text", "") if isinstance(sc, dict) else getattr(sc, "spoken_text", "")
            scenes_summary.append(f"[{ph}]: {sp}")
        scenes_str = "\n".join(scenes_summary)

        brand_soul_str = ""
        if brand_brain:
            brand_soul_str = f"\nBrand Soul / Identity context: {json.dumps(brand_brain, ensure_ascii=False)}"

        system_instruction = (
            "You are a social media manager expert in personal branding content.\n"
            "Generate publication metadata tailored for 3 platforms: LinkedIn, Instagram, and TikTok.\n"
            "Platform guidelines:\n"
            "- LinkedIn: B2B, personal brand, professional tone, minimal emojis.\n"
            "- Instagram: less formal, engaging hook in first line, moderate emojis.\n"
            "- TikTok: direct, punchy, concise.\n"
            "- first_comment: call-to-action for the first comment.\n"
            "Must output ONLY valid JSON matching this structure:\n"
            "{\n"
            '  "platforms": {\n'
            '    "linkedin": {"title": str, "description": str, "hashtags": [str], "first_comment": str},\n'
            '    "instagram": {"title": str, "description": str, "hashtags": [str], "first_comment": str},\n'
            '    "tiktok": {"title": str, "description": str, "hashtags": [str], "first_comment": str}\n'
            "  }\n"
            "}\n"
            "Use the exact language of the script."
        )

        prompt = (
            f"Script Title: {title}\n"
            f"Script Angle: {angle}\n"
            f"Frame Zero: {fz_text}\n"
            f"Scenes:\n{scenes_str}\n"
            f"Close CTA: {cta_text}\n"
            f"{brand_soul_str}\n"
        )

        client = get_genai_client()
        model_name = getattr(settings, "vertex_ai_model", "gemini-2.5-flash")

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.7,
        )

        actual_timeout = timeout_s if timeout_s is not None else LLM_TIMEOUT_META

        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            ),
            timeout=actual_timeout,
        )

        raw_text = (getattr(resp, "text", "") or "").strip()
        if not raw_text:
            return fb

        data = json.loads(raw_text)
        if not isinstance(data, dict):
            return fb

        platforms_data = data.get("platforms", data)
        if not isinstance(platforms_data, dict):
            return fb

        llm_platforms = {}
        for p in PLATFORMS:
            limit_t = LIMITS[p]["title"]
            limit_d = LIMITS[p]["description"]
            fb_item = fb_platforms[p]

            p_item = platforms_data.get(p)
            if isinstance(p_item, dict):
                raw_t = p_item.get("title")
                clean_t = sanitize_text(raw_t, limit_t) if raw_t else fb_item["title"]

                raw_d = p_item.get("description")
                clean_d = sanitize_text(raw_d, limit_d) if raw_d else fb_item["description"]

                raw_h = p_item.get("hashtags")
                clean_h = sanitize_hashtags(raw_h) if raw_h else fb_item["hashtags"]

                raw_c = p_item.get("first_comment")
                clean_c = sanitize_text(raw_c, 300) if raw_c else fb_item["first_comment"]

                llm_platforms[p] = {
                    "title": clean_t or fb_item["title"],
                    "description": clean_d or fb_item["description"],
                    "hashtags": clean_h,
                    "first_comment": clean_c or fb_item["first_comment"],
                }
            else:
                llm_platforms[p] = fb_item

        return {
            "source": "llm",
            "platforms": llm_platforms,
        }
    except Exception:
        return fb
