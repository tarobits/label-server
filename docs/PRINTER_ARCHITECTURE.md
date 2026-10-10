# Printer architecture and scope

Operational multi-printer support includes independent Brother PT-P710BT
USB printers and explicit printer-group destinations. Other printer models and
Wi-Fi/Ethernet transport implementations remain architecture-only. Accounts,
directly assigned roles, scoped moderation and revocation holds are integrated at
application boundaries; see [the access-control specification](ACCESS_CONTROL.md).

## Device and protocol boundaries

`app/printer/registry.py` separates stable device definitions, media/rendering
capabilities, connections and backend instances. Two identical models have
separate device IDs and USB serial numbers. `PrinterBackend` owns status,
rendered-label printing and consumption planning. USB commands and Brother status
packets stay inside adapters; queue and routing code contains no protocol bytes.

`NetworkConnection` still describes Wi-Fi/Ethernet endpoints and explicit
protocols for future drivers. A network descriptor does not imply a working
transport, discovery, or Wi-Fi provisioning implementation.

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

## Interruptions, reminders and persistence

An interrupted printer blocks only its own device. Uncertain copies require human
review and are never silently retried on another member. Other group jobs may
continue on another ready device. Restart recovery marks in-flight attempts
uncertain per printer and retains completed-copy accounting.

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
  physical flush endpoints accept `printer_id`; omission is valid only with one configured device.
- Label, image and CSV submissions and previews accept `destination_id`.
  Queued previews and CSV manifests retain their original rendering settings.
- Existing idempotency receipts for the default destination remain valid.
  Reusing a key with another destination is a conflict, not a second print.

Migration and tests cover existing single-printer data, group matching, reservation
races, simultaneous printing, independent review, CSV pinning, holds, missing-tape
reminders and restart persistence. The user validated physical printer testing
on 2026-10-04 after the review fixes. The confirmation did not specify simultaneous
two-device USB coverage; mock tests provide separate software regression coverage.

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
