# Interface colors

The UI uses dark gray surfaces, indigo actions, and red/green status colors.
CSS variables in [frontend/src/style.css](frontend/src/style.css) define the palette;
use them in components instead of adding color literals. Tape previews and swatches
use the selected tape profile's colors.

## Palette

| CSS variable | Value | Use |
| --- | --- | --- |
| `--surface-deepest` | `#030712` | Selected navigation and inputs |
| `--surface-dense` | `#111827` | Page background and dense regions |
| `--surface` | `#1f2937` | Panels, headers, and sidebar |
| `--surface-secondary` | `#374151` | Neutral buttons and dialogs |
| `--border-strong` | `#4b5563` | Stronger boundaries |
| `--ink` | `#ffffff` | Main text |
| `--text-label` | `#f3f4f6` | Form labels |
| `--text-secondary` | `#d1d5db` | Supporting text |
| `--muted` | `#9ca3af` | Descriptions and metadata |
| `--placeholder` | `#6b7280` | Placeholders |
| `--accent` / `--accent-hover` | `#6366f1` / `#818cf8` | Primary actions |
| `--link-hover` | `#a5b4fc` | Link hover |
| `--accent-compact` / `--accent-compact-hover` | `#4f46e5` / `#4338ca` | Compact actions |
| `--danger` / `--danger-text` | `#ef4444` / `#f87171` | Errors and destructive actions |
| `--success` / `--success-text` | `#22c55e` / `#4ade80` | Successful states |
| `--progress` | `#16a34a` | Progress |
| `--overlay` | White at 5% | Subtle fills |
| `--line` / `--line-strong` | White at 10% / 25% | Borders and outlines |

## Usage

Keep large surfaces gray. Use indigo for actions and links, red for errors or
removal, and green for successful states. Pair status colors with text or icons.
Maintain visible keyboard focus and readable text on every surface.

Use the existing opacity variables for fills and boundaries. The stylesheet also
provides tinted danger, success, and accent fills. See
[FIGMA_COLOR_SCHEME.md](FIGMA_COLOR_SCHEME.md) for design-file style names.
