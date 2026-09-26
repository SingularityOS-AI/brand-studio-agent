import re

with open("app/tools/brand_soul/generator.py", "r") as f:
    content = f.read()

# Ah! The second fix block (from the first attempt, the one that left Spanish prompts) is actually what is in the file!
# `def _call_llm_for_redaction(` has:
#         try:
#             # If it's a json string, parse and format
#             data = json.loads(section_text)
#             if isinstance(data, dict):
#                 return " ".join([f"The {k} is {v}." for k, v in data.items() if v])
#         except Exception:
#             pass

old_llm_func = """def _call_llm_for_redaction(
    section_text: str,
    citation_text: str,
    instruction: str
) -> str:
    \"\"\"
    Call Gemini 2.5 Flash-Lite to redact section content with strategic voice.

    Args:
        section_text: The original section content to redact
        citation_text: The literal citation (for context, NOT to paraphrase)
        instruction: Specific instruction for this section type

    Returns:
        Redacted text string

    Raises:
        SoulGenerationError: If LLM call fails
    \"\"\"
    model = _get_vertex_ai_client()

    # In test mode, return the original text converted to simple sentences to avoid JSON formats
    if model is None:
        import json
        try:
            # If it's a json string, parse and format
            data = json.loads(section_text)
            if isinstance(data, dict):
                return " ".join([f"The {k} is {v}." for k, v in data.items() if v])
        except Exception:
            pass
        # Basic cleanup to avoid raw colons or dict-like formatting
        clean_text = section_text.replace("{", "").replace("}", "").replace('"', "")
        # Convert "key: value" to "The key is value."
        parts = clean_text.split(". ")
        sentences = []
        for part in parts:
            if ":" in part:
                k, v = part.split(":", 1)
                sentences.append(f"The {k.strip()} is {v.strip()}.")
            else:
                sentences.append(part)
        return " ".join(sentences)

    # Build the strict prompt
    prompt = f\"\"\"You are a senior brand strategist. Your task is to REDACT (not rewrite, not invent) the following text with a professional and strategic voice.

IMPORTANT - INVIOLABLE RULES:
1. DO NOT invent data, facts, or details that are NOT in the original text.
2. DO NOT add examples, statistics, or testimonials that are not in the original.
3. DO NOT change the fundamental meaning of any statement.
4. Use a professional and strategic tone, like a brand consultant.
5. WRITE LONG-FORM PROSE: Write 2-4 paragraphs of prose (150-350 words). DO NOT output JSON. DO NOT use key-value pairs. DO NOT use snake_case keys or curly braces.
6. OUTPUT IN ENGLISH.
7. The citation is for context, DO NOT paraphrase it or mention it in the redaction.

Text to redact:
{section_text}

Specific instruction:
{instruction}

Original citation (DO NOT CHANGE, DO NOT PARAPHRASE, only for context):
{citation_text}
\"\"\"

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.0}
        )

        if not response or not response.text:
            raise SoulGenerationError("LLM returned empty response")

        # Clean up the response - remove any markdown or extra whitespace
        redacted = response.text.strip()

        # Remove markdown code blocks if present
        if redacted.startswith("```"):
            lines = redacted.split("\\n")
            # Skip first line (```...) and last line (```)
            if len(lines) > 2:
                redacted = "\\n".join(lines[1:-1])
            else:
                # Malformed, just take everything after the first line
                redacted = "\\n".join(lines[1:])

        return redacted.strip() or section_text

    except Exception as e:
        # If LLM fails, return original text (graceful degradation)
        print(f"[WARN] LLM redaction failed for section: {e}. Using original text.")
        return section_text"""

