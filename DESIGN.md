---
name: Taro's Label Room
description: A compact dark interface for designing labels and operating shared printers.
colors:
  surface-deepest: "#030712"
  surface-dense: "#111827"
  surface: "#1f2937"
  surface-secondary: "#374151"
  border-strong: "#4b5563"
  muted: "#9ca3af"
  text-secondary: "#d1d5db"
  text-label: "#f3f4f6"
  ink: "#ffffff"
  accent: "#4f46e5"
  accent-button-hover: "#4338ca"
  accent-hover: "#818cf8"
  link-hover: "#a5b4fc"
  danger: "#ef4444"
  danger-text: "#f87171"
  success: "#22c55e"
  success-text: "#4ade80"
  progress: "#16a34a"
  overlay: "rgb(255 255 255 / 5%)"
  line: "rgb(255 255 255 / 10%)"
  line-strong: "rgb(255 255 255 / 25%)"
  danger-fill: "rgb(239 68 68 / 10%)"
  danger-border: "rgb(239 68 68 / 30%)"
  success-fill: "rgb(34 197 94 / 10%)"
  success-border: "rgb(34 197 94 / 30%)"
  accent-fill: "rgb(99 102 241 / 10%)"
typography:
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  page-title:
    fontSize: "31px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-1.1px"
  section-title:
    fontSize: "17px"
    fontWeight: 650
    letterSpacing: "-0.25px"
  label:
    fontSize: "13px"
    fontWeight: 600
  small:
    fontSize: "12px"
rounded:
  badge: "5px"
  control: "6px"
  panel: "8px"
  avatar: "12px"
spacing:
  icon-gap: "8px"
  action-gap: "10px"
  compact-stack: "12px"
  field-gap: "16px"
  form-gap: "20px"
  panel-padding: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.accent-button-hover}"
  button-secondary:
    backgroundColor: "{colors.surface-secondary}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "42px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
    padding: "24px"
---

## Overview

This document extracts the implemented design language; it does not propose a
redesign. The interface is dark, compact and operational. Neutral surfaces carry
the work, indigo identifies actions and selections, and status colors explain
printer and queue state. Label previews remain the visual focus of design work.

Scope: the main web application and companion touchscreen interface. Extracted
on 2026-11-10 from the current working tree, including the unpublished cartridge
layout and companion feedback fixes. Those behaviors are not yet in the published
0.13.0 release.

Implementation references:

- [Shared styles](frontend/src/style.css): palette, typography, controls and layout.
- [Motion styles](frontend/src/motion.css) and
  [preferences](frontend/src/shared/preferences.ts): transitions and reduced motion.
- [Application shell](frontend/src/App.vue) and
  [companion interface](frontend/src/CompanionApp.vue): navigation and station layout.
- [Components](frontend/src/components): reusable interaction patterns.
- [AGENTS.md](AGENTS.md) and [README.md](README.md): project requirements and product context.

Use the existing CSS variables and components in implementation. The frontmatter
records shared values; its spacing and radius names describe observed usage, not
new CSS variables. Scoped component overrides still apply. Update this document
when deliberately changing the shared system.

## Colors

The shared palette has one primary accent and a layered neutral foundation.
There is no separate light theme in the current shared stylesheet.

| Role | Existing CSS token | Application |
| --- | --- | --- |
| Page background | `--surface-dense` | Main canvas behind panels; inset surfaces |
| Raised surface | `--surface` | Sidebar, panels and form controls |
| Control surface | `--surface-secondary` | Secondary buttons, compact controls and counts |
| Deep selection | `--surface-deepest` | Selected navigation and avatar backgrounds |
| Main text | `--ink` | Headings, values and button text |
| Labels and secondary text | `--text-label`, `--text-secondary` | Field labels, navigation and metadata |
| Supporting text | `--muted` | Descriptions, small text and placeholders |
| Primary action | `--accent` | Filled primary buttons and selected text |
| Interactive text and focus | `--accent-hover` | Links, text buttons, selected icons and focus outlines |
| Link hover | `--link-hover` | Brighter hover treatment for interactive text |
| Separators | `--line`, `--line-strong` | Subtle boundaries and emphasized control borders |
| Hover wash | `--overlay` | Neutral hover and badge fills |

Success uses green; errors, failed work and destructive actions use red. Printing
uses an indigo-tinted badge. Queued and pending states use neutral badges. Pair
color with text or an icon: a dot alone must not explain an operational state.
Use the brighter status text tokens on dark surfaces rather than substituting
the stronger fill colors for text.

## Typography

