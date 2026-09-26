"""
Brand Soul Generator

Generates the Brand Soul document from a BrandBrain as one consolidated,
long-form prose document: an executive summary, nine titled chapters (one
per confirmed section) and a closing note — never a JSON-like or
key:value dump.

1. LLM ON A LEASH:
   - Only sees the facts of one section (plus its literal citation) at a time
   - Strictly forbidden from introducing new facts
   - Temperature = 0 for deterministic output
   - If the LLM is unavailable or fails, a deterministic fallback builds the
     same chapter as flowing sentences from the same facts — never a
     "field: value" dump.

2. CITATION VALIDATION:
   - Every citation in the generated HTML must exist literally in the brain
   - If any citation is invented, validation fails and document is NOT shown
   - Citations are taken from the brain verbatim, not reworded by LLM

3. CACHE LAYER:
   - Generated HTML is cached in Supabase (soul_html column)
   - Same brain produces same HTML every time (determinism)
   - Instant reopening of previously generated documents

Core design principle:
"The brand_brain is the ONLY source of truth. The LLM only redacts."
"""

import hashlib
import json

from app.config import settings
from app.tools.brand_brain.models import BrandBrain, Section
from app.tools.brand_brain.store import get_brand_brain
from app.tools.brand_soul.template import (
    build_soul_html,
    detect_etapa_from_brand_brain,
    get_etapa_context,
)


class SoulGenerationError(Exception):
    """Raised when Brand Soul cannot be generated"""


class CitationValidationError(SoulGenerationError):
    """Raised when generated HTML contains invented citations"""


class IncompleteBrainError(SoulGenerationError):
    """Raised when brain doesn't have all 9 confirmed sections"""


# =============================================================================
# CHAPTER MAP — section id -> English chapter heading, in document order
# =============================================================================

CHAPTERS: list[tuple[str, str]] = [
    ("diagnostico", "Diagnosis"),
    ("brand_journey", "Brand Journey"),
    ("charco", "Your Pond"),
    ("icp", "Ideal Client"),
    ("contrarian", "Contrarian Take"),
    ("asociaciones", "Associations"),
    ("identidad", "Identity"),
    ("oferta", "Offer"),
    ("lead_magnet", "Lead Magnet"),
]

REQUIRED_SECTION_IDS: list[str] = [section_id for section_id, _ in CHAPTERS]


def _check_all_sections_confirmed(brain: BrandBrain) -> tuple[bool, list[str]]:
    """
    Check if all 9 sections exist and are confirmed.

    Returns:
        Tuple of (is_complete, list_of_missing_sections)
    """
    missing_sections = []

    for section_id in REQUIRED_SECTION_IDS:
        section = brain.get_section(section_id)
        if not section:
            missing_sections.append(f"{section_id} (no existe)")
        elif section.status != "confirmado":
            missing_sections.append(f"{section_id} (estado: {section.status})")

    is_complete = len(missing_sections) == 0
    return is_complete, missing_sections


def _extract_literal_citations(brain: BrandBrain) -> dict[str, str]:
    """
    Extract all literal citation texts from the brand_brain.

    Returns:
        Dict mapping section_id -> literal citation text
    """
    return {section.id: section.citation_text for section in brain.sections}


def _get_vertex_ai_client():
    """
    Get the Vertex AI client for Gemini models.

    Returns:
        Vertex AI client or None if not configured/test mode

    Raises:
        RuntimeError: If Vertex AI is not configured in production mode
    """
    if not settings.vertex_ai_project_id:
        raise RuntimeError(
            "VERTEX_AI_PROJECT_ID is not configured. "
            "Set it in .env file or environment variable before starting the server."
        )

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(
            project=settings.vertex_ai_project_id,
            location=settings.vertex_ai_location,
        )

        return GenerativeModel(settings.vertex_ai_model)

    except ImportError:
        raise RuntimeError(
            "google-cloud-aiplatform is not installed. "
            "Install it with: pip install google-cloud-aiplatform"
        )
    except Exception as e:  # noqa: BLE001 - any client init failure must degrade, not crash
        raise RuntimeError(
            f"Failed to initialize Vertex AI client: {e}. "
            "Ensure VERTEX_AI_PROJECT_ID and VERTEX_AI_LOCATION are correct."
        )


# =============================================================================
# FACT EXTRACTION — plain (English label, raw value) pairs per section.
# Feeds both the LLM prompt and the deterministic fallback. Never rendered
# as "label: value" in the document itself — only used as prompt material
# or read individually inside a hand-written sentence.
# =============================================================================

