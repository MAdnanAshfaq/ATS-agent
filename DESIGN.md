# DESIGN.md — ATS Agent & Career Copilot
# Source of truth for all UI tokens and component rules.
# This file is read by the AI agent before any CSS is written or modified.

## 1. Color Tokens
```
Surface (dark backgrounds — layered)
  --s0: #0A0D12      base page background
  --s1: #111318      card / panel surface
  --s2: #181C24      inset / input surface
  --s3: #1E2330      deepest inset (code, terminal)

Borders
  --b0: #252B38      structural borders (cards, panels)
  --b1: #323B4E      emphasis borders (active states)

Text (all meet ≥ 4.5:1 contrast on --s1)
  --t0: #DDE2EA      primary text
  --t1: #8B95A8      secondary / label text
  --t2: #505A6E      tertiary / placeholder / disabled text

Accent (one action color only — no purple, no gradient)
  --a0: #4A90D9      primary action (links, buttons, focus rings)
  --a1: #2A6AB0      action hover
  --a2: #1A3D6A      action background tint (chip bg, inset on dark)

Status (use ONLY for their named state — never decorative)
  --ok0: #22C55E     match / verified / success
  --ok1: #14532D     success background tint
  --wn0: #F59E0B     gap / flag / warning (amber, as spec'd)
  --wn1: #451A03     warning background tint
  --er0: #EF4444     error / danger
  --er1: #450A0A     error background tint

Matrix Card (inverted — light surface on dark page)
  --mx-bg: #FFFFFF
  --mx-s1: #F4F5F7
  --mx-b0: #E4E7EE
  --mx-t0: #0F172A
  --mx-t1: #4B5563
  --mx-t2: #9CA3AF
```

## 2. Typography
```
Body font: "Inter", system-ui, -apple-system, sans-serif
  Weight scale: 400 regular / 500 medium / 600 semibold / 700 bold

Mono font: "Cascadia Code", "Consolas", "Fira Code", monospace
  Used for: scores, metrics, file paths, timestamps, code snippets

Size scale (px — no arbitrary values):
  11 / 12 / 13 / 14 / 16 / 20 / 24

Line heights:
  Tight headings: 1.2
  Body copy:      1.6
  Code:           1.5

Letter spacing:
  Uppercase labels: 0.06em
  Body: 0 (default)

NO display font. NO serif. NO Outfit. NO Space Grotesk. NO Instrument Serif.
```

## 3. Spacing (8pt grid)
```
All spacing is a multiple of 4px:
  xs:  4px
  sm:  8px
  md:  12px
  lg:  16px
  xl:  24px
  2xl: 32px
  3xl: 48px
  4xl: 64px

Container max-width: 1400px
Container horizontal padding: 32px
Card padding: 24px (uniform, no exceptions)
```

## 4. Radii
```
sm:  4px  (chips, badges, small buttons)
md:  6px  (cards, inputs, buttons)
lg:  8px  (modal, large panels)
pill: 9999px (only for status pills, not for cards)
```

## 5. Interaction Rules
```
Hover states:
  - Background shift ONLY. No transform. No expanding box-shadow.
  - Duration: 120ms
  - Property: background-color, border-color, color

Focus:
  - 2px solid var(--a0) outline, offset 2px
  - No glow ring. No box-shadow spread beyond 2px.

Transitions:
  - Max 150ms
  - Properties: color, background-color, border-color, opacity
  - Easing: linear (not cubic-bezier theatrics)

Active / selected:
  - Border-color → --a0
  - Background → --a2

BANNED:
  - transform: translateY() on hover
  - box-shadow with blur > 0 on hover
  - backdrop-filter on any app-level element
  - animation: fadeIn on tab-content (remove)
  - Any gradient on interactive elements (buttons, chips)
```

## 6. Component Rules

### Header
- Background: --s0, border-bottom: 1px solid --b0
- No backdrop-filter
- Logo: 36×36 px square, radius md, bg --s2, monogram text --t0 at 13px 700
- Nav tab active: bg --s2, left-border 2px solid --a0, color --t0
- Nav tab hover: bg --s2, color --t0
- No badge next to brand name

### Cards
- bg: --s1, border: 1px solid --b0, radius: md (6px), padding: 24px
- No backdrop-filter, no rgba bg, no colored borders

### Buttons
- btn-primary: bg --a0, hover bg --a1, color #fff, radius md
- btn-secondary: bg transparent, border 1px solid --b1, hover border-color --a0, radius md
- btn-danger: bg transparent, border 1px solid --er0 at 50% opacity, color --er0, radius md
- btn-sm: padding 6px 12px, font-size 12px
- btn-lg: padding 12px 20px, font-size 14px
- NO gradient backgrounds on any button
- NO box-shadow on any button

### Inputs
- bg --s2, border 1px solid --b0, color --t0, radius md
- focus: border-color --a0, outline 2px solid --a0 offset 1px
- placeholder color --t2

### Status States (pipeline steps)
- working: border-left 2px solid --a0, bg --a2
- success: border-left 2px solid --ok0, bg --ok1
- error: border-left 2px solid --er0, bg --er1
- NO colored glow box-shadow

### Pills / Chips
- matched: bg --ok1, color --ok0, border none, radius sm
- missing: bg --s2, color --t1, border 1px solid --b0, radius sm
- missing:hover: border-color --a0, color --t0
- missing.selected: bg --a2, color --a0, border-color --a0
- NO transform on chip hover

### Terminal
- bg: --s3, color --t1, mono font
- Keep as-is, already clean

### Modal
- overlay: rgba(0,0,0,0.7), NO backdrop-filter
- card: bg --s1, border 1px solid --b0, radius lg

### ATS Matrix Card (light surface — do not invert)
- bg: --mx-bg (#fff), color --mx-t0
- All borders use --mx-b0
- Focus rings use --a0
- No rgba background hacks
