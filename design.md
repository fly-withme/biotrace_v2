# BioTrace — Design System & UI Specification

All values in this document are the single source of truth for visual implementation.
Every spacing, size, and color value must be sourced from here and defined as a constant
in `app/ui/theme.py`. Never hardcode a pixel value or color string in a widget file.

---

## 1. Design Principles

### Rule of 8 — Spacing Grid
Every spacing, padding, margin, and dimension is a multiple of **8px**.
The base unit is `8px`. Allowed values:

```
4px   (½ unit  — hairline gaps only, e.g. icon-to-label)
8px   (1 unit  — tight internal padding)
16px  (2 units — default component padding)
24px  (3 units — card padding, section gaps)
32px  (4 units — between major sections)
40px  (5 units — large section gaps)
48px  (6 units — view-level padding)
64px  (8 units — hero areas, large separators)
96px  (12 units — empty states, illustration zones)
128px (16 units — splash / onboarding areas)
```

> Rule: If you are tempted to use an odd value (e.g. 10px, 15px, 20px), round to the
> nearest multiple of 8. Exception: 4px is allowed only for micro-gaps between tightly
> coupled elements (e.g. icon + label).

### Rule of Thirds — Layout Proportions
Divide major layout areas into thirds. Exact column counts follow a 12-column grid
(see Section 6), which maps cleanly to thirds (4 col), halves (6 col), and quarters (3 col).

| Layout zone          | Columns | Fraction | Pixel width @ 1440px content |
|----------------------|---------|----------|------------------------------|
| Full width           | 12      | 1/1      | 1152px                       |
| Two-thirds           | 8       | 2/3      | 768px                        |
| One-third            | 4       | 1/3      | 384px                        |
| Three-quarters       | 9       | 3/4      | 864px                        |
| One-quarter          | 3       | 1/4      | 288px                        |
| Half                 | 6       | 1/2      | 576px                        |

### Golden Ratio — Card Aspect
For metric cards and illustration panels where a natural proportion is needed:
`width / height ≈ 1.618`. This yields visually restful rectangles without being square.

---

## 2. Color System

### Primary Color Usage Rule
`#3B579F` is an **accent-only** color. It must never be used as a background for
any card, panel, sidebar, or container. Its uses are strictly:

- Button fill (primary action buttons)
- Icon fill / stroke
- Active navigation indicator
- Chart lines, area fills, progress bars
- Metric value text (the large number readout in metric cards)
- Section divider / accent bar (left border stripe on cards)
- Link text

### Color Palette

```
────────────────────────────────────────────────────────
  TOKEN                  HEX         USAGE
────────────────────────────────────────────────────────
  COLOR_PRIMARY          #3B579F     Buttons, icons, chart lines, active states
  COLOR_PRIMARY_HOVER    #2F4785     Hover state for primary buttons
  COLOR_PRIMARY_SUBTLE   #EEF1F9     Tinted background for selected rows,
                                     input focus ring fill — never card bg
  COLOR_BACKGROUND       #F9FBFF     Main window background, sidebar background
  COLOR_CARD             #FFFFFF     All card and panel backgrounds
  COLOR_FONT             #142970     Primary body text, labels
  COLOR_FONT_MUTED       #6B7A9F     Secondary text, captions, placeholders
  COLOR_FONT_DISABLED    #A8B4CE     Disabled state text
  COLOR_BORDER           #DDE3F0     Card borders, dividers, table row lines
  COLOR_BORDER_FOCUS     #3B579F     Input focus ring
────────────────────────────────────────────────────────
  SEMANTIC — STATUS / ALERT
────────────────────────────────────────────────────────
  COLOR_SUCCESS          #22C55E     CLI low zone (0.0–0.40), good signal quality
  COLOR_SUCCESS_BG       #F0FDF4     Success badge / chip background
  COLOR_WARNING          #F59E0B     CLI medium zone (0.40–0.70), moderate load
  COLOR_WARNING_BG       #FFFBEB     Warning badge background
  COLOR_DANGER           #EF4444     CLI high zone (0.70–1.0), alert state
  COLOR_DANGER_BG        #FEF2F2     Danger badge background
────────────────────────────────────────────────────────
  CHART PALETTE (additional trace colors)
────────────────────────────────────────────────────────
  COLOR_CHART_CLI        #3B579F     CLI trace — primary blue
  COLOR_CHART_RMSSD      #22C55E     RMSSD trace — green
  COLOR_CHART_PDI        #A78BFA     PDI trace — soft violet
  COLOR_CHART_GRID       #E8EDF7     Chart gridlines
  COLOR_CHART_AXIS       #6B7A9F     Chart axis labels
────────────────────────────────────────────────────────
```