_FACT_LABELS: dict[str, list[tuple[str, str]]] = {
    "diagnostico": [
        ("Current stage", "etapa"),
        ("Maturity level", "nivel_ramiro"),
        ("Observable symptom", "sintoma_diagnostico"),
        ("Skill to unlock", "habilidad_a_desbloquear"),
        ("Discipline to avoid", "prohibicion"),
        ("Speaking posture", "postura"),
        ("Evidence for that posture", "justificacion_postura"),
    ],
    "brand_journey": [
        ("Desired outcome", "resultado_deseado"),
        ("Reputation to build", "de_que_ser_conocido"),
        ("What to do", "que_hacer"),
        ("What to learn", "que_aprender"),
    ],
    "charco": [
        ("Core problem", "problema"),
        ("Pond level", "nivel"),
        ("Proof / track record", "logro_que_lo_respalda"),
        ("Cost of not solving it", "costo_de_no_resolverlo"),
        ("Past failed attempts", "intentos_fallidos"),
    ],
    "icp": [
        ("Who decides", "quien_decide"),
        ("Company size", "tamano_empresa"),
        ("Urgency trigger", "disparador_de_urgencia"),
        ("Buying power", "poder_adquisitivo"),
        ("Buying committee", "comite_de_compra"),
        ("Who they answer to", "a_quien_le_rinde_cuentas"),
    ],
    "contrarian": [
        ("Common belief", "creencia_comun"),
        ("Contrarian position", "postura_opuesta"),
        ("Proof", "prueba"),
        ("Why it is not provocation", "por_que_no_es_provocacion"),
    ],
    "asociaciones": [
        ("Desired associations", "deseadas"),
        ("Prohibited associations", "prohibidas"),
    ],
    "identidad": [
        ("Voice", "voz"),
        ("Colors", "colores"),
        ("Typography", "tipografias"),
        ("Origin story", "narrativa_de_origen"),
    ],
    "oferta": [
        ("Dream outcome", "resultado_sonado"),
        ("Perceived likelihood", "probabilidad_percibida"),
        ("Time delay", "retraso"),
        ("Effort required", "esfuerzo"),
        ("Offer components", "componentes"),
        ("Guarantee", "garantia"),
    ],
    "lead_magnet": [
        ("Type", "tipo"),
        ("Problem A (solved for free)", "problema_A"),
        ("Problem B (revealed by A)", "problema_B_que_revela"),
    ],
}


def _s(value) -> str:
    """Coerce a possibly-missing/list field into a single plain string."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_s(v) for v in value if _s(v))
    return str(value).strip()


def _facts_for(section_id: str, content: dict) -> list[tuple[str, str]]:
    """Non-empty (English label, value) pairs for one section's content."""
    labels = _FACT_LABELS.get(section_id, [])
    facts = [(label, _s(content.get(key))) for label, key in labels]
    return [(label, value) for label, value in facts if value]


# =============================================================================
# DETERMINISTIC FALLBACK PROSE — used when the LLM is unavailable/fails.
# Every builder returns 2-4 paragraphs (joined with a blank line) built from
# full sentences. Never a bullet list, never "label: value".
# =============================================================================


def _fallback_diagnostico(content: dict, etapa_context: dict) -> str:
    etapa = _s(content.get("etapa"))
    nivel_ramiro = _s(content.get("nivel_ramiro"))
    sintoma = _s(content.get("sintoma_diagnostico"))
    habilidad = _s(content.get("habilidad_a_desbloquear"))
    prohibicion = _s(content.get("prohibicion"))
    postura = _s(content.get("postura")).lower()
    justificacion = _s(content.get("justificacion_postura"))
    skill_to_unlock = _s(etapa_context.get("skill_to_unlock"))
    prohibited = _s(etapa_context.get("prohibited"))

    is_student = postura in ("estudiante", "hipotesis", "hipótesis")
    posture_word = "student" if is_student else "expert"
    posture_sentence = (
        "That means the founder is still at the beginning of the path, and right now a fresh, "
        "unfiltered perspective carries more weight with the audience than a long track record ever could."
        if is_student
        else "That means the founder has already walked the path others are still stuck on, and that "
        "lived experience — not a title — is the real competitive edge to lean on."
    )

    p1 = (
        f"This brand's honest starting point is the '{etapa}' stage"
        + (f", tracking at maturity level {nivel_ramiro} on the internal scale" if nivel_ramiro else "")
        + ". "
        + (f"The clearest observable symptom of where things stand today is {sintoma}. " if sintoma else "")
        + "Every recommendation in the chapters that follow is built on top of this diagnosis, not around it, "
        "because a stage that gets misread turns good advice into the wrong advice."
    )

    p2 = (
        f"Strategically, this founder is speaking from a position of {posture_word}. {posture_sentence}"
        + (f" The evidence behind that call is: {justificacion}." if justificacion else "")
    )

    p3 = (
        (f"At this stage, the single skill worth unlocking is {skill_to_unlock or habilidad}. " if (skill_to_unlock or habilidad) else "")
        + (f"The one discipline to actively avoid right now is {prohibited or prohibicion}. " if (prohibited or prohibicion) else "")
        + "Anything else competing for the founder's attention this quarter is, by definition, a distraction "
        "from the one move that actually changes the trajectory of the brand."
    )

    return "\n\n".join(p for p in (p1, p2, p3) if p.strip())


