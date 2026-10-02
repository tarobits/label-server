# L's Zone Color Scheme

## Design concept

L's Zone uses a dark, low-distraction workspace palette. Charcoal surfaces keep attention on personal tools and data, while indigo supplies a consistent interactive accent. White and cool gray text create a clear reading hierarchy without introducing a second dominant hue. Red and green are reserved for meaning: risk, deletion, errors, and unverified states use red; successful verification and progress use green.

The overall effect is a compact utility interface with a quiet technical character. Semi-transparent white overlays and borders add separation to the dark surfaces without turning every section into a heavy card.

## Core palette

The values below are the Tailwind CSS color tokens currently used throughout the Vue components.

| Role | Tailwind token | Hex value | Usage |
| --- | --- | --- | --- |
| Deepest surface | `gray-950` | `#030712` | Active navigation background and the darkest selected states |
| Primary dark surface | `gray-900` | `#111827` | Footer, message board, data groups, and dense content regions |
| Main surface | `gray-800` | `#1f2937` | Navigation, page headers, sidebar panels, forms, and content shells |
| Secondary surface | `gray-700` | `#374151` | Modal surfaces and neutral action buttons |
| Surface border | `gray-600` | `#4b5563` | Modal borders and other stronger neutral boundaries |
| Muted text | `gray-500` | `#6b7280` | Secondary copy, placeholders, and subdued metadata |
| Supporting text | `gray-400` | `#9ca3af` | Descriptions, timestamps, footer text, and inactive controls |
| Navigation text | `gray-300` | `#d1d5db` | Inactive navigation and menu items |
| Form labels | `gray-100` | `#f3f4f6` | High-contrast labels on dark forms |
| Primary text | `white` | `#ffffff` | Headings, values, body copy, and text on colored controls |

## Semantic accents

| Meaning | Default | Hover or related states | Usage |
| --- | --- | --- | --- |
| Primary action | `indigo-500` `#6366f1` | `indigo-400` `#818cf8` | Save, upload, authentication, and other primary buttons |
| Compact action | `indigo-600` `#4f46e5` | `indigo-700` `#4338ca` | Inline add/send controls and compact actions |
| Interactive text | `indigo-400` `#818cf8` | `indigo-300` `#a5b4fc` | Links, upload prompts, and focus-visible outlines |
| Destructive action | `red-500` `#ef4444` | `red-400` `#f87171` | Delete and other irreversible actions |
| Error or warning | `red-500` `#ef4444` | `red-400` `#f87171` | Validation messages and unverified account states |
| Destructive icon | `red-600` `#dc2626` | `red-400` `#f87171` | Delete icons and negative table status |
| Positive status | `green-500` `#22c55e` | `green-400` `#4ade80` | Verified account states and successful status icons |
| Progress indicator | `green-600` `#16a34a` | N/A | Salary goal progress bars |

## Transparency and layering

The design uses opacity modifiers to preserve the dark foundation while adding depth:

- `bg-gray-800/50` creates translucent navigation and header bands.
- `bg-gray-900/50` groups related salary data while keeping the parent surface visible.
- `bg-white/5` is used for form controls, inactive hover states, and subtle selected surfaces.
- `border-white/10` and `outline-white/10` provide low-contrast boundaries for panels and inputs.
- `border-white/25` marks the upload drop zone with a more visible dashed boundary.
- `bg-gray-700/50` dims the page behind confirmation modals.
- `bg-[#ffffff00]`, `bg-[#ffffff22]`, `border-[#ffffff44]`, and `border-[#ffffff66]` create transparent notification actions with restrained hover feedback.

These alpha layers are intentionally white rather than additional colored surfaces, so the same components remain visually coherent across the gray-800 and gray-900 regions.

## Application guidance

- Keep large surfaces in the gray family and use indigo sparingly for actions and navigation links.
- Use white for primary information, gray-300/400 for supporting information, and gray-500 for metadata or placeholders.
- Reserve red for a real error, warning, or destructive action; do not use it as a general accent.
- Reserve green for positive state or progress; it should communicate completion rather than decoration.
- Preserve the existing opacity-based borders and controls when adding new panels so the interface keeps its lightweight layering.
- Pair colored controls with white text and a visible focus outline for keyboard accessibility.