### Color in Context — What Is Allowed Where

| Surface                    | Background          | Border          | Accent / highlight      |
|----------------------------|---------------------|-----------------|-------------------------|
| Main window                | COLOR_BACKGROUND    | —               | —                       |
| Sidebar                    | COLOR_BACKGROUND    | COLOR_BORDER    | COLOR_PRIMARY (nav bar) |
| Card / panel               | COLOR_CARD          | COLOR_BORDER    | COLOR_PRIMARY_SUBTLE    |
| Active nav item            | COLOR_PRIMARY_SUBTLE| —               | COLOR_PRIMARY (left bar)|
| Primary button             | COLOR_PRIMARY       | —               | —                       |
| Secondary button           | COLOR_CARD          | COLOR_BORDER    | COLOR_PRIMARY (text)    |
| Table row (default)        | COLOR_CARD          | COLOR_BORDER    | —                       |
| Table row (selected)       | COLOR_PRIMARY_SUBTLE| COLOR_PRIMARY   | —                       |
| Input (default)            | COLOR_CARD          | COLOR_BORDER    | —                       |
| Input (focused)            | COLOR_CARD          | COLOR_BORDER_FOCUS | —                    |
| Status badge — low load    | COLOR_SUCCESS_BG    | —               | COLOR_SUCCESS (text)    |
| Status badge — mid load    | COLOR_WARNING_BG    | —               | COLOR_WARNING (text)    |
| Status badge — high load   | COLOR_DANGER_BG     | —               | COLOR_DANGER (text)     |

---

## 3. Typography

**Font Family:** Inter (all weights)
**Font rendering:** `font-hinting: auto`, `antialiasing: subpixel` in Qt stylesheet.

### Type Scale (Major Third — ratio 1.25)

Base size: **14px** (appropriate for dense, data-heavy desktop medical software).

```
────────────────────────────────────────────────────────────────────────
  TOKEN              PX    WEIGHT   LINE-HEIGHT   LETTER-SPACING   USE
────────────────────────────────────────────────────────────────────────
  TEXT_CAPTION       11    400      16px          +0.3px           Timestamps, axis labels
  TEXT_SMALL         12    400      18px          +0.2px           Table secondary cells
  TEXT_BODY          14    400      22px           0               Default UI text
  TEXT_BODY_MEDIUM   14    500      22px           0               Emphasized body, labels
  TEXT_BODY_LARGE    16    400      24px           0               Intro paragraphs
  TEXT_SUBTITLE      16    600      24px          -0.1px           Card subheadings
  TEXT_TITLE         20    600      28px          -0.2px           Card titles, view headings
  TEXT_HEADING_2     24    700      32px          -0.3px           Section headings
  TEXT_HEADING_1     32    700      40px          -0.4px           Page titles
  TEXT_DISPLAY       40    800      48px          -0.5px           CLI gauge number, hero metric
  TEXT_METRIC_XL     48    800      56px          -0.8px           Full-screen metric callout
────────────────────────────────────────────────────────────────────────
```

### Typography Rules

- **Color:** Body text → `COLOR_FONT (#142970)`. Captions/secondary → `COLOR_FONT_MUTED`.
  Metric values (the big numbers) → `COLOR_PRIMARY (#3B579F)`.
- **Heading color:** `COLOR_FONT` for all headings. Never `COLOR_PRIMARY` for headings
  except in the active sidebar navigation item.
- **Avoid mixing more than 2 font weights on a single card.**
- **Line length:** Body text lines should not exceed 72 characters (~640px at 14px).

---

## 4. Spacing & Sizing Reference

All values derived from the Rule of 8.

### Padding Inside Components

