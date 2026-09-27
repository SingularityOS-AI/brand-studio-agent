"""Tests for F-09: Catalog + Brand Soul tools.

F-09 adds Catalog and Brand Soul step voice tools:
- soul_generate (20 credits, needs confirm)
- soul_regenerate (20 credits, needs confirm)
- catalog_research_demand (confirm)
- catalog_generate_ideas (5 credits, needs confirm)
- catalog_regenerate_idea({idea}) (3 credits, needs confirm)
- catalog_add_idea({text}) (free)
- catalog_accept({idea}) (free)
- catalog_discard({idea}) (needs confirm)
- catalog_explain_demand({idea}) (free)
- catalog_lock (needs confirm)

These tests verify:
1. agent.js exports findIdeaInCatalog, CATALOG_TOOL_SCHEMAS, and SOUL_TOOL_SCHEMAS
2. actions.js registers soul.* and catalog.* actions
3. Node harness test passes cleanly
"""
from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent
AGENT_JS = REPO_ROOT / "app" / "static" / "agent.js"
ACTIONS_JS = REPO_ROOT / "app" / "static" / "actions.js"


def test_agent_js_exports_f09_catalog_soul_api():
    """Verify agent.js exports F-09 catalog and soul tools."""
    content = AGENT_JS.read_text(encoding="utf-8")

    assert "findIdeaInCatalog" in content
    assert "CATALOG_TOOL_SCHEMAS" in content
    assert "SOUL_TOOL_SCHEMAS" in content
    assert "findIdeaInCatalog: findIdeaInCatalog" in content
    assert "CATALOG_TOOL_SCHEMAS: CATALOG_TOOL_SCHEMAS" in content
    assert "SOUL_TOOL_SCHEMAS: SOUL_TOOL_SCHEMAS" in content


def test_actions_js_registers_f09_soul_and_catalog_actions():
    """Verify actions.js registers all F-09 soul and catalog actions."""
    content = ACTIONS_JS.read_text(encoding="utf-8")

    expected_actions = [
        "soul.generate",
        "soul.regenerate",
        "catalog.research_demand",
        "catalog.generate_ideas",
        "catalog.regenerate_idea",
        "catalog.add_idea",
        "catalog.accept",
        "catalog.discard",
        "catalog.explain_demand",
        "catalog.lock",
    ]

    for act in expected_actions:
        assert f"id: '{act}'" in content or f'id: "{act}"' in content, f"Missing action: {act}"


def test_node_harness_f09_passes():
    """Run Node test harness for F-09 and assert 0 returncode."""
    test_file = REPO_ROOT / "tests" / "agent_catalog.test.js"
    assert test_file.exists(), f"Test file not found: {test_file}"

    result = subprocess.run(
        ["node", str(test_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"F-09 Node harness failed:\n{result.stderr}\n{result.stdout}"
