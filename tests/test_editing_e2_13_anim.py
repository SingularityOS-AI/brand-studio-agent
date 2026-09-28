"""Test suite for Piece E2-13 — Animated Overlay Library (Templates + Render + Preview)"""

import re
import pytest
from pathlib import Path
from render_service.manifest import OverlayCue, OVERLAY_KINDS


class TestE2_13AnimatedOverlaysContract:
    """E2-13.1: Render contract validation.

    Verify that overlay animated kinds are in OVERLAY_KINDS and OverlayCue has
    anim/params fields with None defaults for zero-regression deployment.
    """

    def test_animated_kinds_in_manifest(self):
        """E2-13.1.1: All 8 animated kinds in OVERLAY_KINDS."""
        animated_kinds = {
            "stat_counter",
            "checklist",
            "arrow_callout",
            "lower_third_anim",
            "quote_reveal",
            "icon_pop",
            "progress_bar",
            "keyword_highlight",
        }
        assert animated_kinds.issubset(OVERLAY_KINDS), (
            "Missing animated kinds in OVERLAY_KINDS"
        )

    def test_overlay_cue_has_anim_field(self):
        """E2-13.1.2: OverlayCue has anim field with str | None type."""
        assert "anim" in OverlayCue.model_fields
        field = OverlayCue.model_fields["anim"]
        # Check field is optional (default is None)
        assert field.default is None

    def test_overlay_cue_has_params_field(self):
        """E2-13.1.3: OverlayCue has params field with dict[str, Any] | None type."""
        assert "params" in OverlayCue.model_fields
        field = OverlayCue.model_fields["params"]
        # Check field is optional (default is None)
        assert field.default is None

    def test_animated_cue_accepts_anim_field(self):
        """E2-13.1.4: Animated overlay cue accepts anim field."""
        params = {
            "text": "Hello",
            "brandSoul": {"color": "#000000", "accent": "#FF6B35", "font": "Arial"},
        }
        cue = OverlayCue(
            id="test",
            kind="lower_third_anim",
            anim="lower_third",
            params=params,
            start_ms=0,
            end_ms=1000,
            text="Test",
            x=50,
            y=1500,
            w=800,
            h=120,
        )
        assert cue.anim == "lower_third"

    def test_animated_cue_accepts_params_field(self):
        """E2-13.1.5: Animated overlay cue accepts params dict."""
        params = {
            "text": "Hello",
            "brandSoul": {"color": "#000000", "accent": "#FF6B35", "font": "Arial"},
        }
        cue = OverlayCue(
            id="test",
            kind="lower_third_anim",
            params=params,
            start_ms=0,
            end_ms=1000,
            text="Test",
            x=50,
            y=1500,
            w=800,
            h=120,
        )
        assert cue.params == params


class TestE2_13AnimatedOverlayTemplates:
    """E2-13.2: Template file structure validation.

    Verify all 8 templates exist, follow the closed spec (1080×1920 single page,
    window.__timelines.main, window.__params JSON, GSAP CDN).
    """

    templates_dir = Path(__file__).parent.parent / "render_service" / "overlay_templates"
    animated_templates = {
        "stat_counter.html",
        "checklist.html",
        "arrow_callout.html",
        "lower_third.html",
        "quote_reveal.html",
        "icon_pop.html",
        "progress_bar.html",
        "keyword_highlight.html",
    }

    def test_templates_dir_exists(self):
        """E2-13.2.1: overlay_templates directory exists."""
        assert self.templates_dir.is_dir()

    def test_all_templates_exist(self):
        """E2-13.2.2: All 8 animated template HTML files exist."""
        existing = {f.name for f in self.templates_dir.glob("*.html")}
        assert self.animated_templates.issubset(existing), (
            f"Missing templates: {self.animated_templates - existing}"
        )

    @pytest.mark.parametrize("template_name", animated_templates)
    def test_template_declares_window_params(self, template_name):
        """E2-13.2.3: Template reads window.__params for brand soul colors."""
        template_path = self.templates_dir / template_name
        content = template_path.read_text(encoding="utf-8")
        assert "__params" in content, f"{template_name}: No window.__params reference"

    @pytest.mark.parametrize("template_name", animated_templates)
    def test_template_exports_window_timelines_main(self, template_name):
        """E2-13.2.4: Template exports window.__timelines.main GSAP timeline."""
        template_path = self.templates_dir / template_name
        content = template_path.read_text(encoding="utf-8")
        assert "__timelines" in content, f"{template_name}: No window.__timelines reference"
        # Check for main key with quotes, dot notation, or bare identifier in object literal (all valid JS)
        assert '"main"' in content or "'main'" in content or ".main" in content or re.search(r'__timelines\s*=\s*\{[^}]*\bmain\b', content), f"{template_name}: No main timeline reference"

    @pytest.mark.parametrize("template_name", animated_templates)
    def test_template_uses_gsap(self, template_name):
        """E2-13.2.5: Template uses GSAP (CDN or local)."""
        template_path = self.templates_dir / template_name
        content = template_path.read_text(encoding="utf-8")
        assert "gsap" in content.lower(), f"{template_name}: No GSAP reference"

    @pytest.mark.parametrize("template_name", animated_templates)
    def test_template_timeline_paused(self, template_name):
        """E2-13.2.6: GSAP timeline is paused by default (for seek control)."""
        template_path = self.templates_dir / template_name
        content = template_path.read_text(encoding="utf-8")
        assert "paused: true" in content or "paused:true" in content, (
            f"{template_name}: Timeline not paused"
        )

    @pytest.mark.parametrize("template_name", animated_templates)
    def test_template_background_transparent(self, template_name):
        """E2-13.2.7: Body has transparent background for PNG frame composition."""
        template_path = self.templates_dir / template_name
        content = template_path.read_text(encoding="utf-8")
        # Check for transparent OR rgba(0, 0, 0, 0) which are both valid transparent backgrounds
        assert (
            ("transparent" in content and "background" in content) or
            ("rgba(0, 0, 0, 0)" in content or "rgba(0,0,0,0)" in content)
        ), f"{template_name}: Non-transparent background"