The UI uses the font stack in the frontmatter. Inter is preferred when available;
the system fallbacks are part of the implementation. Form controls inherit it.
Fonts selected for printed label artwork are separate from interface typography.

- Page headings lead the hierarchy; below 600px they reduce to 27px.
- Section headings are compact rather than display-sized. Third-level headings
  use 16px. Large numeric metrics are an existing dashboard pattern, not a
  replacement for ordinary field values.
- Labels sit above inputs with a 7px gap. Supporting text is quieter and smaller.
- Below 850px, input, select and textarea text increases to 16px.
- Long headings and resource names wrap. Do not let names squeeze action buttons
  out of their container or force page-wide horizontal scrolling.
- Existing resource metadata sometimes uses a small, tracked eyebrow. Preserve
  its informational purpose; do not add redundant subtitles or decorative labels.

## Layout

Desktop navigation is a fixed left sidebar (242px); content offsets by the same
amount. The main content region is centered with a maximum width of 1470px and
default padding of 36px 42px 20px. A page header separates its title from global
print shortcuts with a 20px gap. New label and New CSV run use secondary buttons
inside a rounded surface panel; page-specific create actions remain in the page
content. At 600px and below, the shortcut panel occupies its own row. Hide the
shortcut for the creation form already open, and show the panel only to users
with print-submission permission.

| Breakpoint | Shared adaptation |
| --- | --- |
| At least 1600px | Main top padding becomes 48px; panels use 28px padding |
| At most 1150px | Sidebar narrows to 205px; main padding becomes 28px 24px; panels use 20px |
| At most 850px | Sidebar becomes a top header. Navigation shows a row only when its translated links and counts fit; otherwise the current section and Menu button open an animated vertical list. Main padding becomes 26px 20px; general two-column content stacks |
| At most 600px | Page headers wrap; dashboard statistics stack; compact layouts reduce spacing |

These are shared-shell breakpoints. Editors, dialogs and station components have
their own content-driven rules; reuse them rather than assuming every grid
changes at the same width.

**Keep clearance in the layout.** Related actions use the shared row gap (10px).
Forms use a 20px vertical stack and 16px field gaps. Panels normally use 24px
padding, and repeated resource cards use 20px gaps. Allow rows to wrap and give
grid children `min-width: 0` where content can shrink. Focus outlines need room
outside their controls, including inside scrollable containers.

Cards with optional content must grow naturally. The cartridge view uses a
vertical flex layout with 12px gaps and actions pushed toward the bottom. Do not
reintroduce a fixed row count that cannot accommodate notes, warnings or forms.
Deletion explanations belong after the action group, clear of every button.

The companion is tuned for a 1024 × 600 touchscreen as well as smaller screens.
Its shell has a 1280px maximum width and 16px 20px 64px padding; the bottom space
reserves room for connection status. Printer cards use two columns, becoming
one on narrow screens. The lock state/countdown stays in the header. Unlock
actions are centered, at least 160px wide and 44px high. User selection uses
compact horizontal avatar/name tiles before showing PIN controls. The keypad
and unlock action fit together on the 1024 × 600 screen.

## Elevation & Depth

Depth comes mainly from differences between dark surfaces, fine borders and
restrained shadows. Shared panels have a 1px separator-colored border and a
small shadow (`0 2px 3px rgb(0 0 0 / 20%)`). This combination is established
project styling, not a reason to introduce stronger shadows everywhere.

Printed label samples use a more visible shadow (`0 7px 13px` with the same
shadow color), distinguishing the physical artifact from the surrounding editor.
Dialogs use a backdrop and a small entry movement to establish foreground focus.
Keep this hierarchy; avoid adding unrelated floating layers or decorative blur.

## Shapes

Controls have modest rounded corners, panels slightly softer ones, and companion
tiles/avatars more pronounced rounding. Shared radii are recorded above; not
every local component uses the same radius.

Avatars are **rounded squares**, never circles. `UserAvatar` defaults to 64px
square with a 12px radius and cover-cropped artwork; consuming views may resize
it. A missing or failed image falls back to the username's first letter. Circular
status dots are a separate, existing convention.

Use the existing Heroicons SVG icon family for controls and navigation. Common
sizes range from 16px to 24px. Preserve the surrounding stroke style and use
accessible names for icon-only actions; decorative icons are hidden from
assistive technology.

## Components

Group funding follows the administration page's section navigation, compact
mobile section picker, plain record lists and focused `AdminDialog` forms.
Funding decisions show their authorized label preview inside the dialog.
Keep account selection separate from section navigation and preserve drafts
when switching sections.

