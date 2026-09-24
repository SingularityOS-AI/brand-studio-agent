"""
Motion Graphics Resolver using HyperFrames templates (Pieza 54).

Generates HTML compositions from templates (stat, quote, list, lower_third)
based on deterministic rules applied to scene content.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Literal

from app.audiovisual.storage import upload_bytes

# Template directory
TEMPLATES_DIR = Path(__file__).parent / "motion_templates"


def _escape_for_html(text: str) -> str:
    """Escape text for safe HTML insertion."""
    return html.escape(text, quote=True)


def _escape_for_json(text: str) -> str:
    """Escape text for safe JSON insertion, then escape </ to prevent script injection."""
    # First JSON encode, then escape </ to prevent </script> injection
    json_str = json.dumps(text)
    # Remove the surrounding quotes that json.dumps adds
    if json_str.startswith('"') and json_str.endswith('"'):
        json_str = json_str[1:-1]
    # Escape </ to prevent closing script tags
    return json_str.replace('</', '\\u003c/')


def _extract_number(text: str) -> str:
    """Extract a number (with optional % suffix) from text."""
    # Match patterns like: 40%, 40 percent, $40M, 1,234, 1.5M, etc.
    patterns = [
        r'(\d{1,3}(?:,\d{3})+)\s*(%|percent|k|K|m|M|b|B)?',  # 1,000 or 1,000K
        r'(\d+(?:\.\d+)?)\s*(%|percent|k|K|m|M|b|B)?',  # 40.5 or 40.5%
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            num = match.group(1)
            suffix = match.group(2) or ''
            if suffix.lower() == 'percent':
                suffix = '%'
            return num + suffix
    # Fallback: return the first number found
    digits = re.search(r'\d+(?:\.\d+)?', text)
    if digits:
        return digits.group(0)
    return "0"


def _is_list(text: str) -> bool:
    """Check if text contains 2+ list items."""
    text = text.strip()
    # Count bullet points
    bullet_count = len(re.findall(r'^[\s]*[•\-\*\–\—][\s]', text, re.MULTILINE))
    if bullet_count >= 2:
        return True
    # Count items separated by commas, "y", "and", "or"
    # Split by common separators and filter out empty
    separators = r'[,;]|\sy\s|\sand\s|\sor\s|\n'
    parts = re.split(separators, text)
    non_empty = [p.strip() for p in parts if p.strip()]
    return len(non_empty) >= 2


def _parse_list_items(text: str) -> list[str]:
    """Extract list items from text."""
    text = text.strip()
    if not text:
        return ["Item 1", "Item 2"]

    # Try bullet points first
    bullet_pattern = r'^[\s]*[•\-\*\–\—][\s]*(.*?)$'
    bullets = re.findall(bullet_pattern, text, re.MULTILINE | re.IGNORECASE)
    if bullets and len(bullets) >= 2:
        return [b.strip() for b in bullets[:4] if b.strip()] or ["Item 1", "Item 2"]

    # Try numbered list
    numbered_pattern = r'^[\s]*\d+[.\)][\s]*(.*?)$'
    numbered = re.findall(numbered_pattern, text, re.MULTILINE | re.IGNORECASE)
    if numbered and len(numbered) >= 2:
        return [n.strip() for n in numbered[:4] if n.strip()] or ["Item 1", "Item 2"]

    # Split by common separators
    separators = r'[,;]|\sy\s|\sand\s|\sor\s|\n'
    parts = re.split(separators, text)
    items = [p.strip() for p in parts if p.strip()]
    if len(items) >= 2:
        return items[:4]

    # Fallback: split by sentence endings
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sentences) >= 2:
        return sentences[:4]

    return [text[:60], text[60:120]] if len(text) > 60 else [text, ""]


def select_template(
    on_screen_text: str = "",
    visual_prompt: str = "",
    spoken_text: str = "",
) -> tuple[Literal["stat", "quote", "list", "lower_third"], dict[str, Any]]:
    """
    Select template based on deterministic rules.

    Rules (in order of precedence):
    1. Contains number or % → stat (extracts the number)
    2. Contains quotes or starts with first-person affirmation → quote
    3. Contains 2+ items separated by comma/"y"/"and"/bullets → list
    4. Default → lower_third

    Returns (template_name, fields_dict).
    """
    combined = f"{on_screen_text} {visual_prompt} {spoken_text}".strip()
    text_lower = combined.lower()

    # Rule 1: Number or percentage → stat
    if re.search(r'\d+\s*%|\d+\s*percent|\b\d{1,3}(?:,\d{3})+\b|\$?\d+(?:\.\d+)?[kKmMbB]?', combined):
        value = _extract_number(on_screen_text or visual_prompt or spoken_text)
        # Use on_screen_text as label, or spoken_text if on_screen is empty
        label = (on_screen_text or spoken_text or "Statistic").strip()
        # Remove the number from label to avoid duplication
        label_clean = re.sub(r'\d+\s*%|\d+\s*percent|\$?\d[\d,.]*[kKmMbB%]?', '', label, flags=re.IGNORECASE).strip()
        label_clean = re.sub(r'^[\s\-\–\—\*•]+|[\s\-\–\—\*•]+$', '', label_clean).strip()
        if not label_clean:
            label_clean = "Result"
        return "stat", {"value": value, "headline": label_clean}

    # Rule 2: Contains quotes or starts with first-person → quote
    has_quotes = '"' in combined or '"' in combined or '"' in combined
    first_person_patterns = [
        r'^\s*"\s*i\s',
        r'^\s*"\s*we\s',
        r'^\s*i\s',
        r'^\s*we\s',
        r"^\s*my\s",
        r"^\s*our\s",
    ]
    is_first_person = any(re.search(p, text_lower, re.IGNORECASE) for p in first_person_patterns)

    if has_quotes or is_first_person:
        # Remove quotes from headline
        headline = (on_screen_text or spoken_text or "").strip()
        headline = headline.strip('"""').strip()
        # Subline could be speaker/attribution
        subline = visual_prompt.strip() if visual_prompt else ""
        if not subline and len(headline) > 100:
            parts = headline.rsplit(' - ', 1)
            if len(parts) == 2:
                headline, subline = parts
        return "quote", {"headline": headline, "subline": subline}

    # Rule 3: Contains list items → list
    if _is_list(on_screen_text or spoken_text):
        items = _parse_list_items(on_screen_text or spoken_text)
        headline = visual_prompt.strip() if visual_prompt else "Key Points"
        return "list", {"items": items, "headline": headline}

    # Rule 4: Default → lower_third
    headline = (on_screen_text or spoken_text or "").strip()
    # Truncate if too long for lower third
    if len(headline) > 120:
        headline = headline[:117] + "..."
    subline = visual_prompt.strip() if visual_prompt else ""
    if not subline and len(spoken_text) > 150:
        # Use first sentence as headline
        sentences = re.split(r'[.!?]+', spoken_text)
        if len(sentences) > 1:
            headline = sentences[0].strip()[:120]
            subline = '. '.join(sentences[1:])[:120]
    return "lower_third", {"headline": headline, "subline": subline}