```
Micro pad   (inner icon)          4px
Tight pad   (badge / chip)        4px top/bottom, 8px left/right
Default pad (buttons)             10px top/bottom, 16px left/right
Card pad    (all cards)           24px all sides
Section pad (view content area)   32px all sides
View pad    (outermost container) 32px left/right, 24px top/bottom
```

### Gaps Between Components

```
Icon → label                       4px
Label → input                      8px
Stacked form fields                16px
Between cards in same row          24px
Between rows of cards              24px
Between major layout sections      32px
Between view-level panels          40px
```

### Border Radius

```
RADIUS_SM     4px    Badges, chips, tags
RADIUS_MD     8px    Buttons, inputs, small widgets
RADIUS_LG     12px   Cards, panels, metric cards
RADIUS_XL     16px   Modal dialogs, large containers
RADIUS_PILL   999px  Toggle switches, pill badges
```

### Elevation / Shadow

Cards use a very subtle shadow to lift off the background. No harsh drop shadows.

```
SHADOW_SM    0px 1px 3px rgba(20, 41, 112, 0.06)    Inactive cards
SHADOW_MD    0px 4px 12px rgba(20, 41, 112, 0.08)   Default cards
SHADOW_LG    0px 8px 24px rgba(20, 41, 112, 0.10)   Modal dialogs, popovers
SHADOW_FOCUS 0px 0px 0px 3px rgba(59, 87, 159, 0.25) Focus ring on inputs/buttons
```

---

## 5. Component Specifications

### 5.1 Metric Card (MetricCard widget)

The primary data display unit. Used on dashboard and live view.

```
┌─────────────────────────────────────┐
│ ▌ Label text                 [badge]│  ← accent bar: 3px × full height, COLOR_PRIMARY
│                                     │
│   48                                │  ← value: TEXT_DISPLAY or TEXT_METRIC_XL
│   ms  (unit label, TEXT_SMALL)      │
│                                     │
│   ─────────────────────────         │  ← sparkline or delta indicator
│   ▲ +4.2 vs baseline  (caption)     │
└─────────────────────────────────────┘

Width:    280px  (fits 4 across a 1280px content area with 24px gutters)
Height:   160px  (golden ratio to width: 280 / 1.618 ≈ 173px → round to 168px = 21×8)
Padding:  24px
Radius:   12px (RADIUS_LG)
Shadow:   SHADOW_MD
Accent:   Left border 3px solid COLOR_PRIMARY
BG:       COLOR_CARD (#FFFFFF)
```

**Variant — Compact Card** (used in live view side panel):
```
Width:    full column width
Height:   96px  (12 × 8)
Padding:  16px
Value:    TEXT_HEADING_1 (32px)
```

**Variant — Alert Card** (CLI in danger zone):
- Border becomes 3px solid `COLOR_DANGER`
- Value text color switches to `COLOR_DANGER`
- Background remains `COLOR_CARD` — never red background

### 5.2 Primary Button

```
Height:       40px  (5 × 8)
Padding:      10px top/bottom, 16px left/right
Border radius: 8px (RADIUS_MD)
Font:         TEXT_BODY_MEDIUM (14px, weight 500)
Background:   COLOR_PRIMARY
Text:         #FFFFFF
Border:       none

Hover:        background → COLOR_PRIMARY_HOVER
Active:       opacity 0.9
Disabled:     background → #A8B4CE, cursor not-allowed
Focus:        SHADOW_FOCUS ring
```

### 5.3 Secondary Button

```
Height:       40px
Padding:      10px top/bottom, 16px left/right
Border radius: 8px
Font:         TEXT_BODY_MEDIUM
Background:   COLOR_CARD
Text:         COLOR_PRIMARY
Border:       1px solid COLOR_BORDER

Hover:        background → COLOR_PRIMARY_SUBTLE
```

### 5.4 Icon Button (circular)

```
Size:         40px × 40px  (5 × 8)
Border radius: 999px (pill/circle)
Icon size:    20px
Background:   transparent
Color:        COLOR_PRIMARY

Hover:        background → COLOR_PRIMARY_SUBTLE
```

### 5.5 Input Field

