import re

with open("app/tools/brand_soul/generator.py", "r") as f:
    content = f.read()

# I see what happened. In `generate_brand_soul` around line 504:
# `full_context += f"\\n\\n--- {section.id} ---\\n{redacted_text}"`
# When _redact_section_content_with_llm returns the fallback string, if section.content is passed directly without string conversion, does the fallback logic catch it?
# In `_redact_section_content_with_llm`:
# `redacted_text = _call_llm_for_redaction(section_text=content, ...)`
# `content` is a dict!
# Let's check `_call_llm_for_redaction` fallback:
# `def build_deterministic_fallback(data):`
# It says `elif isinstance(data, str):` but if it's a dict, it iterates `for k, v in data.items():`
# Wait, the failure shows `{'etapa': 'creador atascado', ...}` in the html.
# Why is it a string dict?
# Oh! Because in `_redact_section_content_with_llm`, `content` is `section.content` which IS a dict.
# Let's look at `_call_llm_for_redaction` fallback logic again:

old_fallback = """    def build_deterministic_fallback(data):
        if isinstance(data, dict):
            # Create proper sentences from keys and values without colons
            sentences = []
            for k, v in data.items():
                if v:
                    clean_k = str(k).replace('_', ' ').lower()
                    sentences.append(f"Regarding the {clean_k}, it is {v}.")
            return " ".join(sentences)
        elif isinstance(data, str):
            # Convert raw "Key: value" to sentences if needed
            import re
            return re.sub(r'([A-Za-z\\s]+):\\s*([^:]+?)(?=\\s*[A-Za-z\\s]+:|$)', r'Regarding \\1, it is \\2. ', data).strip()
        return str(data)"""

# Actually, the fallback block in generator.py has:
#    # In test mode, return the deterministic fallback
#    if model is None:
#        return fallback_text
# Wait! Let me just use replace on `fallback_text = build_deterministic_fallback(section_text)` to see what's wrong.

# The exception fallback:
#    except Exception as e:
#        return fallback_text

# Let me print the exact fallback block in the file to make sure it's doing what I expect.
