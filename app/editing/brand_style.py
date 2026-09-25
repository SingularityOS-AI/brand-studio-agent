"""Brand style derivation from Brand Soul text free format into CaptionStyle contract (Bloque E)."""

from __future__ import annotations

import re

from render_service.manifest import FONT_ALLOWLIST, CaptionStyle

COLOR_NAME_HEX: list[tuple[str, str]] = [
    ("azul marino", "#1E3A8A"),
    ("sky blue", "#38BDF8"),
    ("celeste", "#38BDF8"),
    ("azul", "#2563EB"),
    ("blue", "#2563EB"),
    ("rojo", "#EF4444"),
    ("red", "#EF4444"),
    ("verde", "#22C55E"),
    ("green", "#22C55E"),
    ("amarillo", "#EAB308"),
    ("yellow", "#EAB308"),
    ("naranja", "#F97316"),
    ("orange", "#F97316"),
    ("morado", "#A855F7"),
    ("purple", "#A855F7"),
    ("violeta", "#A855F7"),
    ("rosa", "#EC4899"),
    ("pink", "#EC4899"),
    ("turquesa", "#14B8A6"),
    ("teal", "#14B8A6"),
    ("dorado", "#EAB308"),
    ("gold", "#EAB308"),
]

COOL_PAPER_ACCENT = "#2B4CD8"


def _extract_identidad(brand_brain: dict | None) -> dict:
    if not isinstance(brand_brain, dict):
        return {}
    if "identidad" in brand_brain and isinstance(brand_brain["identidad"], dict):
        return brand_brain["identidad"]
    if "data" in brand_brain and isinstance(brand_brain["data"], dict):
        d = brand_brain["data"]
        if "identidad" in d and isinstance(d["identidad"], dict):
            return d["identidad"]
    if "sections" in brand_brain and isinstance(brand_brain["sections"], dict):
        s = brand_brain["sections"]
        if "identidad" in s and isinstance(s["identidad"], dict):
            return s["identidad"]
    return {}


def _is_black_white_gray(r: int, g: int, b: int) -> bool:
    if r < 40 and g < 40 and b < 40:
        return True
    if r > 220 and g > 220 and b > 220:
        return True
    if max(r, g, b) - min(r, g, b) < 15:
        return True
    return False


def _relative_luminance(r: int, g: int, b: int) -> float:
    rs = r / 255.0
    gs = g / 255.0
    bs = b / 255.0
    r_lin = rs / 12.92 if rs <= 0.04045 else ((rs + 0.055) / 1.055) ** 2.4
    g_lin = gs / 12.92 if gs <= 0.04045 else ((gs + 0.055) / 1.055) ** 2.4
    b_lin = bs / 12.92 if bs <= 0.04045 else ((bs + 0.055) / 1.055) ** 2.4
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def _lighten_color_40_percent(r: int, g: int, b: int) -> str:
    nr = round(r * 0.6 + 255 * 0.4)
    ng = round(g * 0.6 + 255 * 0.4)
    nb = round(b * 0.6 + 255 * 0.4)
    nr = max(0, min(255, nr))
    ng = max(0, min(255, ng))
    nb = max(0, min(255, nb))
    return f"#{nr:02X}{ng:02X}{nb:02X}"


def _process_hex(hex_str: str) -> str | None:
    hex_str = hex_str.upper()
    r = int(hex_str[1:3], 16)
    g = int(hex_str[3:5], 16)
    b = int(hex_str[5:7], 16)
    if _is_black_white_gray(r, g, b):
        return None
    lum = _relative_luminance(r, g, b)
    if lum < 0.25:
        return _lighten_color_40_percent(r, g, b)
    return hex_str


def _derive_accent_color(identidad: dict) -> str:
    raw_colores = identidad.get("colores")
    if isinstance(raw_colores, list):
        colores_text = " ".join(str(c) for c in raw_colores)
    elif isinstance(raw_colores, str):
        colores_text = raw_colores
    else:
        colores_text = ""

    if colores_text:
        # 1. Find hex codes
        hex_matches = re.findall(
            r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b", colores_text
        )
        for m in hex_matches:
            if len(m) == 3:
                expanded = f"#{m[0]*2}{m[1]*2}{m[2]*2}"
            else:
                expanded = f"#{m}"
            processed = _process_hex(expanded)
            if processed:
                return processed

        # 2. Search named colors
        colores_lower = colores_text.lower()
        for name, hex_val in COLOR_NAME_HEX:
            if name in colores_lower:
                processed = _process_hex(hex_val)
                if processed:
                    return processed

    # Fallback Cool Paper accent
    fallback_processed = _process_hex(COOL_PAPER_ACCENT)
    return fallback_processed or "#8094E8"


def _derive_font(identidad: dict) -> str:
    raw_tipografias = identidad.get("tipografias")
    if isinstance(raw_tipografias, list):
        tipo_text = " ".join(str(t) for t in raw_tipografias)
    elif isinstance(raw_tipografias, str):
        tipo_text = raw_tipografias
    else:
        tipo_text = ""

    tipo_lower = tipo_text.lower()
    if tipo_lower:
        found_fonts: list[tuple[int, str]] = []
        for font_name in FONT_ALLOWLIST:
            pos = tipo_lower.find(font_name.lower())
            if pos != -1:
                found_fonts.append((pos, font_name))
        if found_fonts:
            found_fonts.sort(key=lambda x: x[0])
            return found_fonts[0][1]

        if "condens" in tipo_lower or "impact" in tipo_lower:
            return "Anton"
        if "bebas" in tipo_lower:
            return "Bebas Neue"
        if "geométric" in tipo_lower or "geometric" in tipo_lower:
            return "Montserrat"
        if (
            "redonda" in tipo_lower
            or "rounded" in tipo_lower
            or "friendly" in tipo_lower
        ):
            return "Poppins"

    return "Montserrat"


def derive_caption_style(brand_brain: dict | None) -> dict:
    """{"font": <FONT_ALLOWLIST>, "text": "#FFFFFF", "accent": "#RRGGBB", "outline": "#000000"}"""
    identidad = _extract_identidad(brand_brain)
    font = _derive_font(identidad)
    accent = _derive_accent_color(identidad)

    result = {
        "font": font,
        "text": "#FFFFFF",
        "accent": accent,
        "outline": "#000000",
    }
    CaptionStyle.model_validate(result)
    return result