```
Height:       40px
Padding:      0px 12px
Border radius: 8px
Border:       1px solid COLOR_BORDER
Font:         TEXT_BODY (14px)
Background:   COLOR_CARD
Text:         COLOR_FONT
Placeholder:  COLOR_FONT_MUTED

Focus:        border → COLOR_BORDER_FOCUS + SHADOW_FOCUS
Error:        border → COLOR_DANGER
```

### 5.6 Slider (NASA-TLX & threshold config)

```
Track height:   6px  (not a multiple of 8 — Qt limitation, visually fine)
Track radius:   999px
Track bg:       COLOR_BORDER
Track fill:     COLOR_PRIMARY
Thumb size:     20px × 20px
Thumb radius:   999px
Thumb bg:       COLOR_PRIMARY
Thumb border:   2px solid #FFFFFF + SHADOW_MD
```

### 5.7 Navigation Sidebar Item

```
Height:       48px  (6 × 8)
Padding:      0px 16px
Border radius: 8px (applied to the item block, not the window edge)
Font:         TEXT_BODY_MEDIUM
Icon size:    20px
Gap icon→text: 12px

Default:      bg transparent, text COLOR_FONT_MUTED, icon COLOR_FONT_MUTED
Hover:        bg COLOR_PRIMARY_SUBTLE, text COLOR_PRIMARY
Active:       bg COLOR_PRIMARY_SUBTLE, text COLOR_PRIMARY, icon COLOR_PRIMARY,
              left border: 3px solid COLOR_PRIMARY (inset)
```

### 5.8 Status Badge / Chip

```
Height:       24px  (3 × 8)
Padding:      4px 8px
Border radius: 999px
Font:         TEXT_CAPTION (11px, weight 600, uppercase)
Letter-spacing: +0.5px

Low load:     bg COLOR_SUCCESS_BG,  text COLOR_SUCCESS
Mid load:     bg COLOR_WARNING_BG,  text COLOR_WARNING
High load:    bg COLOR_DANGER_BG,   text COLOR_DANGER
Neutral:      bg COLOR_BORDER,      text COLOR_FONT_MUTED
```

### 5.9 Live Chart (pyqtgraph)

```
Background:   COLOR_CARD
Grid lines:   COLOR_CHART_GRID
Axis text:    COLOR_CHART_AXIS, TEXT_CAPTION (11px)
Padding:      16px all sides inside chart widget

CLI trace:    COLOR_CHART_CLI,   line width 2px, filled area opacity 15%
RMSSD trace:  COLOR_CHART_RMSSD, line width 2px
PDI trace:    COLOR_CHART_PDI,   line width 2px

Threshold line: COLOR_WARNING, dashed (4px dash, 4px gap), line width 1px
Alert zone:   COLOR_DANGER background fill at opacity 8%
```

### 5.10 Divider / Separator

```
Height:   1px
Color:    COLOR_BORDER
Margin:   16px 0  (vertical spacing around the line)
```

---

## 6. Layout Grid

**Target resolution:** 1440 × 900px (minimum). Designed to scale up to 1920 × 1080px.

**Grid:** 12 columns, 24px gutters, 32px outer margins.

```
Total content width @ 1440px:
  1440 - (2 × 32px margin) = 1376px available
  Sidebar: 240px + 24px gutter = 264px
  Content area: 1376 - 264 = 1112px
  Column width: (1112 - 11 × 24px) / 12 = (1112 - 264) / 12 = 70.7px ≈ 71px per col
```

### Application Shell

```
┌────────────────────────────────────────────────────────────────────────┐
│  TOPBAR  64px tall                                                     │
│  (Logo left, Page title center, User/session controls right)           │
├────────┬───────────────────────────────────────────────────────────────┤
│        │                                                               │
│  SIDE  │   CONTENT AREA                                                │
│  BAR   │   padding: 32px left/right, 24px top/bottom                  │
│  240px │                                                               │
│        │                                                               │
│        │                                                               │
└────────┴───────────────────────────────────────────────────────────────┘

Sidebar width:   240px  (30 × 8)
Topbar height:    64px  (8 × 8)
Content width:  1112px  (@ 1440px window)
```

---

## 7. View-Level Layout Specifications