def _fallback_brand_journey(content: dict) -> str:
    resultado = _s(content.get("resultado_deseado"))
    conocido_por = _s(content.get("de_que_ser_conocido"))
    que_hacer = _s(content.get("que_hacer"))
    que_aprender = _s(content.get("que_aprender"))

    p1 = (
        f"The destination this founder is building toward is {resultado}. That outcome is the reason the "
        "sacrifices along the way are worth making, and it is the yardstick every future decision about the "
        "brand should be measured against."
        if resultado
        else ""
    )
    p2 = (
        f"To get there, this brand needs to become known for {conocido_por}. Reputation is not a side effect "
        "here — it is the mechanism that turns strangers into an audience willing to listen, and an audience "
        "into buyers willing to pay."
        if conocido_por
        else ""
    )
    p3 = (
        (f"Practically, that means the founder has to actually do {que_hacer}, " if que_hacer else "")
        + (f"while deliberately learning {que_aprender}. " if que_aprender else "")
        + "Neither the doing nor the learning is optional: skipping either one stretches the timeline to the "
        "same destination without shortening the distance, and no amount of clever marketing substitutes "
        "for the work itself. This is the map every other chapter in this document points back to — the "
        "reason the pond, the offer, and the voice all have to line up with the same destination instead of "
        "pulling in three different directions."
    )

    return "\n\n".join(p for p in (p1, p2, p3) if p.strip())


def _fallback_charco(content: dict) -> str:
    problema = _s(content.get("problema"))
    nivel = _s(content.get("nivel"))
    logro = _s(content.get("logro_que_lo_respalda"))
    costo = _s(content.get("costo_de_no_resolverlo"))
    intentos = _s(content.get("intentos_fallidos"))

    p1 = (
        f"The pond this brand fishes in is defined by one recurring problem: {problema}. This is not a "
        f"topic the founder finds interesting in the abstract — it is a {nivel or 'specific'}-sized pool of "
        "people who run into this exact symptom on a regular basis, which is what makes the positioning "
        "specific enough to actually own."
    )
    p2 = (
        f"The claim to speak on this problem is backed by {logro}, not by ambition alone. A pond claimed "
        "without a receipt behind it is just a hope; a pond claimed with proof is a position competitors "
        "cannot casually copy."
        if logro
        else ""
    )
    p3 = (
        (f"Left unresolved, this problem costs the audience {costo}. " if costo else "")
        + (f"Previous attempts to fix it, such as {intentos}, fell short. " if intentos else "")
        + "That gap between what people have already tried and what actually works is exactly where this "
        "brand's message needs to live."
    )

    return "\n\n".join(p for p in (p1, p2, p3) if p.strip())


def _fallback_icp(content: dict) -> str:
    quien_decide = _s(content.get("quien_decide"))
    tamano = _s(content.get("tamano_empresa"))
    disparador = _s(content.get("disparador_de_urgencia"))
    poder = _s(content.get("poder_adquisitivo"))
    comite = _s(content.get("comite_de_compra"))
    rinde_cuentas = _s(content.get("a_quien_le_rinde_cuentas"))

    p1 = (
        f"Every message this brand sends should be written for one person: {quien_decide}, the one who "
        "actually signs the check."
        + (f" That buyer typically shows up inside companies of {tamano}, " if tamano else " ")
        + "which keeps the targeting concrete instead of a vague 'anyone who might be interested'."
    )
    p2 = (
        f"They buy the moment {disparador}, not on a schedule the founder controls. Selling before that "
        "trigger fires means preaching to someone who is not yet listening; selling after it fires means "
        "arriving late to a decision someone else already made."
        if disparador
        else ""
    )
    p3 = (
        (f"Their real budget for this is {poder}, which sets the honest ceiling for what this offer can "
         f"charge. " if poder else "")
        + (f"On top of that, {comite} also needs to say yes before a deal closes. " if comite else "")
        + (f"Internally, this buyer answers to {rinde_cuentas}, " if rinde_cuentas else "")
        + "so the pitch has to work for their boss's priorities as much as for their own."
    )

    return "\n\n".join(p for p in (p1, p2, p3) if p.strip())


