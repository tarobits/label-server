# Printer architecture and scope

Operational multi-printer support includes independent Brother PT-P710BT
USB printers and explicit printer-group destinations. Other printer models and
Wi-Fi/Ethernet drivers are not implemented. Accounts,
directly assigned roles, scoped moderation and revocation holds are integrated at
application boundaries; see [the access-control specification](ACCESS_CONTROL.md).

## Device and protocol boundaries

`app/printer/registry.py` separates stable device definitions, media/rendering
capabilities, connections and backend instances. Two identical models have
separate device IDs and USB serial numbers. `PrinterBackend` owns status,
rendered-label printing and consumption planning. USB commands and Brother status
packets stay inside adapters; queue and routing code contains no protocol bytes.

`NetworkConnection` still describes Wi-Fi/Ethernet endpoints and explicit
protocols for future drivers. Network transport, discovery, and Wi-Fi provisioning are not implemented.

## Persistent destinations

- `printers` stores every device registration and its driver configuration. A new
  installation has no devices. No printer is environment-owned or special at
  runtime. Existing physical printer settings are imported once during migration;
  their IDs remain stable. Legacy simulated registrations are retired and their
  historical references remain intact. Test adapters live outside the application.
- `printer_state` has a unique printer ID, installed cartridge, automatic hold
  and blocker. Existing state migrates to `main` without losing cartridge or hold.
- `printer_groups` stores a name, an ordered list of member IDs and a group hold.
  Groups require identical media, printable geometry and resolution capabilities.
  Align the printers' default resolution settings before grouping them.
- Jobs and CSV runs retain their submitted destination. Batches and manual flush
  requests record the actual printer. History identifies that physical printer.
- A cartridge may be installed in only one printer. Its length estimate follows
  the cartridge, including when moved between devices.

Register and edit all printers under **Printers & groups**. A lone USB printer
can use automatic discovery; multiple devices require distinct USB serials.
The form owns name, serial, resolution, feed, leader estimate, cutting and timeout.
Configuration changes require idle hardware and no affected queued work, pending
flush or saved draft. Group members must retain matching rendering capabilities.
Changes commit before the live adapter is replaced, without restarting the server.
The former `/settings` page redirects here.

## Routing and reservation

A submission chooses a printer or a group using `destination_id`,
plus a tape-profile ID. An omitted destination selects the sole configured printer;
multiple printers require an explicit destination. The profile matches width, tape color and ink color as one
identity; matching the width alone is insufficient. Color identity comes from the
operator's installed-cartridge assignment; the current adapter reports width and
status, not color.

Group jobs remain unassigned until reservation. The scheduler chooses the first
available matching group member, considering connection, width, errors, holds,
active/review batches and frozen render capabilities. Missing compatible tape
leaves work queued. Printer-specific jobs never move to a different printer.
Thresholds count copies per submitted destination and tape profile, so unrelated
queues cannot combine to trigger a batch.

One physical worker and hardware lock run per printer. A shared process lock
serializes short database reservations and mutations. The durable PRINTING intent
commits before rendering or any hardware write; raster preparation and physical
printing do not hold the shared lock. API authoring renders outside the lock and
revalidates records, assets and capabilities before committing. Read endpoints
and previews also run without the mutation lock. Another worker can reserve and print independently, but cannot reserve the
same copy. The application still requires one server process per database.

CSV runs select one printer on their first reservation and remain pinned to it,
including after review/requeue. Row and copy order remain unchanged. Membership
changes are refused while a group has queued/printing/uncertain work or saved
unsubmitted drafts. New groups may include a printer already in another group;
reservations still enforce exclusive ownership of each copy and physical device.

Manual group printing reserves currently matching copies by printer. Explicit
selection requires every selected copy to be dispatchable, or the whole request
fails. Moderator-selected printing holds that destination: group selections hold
the group, while direct selections hold the physical printer. Print-level users
can select their own copies without holding other users' work. Manual printing can
run while automatic printing is held.
Pending flushes stay assigned to their chosen printer and wait if it disconnects.
They prevent cartridge reassignment until completed or explicitly cancelled via
`DELETE /api/queue/flush/{id}`. Empty/cancelled selections release reservations.
Both physical and group endpoints apply the same selected-only hold rules.

## Cartridge detection and confirmation

Cartridge installation uses `PUT /api/printer/active-tape?printer_id=…` and requires
Full access directly on that printer. Adapters may implement the generic
`ConfirmableMediaBackend` contract to expose detected media and accept an explicit
selection. The queue continues to use effective width and readiness through
`PrinterStatus`; it never interprets protocol codes.

When a reported type is unrecognized or the detected width differs from the
selected profile, installation returns HTTP 409 with `code: cartridge_mismatch`,
a comparison message, and a `confirmation` token. Resubmit the same cartridge
with that token in `media_confirmation` after the operator accepts the comparison.
No cartridge assignment or acceptance is saved on the initial 409. An already
installed cartridge can be confirmed through the same endpoint.

Mismatch acceptance records the operator and time and is bound to the printer, cartridge,
profile geometry/colors and adapter's opaque detected-media identity. The adapter
rechecks that identity before sending print data and during completion waits.
Observed cartridge changes, power changes or disconnection invalidate the
mismatch acceptance; profile changes and reassignment require fresh confirmation. Devices
cannot distinguish physical cartridges that report identical data without an
observed swap, so operators must keep the installed selection accurate.