### 7.1 Main Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  Page title "Dashboard"     [+ New Session]  [Export]           │  32px top pad
├─────────────────────────────────────────────────────────────────┤
│  [Metric Card]  [Metric Card]  [Metric Card]  [Metric Card]     │  Row 1: summary stats
│  Total Sessions  Avg CLI        Avg RMSSD      Best Session      │  Height: 168px
│  (3 col)         (3 col)        (3 col)        (3 col)           │  Gap: 24px
├────────────────────────┬────────────────────────────────────────┤
│                        │                                        │  Top gap: 32px
│  Session History Table │  Trend Chart (line, CLI over time)     │
│  8 col (66%)           │  4 col (33%)                           │
│                        │                                        │
│  Min height: 400px     │  Height: matches table                 │
│                        │                                        │
└────────────────────────┴────────────────────────────────────────┘
```

**Session History Table rows:**
- Row height: `48px` (6 × 8)
- Header height: `40px` (5 × 8)
- Column content: `TEXT_BODY (14px)`
- Header: `TEXT_BODY_MEDIUM (14px, 500 weight)`

### 7.2 Calibration Page

Centered wizard card. No sidebar clutter — user needs focus.

```
Outer layout: full content area, vertically centered
Wizard card:
  Width:   640px  (fixed, 80 × 8)
  Padding: 40px
  Radius:  16px (RADIUS_XL)
  Shadow:  SHADOW_LG
  BG:      COLOR_CARD

Step indicator (top of card):
  Dots or numbered circles, 32px × 32px each
  Active step: filled COLOR_PRIMARY circle
  Completed:   check icon, COLOR_SUCCESS
  Inactive:    COLOR_BORDER circle, text COLOR_FONT_MUTED
  Line between steps: 1px COLOR_BORDER

Signal quality indicator bar:
  Height:      8px (filled progress bar style)
  Width:       full card content width
  Radius:      999px
  Fill:        COLOR_SUCCESS / COLOR_WARNING / COLOR_DANGER (dynamic)

Baseline recording timer:
  TEXT_METRIC_XL (48px) centered — large countdown
  Sub-label: TEXT_SUBTITLE (16px)
```

### 7.3 Live Feedback — Mode A (Video + Data)

```
┌──────────────────────────────────────┬───────────────────────┐
│                                      │  [CLI Gauge]          │
│  VIDEO FEED                          │  TEXT_METRIC_XL       │  Top section
│  8 col (66.7%)                       │                       │
│                                      │  [RMSSD Card compact] │  4 col (33.3%)
│  Aspect ratio: 16:9                  │  [PDI Card compact]   │
│  Rounded corners: 12px               │  [HR Card compact]    │
│                                      │                       │
│                                      │  [Status badge]       │
├──────────────────────────────────────┴───────────────────────┤
│  TIMELINE BAR (mini scrub bar, session elapsed)              │  40px height
│  COLOR_PRIMARY filled left portion, COLOR_BORDER track       │
├──────────────────────────────────────────────────────────────┤
│  [Live Chart — CLI]                                          │  Chart panel: 200px
│  Full width, scrolling                                       │
└──────────────────────────────────────────────────────────────┘

Video panel height: (8/12 × content_width) / (16/9) — maintain 16:9 ratio
Compact metric card height: 96px
Chart panel height: 200px (25 × 8)
```

### 7.4 Live Feedback — Mode B (Data Only)

```
┌─────────────────────────────────────────────────────────────┐
│  [CLI Card]    [RMSSD Card]    [PDI Card]    [HR Card]       │  Metric row: 168px
│  (3 col each)                                               │  Gap: 24px
├─────────────────────────────────────────────────────────────┤
│  [CLI Chart — full width]                                   │  Chart: 240px
├─────────────────────────────────────────────────────────────┤
│  [RMSSD Chart — 6 col]         [PDI Chart — 6 col]          │  Charts: 200px each
└─────────────────────────────────────────────────────────────┘