def _fallback_contrarian(content: dict) -> str:
    creencia_comun = _s(content.get("creencia_comun"))
    postura_opuesta = _s(content.get("postura_opuesta"))
    prueba = _s(content.get("prueba"))
    no_provocacion = _s(content.get("por_que_no_es_provocacion"))

    p1 = (
        f"Everyone in this space defaults to the same belief: {creencia_comun}. It is accepted so widely "
        "that most founders repeat it without checking whether it is still true, or whether it was ever true "
        "for the audience this brand actually serves."
    )
    p2 = (
        f"This brand takes the opposite position: {postura_opuesta}. That is not a rebrand of the same "
        "idea in edgier words — it is a genuinely different bet about what actually works."
        if postura_opuesta
        else ""
    )
    p3 = (
        (f"The proof behind that bet is {prueba}. " if prueba else "")
        + (f"And it holds up because {no_provocacion}. " if no_provocacion else "")
        + "A contrarian stand only earns attention when it is backed by evidence; otherwise it is just noise "
        "dressed up as insight."
    )

    return "\n\n".join(p for p in (p1, p2, p3) if p.strip())


def _fallback_asociaciones(content: dict) -> str:
    deseadas = _s(content.get("deseadas"))
    prohibidas = _s(content.get("prohibidas"))

    p1 = (
        f"A brand is not remembered for its logo — it is remembered for what people associate it with the "
        f"instant its name comes up. For this founder, the goal is to be paired, consistently, with "
        f"{deseadas}."
        if deseadas
        else ""
    )
    p2 = (
        f"Just as important is what this brand refuses to be linked to: {prohibidas}. Every one of those "
        "associations is off the table on purpose, because a single piece of content that leans the wrong "
        "way can undo months of the right ones."
        if prohibidas
        else ""
    )
    p3 = (
        "This is the filter every script, thumbnail, and caption should pass through before it ships: does "
        "it pull the brand closer to the associations it wants, or does it accidentally feed the ones it "
        "does not? Associations compound quietly over months of content, one small choice at a time, which "
        "is exactly why they are easy to ignore and expensive to fix once an audience has already decided "
        "what this brand reminds them of."
    )
    p4 = (
        "Brandy uses this pairing as a standing check, not a one-time note: any script, caption, or visual "
        "choice that drifts toward a prohibited association gets flagged before it ships, the same way a "
        "human brand manager would catch it in review."
    )

    return "\n\n".join(p for p in (p1, p2, p3, p4) if p.strip())


def _fallback_identidad(content: dict) -> str:
    voz = _s(content.get("voz"))
    colores = _s(content.get("colores"))
    tipografias = _s(content.get("tipografias"))
    narrativa = _s(content.get("narrativa_de_origen"))

    p1 = (
        f"This brand speaks with a voice best described as {voz}. That tone is not a stylistic preference — "
        "it is the filter that decides which drafts sound like this founder and which ones, however "
        "well-written, quietly belong to someone else."
        if voz
        else ""
    )
    p2 = (
        (f"Visually, the brand lives in {colores}, " if colores else "")
        + (f"set in {tipografias}. " if tipografias else "")
        + "These choices are load-bearing, not decorative: they are what makes the brand recognizable a "
        "half-second before anyone reads a single word."
    )
    p3 = (
        f"None of this exists in a vacuum: {narrativa}. That origin story is the reason the voice and the "
        "visuals feel earned instead of borrowed from a template — a founder who can point to where a "
        "choice came from will defend it under pressure, while a founder copying a trend will abandon it "
        "the moment it stops feeling fresh."
        if narrativa
        else ""
    )
    p4 = (
        "Every future script, thumbnail, and post gets checked against this identity before it ships: the "
        "same voice, the same palette, the same typography, on every surface the founder controls. "
        "Consistency here is not about looking polished — it is what lets a stranger recognize this brand "
        "on the third or fourth time they see it, long before they are ready to buy anything."
    )

    return "\n\n".join(p for p in (p1, p2, p3, p4) if p.strip())


