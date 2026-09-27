# EVIDENCE — F-09 Catalog + Brand Soul Tools

Date: 2026-09-27
Piece: F-09 Catalog & Brand Soul Voice Tools
Author: Antigravity (Architect CTO)

## 1. Unit & Integration Test Results

### Node.js Harness Test (`node tests/agent_catalog.test.js`)
```
--- RUNNING F-09 CATALOG & SOUL HARNESS TESTS ---
✓ Test 1 Passed: Public API exports for F-09 present
✓ Test 2 Passed: CATALOG_TOOL_SCHEMAS contains all 8 required tools
✓ Test 3 Passed: SOUL_TOOL_SCHEMAS contains soul_generate and soul_regenerate
✓ Test 4 Passed: findIdeaInCatalog handles position, unique title, ambiguous, and not found cases
✓ Test 5 Passed: All Brand Soul and Catalog actions registered in BrandStudioActions with correct costs
ALL F-09 NODE HARNESS TESTS PASSED CLEANLY! 🎉
```

### Pytest Suite (`pytest tests/test_agent_f09.py -v`)
```
tests/test_agent_f09.py::test_agent_js_exports_f09_catalog_soul_api PASSED [ 33%]
tests/test_agent_f09.py::test_actions_js_registers_f09_soul_and_catalog_actions PASSED [ 66%]
tests/test_agent_f09.py::test_node_harness_f09_passes PASSED             [100%]

============================== 3 passed in 0.66s ==============================
```

## 2. Verification Summary
- **Soul Tools Registered:** `soul_generate` (20 credits), `soul_regenerate` (20 credits).
- **Catalog Tools Registered:** `catalog_research_demand` (5 credits), `catalog_generate_ideas` (5 credits), `catalog_regenerate_idea` (3 credits), `catalog_add_idea` (free), `catalog_accept` (free), `catalog_discard` (0 credits), `catalog_explain_demand` (free), `catalog_lock` (confirm).
- **Ambiguity Resolution:** `findIdeaInCatalog` resolves ideas by position ("idea 4", "4th idea") and title keywords. If ambiguous, returns `status: "ambiguous"` with options to ask founder.
