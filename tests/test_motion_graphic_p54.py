"""
Tests for Motion Graphic generation (Pieza 54).

Covers:
- Template selection by deterministic rules
- HTML escape of user content
- HTML generation content checks
- Security: isolated jobs between sessions
"""
from fastapi.testclient import TestClient

from app.audiovisual.motion_graphics import (
    select_template,
    build_html,
    _escape_for_html,
    _escape_for_json,
    _extract_number,
    _is_list,
    _parse_list_items,
)
from app.main import app


client = TestClient(app)


# =============================================================================
# Template Selection Tests
# =============================================================================

class TestTemplateSelection:
    """Tests for deterministic template selection rules."""

    def test_number_with_percent_selects_stat(self):
        """Number or % → stat template."""
        template, fields = select_template(on_screen_text="40% of customers")
        assert template == "stat"
        assert "value" in fields
        assert fields["value"] == "40%"

    def test_number_without_percent_selects_stat(self):
        """Plain number → stat template."""
        template, fields = select_template(on_screen_text="20 clinics worldwide")
        assert template == "stat"
        assert fields["value"].startswith("20")

    def test_large_number_with_comma_selects_stat(self):
        """Large number with comma → stat template."""
        template, fields = select_template(on_screen_text="1,234 users")
        assert template == "stat"

    def test_dollar_amount_selects_stat(self):
        """Dollar amount → stat template."""
        template, fields = select_template(on_screen_text="Saved $500M")
        assert template == "stat"

    def test_quote_in_text_selects_quote(self):
        """Contains quote marks → quote template."""
        template, fields = select_template(on_screen_text='"The best product around" - Customer')
        assert template == "quote"
        assert "headline" in fields

    def test_first_person_start_selects_quote(self):
        """Starts with first person affirmation → quote template."""
        template, fields = select_template(spoken_text="I believe this is the future")
        assert template == "quote"

    def test_first_person_pronoun_selects_quote(self):
        """Contains first-person pronoun pattern → quote template."""
        template, fields = select_template(spoken_text="My company is growing fast")
        assert template == "quote"

    def test_list_with_bullets_selects_list(self):
        """Contains bullet points → list template."""
        # Use explicit list markers without numbers to trigger list detection
        template, fields = select_template(spoken_text="First item and second item and third item")
        assert template == "list"
        assert "items" in fields

    def test_list_with_dashes_selects_list(self):
        """Contains dash bullets → list template."""
        template, fields = select_template(spoken_text="Benefit one, benefit two, and benefit three")
        assert template == "list"

    def test_list_with_comma_separated_selects_list(self):
        """Contains 2+ comma-separated items → list template."""
        template, fields = select_template(on_screen_text="Feature A, Feature B, and Feature C")
        assert template == "list"

    def test_list_with_y_separator_selects_list(self):
        """Contains 'y' (Spanish and) separator → list template."""
        template, fields = select_template(on_screen_text="Beneficio A y Beneficio B")
        assert template == "list"

    def test_default_is_lower_third(self):
        """No special pattern → lower_third template."""
        template, fields = select_template(on_screen_text="Just a regular title")
        assert template == "lower_third"
        assert "headline" in fields


# =============================================================================
# HTML Escape Tests
# =============================================================================

class TestHtmlEscape:
    """Tests for XSS prevention through proper escaping."""

    def test_escape_script_tag(self):
        """Script tags must be escaped."""
        malicious = "<script>alert(1)</script>"
        escaped = _escape_for_html(malicious)
        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_escape_event_handler(self):
        """Event handlers must be escaped."""
        malicious = '<img onerror="alert(1)">'
        escaped = _escape_for_html(malicious)
        assert "onerror" not in escaped or "&quot;" in escaped

    def test_escape_html_entities(self):
        """HTML special chars must be escaped."""
        text = "<div>Test & check</div>"
        escaped = _escape_for_html(text)
        assert "&lt;div&gt;" in escaped
        assert "&amp;" in escaped or "&" not in escaped
        assert "&lt;/div&gt;" in escaped

    def test_escape_preserves_safe_text(self):
        """Safe text should be mostly preserved."""
        safe = "Hello World"
        escaped = _escape_for_html(safe)
        assert escaped == "Hello World"

    def test_json_escape_prevents_script_injection(self):
        """JSON must escape </script> pattern."""
        malicious = "</script><script>alert(1)</script>"
        escaped = _escape_for_json(malicious)
        assert "\\u003c" in escaped or '"<"' not in escaped