def _fallback_oferta(content: dict) -> str:
    resultado = _s(content.get("resultado_sonado"))
    probabilidad = _s(content.get("probabilidad_percibida"))
    retraso = _s(content.get("retraso"))
    esfuerzo = _s(content.get("esfuerzo"))
    componentes = _s(content.get("componentes"))
    garantia = _s(content.get("garantia"))

    p1 = (
        f"The offer exists to deliver one dream outcome: {resultado}. Everything else in the offer — the "
        "components, the timeline, the guarantee — is there to make that outcome feel not just possible, but "
        "close to inevitable."
    )
    p2 = (
        (f"Believability comes from {probabilidad}, " if probabilidad else "")
        + (f"speed comes from getting the first win in {retraso}, " if retraso else "")
        + (f"and the load left on the client's shoulders is kept down to {esfuerzo}. " if esfuerzo else "")
        + "Raise any one of those levers and the same offer becomes easier to say yes to without touching the price."
    )
    p3 = (
        (f"Concretely, the offer is built from {componentes}. " if componentes else "")
        + (f"It ships with a {garantia} guarantee, which removes the last excuse to wait. " if garantia else "")
        + "None of this is decoration — it is the exact mechanism that turns interest into a signed deal."
    )

    return "\n\n".join(p for p in (p1, p2, p3) if p.strip())


def _fallback_lead_magnet(content: dict) -> str:
    tipo = _s(content.get("tipo"))
    problema_a = _s(content.get("problema_A"))
    problema_b = _s(content.get("problema_B_que_revela"))

    p1 = (
        f"The first free step into this brand's world is a {tipo} lead magnet. Its only job is to earn "
        "enough trust, in a few minutes, that the next ask — the paid offer — feels like a natural next step "
        "instead of a cold pitch."
        if tipo
        else ""
    )
    p2 = (
        f"It solves one narrow problem for free: {problema_a}. Solving it completely, without holding back "
        "on purpose, is what makes the lead magnet feel generous rather than like a trap disguised as a gift."
        if problema_a
        else ""
    )
    p3 = (
        f"In the process, it reveals a second, deeper problem the person did not know they had: {problema_b}. "
        "That is exactly the problem the paid offer exists to solve, which is why the two are designed as a "
        "single pair, not two unrelated pieces of content stitched together after the fact."
        if problema_b
        else ""
    )
    p4 = (
        "This sequence — solve A for free, reveal B, sell the fix for B — is the entire point of a lead "
        "magnet. Anyone who finishes it should feel like they got real value at no cost, and should "
        "understand, without being told twice, exactly why the paid offer is the obvious next step."
    )

    return "\n\n".join(p for p in (p1, p2, p3, p4) if p.strip())


_FALLBACK_BUILDERS = {
    "brand_journey": _fallback_brand_journey,
    "charco": _fallback_charco,
    "icp": _fallback_icp,
    "contrarian": _fallback_contrarian,
    "asociaciones": _fallback_asociaciones,
    "identidad": _fallback_identidad,
    "oferta": _fallback_oferta,
    "lead_magnet": _fallback_lead_magnet,
}


def _fallback_prose(section: Section, etapa_context: dict) -> str:
    """Deterministic (no-LLM) prose for one chapter — full sentences, no dumps."""
    if section.id == "diagnostico":
        return _fallback_diagnostico(section.content, etapa_context)
    builder = _FALLBACK_BUILDERS.get(section.id)
    if builder is None:
        raise SoulGenerationError(f"No fallback prose builder for section '{section.id}'")
    return builder(section.content)


# =============================================================================
# LLM REDACTION — one chapter at a time, on a leash.
# =============================================================================


def _build_chapter_prompt(heading: str, facts: list[tuple[str, str]]) -> str:
    facts_block = "\n".join(f"- {label}: {value}" for label, value in facts)

    return f"""You are a senior brand strategist writing one chapter of a founder's brand strategy document.

Chapter title: {heading}

FACTS (the only material you may use — do not invent anything beyond this list):
{facts_block}

Rules — all of them are inviolable:
1. Write ONLY in English, as flowing prose: 2 to 4 well-developed paragraphs, 150 to 350 words total.
2. Never use bullet points, JSON, markdown, or "label: value" lines anywhere in the output.
3. Do not add a heading, an introduction, or any meta-commentary — return only the prose paragraphs,
   separated by a single blank line.
4. Use every fact naturally in the narrative; never invent examples, statistics, or testimonials that
   are not in the facts above.
5. Never put any of the facts inside quotation marks — write them as plain narrative, never as a direct
   quote (a literal citation is added separately, after your text).
6. Keep the tone confident and strategic, the way a senior brand consultant would present it to the founder.

Return only the prose paragraphs."""


