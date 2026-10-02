# L's Zone Figma Color Handoff

This handoff translates the implemented palette into Figma-friendly styles and frames. Use the existing [COLOR_SCHEME.md](./COLOR_SCHEME.md) for the broader rationale and code-level Tailwind usage.

## Concept

**Quiet utility, focused signal.** L's Zone is a personal workspace rather than a promotional surface. Deep charcoal frames create a calm working field; cool white text carries the information; indigo marks the next useful action. Red and green are semantic signals only, so they retain meaning when the interface becomes dense.

The visual language should feel like a tidy dark-mode canvas: restrained contrast between neighboring surfaces, thin white-alpha boundaries, compact controls, and a few deliberate color signals.

## Figma file setup

- **Page:** `L's Zone / Design System`
- **Reference frame:** `Desktop / 1440 x 1024`
- **Mobile frame:** `Mobile / 390 x 844`
- **Canvas background:** `#0b0f19` (a documentation-only canvas color; product surfaces remain Tailwind gray)
- **Grid:** 8 px; use 4 px for icon and optical adjustments
- **Corner radius:** 6 px for controls, 8 px for panels, and 4 px for compact data rows
- **Spacing:** 8, 12, 16, 24, 32, 40, 48 px

## Color styles

Create local Figma color styles with these names. Opacity belongs in the style name when it is part of the behavior.

| Figma style | Value | Purpose |
| --- | --- | --- |
| `Surface / Deepest` | `#030712` | Selected navigation and deepest content regions |
| `Surface / Primary` | `#1f2937` | Main page shells, headers, and panels |
| `Surface / Secondary` | `#374151` | Modals and neutral buttons |
| `Surface / Dense` | `#111827` | Footer, message board, and data groups |
| `Border / Subtle` | `#ffffff` at 10% | Panel boundaries and form outlines |
| `Border / Dropzone` | `#ffffff` at 25% | Upload drop zone boundary |
| `Text / Primary` | `#ffffff` | Headings, values, and control labels |
| `Text / Secondary` | `#d1d5db` | Supporting navigation and menu labels |
| `Text / Muted` | `#9ca3af` | Descriptions, metadata, and timestamps |
| `Text / Placeholder` | `#6b7280` | Placeholder and lowest-emphasis copy |
| `Action / Primary` | `#6366f1` | Main buttons and committed actions |
| `Action / Hover` | `#818cf8` | Hover, link, and focus emphasis |
| `Action / Compact` | `#4f46e5` | Inline add/send controls |
| `Status / Danger` | `#ef4444` | Errors, deletion, and unverified states |
| `Status / Success` | `#22c55e` | Verification and positive status |
| `Status / Progress` | `#16a34a` | Salary goal progress bars |

## Type styles

Use the product's existing compact hierarchy. Keep text white or cool gray rather than introducing a new text color.

| Figma style | Suggested size / line height | Usage |
| --- | --- | --- |
| `Type / Page title` | 30 / 36, bold | Layout titles and major page headings |
| `Type / Section title` | 24 / 32, bold | Feature headings and primary forms |
| `Type / Body` | 16 / 24, regular | Main values and explanatory copy |
| `Type / Label` | 14 / 20, medium | Field labels and navigation |
| `Type / Metadata` | 14 / 20, regular | Dates, helper copy, and footer content |
| `Type / Compact` | 12 / 16, regular | Dense table and status details |

## Component frames

Build these as named auto-layout components in a `Components` section:

- `Button / Primary / Default`, `Hover`, `Focus`, `Disabled`
- `Button / Danger / Default`, `Hover`, `Focus`
- `Input / Default`, `Focus`, `Error`
- `Navigation / Desktop`, `Navigation / Mobile`
- `Panel / Standard`, `Panel / Dense`
- `Status / Success`, `Status / Error`, `Status / Unverified`
- `Modal / Confirmation`

Primary buttons use `Action / Primary` with white labels. Destructive buttons use `Status / Danger`. Inputs use `Surface / Deepest` or 5% white fill, a 10% white outline, and an indigo focus ring. Error inputs replace the outline with `Status / Danger`.

## Suggested board layout

Arrange the reference page as four frames from left to right:

1. **Principles:** the concept statement and three rules: quiet surfaces, focused signal, meaningful status.
2. **Palette:** grouped swatches for surfaces, text, actions, and semantic states.
3. **Components:** button, input, panel, navigation, and modal states.
4. **Application:** a small salary workspace example showing how the palette behaves in context.

Use labels above each frame, 24 px frame padding, and generous empty canvas between groups. The board should explain the system through examples rather than through decoration.

## Review checklist

- Indigo is used for action and navigation, not as a page-wide wash.
- Red and green communicate state and are not interchangeable decoration.
- Primary text remains readable on every product surface.
- Focus states are visible without relying on color alone.
- The darkest surfaces separate dense data from the main panel without adding visual noise.