Template preview inputs use an animated disclosure. The canvas keeps its own
44px previous/next example controls and shows the current example name at the
top right, even while the input section is collapsed. Template-picker cards use
color feedback on press: transforming their title button would shrink the
whole-card click area while the pointer is held down.

| Pattern | Appearance and behavior | Reuse |
| --- | --- | --- |
| Primary action | Indigo fill, white semibold text, darker indigo hover | `.primary` on a button or `.button` link |
| Secondary action | Neutral filled control with a subtle border | `.secondary` |
| Inline action | Indigo text, transparent background; red text for destructive actions | `.text-button`, `.danger-text` |
| Form | Above-field labels, full-width controls, local errors and a validation summary | `.form-stack`, `.field-row`, `vValidateForm`, `VariableInput` |
| Disclosure | Rotating chevron and animated content expansion/collapse | `AnimatedDetails`, `ExpandableContent` |
| Dialog | Protected focus, keyboard dismissal where allowed, focus restoration | `AdminDialog`, `ConfirmDialog` and existing native-dialog patterns |
| Navigation/selection | One moving selection marker, persistent shell | `MotionTrack` |
| Selected editor content | Directional arrival without discarding unsaved field state | `MotionSurface` |
| Changing collections | Items enter, move and leave while neighbors settle | `TransitionGroup` with `collection` and `freezeLeavingItem` |
| Feedback | Semantic color, concise copy, animated arrival and removal | `.alert`, Vue `notice` transition |
| Identity | Uploaded image or initial in a rounded square | `UserAvatar` |

Disabled controls use reduced opacity (0.45) and a not-allowed cursor. Preserve
disabled reasons when they explain a non-obvious restriction. Keyboard focus uses
a 3px indigo outline offset by 3px. Mobile navigation and card text actions have
44px minimum-height targets; checkbox target wrappers are 44px square.

Use `SettingHelp` for requested, contextual explanations of settings. Its circled
information icon sits beside the label, outside the label's interactive control.
Explain what the setting changes and distinguish closely related settings when
needed; keep this detail in the tooltip instead of adding permanent paragraphs.
Help opens on hover, keyboard focus or tap, and dismisses with Escape, another
tap or an outside interaction. Tooltips use the shared notice motion, remain
within the viewport and escape scrolling-panel clipping. Touch targets are 44px.

**Use the shared motion vocabulary.** The default timing tokens are:

| Token | Duration | Main purpose |
| --- | --- | --- |
| `--motion-press` | 100ms | Press response |
| `--motion-fast` | 140ms | Hover/color feedback |
| `--motion-state` | 180ms | State changes and disclosure details |
| `--motion-enter` | 240ms | Panel/dialog arrival |
| `--motion-exit` | 100ms | Fast departure |
| `--motion-page` | 320ms | Page and collection movement |

Movement uses `--motion-ease: cubic-bezier(0.16, 1, 0.3, 1)`; opacity/color
transitions also use the existing ease-out rules. Buttons compress slightly
on press (scale 0.98). Pages slide in navigation order while the shell stays put.
Disclosures retain their content until the closing animation ends. Polling must
not replay arrivals, reset form input or animate the editor canvas away from the
pointer. Both CSS and JavaScript use the shared reduced-motion preference.

Companion success messages dismiss after five seconds through the existing notice
transition. Errors remain visible; connection state and the lock indicator are
persistent operational information. This describes the current unpublished fix.

The shared `SourceLink` component exposes source access and an AGPL license download.
Keep it available on sign-in/recovery screens and in both application footers.
On the companion, source links sit on the left, connection status stays centered,
and version and credit sit on the right. Equal outer grid columns keep status
centered regardless of the side content. Below 800px, status has its own centered
row above the links and credit. Reserve enough shell padding for the footer and
keep interactive links outside the live status region.

## Do's and Don'ts

- Reuse shared styles and components before adding another variant.
- Keep copy concise; explain restrictions, destructive actions and genuinely
  non-obvious behavior, not familiar controls.
- Keep controls, focus rings, messages and expanded content visibly separated.
- Verify opening **and** closing, keyboard focus, long names, permission-limited
  states, disabled actions and reduced motion.
- Check narrow mobile layouts and the companion's 1024 × 600 touchscreen size.
- Treat label artwork as output content, not as part of the application's palette.
- Do not replace rounded-square avatars with circular ones.
- Do not use fixed heights or fixed row counts that make dynamic content overlap.
- Do not add new animation timings or abrupt conditional UI beside animated patterns.
- Do not claim accessibility compliance from these tokens alone; inspect actual
  contrast, focus visibility, semantics and interaction in the rendered state.
