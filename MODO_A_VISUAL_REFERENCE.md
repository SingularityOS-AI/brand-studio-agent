# Modo A: Visual Reference Guide

## Component: Empty Ghost Section (No Content Yet)
```html
<div class="ghost">
  <span class="gnum mono">01</span>
  <span class="gname">Brand Journey</span>
  <span class="gline" style="width:120px"></span>
</div>
```
**Visual**: Gray dashed border, gray text, gray underline, 50% opacity

---

## Component: Proposed Section (Dotted Border)
```
┌─────────────────────────────────────────────┐
│ ┌──┐ Brand Journey               Proposed   │
│ │01│                                  [gray] │
│ └──┘                                          │
├─────────────────────────────────────────────┤
│                                              │
│ Founder-led AI consulting for mid-market    │
│ companies, focused on transformation        │
│                                              │
├─────────────────────────────────────────────┤
│                                              │
│ Source: You said                             │
│ "I run a founder-led AI consulting firm"    │
│ [JetBrains Mono, italic, blue]              │
│                                              │
└─────────────────────────────────────────────┘
```
**Border**: `2px dotted #D5DAE4`
**Background**: `#FFFFFF` (white)
**Status Badge**: "Proposed" in gray
**Citation**: Blue JetBrains Mono, clickable

---

## Component: Confirmed Section (Solid Border)
```
┌─────────────────────────────────────────────┐
│ ┌──┐ The pond                 Confirmed    │
│ │03│                                [blue]   │
│ └──┘                                          │
├─────────────────────────────────────────────┤
│                                              │
│ SMBs spending $50K-500K on AI but            │
│ lacking expertise to execute                │
│                                              │
├─────────────────────────────────────────────┤
│                                              │
│ Source: Analysis                             │
│ "mid-market companies need hands-on help"   │
│ [JetBrains Mono, italic, blue]              │
│                                              │
└─────────────────────────────────────────────┘
```
**Border**: `2px solid #2B4CD8` (accent blue)
**Background**: `#F5F7FB` (light blue)
**Status Badge**: "Confirmed" in accent blue
**Citation**: Blue JetBrains Mono, clickable

---

## Component: Two-Column Layout (Contrarian Stance)
```
┌─────────────────────────────────────────────┐
│ ┌──┐ Contrarian stance          Confirmed    │
│ │05│                                [blue]   │
│ └──┘                                          │
│                                              │
│ ┌──────────────────┬──────────────────────┐ │
│ │ DESIADAS         │ PROHIBIDAS           │ │
│ └──────────────────┴──────────────────────┘ │
│                                              │
│ ┌──────────────────┬──────────────────────┐ │
│ │ vs. competitors  │ "AI for everyone"   │ │
│ │ vs. agencies     │ "do it yourself"    │ │
│ │ vs. big consulting│ "cookie-cutter"    │ │
│ └──────────────────┴──────────────────────┘ │
│                                              │
├─────────────────────────────────────────────┤
│                                              │
│ Source: Analysis                             │
│ "we take a contrarian position on commoditization" │
│ [JetBrains Mono, italic, blue]              │
│                                              │
└─────────────────────────────────────────────┘
```
**Layout**: CSS Grid with 2 columns
**Background**: Light blue grid cells
**Borders**: None (internal grid only)

---

## Component: Nested Object Content (Identity Map)
```
┌─────────────────────────────────────────────┐
│ ┌──┐ Identity map               Confirmed    │
│ │07│                                [blue]   │
│ └──┘                                          │
├─────────────────────────────────────────────┤
│                                              │
│ TONE: Expert, comforting, plain English      │
│ VOICE: Founder-slash-practitioner            │
│ PERSONA: Straight-talking, no jargon         │
│ NO-BULLSHIT: We don't oversell               │
│                                              │
├─────────────────────────────────────────────┤
│                                              │
│ Source: You said                             │
│ "no jargon, straight talk, honest answers"   │
│ [JetBrains Mono, italic, blue]              │
│                                              │
└─────────────────────────────────────────────┘
```
**Format**: Key-value pairs with uppercase keys
**Spacing**: 4px margin-bottom between entries

---

## Component: Citation Block (Hover State)
```
┌─────────────────────────────────────────────┐
│                                              │
│ Source: You said                             │
│ "I run a founder-led AI consulting firm"    │
│ [background: rgba(43, 76, 216, 0.08)]        │
│ [cursor: pointer]                            │
│                                              │
└─────────────────────────────────────────────┘
```
**Indicator**: Light blue background on hover
**Cursor**: Pointer (clickable)
**Title**: "Click to jump to this moment in the conversation"