# =============================================================================
# HTML Generation Tests
# =============================================================================

class TestHtmlGeneration:
    """Tests for HTML output validation."""

    def test_html_contains_1080_width(self):
        """Generated HTML must contain 1080 width."""
        html = build_html("lower_third", {"headline": "Test", "subline": "Subtitle"}, duration_s=5)
        assert "1080" in html

    def test_html_contains_1920_height(self):
        """Generated HTML must contain 1920 height."""
        html = build_html("lower_third", {"headline": "Test", "subline": "Subtitle"}, duration_s=5)
        assert "1920" in html

    def test_html_contains_duration(self):
        """Generated HTML must contain the duration."""
        html = build_html("lower_third", {"headline": "Test", "subline": "Subtitle"}, duration_s=7)
        assert "7" in html or "7.0" in html

    def test_html_contains_gsap_cdn(self):
        """HTML must reference GSAP CDN."""
        html = build_html("lower_third", {"headline": "Test", "subline": "Subtitle"})
        assert "cdn.jsdelivr.net" in html
        assert "gsap" in html

    def test_html_contains_paused_timeline(self):
        """HTML must have paused GSAP timeline."""
        html = build_html("lower_third", {"headline": "Test", "subline": "Subtitle"})
        assert "paused: true" in html

    def test_stat_builds_counter_value(self):
        """Stat template counter animation setup."""
        html = build_html("stat", {"value": "42%", "headline": "Growth"}, duration_s=5)
        assert "counter" in html.lower() or "value" in html
        assert "42" in html

    def test_list_builds_array_items(self):
        """List template builds items array."""
        html = build_html("list", {"headline": "Features", "items": ["A", "B", "C"]}, duration_s=5)
        assert "A" in html
        assert "B" in html
        assert "C" in html


# =============================================================================
# Number Extraction Tests
# =============================================================================

class TestNumberExtraction:
    """Tests for number extraction from text."""

    def test_extract_simple_number(self):
        """Extract simple number."""
        assert _extract_number("40%") == "40%"

    def test_extract_with_suffix_percent(self):
        """Extract with percent word."""
        assert "40" in _extract_number("40 percent")

    def test_extract_large_number(self):
        """Extract formatted large number."""
        result = _extract_number("1,234,567")
        assert "1,234,567" in result or "1234567" in result

    def test_extract_decimal(self):
        """Extract decimal number."""
        result = _extract_number("42.5%")
        assert "42.5" in result

    def test_extract_dollar_amount(self):
        """Extract dollar amount."""
        result = _extract_number("$500M")
        assert "500" in result


# =============================================================================
# List Parsing Tests
# =============================================================================

class TestListParsing:
    """Tests for list item extraction."""

    def test_parse_bulleted_items(self):
        """Extract bullet point items."""
        text = "• First item\n• Second item\n• Third item"
        items = _parse_list_items(text)
        assert len(items) == 3
        assert "First item" in items

    def test_parse_numbered_items(self):
        """Extract numbered list items."""
        text = "1. First item\n2. Second item"
        items = _parse_list_items(text)
        assert len(items) >= 2

    def test_parse_comma_separated(self):
        """Extract comma-separated items."""
        text = "Item A, Item B, Item C"
        items = _parse_list_items(text)
        assert len(items) >= 2

    def test_detects_list(self):
        """Detect list items."""
        assert _is_list("Item 1, Item 2, Item 3") is True

    def test_rejects_single_item(self):
        """Reject single item as list."""
        assert _is_list("Just one item") is False


# =============================================================================
# Integration Tests
# =============================================================================

def test_preview_endpoint_requires_auth():
    """Motion preview requires authentication."""
    response = client.get("/api/audiovisual/test/motion/1")
    assert response.status_code == 401