Cartridge verification after an observed cover opening is enabled by default.
The adapter consumes buffered cover-open/closed notifications as well as fresh
status replies, latches a verification requirement, and rechecks it at the final
USB preflight. Closing the cover does not release queued work. A pending check
is persisted and blocks printing across restarts until the installed cartridge
is explicitly confirmed or changed. Authorized users receive one prompt per
observed change; cancelling leaves the check pending without repeatedly reopening
the dialog during the same browser session.

Full users can disable **Confirm cartridge after opening** independently per
printer, including while work is queued. `PUT /api/printers/{id}/cartridge-check`
accepts `{ "enabled": false }` to release a pending cover check. Hardware faults
and unconfirmed type/width mismatches remain enforced. Opening and closing a
printer whose reported media remains identical does not revoke an existing
third-party type/width acceptance when this optional check is disabled.

For confirmed TZe tape, the Brother adapter renders at the selected supported
width and omits the firmware's media type/width comparison flags, as defined in
the [Raster Command Reference v1.02, printed page 32](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf).
Hardware errors, missing tape, unsupported output widths and heat-shrink media
remain blocked. Confirmation cannot force firmware to accept a cartridge it
rejects independently of the comparison flags. Colors are reported for inspection;
the selected profile remains authoritative for preview colors and queue routing.

Status responses retain the actual `detected_width_mm` and add
`effective_width_mm`, `detected_media`, `media_warning`, `media_confirmed` and
adapter-provided `diagnostics`. The **Detected details** window on **Printers &
groups** shows the decoded Brother status fields, numeric codes and full 32-byte
packet. Unknown fields remain visible as raw values.

## Interruptions, reminders and persistence

An interrupted printer blocks only its own device. Uncertain copies require human
review and are never silently retried on another member. Other group jobs may
continue on another ready device. Restart recovery marks in-flight attempts
uncertain per printer and retains completed-copy accounting.

Manual review defaults to the cartridge recorded when the attempt began. The
reviewer may select a different cartridge for that attempt's tape use and cost;
the requester shares stay fixed, and the reviewed cartridge is retained in the
batch history. Review never installs or confirms a cartridge or clears a pending
cartridge check.
Cartridge-check prompts wait until the operator leaves the review page; physical
confirmation remains a separate action.

Waiting reminders evaluate each destination/profile threshold against every
member's installed cartridge. The existing per-profile interval, silence and
snooze controls remain shared across destinations; one notification lists the
destinations currently missing that tape. Offline/error conditions are distinct
from missing-cartridge reminders. Group-only hardware blockers also generate
alerts. An episode resets when every destination falls below its threshold;
retired destinations do not block unrelated mutations or reroute historical work.

## APIs and compatibility

- `POST /api/printers`: register a Brother USB printer.
- `PUT /api/printers/{id}`: edit any printer, including migrated registrations.
- `GET /api/workspace`: workspace counts and notification status, including when
  no devices exist.
- `GET /api/printers`, `/api/printers/status`, `/api/destinations`: definitions,
  independent status and selectable destinations with queue counts.
- `POST /api/printer-groups`, `PUT /api/printer-groups/{id}`: create/update groups;
  array order defines routing preference.
- `PUT /api/destinations/{id}/automatic-printing`: hold/resume a group or printer.
- `POST /api/destinations/{id}/print`: print matching work, optionally selecting
  `copy_ids` belonging to that destination.
- Existing status, cartridge assignment, automatic holds and
  physical flush endpoints accept `printer_id`; omit it only with one configured device.
- Label, image and CSV submissions and previews accept `destination_id`.
  Queued previews and CSV manifests retain their original rendering settings.
- Existing idempotency receipts for the default destination remain valid.
  Reusing a key with another destination is a conflict, not a second print.

Physical widths are floating-point millimetres throughout the domain and generic
raster contract. Wire width codes belong only to printer adapters. A frozen
render canvas may retain its original dimensions independently of media width;
this preserves pre-migration rasters. Invalid persisted device configurations
remain visible and repairable instead of disappearing from the registry UI.
Distribution groups also remain visible with their scoped queue counts when a
member's configuration is unavailable. Their aggregate `available` flag means
that at least one member has a configured worker; it does not imply that a printer
is connected or has the requested tape installed. Capabilities, rendering, CSV
preparation and approval use the first configured member. If none exists, group
capabilities are null and new print intent returns a clear conflict.

New render specifications align the printable band to whole device pixel rows.
Editor guides use that same band, and clipping warnings measure visible artwork
rather than blank space inside object bounds (QR quiet zones remain protected).
Older job snapshots keep their original raster geometry. A job rejected for ink
outside the print head must be submitted again to use the corrected rendering.

## Verification

Automated tests cover migration, group matching, concurrent reservations, independent
printing and review, CSV pinning, holds, reminders, and restart persistence.
Physical PT-P710BT testing was reported successful on 2026-10-04; simultaneous
two-device USB testing is deferred until a second printer is available. See
[hardware verification](HARDWARE_VERIFICATION.md).