def build_html(template_name: str, fields: dict[str, Any], duration_s: float = 5.0) -> str:
    """
    Build HTML from template with field substitution.

    Escapes all text content to prevent XSS.
    """
    template_path = TEMPLATES_DIR / f"{template_name}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    html_template = template_path.read_text(encoding="utf-8")

    # Prepare substitutions
    subs = {
        "DURATION_S": str(float(duration_s)),
    }

    if template_name == "stat":
        subs["VALUE"] = _escape_for_html(fields.get("value", "0"))
        subs["HEADLINE"] = _escape_for_html(fields.get("headline", ""))
    elif template_name == "quote":
        subs["HEADLINE"] = _escape_for_html(fields.get("headline", ""))
        subs["SUBLINE"] = _escape_for_html(fields.get("subline", ""))
    elif template_name == "list":
        subs["HEADLINE"] = _escape_for_html(fields.get("headline", "Key Points"))
        items = fields.get("items", ["Item 1", "Item 2"])
        # Escape each item and prepare for JSON injection
        escaped_items = [_escape_for_json(item) for item in items if item.strip()]
        subs["ITEMS_JSON"] = json.dumps(escaped_items)
    elif template_name == "lower_third":
        subs["HEADLINE"] = _escape_for_html(fields.get("headline", ""))
        subs["SUBLINE"] = _escape_for_html(fields.get("subline", ""))
    else:
        raise ValueError(f"Unknown template: {template_name}")

    # Perform substitutions
    result = html_template
    for key, value in subs.items():
        result = result.replace(f"{{{{{key}}}}}", value)

    return result


