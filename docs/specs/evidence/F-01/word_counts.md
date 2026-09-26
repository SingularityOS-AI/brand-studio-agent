# F-01 — per-section word counts (round 2 fix)

Literal output of `_build_executive_summary`, `_fallback_prose` (per chapter, no LLM),
and `_build_closing_note` against the `_rich_sections_data()` fixture in
`tests/test_brand_soul_f01_prose.py`, via `get_etapa_context("invisible")`.

| Section | Word count | Paragraphs |
|---|---|---|
| Executive Summary | 193 | 1 |
| Diagnosis | 195 | 3 |
| Brand Journey | 196 | 3 |
| Your Pond | 170 | 3 |
| Ideal Client | 180 | 3 |
| Contrarian Take | 153 | 3 |
| Associations | 197 | 4 |
| Identity | 218 | 4 |
| Offer | 175 | 3 |
| Lead Magnet | 202 | 4 |
| How Brandy Will Use This (closing note) | 133 | 1 |

Spec bounds: Executive Summary 120-200 words (now capped deterministically by
`_cap_word_count`, dropping whole low-priority sentences, never mid-sentence);
each of the 9 chapters 150-350 words, 2-4 paragraphs.

Round-1 review also found the Executive Summary at 212 words (over the 120-200
cap) with the test loosened to 100-220 to match, and Spanish `ETAPAS_CONFIG`
framework copy (`template.py`) splicing into the English chapters. Both are
fixed in this round:
- `_build_executive_summary` now builds a priority-ordered list of sentences and
  calls `_cap_word_count(sentences, max_words=200, min_sentences=3)`, which drops
  whole sentences from the end until the total is <= 200 words. See
  `tests/test_brand_soul_f01_prose.py::test_executive_summary_stays_under_200_words_with_verbose_fields`
  for the cap holding under deliberately verbose field values.
- `ETAPAS_CONFIG` (`template.py`) is now English for every stage (`name`,
  `skill_to_unlock`, `prohibited`, `description`). Founder-provided facts and
  literal citations are untouched and keep their own language.
- `tests/test_brand_soul_f01_prose.py::test_executive_summary_is_short_prose_not_a_chapter_dump`
  tightened to `120 <= word_count <= 200`.
- `tests/test_soul.py::test_get_etapa_context_valid_stage` updated to assert the
  English `ETAPAS_CONFIG` strings.
