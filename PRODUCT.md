# Taro's Label Room

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People creating and printing labels through this self-hosted installation.
Accounts can request printing, print directly, moderate queues and requests, or
administer printers and shared content according to their assigned permissions.
Specific audiences and the objects they label are not yet defined.

## Product Purpose

Design reusable labels, fill in variable values, and print individual labels or
ordered CSV runs through a persistent queue. Success means predictable physical
output, accurate previews, and clear control over queued and interrupted work.

## Operating Context

- The intended workflows are user-initiated label creation in the visual editor
  and CSV printing. External automation is outside the current intended workflow.
- The current installation has one Brother PT-P710BT USB printer. Future
  additional printers are part of the intended scope; do not assume a single
  printer in navigation, destinations, or queue management.
- Existing automatic batch thresholds, holds, and reminders remain supported
  queue features. User-initiated workflows do not imply removing those features.
- Users select a print destination and tape profile. Design destination controls
  editor geometry and is separate from the submission destination.
- The documented deployment is a native Python/systemd service in a Debian VM
  with USB passthrough. The browser is the product interface.

## Capabilities and Constraints

- Reusable, revisioned templates support text, QR codes, images, rectangles,
  lines, variable fields, physical dimensions in millimetres, and raster previews.
- CSV runs support field mapping, record selection, copy counts, ordering,
  validation, saved drafts, and explicit submission of the entire run.
- Persistent queues batch compatible copies by destination and exact tape
  profile. Printer groups can route work to compatible ready members.
- Submitted jobs and CSV drafts preserve their template, values, assets,
  geometry, and rendering settings independently of later edits.
- Interrupted or uncertain output requires human review and must never be
  retried automatically. Stop controls may allow the current label to finish.
- Tape consumption and remaining cartridge length are estimates. Manual printing
  can explicitly override a shortage warning.
- Currently implemented hardware support is Brother PT-P710BT over USB, with
  monochrome output and dithering. Additional printer models, network printing,
  and native grayscale are not implemented.
- Printer-specific protocols belong in adapters under `app/printer`; queue and
  domain layers use the generic printer contract.
- Run one server process per database. Preserve durable queue state, scoped
  permissions, approval boundaries, and historical attribution.
- Existing REST integrations are implemented but are not the primary workflow.

## Brand Commitments

- Product name: **Taro's Label Room**. Use this name in the interface and current
  product documentation.
- Keep UI copy concise and purposeful, following `AGENTS.md`. Assume familiarity
  with common controls and editor conventions. Explain only non-obvious behavior,
  destructive actions, safety limitations, or essential context.

## Evidence on Hand

- `README.md`: implemented workflows, limits, and setup instructions.
- `PLAN.md`: architecture and behavior that future work must preserve.
- `docs/ACCESS_CONTROL.md`: roles and destination permissions.
- `docs/HARDWARE_VERIFICATION.md`: physical printer verification and limitations.
- `TODO.md`: accepted scope and deferred hardware and integration checks.
- `frontend/src`: the existing Vue interface; this initialization does not
  establish a replacement visual direction.

## Product Principles

1. Keep manual label creation and CSV runs direct and predictable.
2. Make previews and saved submissions faithful to the eventual printed label.
3. Preserve human control when physical output is uncertain or irreversible.
4. Support growth to multiple printers without exposing protocol details.
5. Prefer intuitive controls and immediate feedback over explanatory UI copy.