CLI chart height:      240px  (30 × 8)
Sub-chart height:      200px  (25 × 8)
Gap between charts:     24px
```

### 7.5 Post-Session Dashboard

```
┌───────────────────────────────────────────────────────────────┐
│  Session Summary Header: date, duration, final CLI badge      │  48px
├───────────────────────────────────────────────────────────────┤
│  FULL-WIDTH TIMELINE CHART                                    │  320px height
│  All three traces (CLI, RMSSD, PDI), zoomable/pannable        │
│  Click a point → video jumps to that timestamp (Mode A only)  │
├────────────────────────────┬──────────────────────────────────┤
│  METRIC BREAKDOWN          │  NASA-TLX INPUT PANEL            │
│  8 col                     │  4 col                           │
│                            │                                  │
│  - Avg CLI, peak CLI       │  6 sliders (one per dimension)   │
│  - Avg RMSSD               │  Height: 40px each + 8px gap     │
│  - Avg PDI                 │  Pairwise weight section below   │
│  - Annotated event markers │  [Calculate Score] button        │
│                            │                                  │
│  Min height: 320px         │  Final score: TEXT_HEADING_1     │
├────────────────────────────┴──────────────────────────────────┤
│              [Save Session]   [Export CSV]   [Export JSON]     │  64px footer
└───────────────────────────────────────────────────────────────┘

Timeline chart height:    320px  (40 × 8)
Metric breakdown height:  320px  (40 × 8)
NASA-TLX panel height:    320px  (matches)
Footer height:             64px  (8 × 8)
```

---

## 8. Iconography

- **Library:** Material Symbols Rounded (or Phosphor Icons — both have Python-compatible SVG sets)
- **Sizes:** 16px (inline), 20px (default UI), 24px (navigation), 32px (featured/empty state)
- **Color:** Always `COLOR_PRIMARY` for active/filled icons. `COLOR_FONT_MUTED` for inactive.
- **Style:** Rounded / filled style. No outline-only icons — they read poorly at small sizes on dense UIs.
- **Stroke width:** 1.5px for 20px icons, 1.25px for 24px+.

---

## 9. Topbar & Sidebar Dimensions

### Topbar

```
Height:          64px
Padding:         0 32px
BG:              COLOR_CARD
Border-bottom:   1px solid COLOR_BORDER
Shadow:          SHADOW_SM

Left:   App logo (32px tall) + app name "BioTrace" (TEXT_SUBTITLE, COLOR_FONT)
Center: Page/view title (TEXT_TITLE, 20px, COLOR_FONT)
Right:  Session status pill + settings icon button (40px)
```

### Sidebar

```
Width:           240px
Padding:         16px 12px   (top/bottom 16px, left/right 12px)
BG:              COLOR_BACKGROUND
Border-right:    1px solid COLOR_BORDER

Top section:
  App logo block:  64px tall (matches topbar)

Nav section:
  Label:           TEXT_CAPTION (11px, UPPERCASE, +1px letter-spacing),
                   COLOR_FONT_MUTED, margin-bottom 8px
  Nav item:        48px tall, padding 0 16px, RADIUS_MD
  Icon:            20px, gap to label 12px

Bottom section:
  Sensor status indicators (one per device)
  Item height: 40px
  Dot indicator: 8px circle, COLOR_SUCCESS / COLOR_DANGER
```

---

## 10. theme.py Constants Reference

The following must be defined in `app/ui/theme.py` and imported everywhere else.
No hex string, font size, or pixel value should appear outside this file.

```python
# ── Colors ────────────────────────────────────────────────────────────
COLOR_PRIMARY         = "#3B579F"
COLOR_PRIMARY_HOVER   = "#2F4785"
COLOR_PRIMARY_SUBTLE  = "#EEF1F9"
COLOR_BACKGROUND      = "#F9FBFF"
COLOR_CARD            = "#FFFFFF"
COLOR_FONT            = "#142970"
COLOR_FONT_MUTED      = "#6B7A9F"
COLOR_FONT_DISABLED   = "#A8B4CE"
COLOR_BORDER          = "#DDE3F0"
COLOR_BORDER_FOCUS    = "#3B579F"

COLOR_SUCCESS         = "#22C55E"
COLOR_SUCCESS_BG      = "#F0FDF4"
COLOR_WARNING         = "#F59E0B"
COLOR_WARNING_BG      = "#FFFBEB"
COLOR_DANGER          = "#EF4444"
COLOR_DANGER_BG       = "#FEF2F2"