def _call_llm_for_redaction(prompt: str, fallback_text: str) -> str:
    """
    Ask Gemini (via Vertex AI) to redact one chapter's prose.

    Returns fallback_text untouched whenever the model is not configured,
    not installed, or the call fails for any reason — generation must never
    crash because the LLM is unavailable.
    """
    try:
        model = _get_vertex_ai_client()
    except Exception as e:  # noqa: BLE001 - any config/import failure must fall back, not crash
        print(f"[WARN] Vertex AI client unavailable, using fallback prose: {e}")
        return fallback_text

    if model is None:
        return fallback_text

    try:
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 700,
                "candidate_count": 1,
            },
        )

        if not response.text:
            return fallback_text

        redacted = response.text.strip()

        if redacted.startswith("```"):
            lines = redacted.split("\n")
            redacted = "\n".join(lines[1:-1]) if len(lines) > 2 else "\n".join(lines[1:])

        return redacted.strip() or fallback_text

    except Exception as e:  # noqa: BLE001 - any LLM call failure must fall back, not crash
        print(f"[WARN] LLM redaction failed for chapter: {e}. Using fallback prose.")
        return fallback_text


def _build_chapter(section: Section, heading: str, etapa_context: dict) -> dict:
    """Build one rendered chapter: heading, prose paragraphs, literal citation."""
    facts = _facts_for(section.id, section.content)
    if section.id == "diagnostico":
        facts = facts + [
            (label, value)
            for label, value in [
                ("Framework stage name", _s(etapa_context.get("name"))),
                ("Skill this stage unlocks", _s(etapa_context.get("skill_to_unlock"))),
                ("What this stage forbids", _s(etapa_context.get("prohibited"))),
            ]
            if value
        ]

    fallback = _fallback_prose(section, etapa_context)
    prose = _call_llm_for_redaction(_build_chapter_prompt(heading, facts), fallback) if facts else fallback

    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    return {
        "heading": heading,
        "paragraphs": paragraphs,
        "citation": section.citation_text,
    }


# =============================================================================
# EXECUTIVE SUMMARY & CLOSING NOTE — deterministic, short prose.
# Built from a handful of facts, never from concatenating the nine chapters.
# =============================================================================


def _cap_word_count(sentences: list[str], max_words: int, min_sentences: int = 1) -> str:
    """
    Join sentences (already in priority order, most important first) with a
    single space, dropping whole sentences from the end -- lowest priority
    first -- until the total is at or under max_words. Never cuts a sentence
    mid-way: each drop removes one complete sentence.
    """
    kept = list(sentences)
    while len(kept) > min_sentences and len(" ".join(kept).split()) > max_words:
        kept.pop()
    return " ".join(kept)


def _build_executive_summary(brain: BrandBrain) -> str:
    diag = brain.get_section("diagnostico").content
    charco = brain.get_section("charco").content
    icp = brain.get_section("icp").content
    contrarian = brain.get_section("contrarian").content
    oferta = brain.get_section("oferta").content
    lead_magnet = brain.get_section("lead_magnet").content
    journey = brain.get_section("brand_journey").content

    etapa = _s(diag.get("etapa")) or "an early"
    problema = _s(charco.get("problema")) or "a clearly defined problem"
    quien_decide = _s(icp.get("quien_decide")) or "a specific buyer"
    postura_opuesta = _s(contrarian.get("postura_opuesta")) or "a deliberately different stance"
    resultado_sonado = _s(oferta.get("resultado_sonado")) or "a concrete outcome"
    tipo_lead = _s(lead_magnet.get("tipo")) or "a focused"
    resultado_deseado = _s(journey.get("resultado_deseado")) or "a clear long-term destination"
    de_que_ser_conocido = _s(journey.get("de_que_ser_conocido")) or "a distinct reputation"

    # Priority order, most essential first -- the cap below drops from the
    # end (lowest priority) one whole sentence at a time, never mid-sentence.
    sentences = [
        (
            "This Brand Soul is the strategic backbone behind every script, offer, and piece of content "
            "this founder ships from here on — nine confirmed decisions distilled into one read."
        ),
        f"The brand sits at the '{etapa}' stage, and the single problem it exists to solve is {problema}.",
        (
            f"The buyer who signs the check is {quien_decide}, which keeps every message anchored to a "
            "real budget instead of a vague audience."
        ),
        (
            "Where the market defaults to conventional wisdom, this brand takes the contrarian stand that "
            f"{postura_opuesta}, and backs it with an offer promising {resultado_sonado}."
        ),
        (
            f"The first free step into that offer is a {tipo_lead} lead magnet, built to earn trust "
            "before asking for money."
        ),
        (
            f"None of this is static: the destination is {resultado_deseado}, reached by becoming known "
            f"for {de_que_ser_conocido}."
        ),
        (
            "Every chapter that follows unpacks one piece of this same throughline, always tied back to "
            "the founder's own words."
        ),
    ]

    return _cap_word_count(sentences, max_words=200, min_sentences=3)


