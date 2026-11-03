# Figma styles

Use [COLOR_SCHEME.md](COLOR_SCHEME.md) and `frontend/src/style.css` as the palette
reference for Taro's Label Room. The stylesheet is authoritative when design-file
styles differ from the interface.

## File setup

- Page: `Taro's Label Room / Design System`
- Reference frames: desktop 1440 × 1024; mobile 390 × 844
- Canvas background: `#111827`
- Grid: 8 px; 4 px for small adjustments
- Corner radii: 6 px controls, 8 px panels, 12 px dialogs, 4 px compact rows
- Spacing: 8, 12, 16, 24, 32, 40, 48 px

## Color styles

| Figma style | Value | Use |
| --- | --- | --- |
| `Surface / Deepest` | `#030712` | Selected navigation and inputs |
| `Surface / Primary` | `#1f2937` | Panels and headers |
| `Surface / Secondary` | `#374151` | Neutral buttons and dialogs |
| `Surface / Dense` | `#111827` | Page background and dense regions |
| `Border / Subtle` | White at 10% | Panel and input outlines |
| `Border / Strong` | White at 25% | Emphasized boundaries |
| `Text / Primary` | `#ffffff` | Main text |
| `Text / Label` | `#f3f4f6` | Form labels |
| `Text / Secondary` | `#d1d5db` | Supporting text |
| `Text / Muted` | `#9ca3af` | Descriptions and metadata |
| `Text / Placeholder` | `#9ca3af` | Placeholders |
| `Action / Primary` | `#4f46e5` | Primary buttons |
| `Action / Button hover` | `#4338ca` | Primary button hover |
| `Action / Link and focus` | `#818cf8` | Links and focus |
| `Action / Compact` | `#4f46e5` | Compact actions |
| `Status / Danger` | `#ef4444` | Errors and destructive actions |
| `Status / Success` | `#22c55e` | Successful states |
| `Status / Progress` | `#16a34a` | Progress |

## Type styles

Use the shared stylesheet's base sizes; individual components may override them.

| Figma style | Size / line height | Use |
| --- | --- | --- |
| `Type / Page title` | 31 / 37.2, weight 650 | Page headings |
| `Type / Section title` | 17 / 25.5, weight 650 | Section headings |
| `Type / Body` | 14 / 21, regular | Body copy |
| `Type / Label` | 13 / 19.5, weight 600 | Form labels |
| `Type / Metadata` | 12 / 18, regular | Shared small text |

## Components

Create button, input, navigation, panel, status, and confirmation-dialog components.
Include default, hover, focus, disabled, and error states where applicable.

Use white labels on primary and destructive buttons. Inputs use the deepest
surface or a 5% white fill, a subtle outline, and visible indigo focus. Error
outlines use the danger color. Pair status colors with labels or icons.

Organize the reference board into palette, typography, component states, and
application examples. Use queue, printer-card, and editor examples to check the
styles in context.
