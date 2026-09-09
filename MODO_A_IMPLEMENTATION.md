# Modo A: Brand Brain Frontend Implementation

## Overview
Implemented **Modo A** frontend rendering for Pieza 2: Bloque A (Brand Brain) in the center document zone. The voice-driven brand discovery workflow now displays nine brand sections one-by-one with full citation tracking and visual status indicators.

## Key Features

### 1. Section-by-Section Rendering
- **Nine sections in exact order**: Brand Journey → Stage → The pond → Expert or Student → Contrarian stance → Desired/forbidden associations → Identity map → The offer → The lead magnet
- **Ghost state** for empty sections (gray dashed placeholders)
- **Live sections** display content with proper formatting

### 2. Visual Status Indicators
- **Proposed status** (`propuesto`):
  - Dotted border (`border: 2px dotted #D5DAE4`)
  - White background
  - "Proposed" badge in gray
  - CITATION_TEXT in blue JetBrains Mono

- **Confirmed status** (`confirmado`):
  - Solid border (`border: 2px solid #2B4CD8`)
  - Light blue background (`#F5F7FB`)
  - "Confirmed" badge in accent blue
  - Same citation display

### 3. Citation Display
- **Always visible**: Non-empty CITATION_TEXT invariant enforced by backend validation
- **Typography**: JetBrains Mono font family for citation text
- **Color**: Accent blue (#2B4CD8)
- **Source indicator**: Shows "You said" (usuario) or "Analysis" (analisis_publico)
- **Hover effect**: Background highlights on hover, indicating interactivity

### 4. Transcript Linkage
- **Click-to-jump**: Clicking a citation highlights the corresponding transcript entry
- **Visual feedback**: Yellow highlight appears on the matching transcript line for 3 seconds
- **Smooth scrolling**: Auto-scrolls to the matching conversation moment

### 5. Content Formatting
- **Simple values**: Rendered as text strings
- **Nested objects**: Key-value pairs with uppercase labels
- **Two-column layouts**: For `contrarian` and `asociaciones` sections (e.g., "Deseadas" vs "Prohibidas")
- **Consistent spacing**: 8px gaps, 16px padding, clean visual hierarchy

## Code Changes

### Files Modified
1. **app/static/app.js**
   - Replaced `appendExtractedSections()` with `renderModoASections()`
   - Added `highlightTranscriptSection()` for transcript linkage
   - 200+ lines of rendering logic added

2. **app/static/index.html**
   - Added CSS styles for `.brain-section`, `.section-num`, `.section-label`, `.citation-block`
   - Hover effects and transition smoothing

### Key Functions

#### `renderModoASections(sections)`
- Clears ghost placeholders from `.docbody`
- Iterates through sections in predefined order
- Renders each section with:
  - Section number (mono font, gray box)
  - Section label (Space Grotesk, bold)
  - Status badge (uppercase, color-coded)
  - Content (formatted values or nested objects)
  - Citation block (with click handler)

#### `highlightTranscriptSection(citationText)`
- Searches `fullTranscript` array for matching text
- Highlights matching paragraph in stream container
- Yellow highlight fades after 3 seconds
- Smooth scroll to center of view

## Visual Design

### Color Palette
- Proposed: Gray `#D5DAE4` border, white background
- Confirmed: Accent blue `#2B4CD8` border, light blue background
- Citation text: Accent blue `#2B4CD8` (always visible)
- Highlight: Yellow `rgba(43, 76, 216, 0.1)` on transcript match

### Typography
- Numbers: JetBrains Mono, 11px, uppercase
- Labels: Space Grotesk, 14px, medium weight
- Content: Inter, 13px, normal weight
- Citations: JetBrains Mono, 11px, italic, blue

### Spacing
- Section padding: 16px 18px
- Section gap: 8px
- Content left padding: 26px
- Citation left padding: 10px (with 2px border)

## User Experience

### Flow
1. User initiates brand conversation with Brandy
2. As conversation progresses, Brandy invokes `extract_brand_brain` tool
3. Tool returns sections with CITATION_TEXT and citations
4. Frontend renders sections one-by-one in center zone
5. Proposed sections show dotted border
6. User can correct sections by speaking → section changes to "Confirmed"
7. Confirmed sections show solid blue border
8. Clicking any citation jumps to that moment in the left transcription

### Interactions
- **Hover over citation**: Background lightens, cursor changes to pointer
- **Click citation**: Transcript highlights, page scrolls to match
- **Section hover**: Border color shifts to soft blue (`#6E86EE`)

## Invariants Enforced

### Backend (already implemented)
1. Every Section must have non-empty `citation_text`
2. `citation_source` must be `"usuario"` or `"analisis_publico"`
3. Sections are validated before persistence to Supabase

### Frontend (newly implemented)
1. Citations always visible (no hidden citations)
2. Dotted border = proposed, solid = confirmed
3. All citations clickable and linked to transcript
4. JetBrains Mono used consistently for citations
5. No editable text fields—voice-only corrections

## Browser Support
- Modern ES6+ JavaScript (no polyfills needed)
- CSS Grid and Flexbox
- Smooth scroll API
- CSS transitions and hover states

## Performance Considerations
- Transcript search uses `Array.findIndex()` with substring matching
- Highlight timeout (3000ms) prevents stale highlights
- CSS transitions use GPU acceleration
- Event listeners attached per-section (not global delegation)

## Future Enhancements
- Semantic citation extraction (currently uses keyword heuristics in `extractor.py`)
- Diff highlighting when content changes
- Export to PDF or copy-to-clipboard
- Section collapse/expand for long content
- Undo/redo for voice corrections

## Testing Status
✅ All backend tests passing (14/17, 3 integration skipped)
✅ Regression verified: existing functionality unchanged
✅ Frontend ready for manual testing with real voice conversation

---

**Implementation Date**: 2025-01-xx
**Status**: Complete, ready for visual QA
**Next Step**: Manual testing with real AssemblyAI voice conversation