COLOR_CHART_CLI       = "#3B579F"
COLOR_CHART_RMSSD     = "#22C55E"
COLOR_CHART_PDI       = "#A78BFA"
COLOR_CHART_GRID      = "#E8EDF7"
COLOR_CHART_AXIS      = "#6B7A9F"

# ── Spacing (Rule of 8) ───────────────────────────────────────────────
SPACE_1  =   8
SPACE_2  =  16
SPACE_3  =  24
SPACE_4  =  32
SPACE_5  =  40
SPACE_6  =  48
SPACE_8  =  64
SPACE_12 =  96
SPACE_16 = 128
SPACE_MICRO = 4    # hairline gaps only

# ── Border Radius ─────────────────────────────────────────────────────
RADIUS_SM   =   4
RADIUS_MD   =   8
RADIUS_LG   =  12
RADIUS_XL   =  16
RADIUS_PILL = 999

# ── Font Family ───────────────────────────────────────────────────────
FONT_FAMILY = "Inter"

# ── Font Sizes ────────────────────────────────────────────────────────
FONT_CAPTION      = 11
FONT_SMALL        = 12
FONT_BODY         = 14
FONT_BODY_LARGE   = 16
FONT_SUBTITLE     = 16
FONT_TITLE        = 20
FONT_HEADING_2    = 24
FONT_HEADING_1    = 32
FONT_DISPLAY      = 40
FONT_METRIC_XL    = 48

# ── Font Weights ──────────────────────────────────────────────────────
WEIGHT_REGULAR = 400
WEIGHT_MEDIUM  = 500
WEIGHT_SEMIBOLD = 600
WEIGHT_BOLD    = 700
WEIGHT_EXTRABOLD = 800

# ── Component Dimensions ──────────────────────────────────────────────
SIDEBAR_WIDTH       = 240
TOPBAR_HEIGHT       =  64
BTN_HEIGHT_DEFAULT  =  40
INPUT_HEIGHT        =  40
NAV_ITEM_HEIGHT     =  48
CARD_PADDING        =  24
CARD_RADIUS         =  12
METRIC_CARD_WIDTH   = 280
METRIC_CARD_HEIGHT  = 168
METRIC_CARD_COMPACT_HEIGHT = 96

# ── Layout ────────────────────────────────────────────────────────────
CONTENT_PADDING_H   =  32
CONTENT_PADDING_V   =  24
GRID_GUTTER         =  24
CHART_HEIGHT_FULL   = 240
CHART_HEIGHT_HALF   = 200
CHART_HEIGHT_TIMELINE = 320
CALIBRATION_CARD_WIDTH = 640

# ── Shadows (as QSS string) ───────────────────────────────────────────
# Note: Qt stylesheet shadow simulation via border — true drop shadows
# require QGraphicsDropShadowEffect applied in Python code.
SHADOW_COLOR_SM = (20, 41, 112, 15)   # RGBA tuple for QGraphicsDropShadowEffect
SHADOW_COLOR_MD = (20, 41, 112, 20)
SHADOW_COLOR_LG = (20, 41, 112, 26)
SHADOW_BLUR_SM  =  6
SHADOW_BLUR_MD  = 16
SHADOW_BLUR_LG  = 32
SHADOW_OFFSET_SM = (0, 1)
SHADOW_OFFSET_MD = (0, 4)
SHADOW_OFFSET_LG = (0, 8)
```

---

## 11. Design Anti-Patterns — What to Avoid

- **Never fill a card background with `COLOR_PRIMARY`.** Use `COLOR_PRIMARY_SUBTLE` for
  tinted states, `COLOR_CARD` for normal cards.
- **Never mix chart trace colors with semantic status colors.** The CLI chart line is
  always `COLOR_CHART_CLI` — it does not change to red when load is high. Use an alert
  badge or border change for the alert state instead.
- **Never use more than 2 type sizes within a single card.** Title + value is the max.
  Add a caption if needed, but keep it to 3 levels maximum.
- **Never use drop shadows larger than `SHADOW_MD` on cards.** Reserve `SHADOW_LG` for
  modals and dialogs only.
- **Never use a pixel value not in the Rule-of-8 table** (Section 4) without a comment
  explaining the exception.
- **Never set explicit widths on cards inside a grid.** Use column spans and let the
  grid determine the width — cards should stretch to fill their column.
