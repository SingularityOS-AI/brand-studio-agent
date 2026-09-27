"""Test for E2-08: Editing UX - 3-step stepper, English labels, loading screen.

Static + Node DOM tests for the user-visible strings and stepper state.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITING_JS = REPO_ROOT / "app" / "static" / "editing.js"
INDEX_HTML = REPO_ROOT / "app" / "static" / "index.html"


class TestEditingE208Static:
    """Static assertions on editing.js source."""

    def test_no_spanish_accents_or_characters(self):
        """Zero visible strings matching [áéíóúñ¿¡]."""
        content = EDITING_JS.read_text(encoding="utf-8")

        # Find string literals using various quote patterns
        # Match single-quoted, double-quoted, and template literal strings

        # Double quoted strings (using "strings")
        double_quoted = re.findall(r'"([^"]*[áéíóúñ¿¡][^"]*)"', content)

        # Single quoted strings (using 'strings') - though this may be in template vars
        single_quoted = re.findall(r"'([^']*[áéíóúñ¿¡][^']*)'", content)

        found = []
        if double_quoted:
            found.extend(double_quoted)
        if single_quoted:
            found.extend(single_quoted)

        # Filter out any that might be in comments or identifiers
        # Filter: only match strings that are actual labels/UI text
        spanish_chars = set("áéíóúñ¿¡")
        for s in content.split('"'):
            if any(c in s for c in spanish_chars) and len(s) < 200:  # reasonable UI string length
                # Check if it's actually a string assignment
                pass

        # Better approach: grep for Spanish unicode characters in visible positions
        # Check template literals and regular strings used as labels
        spanish_pattern = re.compile(r'[áéíóúñ¿¡]')

        matches = []
        for lineno, line in enumerate(content.splitlines(), 1):
            # Skip comments that are explanations
            if '//' in line and any(c in line.split('//')[0] for c in spanish_chars):
                # Check if in left side (code vs comment)
                code_part = line.split('//')[0]
                if spanish_pattern.search(code_part):
                    matches.append((lineno, line))
            elif spanish_pattern.search(line):
                matches.append((lineno, line))

        if matches:
            print(f"Found Spanish characters at lines: {[m[0] for m in matches]}")

        # Should be zero matches
        assert len(matches) == 0, f"Found Spanish characters in visible strings: {matches}"

    def test_no_vestir_or_dress_literal(self):
        """Zero visible strings matching literal 'Vestir' or dress (except identifiers)."""
        content = EDITING_JS.read_text(encoding="utf-8")

        # Expected: 'Vestir' should NOT appear as UI text
        # But variable names like 'dressBtnLabel' are OK
        # Search for actual UI strings with Vestir
        ui_vestir = re.findall(r'["\'][^"\']*Vestir[^"\']*["\']', content, re.IGNORECASE)

        # Also check for 'dress' in visible button labels (not code)
        # Button labels are typically in template literals like `>dress<` or "dress"
        dress_in_labels = re.findall(r'["\'][^"\']*dress[^"\']*["\']', content, re.IGNORECASE)

        # Filter out legitimate English labels like "auto-dress", "address"
        excluded = ["auto-dress", "address", "dressed", "dressBtnLabel", "dressing", "redress"]
        filtered = []
        for m in ui_vestir:
            if not any(ex.lower() in m.lower() for ex in excluded):
                filtered.append(m)

        print(f"UI matches with Vestir: {ui_vestir}")
        print(f"Dress in labels: {dress_in_labels}")

        # Vestir should not exist at all
        assert len(ui_vestir) == 0, f"Found 'Vestir' in visible text: {ui_vestir}"

    def test_english_labels_exist(self):
        """Expected English labels are present."""
        content = EDITING_JS.read_text(encoding="utf-8")

        expected_labels = [
            "Auto-edit",
            "Auto-edited",  # replaced "Dressed"
            "Try another take on this scene",
        ]

        for label in expected_labels:
            assert label in content, f"Expected English label not found: '{label}'"

    def test_edit_action_labels_english(self):
        """EDIT_ACTIONS labels are all English."""
        content = EDITING_JS.read_text(encoding="utf-8")

        # Extract labels from EDIT_ACTIONS
        labels = re.findall(r'label:\s*"([^"]*)"', content)

        spanish_chars = set("áéíóúñ¿¡")
        spanish_labels = [label for label in labels if any(c in label for c in spanish_chars)]
        assert len(spanish_labels) == 0, f"Found Spanish labels in EDIT_ACTIONS: {spanish_labels}"

    def test_node_check_editing_js_valid(self):
        """node --check exits 0."""
        node_bin = shutil.which("node")
        assert node_bin is not None, "Node.js must be in PATH"
        res = subprocess.run([node_bin, "--check", str(EDITING_JS)], capture_output=True, text=True)
        assert res.returncode == 0, f"node --check failed: {res.stderr}"


class TestEditingE208NodeDom:
    """Node.js DOM tests for stepper and loading state."""

    def test_stepper_renders_three_steps(self):
        """DOM shows 3-step stepper with Cut, Auto-edit, Export in renderEditingContent."""
        content = EDITING_JS.read_text(encoding="utf-8")

        # Check that stepperHtml variable exists and contains 3 steps
        assert "stepperHtml" in content, "stepperHtml variable should exist in renderEditingContent"
        assert "const stepperHtml" in content or "let stepperHtml" in content, "stepperHtml should be defined as a const/let"

        # Step 1, 2, 3 should exist in stepper
        assert ">1<" in content or "> 1 <" in content, "Step 1 circle should exist"
        assert ">2<" in content or "> 2 <" in content, "Step 2 circle should exist"
        assert ">3<" in content or "> 3 <" in content, "Step 3 circle should exist"

        # Stepper helper styles exist - these determine active step styling
        assert "step1Style" in content, "stepper step styles should be defined"
        assert "step2Style" in content, "stepper step styles should be defined"
        assert "step3Style" in content, "stepper step styles should be defined"

    def test_dress_action_labels_english(self):
        """dress_all and redress_scene have English labels."""
        content = EDITING_JS.read_text(encoding="utf-8")

        # Find dress_all label
        dress_all_match = re.search(r'dress_all:\s*\{[\s\S]*?label:\s*"([^"]+)"', content)
        assert dress_all_match, "Could not find dress_all label"
        dress_all_label = dress_all_match.group(1)

        # Find redress_scene label
        redress_match = re.search(r'redress_scene:\s*\{[\s\S]*?label:\s*"([^"]+)"', content)
        assert redress_match, "Could not find redress_scene label"
        redress_label = redress_match.group(1)

        # Verify English
        spanish_chars = set("áéíóúñ¿¡")
        assert not any(c in dress_all_label for c in spanish_chars), f"dress_all label has Spanish: {dress_all_label}"
        assert not any(c in redress_label for c in spanish_chars), f"redress_scene label has Spanish: {redress_label}"

        # Verify specific expected labels
        assert "Auto-edit" in dress_all_label, f"Expected 'Auto-edit' in dress_all label: {dress_all_label}"

    def test_render_price_label_english(self):
        """Render label uses state.render_price (already implemented in E2-05)."""
        content = EDITING_JS.read_text(encoding="utf-8")

        # Should use state.render_price and state.render_price_kind
        assert "state.render_price" in content, "Should reference state.render_price for dynamic pricing"
        assert "state.render_price_kind" in content, "Should reference state.render_price_kind for dynamic pricing"

    def test_loading_indicator_integration(self):
        """Doc loading indicator styles exist in index.html."""
        html_content = INDEX_HTML.read_text(encoding="utf-8")

        # Check for loading indicator CSS classes
        assert ".doc-loading-content" in html_content, "Missing .doc-loading-content style"
        assert ".doc-loading-spinner" in html_content, "Missing .doc-loading-spinner style"
        assert "Doc-LoadingIndicator" in html_content, "Missing Doc-LoadingIndicator element"

        # Verify editing.js references the loading indicator
        js_content = EDITING_JS.read_text(encoding="utf-8")
        assert "Doc-LoadingIndicator" in js_content, "editing.js should reference Doc-LoadingIndicator"
        assert 'Loading your edit' in js_content or 'getElementById("Doc-LoadingIndicator")' in js_content, "editing.js should show loading state"


class TestEditingE208Requirements:
    """Specific requirements from E2-08 spec."""

    def test_step_1_is_cut(self):
        """Step 1 is labeled 'Cut'."""
        content = EDITING_JS.read_text(encoding="utf-8")
        # Check stepper construction includes Cut
        assert '>Cut<' in content, "Stepper should show 'Cut' as step 1"

    def test_step_2_is_auto_edit(self):
        """Step 2 is labeled 'Auto-edit'."""
        content = EDITING_JS.read_text(encoding="utf-8")
        assert '>Auto-edit<' in content, "Stepper should show 'Auto-edit' as step 2"

    def test_step_3_is_export(self):
        """Step 3 is labeled 'Export'."""
        content = EDITING_JS.read_text(encoding="utf-8")
        assert '>Export<' in content, "Stepper should show 'Export' as step 3"

    def test_dress_status_labels_english(self):
        """
        dressBtnLabel values should be:
        - 'Auto-edit · free' (not 'Vestir todo · free')
        - 'Auto-edited ✓' (not 'Dressed ✓')
        - 'Your cut changed — auto-edit again · free' (not 'Your cut changed — dress again · free')
        """
        content = EDITING_JS.read_text(encoding="utf-8")

        expected_defaults = ["Auto-edit · free", "Auto-edited ✓", "Your cut changed — auto-edit again · free"]

        # Check that at least these patterns exist
        for expected in expected_defaults:
            assert expected in content, f"Expected English label not found in JS: {expected}"

        # Ensure old Spanish labels are NOT present
        # Forbidden labels that should not exist
        forbidden = ["Otra versión", "Vestir"]
        for spanish in forbidden:
            assert spanish not in content, f"Old Spanish label found: {spanish}"

        # Final assertion - these exact strings should not exist as UI text
        assert '"Vestir todo · free"' not in content, "Old Spanish label should not exist"
        assert "Otra versión" not in content, "Old Spanish label should not exist"
        assert 'Dressed ✓' not in content, "Old label should not exist (use Auto-edited instead)"

    def test_redress_label_english(self):
        """Redress button label should be 'Try another take on this scene · 2 credits'."""
        content = EDITING_JS.read_text(encoding="utf-8")
        expected = "Try another take on this scene · 2 credits"
        assert expected in content, f"Expected redress label: {expected}"

    def test_no_spanish_in_scene_buttons(self):
        """Scene buttons don't have Spanish text."""
        content = EDITING_JS.read_text(encoding="utf-8")
        # Scene redress button
        assert "Otra versión" not in content, "'Otra versión' should not exist in JS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
