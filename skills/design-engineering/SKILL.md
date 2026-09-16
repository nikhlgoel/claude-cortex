---
name: design-engineering
description: UI/UX implementation standards: surface layering, typography rhythm, micro-interactions, tactile states. Use when generating or reviewing interface code.
---

﻿# Senior Design Engineer: UI/UX Aesthetic & Anti-AI-Slop Standards

This rule applies automatically whenever generating, styling, or reviewing UI code (Web, Mobile/Flutter, Desktop).
Never produce generic "AI template" aesthetics. Enforce modern, premium, tactile design engineering by default.


## 2. Visual Hierarchy & Surface Architecture

- **Surface Layering**:
  - Base: `bg-neutral-50` (or `dark:bg-neutral-950`).
  - Card/Container: `bg-white` (or `dark:bg-neutral-900`) with a fine, translucent border (`border border-neutral-200/80 dark:border-neutral-800`).
  - Elevated / Popovers / Modals: `bg-white dark:bg-neutral-850 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.1)]`.
- **Typography Rhythms**:
  - Headings: Bold weights (`font-semibold` / `font-bold`), tighter letter-spacing (`tracking-tight` or `-0.02em`), compact line-height (`leading-tight`).
  - Body: Regular weight, relaxed line-height (`leading-relaxed`), clear contrast.
  - Paired Fonts: Prefer modern humanist/geometric sans (Geist, Inter, Plus Jakarta Sans, DM Sans).
- **Spatial Rhythm**:
  - Use a strict 4px/8px grid. Generous internal padding (`p-4`, `p-6`) with tight gap groupings (`gap-1.5` for label+input, `gap-4` for sections).
  - High information density with clear visual anchors (tags, status dots, metric badges).


## 4. Mobile / Flutter Standards (e.g., Mioryde Apps)

- **Haptics**: Always trigger `HapticFeedback.lightImpact()` on key button taps, status toggles, and selection pills.
- **Sheets & Drawers**: Use modern rounded top corners (`BorderRadius.vertical(top: Radius.circular(24))`) with a visual drag handle (`Container(width: 36, height: 4, decoration: ...)`).
- **Animations**: Prefer fluid transitions and declarative spring animations (`flutter_animate` style: `.animate().fade(duration: 200.ms).slideY(begin: 0.1, end: 0)`).
- **Clean Iconography**: Use standard Lucide/Phosphor geometry with consistent stroke widths (1.5px or 2px).