async def resolve_motion_graphic(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'motion_graphic' job (Pieza 54).

    1. Selects template based on deterministic rules
    2. Builds HTML from template with field substitution
    3. Uploads HTML to storage
    4. Returns output dict with template name, storage_path, duration, fields
    """
    input_data = job.get("input") or {}

    # Extract scene data
    on_screen_text = input_data.get("on_screen_text", "")
    visual_prompt = input_data.get("visual_prompt", "")
    spoken_text = input_data.get("spoken_text", "")
    duration_s = input_data.get("duration_s", 5.0)

    # Ensure duration is reasonable (default 5s, max 10s for motion graphics)
    try:
        duration_s = float(duration_s)
        if duration_s < 1.0:
            duration_s = 1.0
        elif duration_s > 10.0:
            duration_s = 10.0
    except (TypeError, ValueError):
        duration_s = 5.0

    # Select template
    template_name, fields = select_template(
        on_screen_text=on_screen_text,
        visual_prompt=visual_prompt,
        spoken_text=spoken_text,
    )

    # Build HTML
    html_content = build_html(template_name, fields, duration_s)

    # Upload HTML
    storage_path = upload_bytes(
        session_token=job["session_token"],
        idea_id=job["idea_id"],
        scene_n=job.get("scene_n"),
        job_id=job["id"],
        data=html_content.encode("utf-8"),
        mime="text/html",
    )

    return {
        "template": template_name,
        "storage_path": storage_path,
        "duration_s": duration_s,
        "fields": fields,
        "mime": "text/html",
    }


def get_motion_html(session_token: str, idea_id: str, scene_n: int) -> tuple[str, str] | tuple[None, None]:
    """
    Retrieve the HTML content for a motion graphic job.

    Returns (html_content, storage_path) or (None, None) if not found.
    """
    from app.audiovisual.jobs import list_jobs
    from app.audiovisual.storage import _get_storage_client, AV_STORAGE_BUCKET

    # Find the motion_graphic job for this scene
    jobs = list_jobs(session_token, idea_id)
    motion_job = None
    for job in jobs:
        if job.get("kind") == "motion_graphic" and job.get("scene_n") == scene_n:
            motion_job = job
            break

    if not motion_job:
        return None, None

    if motion_job.get("status") != "done":
        return None, None

    output = motion_job.get("output") or {}
    storage_path = output.get("storage_path")
    if not storage_path:
        return None, None

    # Try to fetch from storage
    client = _get_storage_client()
    if client is not None:
        try:
            # Download file content
            response = client.storage.from_(AV_STORAGE_BUCKET).download(storage_path)
            if response:
                html_content = response.decode("utf-8") if isinstance(response, bytes) else response
                return html_content, storage_path
        except Exception:
            # Fall through to None
            pass

    # Fallback: try local cache
    import os
    local_path = os.path.join("cache", "storage", AV_STORAGE_BUCKET, storage_path)
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read(), storage_path
        except Exception:
            pass

    return None, None