new_llm_func = """def _call_llm_for_redaction(
    section_text: str | dict,
    citation_text: str,
    instruction: str
) -> str:
    \"\"\"
    Call Gemini 2.5 Flash-Lite to redact section content with strategic voice.

    Args:
        section_text: The original section content to redact
        citation_text: The literal citation (for context, NOT to paraphrase)
        instruction: Specific instruction for this section type

    Returns:
        Redacted text string

    Raises:
        SoulGenerationError: If LLM call fails
    \"\"\"
    model = _get_vertex_ai_client()

    def build_deterministic_fallback(data):
        if isinstance(data, dict):
            sentences = []
            for k, v in data.items():
                if v:
                    clean_k = str(k).replace('_', ' ').lower()
                    sentences.append(f"Regarding the {clean_k}, it is {v}.")
            return " ".join(sentences)
        elif isinstance(data, str):
            import re
            return re.sub(r'([A-Za-z\\s]+):\\s*([^:]+?)(?=\\s*[A-Za-z\\s]+:|$)', r'Regarding \\1, it is \\2. ', data).strip()
        return str(data)

    fallback_text = build_deterministic_fallback(section_text)

    # In test mode, return the original text converted to simple sentences to avoid JSON formats
    if model is None:
        return fallback_text

    # Build the strict prompt
    llm_input_text = " ".join([f"{str(k).replace('_', ' ').capitalize()}: {v}" for k, v in section_text.items() if v]) if isinstance(section_text, dict) else section_text

    prompt = f\"\"\"You are a senior brand strategist. Your task is to REDACT (not rewrite, not invent) the following text with a professional and strategic voice.

IMPORTANT - INVIOLABLE RULES:
1. DO NOT invent data, facts, or details that are NOT in the original text.
2. DO NOT add examples, statistics, or testimonials that are not in the original.
3. DO NOT change the fundamental meaning of any statement.
4. Use a professional and strategic tone, like a brand consultant.
5. WRITE LONG-FORM PROSE: Write 2-4 paragraphs of prose (150-350 words). DO NOT output JSON. DO NOT use key-value pairs. DO NOT use snake_case keys or curly braces.
6. OUTPUT IN ENGLISH.
7. The citation is for context, DO NOT paraphrase it or mention it in the redaction.

Text to redact:
{llm_input_text}

Specific instruction:
{instruction}

Original citation (DO NOT CHANGE, DO NOT PARAPHRASE, only for context):
{citation_text}
\"\"\"

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.0}
        )

        if not response or not response.text:
            raise SoulGenerationError("LLM returned empty response")

        # Clean up the response - remove any markdown or extra whitespace
        redacted = response.text.strip()

        # Remove markdown code blocks if present
        if redacted.startswith("```"):
            lines = redacted.split("\\n")
            # Skip first line (```...) and last line (```)
            if len(lines) > 2:
                redacted = "\\n".join(lines[1:-1])
            else:
                # Malformed, just take everything after the first line
                redacted = "\\n".join(lines[1:])

        return redacted.strip() or fallback_text

    except Exception as e:
        # If LLM fails, return original text (graceful degradation)
        print(f"[WARN] LLM redaction failed for section: {e}. Using original text.")
        return fallback_text"""

content = content.replace(old_llm_func, new_llm_func)

# We must also ensure `_redact_section_content_with_llm` sends the dict!
old_redact = """def _redact_section_content_with_llm(
    section: Section,
    all_citations: dict[str, str]
) -> tuple[str, int]:
    \"\"\"
    Redact a section's content using Gemini 2.5 Flash-Lite via Vertex AI.

    CRITICAL: The LLM only sees the section content and its own citation.
    It NEVER sees the raw transcript or external context.
    \"\"\"
    content = section.content
    citation = all_citations.get(section.id, "")

    # Format the dictionary content into a plain string to avoid JSON inputs
    content_vals = " ".join([str(v) for v in content.values() if v])

    instruction = (
        f"Consolidate this information about the '{section.id}' section into a compelling narrative. "
        "Write 2-4 paragraphs of prose (150-350 words). "
        "OUTPUT IN ENGLISH. "
        "DO NOT output JSON, key-value pairs, bullet dumps, or use snake_case keys or curly braces. "
        "Use a strategic, professional voice."
    )

    redacted_text = _call_llm_for_redaction(
        section_text=content,
        citation_text=citation,
        instruction=instruction
    )

    return redacted_text, _estimate_tokens(content_vals) + _estimate_tokens(redacted_text) + 500"""

# Wait, `section_text=content` is already passing the dict!
# The issue was that the `old_llm_func` in my previous replacement script wasn't matching because I didn't replace it in the file.

with open("app/tools/brand_soul/generator.py", "w") as f:
    f.write(content)
