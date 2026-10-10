# Figma styles

Use [COLOR_SCHEME.md](COLOR_SCHEME.md) and `frontend/src/style.css` as the palette
reference for Label Printer Server.

## File setup

- Page: `Label Printer Server / Design System`
- Reference frames: desktop 1440 × 1024; mobile 390 × 844
- Canvas background: `#111827`
- Grid: 8 px; 4 px for small adjustments
- Corner radii: 6 px controls, 8 px panels, 4 px compact rows
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
| `Text / Placeholder` | `#6b7280` | Placeholders |
| `Action / Primary` | `#6366f1` | Primary buttons |
| `Action / Hover` | `#818cf8` | Hover, links, and focus |
| `Action / Compact` | `#4f46e5` | Compact actions |
| `Status / Danger` | `#ef4444` | Errors and destructive actions |
| `Status / Success` | `#22c55e` | Successful states |
| `Status / Progress` | `#16a34a` | Progress |

## Type styles

| Figma style | Size / line height | Use |
| --- | --- | --- |
| `Type / Page title` | 30 / 36, bold | Page headings |
| `Type / Section title` | 24 / 32, bold | Section headings |
| `Type / Body` | 16 / 24, regular | Body copy |
| `Type / Label` | 14 / 20, medium | Labels and navigation |
| `Type / Metadata` | 14 / 20, regular | Dates and helper text |
| `Type / Compact` | 12 / 16, regular | Dense status details |

## Components

Create button, input, navigation, panel, status, and confirmation-dialog components.
Include default, hover, focus, disabled, and error states where applicable.

Use white labels on primary and destructive buttons. Inputs use the deepest
surface or a 5% white fill, a subtle outline, and visible indigo focus. Error
outlines use the danger color. Pair status colors with labels or icons.

Organize the reference board into palette, typography, component states, and
application examples. Use queue, printer-card, and editor examples to check the
styles in context.