def _build_closing_note(brain: BrandBrain) -> str:
    charco = brain.get_section("charco").content
    icp = brain.get_section("icp").content
    oferta = brain.get_section("oferta").content

    problema = _s(charco.get("problema")) or "the founder's core problem"
    quien_decide = _s(icp.get("quien_decide")) or "the ideal buyer"
    resultado_sonado = _s(oferta.get("resultado_sonado")) or "the offer's promised outcome"

    return (
        "Brandy treats everything above as the single source of truth for this brand, not a document to "
        "read once and forget. Every script idea, catalog concept, and piece of copy Brandy proposes gets "
        f"checked against this diagnosis first: does it speak to {quien_decide}, does it address "
        f"{problema}, and does it move the founder closer to {resultado_sonado}? When a request drifts away "
        "from any of these nine decisions, Brandy will say so out loud instead of quietly improvising — the "
        "founder decides every change to the brand itself, voice included. Regenerating this document is "
        "the only way to update what Brandy knows; nothing here changes on its own."
    )


# =============================================================================
# CITATION VALIDATION
# =============================================================================


def validate_citations_in_html(html: str, brain: BrandBrain) -> tuple[bool, list[str]]:
    """
    Validate that every citation in the HTML exists literally in the brain.

    This is the CRITICAL validation step that prevents the LLM from
    inventing citations. If ANY citation in the HTML doesn't match
    a literal citation from the brain, validation FAILS.

    Args:
        html: The generated HTML document
        brain: The BrandBrain object

    Returns:
        Tuple of (is_valid, list_of_invented_citations)

    Note:
        This function searches for citations within <div class="citation"> tags
        and checks if the literal text (excluding quotes) exists in the brain's
        citation_text fields.
    """
    import html as _html
    import re

    # Se revisa TODO texto entrecomillado del documento, no solo el que esta
    # dentro de <div class="citation">.
    #
    # Por que: mirar solo ese contenedor deja pasar exactamente el caso mas
    # probable. Un LLM al que se le pide que "escriba como estratega" teje las
    # citas dentro de la prosa antes que ponerlas en el div designado:
    #
    #   <p>Como tu mismo dijiste, "llevo quince anos en banca", y eso...</p>
    #
    # Medido: esa frase inventada pasaba la validacion anterior sin tocarla.
    # Y este documento circula sin nosotros: una cita inventada aqui no es un
    # bug, es la credibilidad del fundador y la nuestra.

    # 1. Quitar etiquetas para trabajar sobre el texto visible, y deshacer
    #    entidades (&quot; volveria invisible una cita para el regex).
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = _html.unescape(texto)

    # 2. Todo lo entrecomillado: comillas rectas, tipograficas y angulares.
    entrecomillado = re.findall(r'"([^"]{4,})"|“([^”]{4,})”|«([^»]{4,})»', texto)
    encontradas = [next(g for g in grupo if g) for grupo in entrecomillado]

    def _norm(s: str) -> str:
        """Compara por contenido, no por espaciado ni puntuacion de borde."""
        return re.sub(r"\s+", " ", s).strip().strip(".,;:!?").lower()

    permitidas = {_norm(s.citation_text) for s in brain.sections if s.citation_text}

    invented_citations = []
    for cita in encontradas:
        if _norm(cita) not in permitidas:
            invented_citations.append(cita)

    is_valid = len(invented_citations) == 0
    return is_valid, invented_citations


def _compute_brain_hash(brain: BrandBrain) -> str:
    """
    Compute a hash of the brain to check if it has changed.

    Used for cache invalidation.

    Args:
        brain: BrandBrain object

    Returns:
        SHA256 hash of the brain's serialized state

    NOTE: Only hashes the actual content (sections and formato), NOT
    created_at/updated_at which change automatically on every DB update.
    """
    hashable = {
        "sections": [
            {
                "id": s.id,
                "content": s.content,
                "citation_text": s.citation_text,
                "citation_source": s.citation_source,
                "status": s.status,
            }
            for s in brain.sections
        ],
        "formato": brain.formato,
    }
    brain_json = json.dumps(hashable, sort_keys=True)
    return hashlib.sha256(brain_json.encode()).hexdigest()


