# Senior Design Engineer: UI/UX Aesthetic & Anti-AI-Slop Standards

This rule applies automatically whenever generating, styling, or reviewing UI code (Web, Mobile/Flutter, Desktop).
Never produce generic "AI template" aesthetics. Enforce modern, premium, tactile design engineering by default.

---

## 1. Absolute Bans (Eliminate "AI Slop")

- 🚫 **NO generic purple/indigo linear gradients** on primary buttons, badges, or hero backgrounds (`bg-gradient-to-r from-indigo-500 to-purple-600`).
- 🚫 **NO lonely floating cards** centered in vast, empty gray space.
- 🚫 **NO unstyled, low-contrast gray body text** (`text-gray-400` / `#9ca3af` on white). Use readable, deliberate slate/zinc values (`text-neutral-700 dark:text-neutral-300`).
- 🚫 **NO blunt, oversized box shadows** (`shadow-2xl` with 30px blur). Use subtle, crisp multi-layered micro-shadows.
- 🚫 **NO unstyled spinner wheels** as the only loading indicator. Always provide skeleton loaders or optimistic UI updates.
- 🚫 **NO lifeless static elements**. Every interactive button, card, and tab MUST have active, hover, and focus-visible states.

---

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

---

## 3. Micro-Interactions & Tactile Motion

- **Button States**:
  - Hover: Subtle brightness lift or micro-translate (`hover:-translate-y-0.5 transition-all duration-150`).
  - Active/Press: Tactile compression (`active:scale-[0.98] transition-transform duration-75`).
  - Focus: Clear outline with ring offset (`focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2`).
- **Transitions**:
  - Always specify property, duration, and curve: `transition-all duration-200 ease-out`. Never use jarring, instant state changes.

---

## 4. Mobile / Flutter Standards (e.g., Mioryde Apps)

- **Haptics**: Always trigger `HapticFeedback.lightImpact()` on key button taps, status toggles, and selection pills.
- **Sheets & Drawers**: Use modern rounded top corners (`BorderRadius.vertical(top: Radius.circular(24))`) with a visual drag handle (`Container(width: 36, height: 4, decoration: ...)`).
- **Animations**: Prefer fluid transitions and declarative spring animations (`flutter_animate` style: `.animate().fade(duration: 200.ms).slideY(begin: 0.1, end: 0)`).
- **Clean Iconography**: Use standard Lucide/Phosphor geometry with consistent stroke widths (1.5px or 2px).

---

## 5. Design Reference Benchmarks

Whenever designing UI, mentally benchmark against:
- **Linear.app** (dense, keyboard-first, refined micro-borders, purposeful monochrome + single vibrant accent).
- **Stripe Dashboard** (flawless data tables, clear metric cards, tabular typography, pristine alignment).
- **Apple HIG / Raycast** (deeply tactile, subtle glassmorphism, responsive spring curves).
- **Uber / Porter** (for logistics/ride apps: clear bottom drawers, high-contrast map pin badges, prominent ETA metrics).
