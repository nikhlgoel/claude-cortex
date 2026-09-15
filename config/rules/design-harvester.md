# AI Design Harvester & Website Reverse-Engineering Protocol

## 1. Capabilities & Core Architecture
You have direct access to the **AI Design Harvester Engine 2.0** located at:
`C:\Claude\Tools\design-harvester`

This engine uses a stealth headless browser to bypass bot detection, auto-scrolls down live websites to trigger dynamic IntersectionObserver lazy loading, and deep-inspects computed styles directly in the DOM.

It generates:
1. `DESIGN-SPEC.md`: Complete master design system specification (typography, colors, contrast, components).
2. `design-tokens.json`: Structured token tree for Tailwind, CSS, or Figma.
3. `tailwind.theme.js`: Drop-in Tailwind theme configuration.
4. `tokens.css`: Pure CSS custom properties for light and dark themes.
5. `flutter_theme.dart`: Drop-in Flutter ThemeData with ColorScheme and widget themes.
6. `components.tsx`: Production-grade React + Tailwind components.
7. `screenshot-desktop.png` & `screenshot-mobile.png`: High-resolution visual screenshots.

---

## 2. How to Execute

### Option A: Native MCP Tool (When in Claude Desktop or Claude Code)
Call the `harvest_design_system` tool directly:
```json
{
  "url": "https://antigravity.google"
}
```
Claude will receive the complete extracted tokens, component blueprints, and spec in real time.

### Option B: Terminal Command Execution
If running via terminal or bash:
```bash
node C:\Claude\Tools\design-harvester\harvest.js <URL> [OUTPUT_DIR]
```
Example:
```bash
node C:\Claude\Tools\design-harvester\harvest.js https://antigravity.google C:\Claude\Shared\Harvested-Designs\antigravity
```

---

## 3. Downstream Workflow: Recreating World-Class Designs
Once the design system has been harvested:
1. **Read Tokens:** Review the generated `DESIGN-SPEC.md` or `design-tokens.json`.
2. **Apply Typography:** Bind the exact heading sizes, font families, letter-spacing, and line heights.
3. **Apply Color Hierarchy:** Match the primary surface, card surface, and accent tokens with WCAG-compliant contrast.
4. **Build Production Screens:** Generate new screens, pages, or components using the extracted design tokens rather than generic AI defaults.