def _check_cache(brain: BrandBrain, session_token: str) -> str | None:
    """
    Check if a cached HTML exists for this brain.

    The cache is stored in the brand_brains table as soul_html.
    We also store a brain_hash to invalidate the cache.

    Args:
        brain: BrandBrain object
        session_token: Session token to query cache

    Returns:
        Cached HTML string if valid cache hit, None otherwise
    """
    try:
        from app.tools.brand_brain.store import _get_client

        client = _get_client()
        if client is None:
            return None

        result = (
            client.table("brand_brains")
            .select("soul_html", "brain_hash")
            .eq("session_token", session_token)
            .execute()
        )

        if not result.data:
            return None

        row = result.data[0]

        current_hash = _compute_brain_hash(brain)
        cached_hash = row.get("brain_hash")

        if not cached_hash or cached_hash != current_hash:
            # Brain changed, cache is invalid
            return None

        return row.get("soul_html")

    except Exception as e:  # noqa: BLE001 - a cache-read failure must degrade to a miss, not crash
        print(f"[WARN] Failed to check cache: {e}")
        return None


def _save_cache(brain: BrandBrain, html: str, session_token: str) -> bool:
    """
    Save the generated HTML to cache.

    Stores in brand_brains table:
    - soul_html: the generated HTML
    - brain_hash: hash of brain state for invalidation
    - soul_generated_at: timestamp

    Args:
        brain: BrandBrain object
        html: Generated HTML document
        session_token: Session token to update cache

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        from app.tools.brand_brain.store import _get_client

        client = _get_client()
        if client is None:
            return False

        brain_hash = _compute_brain_hash(brain)

        response = (
            client.table("brand_brains")
            .update(
                {
                    "soul_html": html,
                    "brain_hash": brain_hash,
                    "soul_generated_at": "now()",
                }
            )
            .eq("session_token", session_token)
            .execute()
        )

        return len(response.data) > 0

    except Exception as e:  # noqa: BLE001 - a cache-write failure must not crash generation
        print(f"[WARN] Failed to save cache: {e}")
        return False


def generate_brand_soul(session_token: str) -> tuple[str, str]:
    """
    Generate the Brand Soul document for the given session.

    This is the MAIN function that orchestrates the entire process:

    1. Validate brain has all 9 confirmed sections
    2. Check cache for existing HTML
    3. If cache miss, generate new HTML:
       a. Redact each section into a titled prose chapter (LLM on a leash,
          with a deterministic fallback)
       b. Build an executive summary and a closing note
       c. Assemble the document from the template
       d. Validate all citations exist literally in brain
    4. Save to cache
    5. Return HTML

    Args:
        session_token: The session token

    Returns:
        Tuple of (html_document, cache_status)
        cache_status is "cached" or "generated"

    Raises:
        IncompleteBrainError: If brain is missing sections
        CitationValidationError: If LLM invented citations
        SoulGenerationError: For other generation errors
    """
    # 1. Load brand brain
    brain = get_brand_brain(session_token)
    if not brain:
        raise SoulGenerationError("No brand brain found for this session")

    # 2. Validate all sections confirmed
    is_complete, missing_sections = _check_all_sections_confirmed(brain)
    if not is_complete:
        missing_text = ", ".join(missing_sections)
        raise IncompleteBrainError(f"Faltan secciones: {missing_text}")

    # 3. Check cache
    cached_html = _check_cache(brain, session_token)
    if cached_html:
        # Validate cached HTML citations (defense in depth)
        is_valid, invented = validate_citations_in_html(cached_html, brain)
        if not is_valid:
            # Cache corrupted! Fall through to regeneration
            print(f"[WARN] Cache corrupted - invented citations: {invented}")
        else:
            return cached_html, "cached"

    # Credit deduction for this generation happens once, in app/main.py's
    # /soul/generate endpoint (20 credits), before this function is called.
    # Do not deduct here too.

    # 4. Generate new HTML
    etapa_id = detect_etapa_from_brand_brain(brain) or "invisible"
    etapa_context = get_etapa_context(etapa_id)

    chapters = []
    for section_id, heading in CHAPTERS:
        section = brain.get_section(section_id)
        if not section:
            raise SoulGenerationError(f"Missing section in redacted content: '{section_id}'")
        chapters.append(_build_chapter(section, heading, etapa_context))

    html = build_soul_html(
        executive_summary=_build_executive_summary(brain),
        chapters=chapters,
        closing_note=_build_closing_note(brain),
    )

    # Validate citations (CRITICAL!)
    is_valid, invented_citations = validate_citations_in_html(html, brain)
    if not is_valid:
        raise CitationValidationError(
            f"El documento contiene citas inventadas: {', '.join(invented_citations)}. "
            "El documento NO se mostrará."
        )

    # 5. Save to cache
    _save_cache(brain, html, session_token)

    return html, "generated"
