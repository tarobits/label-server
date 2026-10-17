# Implementation plan

## Current scope

Label Printer Server provides a visual editor, persistent queue, Brother PT-P710BT
USB printing, printer groups, CSV runs, REST integrations, and accounts with
approval workflows. These features are implemented. See [README.md](README.md)
for usage and [TODO.md](TODO.md) for remaining work.

Physical printer testing was reported successful on 2026-10-04. Docker image build
and isolated local runtime checks passed on 2026-10-17. The user accepted the
consumption baseline and stopping after the current label on 2026-10-17; no
repeat measurements or mid-label interruption are required. Simultaneous
two-device USB testing is deferred until a second printer is available.
Native VM service startup, health/frontend checks, application USB access,
physical printing, VM reboot, hold persistence and USB reconnect without a
service restart passed on 2026-10-17. The deployment uses a Python virtual
environment and systemd directly inside the Debian VM, with a Proxmox USB resource
mapping. Live HomeBox verification is deferred in favor of manual label creation
with the native editor. Additional printer drivers,
network printing, and native grayscale are not implemented. The documented
PT-P710BT raster protocol provides no native grayscale mode; use dithering.

## Architecture constraints

- Keep printer-specific protocols in adapters. Queue and domain code use generic
  status, rendering capabilities, consumption estimates, and print results.
- Run one server process per database, with one worker and hardware lock per
  physical printer. Use short shared database locks for reservations and mutations.
- Render immutable inputs outside the mutation lock. Recheck records, assets,
  capabilities, and authorization before saving; concurrent changes return a
  conflict rather than overwriting newer data.
- Store jobs, copies, attempts, flush requests, reminders, and notification delivery
  state durably. Apply schema migrations explicitly.
- Treat physical media widths as millimetres, including 3.5 mm tape. Wire codes
  belong only to adapters. Preserve frozen render geometry during migrations.

## Queue and recovery requirements

Count copies per destination and exact tape profile, rather than job records or
width alone. The default automatic threshold is 10. Printing requires the assigned
profile, a ready printer, and a known matching tape width. Cartridge assignment
identifies colors; printer status does not.

Freeze submitted inputs and rendering settings. Commit the batch's `printing`
state and copy membership before rendering or hardware writes. New arrivals wait
for another batch. Manual requests freeze their selection when accepted.

Automatic holds survive restarts and tape swaps. They allow manual printing and
do not interrupt reserved batches. Resuming rechecks thresholds immediately.
Moderator-selected printing holds the destination to leave unselected work queued;
Print-level users can select their own copies without holding others' work.

Per-device stop controls commit the hold and cancel pending manual intents before
signaling the hardware owner. Stop after current label requires direct Moderator;
emergency stop requires direct Full. Drivers consume stop intent at safe command
boundaries without concurrent transport writes. A cancellation request does not
guarantee a mid-label stop; physical PT-P710BT tests completed the current label.
Stopping after the current label is sufficient for the current scope.
Interrupted output goes through normal review; saving review preserves the hold.
Bulk review actions include the
selected copy and subsequent uncertain copies, leaving confirmed copies locked.
Standalone cutter capability is separate from automatic cuts and requires Full;
it remains unavailable on the PT-P710BT USB driver.

A guaranteed no-start failure returns copies to the queue. A confirmed prefix may
be marked printed; the uncertain remainder needs review. Other errors after the
adapter starts printing are uncertain. Restart recovery also sends in-flight
attempts to review. Never replay uncertain copies automatically.

Review requires a decision for every uncertain copy and total tape consumption
for the attempt. Confirmed copies cannot be changed. Cartridge estimates survive
swaps; manual printing warns before reserving copies when estimated consumption
exceeds remaining tape, with an explicit Print anyway override for all affected
printers. Automatic shortages retain their batch warning, and uncertain
consumption stays flagged until review. The measured feed and leader defaults
were accepted for the tested conditions; different settings need their own
physical validation before changing the estimates.

An installed cartridge with zero estimated remaining tape blocks automatic
reservation before raster preparation. Group routing skips empty members while
respecting CSV printer assignments. A durable depletion episode alerts
administrators once, independently of approval notification settings; stale
unsent alerts are cancelled after a swap or length correction. Correcting or
replacing tape restores eligibility without changing manual holds. Explicitly
acknowledged manual printing remains available.

Groups route to the first ready member with the exact profile and matching render
capabilities. CSV runs stay pinned to their first printer, including after review.
An interrupted device blocks only itself. See
[printer architecture](docs/PRINTER_ARCHITECTURE.md) for reservation and group rules.

## Editor and rendering requirements

Use a validated structured document as the editable source. Generate SVG and the
1-bit raster in the backend. Escape substituted field values and reject executable
templates, external rendering resources, and active SVG content.