class TestE2_13AnimatedOverlayRendering:
    """E2-13.3: Seek-capture rendering integration.

    Verify ffmpeg_dress.py correctly delegates to seek_capture for animated overlays.
    """

    def test_animated_kinds_constant_defined(self):
        """E2-13.3.1: ANIMATED_OVERLAY_KINDS constant matches IR kinds."""
        from render_service.ffmpeg_dress import ANIMATED_OVERLAY_KINDS
        expected = {
            "stat_counter",
            "checklist",
            "arrow_callout",
            "lower_third_anim",
            "quote_reveal",
            "icon_pop",
            "progress_bar",
            "keyword_highlight",
        }
        assert ANIMATED_OVERLAY_KINDS == expected

    def test_kind_to_template_mapping(self):
        """E2-13.3.2: KIND_TO_TEMPLATE includes lower_third_anim mapping."""
        from render_service.ffmpeg_dress import KIND_TO_TEMPLATE
        assert "lower_third_anim" in KIND_TO_TEMPLATE
        assert KIND_TO_TEMPLATE["lower_third_anim"] == "lower_third"

    def test_render_animated_overlay_png_frames_exists(self):
        """E2-13.3.3: _render_animated_overlay_png_frames function exists."""
        from render_service.ffmpeg_dress import _render_animated_overlay_png_frames
        assert callable(_render_animated_overlay_png_frames)


class TestE2_13CatalogIntegration:
    """E2-13.4: Editing catalog integration.

    Verify animated kinds are in catalog for LLM reference.
    """

    def test_animated_kinds_in_catalog(self):
        """E2-13.4.1: catalog_v1.json has animated_kinds array."""
        catalog_path = Path(__file__).parent.parent / "app" / "editing" / "catalog" / "catalog_v1.json"
        catalog = __import__("json").loads(catalog_path.read_text(encoding="utf-8"))
        assert "overlays" in catalog
        assert "animated_kinds" in catalog["overlays"]
        assert len(catalog["overlays"]["animated_kinds"]) == 8


class TestE2_13PreviewIntegration:
    """E2-13.6: Browser preview integration.

    Verify editing_preview.js has constants and iframe support for animated overlays.
    """

    def test_animated_overlay_kinds_constant_exists(self):
        """E2-13.6.1: ANIMATED_OVERLAY_KINDS constant exists in preview."""
        preview_path = Path(__file__).parent.parent / "app" / "static" / "editing_preview.js"
        content = preview_path.read_text(encoding="utf-8")
        assert "ANIMATED_OVERLAY_KINDS" in content

    def test_preview_uses_iframe_for_animated_overlays(self):
        """E2-13.6.2: createOverlayNode creates iframe for animated kinds."""
        preview_path = Path(__file__).parent.parent / "app" / "static" / "editing_preview.js"
        content = preview_path.read_text(encoding="utf-8")
        assert "iframe" in content
        assert "/static/overlay_templates/" in content

    def test_preview_seeks_gsap_timeline(self):
        """E2-13.6.3: applyState seeks GSAP timeline for animated overlays."""
        preview_path = Path(__file__).parent.parent / "app" / "static" / "editing_preview.js"
        content = preview_path.read_text(encoding="utf-8")
        assert "__timelines" in content
        assert ".seek(" in content


class TestE2_13StaticMount:
    """E2-13.7: Static file mount.

    Verify app/main.py serves overlay_templates at /static/overlay_templates.
    """

    def test_animated_overlay_static_mount_defined(self):
        """E2-13.7.1: app/main.py has /static/overlay_templates mount."""
        main_path = Path(__file__).parent.parent / "app" / "main.py"
        content = main_path.read_text(encoding="utf-8")
        assert '"/static/overlay_templates"' in content
        assert "StaticFiles" in content
        assert "mount" in content


class TestE2_13CatalogFormat:
    """E2-13.8: Catalog format.

    Verify catalog_v1.json has animated_kinds array for LLM reference.
    """

    def test_catalog_has_animated_kinds_array(self):
        """E2-13.8.1: Overlays section has animated_kinds array."""
        catalog_path = Path(__file__).parent.parent / "app" / "editing" / "catalog" / "catalog_v1.json"
        import json
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert "overlays" in catalog
        assert "animated_kinds" in catalog["overlays"]
        assert isinstance(catalog["overlays"]["animated_kinds"], list)