---

## Component: Transcript Highlight (After Click)
```
Left sidebar (Voice interface):
┌─────────────────────────────────────────────┐
│ I do not know you.                           │
│                                              │
│ Tell me what you do, and who you do it       │
│ for. There is no form: you talk, I write.    │
│                                              │
│ brandy: Hi! I'm Brandy, your brand           │
│ strategist. Let's explore your               │
│ [background: rgba(43, 76, 216, 0.1)]        │
│ business together. What do you do?           │
│ [border-radius: 6px]                         │
│ [padding: 8px]                               │
│                                              │
│ user: I run a founder-led AI consulting     │
│ firm.                 ──▶ Clicked citation  │
│                                      points   │
│ brandy: Interesting! Tell me           here  │
│ more about your clients...                    │
│                                              │
└─────────────────────────────────────────────┘
```
**Highlight**: Yellow background with slight blue tint
**Scroll**: Auto-centered in view
**Duration**: 3 seconds, then fades out

---

## Color Palette Reference

### Primary Colors
```
accent blue:     #2B4CD8  (confirmed badge, solid border, citation text)
accent soft:     #6E86EE  (hover state)
gray line:       #D5DAE4  (proposed border, ghost underline)
gray soft:       #5C6675  (secondary text, ghost text)

background:      #FFFFFF  (proposed section)
background alt:  #F5F7FB  (confirmed section, ghost)
ground:          #E7EAF0  (body background)
ink:             #14181F  (primary text)
```

### Status Colors
```
Proposed:  Gray text + Gray border + White background
Confirmed: Blue badge + Blue border + Light blue background
```

### Typography Colors
```
Citation text:  #2B4CD8  (accent blue)
Citation label: #5C6675  (gray soft)
Section number: #5C6675  (gray soft, uppercase)
Section label:  #14181F  (ink)
Content text:   #14181F  (ink)
```

---

## Font Stack Reference

```css
/* Numbers (section IDs, status badges) */
font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
font-size: 11px;
text-transform: uppercase;
letter-spacing: 0.12em;
font-weight: 600;

/* Section labels */
font-family: 'Space Grotesk', Inter, sans-serif;
font-size: 14px;
font-weight: 500;
letter-spacing: -0.01em;

/* Content text */
font-family: Inter, -apple-system, 'Segoe UI', sans-serif;
font-size: 13px;
line-height: 1.6;

/* Citation text */
font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
font-size: 11px;
font-style: italic;
color: #2B4CD8;

/* Key labels (in nested objects) */
font-family: Inter, sans-serif;
font-size: 11px;
text-transform: uppercase;
letter-spacing: 0.12em;
color: #5C6675;
```

---

## Spacing System Reference

```css
/* Section container */
padding: 16px 18px;
margin: 8px 0;
border: 2px solid/dotted;
border-radius: 8px;

/* Header inside section */
gap: 12px (between number, label, status)

/* Section content */
padding-left: 26px;
gap: 8px (between entries)

/* Citation block */
padding-left: 10px;
margin-top: 8px;
border-left: 2px solid #D5DAE4;

/* Two-column grid */
gap: 12px;
padding: 8px per cell;
border-radius: 6px;
```

---

## Interactive States

### Section Card
```
default: Border color based on status
hover:   Border shifts to #6E86EE (accent soft)
active:  Cursor pointer if citation present
```

### Citation Block
```
default: Transparent background
hover:   Background rgba(43, 76, 216, 0.04)
active:  Cursor pointer, title tooltip
click:   Transmits highlight request to transcript
```

### Transcript Highlight
```
0s:      Background rgba(43, 76, 216, 0.1)
         Border-radius 6px
         Padding 8px
         Auto-scroll center
0-3s:    Highlight visible
3s:      Highlight fades out (background transparent)
```

---

## Responsive Considerations

### Minimum Width: 900px (three-column layout)
- Left sidebar: 420px fixed
- Center doc:   fluid based on remaining space
- Right prod:   380px fixed

### Mobile (Not targeted for this implementation)
- Fallback to single column
- Two-column grids collapse to stacked
- Citations remain clickable

---

**Status**: All visual components implemented
**Usage**: Copy-paste CSS classes from `app/static/index.html`
**Render**: `renderModoASections()` in `app/static/app.js`