The editor supports text, QR codes, shapes, images, visual and numeric geometry,
90° rotation, layers, alignment, duplication, snapping, undo/redo, and revisioned
saves. Warn before navigation with unsaved edits. Template changes must not alter
saved jobs or drafts.

Text uses shared backend fonts and metrics. Font size is a maximum; shrink to fit
while respecting wrapping and alignment. Padding is independent on all four sides.
Horizontal character spacing and vertical line spacing are saved in millimetres,
default to zero extra spacing, and participate in fitting and automatic width.
Accents and joined characters stay together; right-to-left runs retain native
shaping and character spacing.

Resolve text widths, then acyclic distance-holder links, then automatic label
length, then clipping. Gaps use rotated object bounds. Removing an anchor detaches
its direct followers at their current positions. Corner resizing preserves the
opposite corner at each supported rotation.

Automatic length stays within printer limits and preserves tape width. Clipping
omits outside content while keeping source objects editable. These options cannot
bypass required fields, QR module limits, or media constraints. New templates
use automatic length and clipping; existing documents keep their saved policy.

Pixel previews show the exact print raster at its physical aspect ratio. Smooth
previews use the same layout and fonts. Tape colors change display colors without
changing ink placement. QR codes retain their quiet zone and a minimum of two
device pixels per module, including when scaled to their bounding box.

Fonts and images have immutable content references and bounded uploads. Hiding
assets must preserve saved labels. Permanent image deletion checks templates,
historical revisions, jobs, and runs under the mutation lock. Dithering is
monochrome output; expose native grayscale only after verifying adapter support.

## CSV and integration requirements

CSV imports support quoted delimiters, multiline values, field mapping, selection,
record ordering, and copy counts. Validate all selected records before saving a
draft. Freeze values, template revision, assets, geometry, and rendering settings.
Show individual raster previews, run order, and estimated feed/cuts before submission.

Submission creates the entire run atomically and is idempotent. Preparation keys
reject changed input. Preparing a draft never prints; thresholds and holds apply
after submission. Preserve source-record identity and ordering through retries.

Single-job and image integrations use durable, actor-scoped idempotency keys.
Retries return the original frozen job; changed input returns a conflict.
Intentional reprints require new keys. HomeBox's temporary-file hook cannot
identify upstream retries that regenerate the file. See
[REST integrations](docs/INTEGRATIONS.md).

## Accounts and notifications

Follow [access control](docs/ACCESS_CONTROL.md): directly assigned roles, independent
template-group memberships, scoped moderation, protected administrator access,
confirmed access changes, and explicit release or cancellation of revoked-access
holds. Pending requests remain separate from executable jobs. Approval is
transactional and retry-safe.

Freeze requester, approver, batch starter, and hold-release attribution per event
and physical attempt. Account changes must not rewrite history. Administrator
submission of another user's draft preserves ownership and requires confirmation
when an authorization override is needed.

Notifications use a durable outbox independent of printing. Retry delivery without
retrying prints. Deduplicate repeated blockers until they clear. Waiting reminders
are optional per profile, with persistent interval, snooze, and episode silence.
Request summaries use a fixed window from the first arrival so continuous arrivals
cannot delay them indefinitely.

Manage ntfy endpoints in Administration with masked server-side tokens, selected
event types, printer/distribution-group scopes and per-type message priorities.
Remove role and minimum-access filters. Explicitly select all current and future
printers or snapshot only current physical printers with Select all. Groups remain
manually selectable and follow membership changes. No selected scope disables
and clears printer event types. Group channels include operational alerts from
their members. Approval summaries can be global or limited to selected logical
destinations. Topic subscriptions are configured separately in ntfy.
Fan out each event to all matching endpoints with independent durable delivery
attempts and retries. Endpoint changes cancel old pending deliveries; notification
configuration and delivery never alter print state. Preserve an existing legacy
environment channel once during migration only when the installation has accounts.

## Verification

Use isolated databases and test adapters for automated checks. Cover thresholds,
profile separation, frozen selection, holds, partial failures, restart recovery,
concurrent reservations, group routing, migrations, and notification retries.

Rendering checks compare preview and print pixels, decode QR output, and verify
frozen jobs after template edits. Browser tests cover design-to-queue, CSV drafts,
review, permissions, form persistence during polling, and mobile layouts.

Shared frontend state uses Pinia stores. Cache route-specific catalogs, coalesce
concurrent reads, invalidate affected resources after mutations, and discard stale
responses across session or access changes. Use one visibility-aware polling
scheduler; keep live queues/status fresh without repeatedly fetching every catalog.
Browser checks cover request counts, navigation reuse, mutation freshness, hidden
tabs, and delayed private responses during logout/login.

Hardware acceptance requires printed dimensions, QR scans, cut/feed behavior,
completion, interruption recovery, and measured tape use. Screen previews and
captured USB streams do not establish physical quality. Record results in
[hardware verification](docs/HARDWARE_VERIFICATION.md).
