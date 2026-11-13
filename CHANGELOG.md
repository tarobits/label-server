# Changelog

## [0.20.0] - 2026-11-13

### Added

- Compact language menus in both interfaces, with saved account preferences and
  a configurable default language for signed-out companion stations.
- English and German installer and updater messages, selected from the terminal
  locale or with `--language en|de`.

### Changed

- Expanded English and German coverage across forms, editor help, validation,
  notifications and printer fault messages. Historical printer reasons retain
  their original wording.
- Navigation uses distinct section icons and a collapsible menu when links do
  not fit, without horizontal scrolling.
- New label and New CSV run shortcuts share a separate rounded panel, keeping
  them distinct from page-specific actions.

### Fixed

- Delayed language saves and companion status responses cannot restore a previous
  user's language or overwrite a newer saved preference.

## [0.19.0] - 2026-11-13

### Added

- English and German interfaces for the main server and companion, with account
  language preferences, browser defaults and translated user-facing messages.
- Archived templates can be viewed and restored by users allowed to manage them.
- Payers can report payments for confirmation by the recipient or an accounting
  editor before balances change.
- Historical group transfers can include selected label entries with all their
  copies. Eligible requesters and approvers can view print previews and batch details.
- Administrators can immediately purge retained deleted accounts and content.
- Root-level installation and update launchers, with a step-by-step installer wizard.

### Changed

- Native updates download the prebuilt frontend by default; use `--build-frontend`
  for a local build. Updates run without prompts; use `--check` to preview the plan.
- The updater backs up and replaces itself when needed, then asks users to rerun
  `update.sh`. Missing environment settings and comments are added without replacing
  existing values; `--no-env-update` skips configuration updates.
- Previous print costs open in a separate dialog. Accounting corrections are
  restricted to accounting editors, with unavailable controls hidden from other users.
- The README now focuses on features, licensing, installation and upgrades, with
  task-focused user guides for detailed instructions.

### Fixed

- Group charge descriptions distinguish historical transfers from newly funded prints,
  and label summaries no longer include raw image and boolean input values.
- Notification delivery records show account names.
- Cancelled rendering requests retain their capacity slot until processing and
  cleanup finish, preventing excess simultaneous work.

### Removed

- Automatic changelog-view checks no longer create audit log entries.

### Security

- Companion idle expiry durably revokes the remote session, including when the
  main server is temporarily unreachable.

## [0.18.0] - 2026-11-12

### Added

- Text supports named and numeric font weights, from Thin to Black for built-in
  Noto Sans and within the supported range of uploaded variable TTF/OTF fonts.
  Static fonts retain their actual weight, and saved work preserves its selected
  weight. Existing Regular/Bold templates retain their appearance.

### Fixed

- Disconnected printers and printers without a detected tape width no longer show
  a false tape-width mismatch warning.

**Compatibility:** Templates and saved work using explicit font weights or variable-font
assets require 0.18.0 or later.

## [0.17.2] - 2026-11-12

### Fixed

- Image-library thumbnails and enlarged previews now queue requests and retry
  temporary server-busy responses. Failed previews offer manual retry, and closing
  an enlarged preview cancels pending work.
- The in-app changelog now formats bold text, inline code and links, with clearer
  spacing between paragraphs and lists.

## [0.17.1] - 2026-11-12

### Fixed

- Template and saved-label previews queue their requests and automatically retry
  temporary server-busy responses instead of leaving galleries full of failed
  previews. Pending requests stop when leaving the view; persistent errors retain
  manual retry controls.

## [0.17.0] - 2026-11-12

### Added

- Searchable template picker for CSV runs and a shared tape-profile picker in
  the template editor, new labels and CSV runs.
- Tape profiles can be marked unavailable without deleting them. Unavailable
  profiles remain visible but disabled for new selections; existing queued
  labels, saved runs and pending requests remain printable.

### Changed

- The main server supports up to 25 database connections per process.
- Completed implementation plans and historical audit reports are replaced by
  maintained security, architecture and migration guides and a shorter deployment
  checklist.

### Fixed

- Concurrent requests and password/PIN checks no longer stall the server while
  waiting for database access. Permission changes are rechecked before saving.
- Concurrent saved-label previews no longer exhaust database connections or
  conflict with preview cleanup.
- Delayed companion responses cannot overwrite newer lock/unlock actions.
  Superseded sessions are revoked durably after reconnect or restart, and journal
  polling avoids unnecessary write contention.
- Companion shutdown has a shared 30-second deadline. Stuck workers cause process
  termination while retaining unfinished attempts for review after restart.
- Database ownership checks reject further work after ownership loss, including
  checks before physical printing. Uncertain output still requires review.

### Security

- Request bodies have configurable byte limits, including chunked requests, and
  expensive HTTP rendering/uploads have a configurable concurrency limit. Busy
  requests receive a retry response instead of waiting indefinitely for capacity.
- Administrator setup tokens are no longer written to logs, and sensitive
  validation responses omit submitted values.
- The main interface permits same-origin framing only. Companion embedding uses
  a configurable exact-origin allowlist, defaulting to same-origin only.
- Role deletion removes billing grants, and permission-group deletion requires
  reassignment of associated images and fonts as well as templates.
- Updated certifi and OpenTelemetry API dependencies to address reported advisories.

**Compatibility:** Clients must handle temporary HTTP 503 responses with `Retry-After`
and reuse idempotency keys when retrying supported submissions. Configure
`LABEL_COMPANION_FRAME_ANCESTORS` to permit external companion embedding; the default
allows same-origin framing only.

**Known limitations in this release:** Companion idle auto-lock does not revoke its
remote operator session; reuse requires both the session token and companion
installation API key. Isolated HTTP middleware can release capacity before a cancelled
synchronous worker exits, although the equivalent full-application test passes. The
low-severity deepmerge build-tool advisory remains unresolved. See the [release security
guide](https://github.com/tarobits/label-server/blob/v0.17.0/docs/SECURITY.md).

## [0.16.1] - 2026-11-12

### Fixed

- Temporary USB connection failures and status-read timeouts while idle no longer
  create persistent investigation blocks on companions, including after restart.
  Actual printer faults and uncertain print attempts still require review.
- Printer-block audit entries now explain the reported fault or local print
  uncertainty. Blocks caused by execution results include the batch, outcome and
  confirmed label count, without duplicate entries from repeated polls or retries.

**Manual repair:** Inspect the printer and use **Clear block** once for any false
investigation block recorded by an older version. Historical audit entries cannot
recover reasons that were never recorded.

## [0.16.0] - 2026-11-11

### Added

- Administrator migration screen for reviewing and repairing broken database
  relationships, with explicit reassignments, audited reasons and replacement
  resource creation. Historical financial and print records are preserved.
- Database relationship inventory and security/concurrency review reports,
  documenting findings and remaining work.

### Changed

- Administrators see their own personal templates by default in the library and
  template picker. **Show others’ personal templates** reveals other users'
  personal templates; templates belonging to someone else show their username.
- Fourteen additional foreign keys enforce current ownership, printer, credential
  and template-group relationships. Broken references require explicit repair
  before normal service resumes.
- Permission groups with templates must have those templates reassigned before
  deletion. Accounts bound to companions must be rebound or explicitly unbound
  before deletion.

### Fixed

- Opening a PT-P710BT cover or removing/changing its cartridge while idle no
  longer creates a persistent companion investigation block. Actual hardware
  faults and interrupted-print reviews remain protected.
- Routine server polling no longer causes false **Printer is busy** refusals
  when selecting or confirming a companion cartridge.
- Printer error messages list every reported fault and unknown error flag,
  retain diagnostic codes, and remain visible alongside investigation blocks.
- SQLite schema downgrades handle inventory tables rebuilt by newer migrations
  without losing their incoming references.

**Migration requirements:** If broken references exist, normal service pauses in
administrator-only migration mode. Repair the references, select **Prepare maintenance
restart**, then restart the main server to apply the constraints. Reaching Alembic
`head` alone does not complete this repair. Schema downgrades do not undo administrator
reassignments. See the [relationship migration
guide](https://github.com/tarobits/label-server/blob/v0.16.0/docs/RELATIONSHIP_MIGRATION.md).

**Manual repair:** Previously recorded false companion blocks require inspection and one
**Clear block** action.

**Known limitations in this release:** The security and concurrency reviews identify
unresolved availability, request-size and lifecycle issues. See the [security
report](https://github.com/tarobits/label-server/blob/v0.16.0/docs/SECURITY_AUDIT.md)
and [concurrency
report](https://github.com/tarobits/label-server/blob/v0.16.0/docs/CONCURRENCY_AUDIT.md).

## [0.15.0] - 2026-11-11

### Added

- Companion packing view for completed batches, with label previews, copy counts
  and requester sorting, governed by each printer's print-activity permissions.
- A companion action to print the installed tape profile's eligible queue for the
  selected destination, including entries beyond the currently displayed page.
- Independent logging settings for main and companion servers through
  `LABEL_LOG_LEVEL` and `LABEL_COMPANION_LOG_LEVEL`.
- Persistent manual-only printer settings, with automatic controls hidden and
  the mode identified separately from printer status on companion dashboards.
- Group-account balances on Tape usage, payer labels in queue and Print Activity,
  and label previews when requesting transfers of historical charges.
- An optional companion notice when a newer stable release is available.
- Retracing a logic connection disconnects it, with undo support.
- Personal Print Activity and printer-change history for every user, with
  permission-aware redaction and access restricted to their own labels unless
  broader activity permissions are granted.

### Changed

- Companion queues show tape profiles and keep CSV runs grouped with expandable
  rows and selection controls.
- Compact companion dashboards, user cards and PIN controls fit the 1024 × 600
  touchscreen. The connection bar keeps status centered, source/license links on
  the left, and the running version and project credit on the right.
- Successful HTTP requests are logged only at DEBUG. Client errors use WARNING,
  server errors use ERROR, and access logs omit request query strings.

### Fixed

- Confirmable cartridge notices no longer incorrectly latch a companion printer
  into "requires investigation". Hardware faults still require human clearance.
- Batch details open correctly when label inputs contain images, numbers or
  booleans instead of only text.
- Profile-picture uploads no longer block the server's event loop while waiting
  for the printer lock, processing images or accessing the database.

**Manual repair:** Previously recorded investigation blocks remain blocked. Inspect the
printer, confirm its cartridge and use **Clear block** once it is safe.

**Logging change:** Successful requests now require `DEBUG`; both log-level settings
default to `INFO`.

## [0.14.0] - 2026-11-11

### Added

- Group billing accounts (Gruppenkassen) with independent user/role permissions,
  funding requests, direct charging, outstanding-debt transfers and reimbursements
  for previously paid prints. Members can wait for approval or print at their own
  expense pending approval; rejecting a waiting request keeps it on hold.
- Group request and decision notifications, account audit histories, and payment
  reports that require confirmation by the creditor or global accounting access.
- Funding approval dialogs with label previews and copy counts. Current approvers
  can preview their pending requests without receiving broader printer queue access.
- An optional bearer-authenticated companion status API for external dashboards,
  exposing station/printer status, queued label counts and cartridge details without
  previews, requester identities or control actions.
- Contextual help for template settings, including the distinction between
  automatic label length, automatic text width and text fitting.

### Changed

- Group accounts and Tape usage use administration-style navigation, with separate
  accounting sections and dialogs for decisions, repayments and corrections.
- Template canvases have previous/next example controls and show the current
  example name. The example-input section can be collapsed.
- Queues distinguish labels waiting for group approval from printable queued work.
- Companion success messages disappear after five seconds.
- Project-owned code and documentation are now licensed under AGPL-3.0-or-later,
  with copyright and third-party notices and source/license links in both interfaces.

### Fixed

- Confirming a companion cartridge no longer immediately prompts again when an
  older status report still describes the acknowledged cartridge change.
- Clicking template cards reliably selects the clicked template, including when
  holding the pointer down before releasing it.
- Long queue status badges no longer overlap actions; review focus outlines,
  cartridge actions and feedback retain clearance. Archived checkbox labels align
  beside their controls.

**Rollback restriction:** Schema downgrade is refused once group accounts exist.
Rollback requires a coordinated backup from before group accounts were introduced.

## [0.13.0] - 2026-11-09

### Added

- Physical locations, printer and cartridge ownership, resource filters, granular
  user/role permissions, location inheritance, explicit allow/deny overrides, and
  an access graph explaining effective permissions.
- Cartridge-attributed debts, owner/requester balances, repayments, price limits,
  authorized substitutions with price protection, and failed-label retry offers.
- Filterable Print Activity, completed-batch packing previews, permission-aware
  audit views, and an in-app notification inbox.
- Companion stations with local printer configuration, queue and printing controls,
  cartridge swaps, personal or shared PINs, optional keypads, inactivity locking,
  operational dashboards, and connection/version indicators. Authorized batches
  can finish through temporary main-server outages.
- MariaDB support, SQLite-to-MariaDB transfer, separate main/companion frontend
  downloads, and native installation and updates for both server roles.
- Profile pictures, a companion user picker, and a searchable template picker.
- Misprint reporting, retry workflows, and review evidence photos with an
  administrator-controlled Disabled/Optional/Required policy.
- Saved template input examples with gallery controls that preview current
  unsaved edits, plus minimum/maximum text lengths enforced in previews and printing.
- Code 128, Code 39, EAN-13 and EAN-8 elements with optional captions, plus
  Data Matrix and Aztec elements. Code content supports variables and logic.

### Changed

- Uploaded images, fonts and profile pictures are stored in the database.
  Existing assets are verified and imported before the old assets folder moves
  into a timestamped backup. Rendering uses a disposable cache with configurable
  expiry based on last access.
- Printer retirement preserves history; moving a printer to a companion retains
  its identity, ownership, permissions, groups and queued work.
- Image fitting, box proportions and artwork scaling have separate controls.
  Design destination lives with template settings, and logic displays object names.
- Controlled tape-profile media properties enforce design/cartridge compatibility.
- Installers and updaters detect deployment role and mode, support explicit
  overrides, show the intended plan, and require confirmation unless `--yes` is used.
- Account navigation shows profile pictures. Updated companion pages reload
  automatically when safely locked, with no open dialog or pending control request.

### Fixed

- MariaDB upgrades handle differing default collations and retries after a
  partially applied review migration. Binary asset transfer and recovery are preserved.
- Automatic text width accounts for logic-bound content and typography before
  positioning dependent elements.
- Companion installation preserves configured environment values; opening the
  PIN form no longer immediately reports missing fields.
- Companion setup and account permission controls retain spacing between buttons,
  fields and feedback, including the Permissions graph and Edit buttons.

### Security

- Resource audit views redact inaccessible information. Companion controls use
  main-server permissions, scoped station credentials and administrator-approved
  shared-user bindings. MariaDB ownership locking prevents concurrent main servers
  from owning the same database.

**Migration requirements:** Upgrades from 0.12.x pause printing until an administrator
completes inventory migration. Legacy asset import requires the original files; retain
the resulting archive for coordinated rollback. See the [deployment
checklist](https://github.com/tarobits/label-server/blob/v0.13.0/docs/DEPLOYMENT_CHECKLIST.md).

**Compatibility:** Older versions cannot read templates saved with the new example
fields, text limits or code element types. Automatic Docker updates remain SQLite-only;
native updates support MariaDB.

## [0.13.0-pre5] - 2026-11-09

### Added

- The Companions page shows connection status, last contact time and reported
  software version, with automatic refresh and warnings for main-server version
  mismatches. Older companions show an unknown version until updated.

### Changed

- The navigation account menu shows the user's rounded-square profile picture,
  with an initial fallback. Uploading or removing a picture updates it immediately.

### Fixed

- Companion pages detect newly installed frontends and reload once the station
  is locked, dialogs are closed and control requests have finished. Reload waits
  for the new page to be available and prevents loops caused by stale cached pages.

**Manual action:** An already-open companion page needs one refresh to adopt automatic
update detection. Subsequent updates can reload safely while locked. The asset-import
and rollback requirements from pre3 still apply; MariaDB users must skip pre3.

## [0.13.0-pre4] - 2026-11-09

### Fixed

- MariaDB upgrades no longer fail when the database's default collation differs
  from the existing batch tables.
- Retrying the failed review migration preserves the existing evidence-policy
  setting instead of failing on a duplicate column.

**Migration recovery:** MariaDB users must skip pre3 and use pre4 or later. If a failed
update restored pre2, retry with pre4. The asset-import and rollback requirements from
pre3 still apply.

## [0.13.0-pre3] - 2026-11-09

> **MariaDB users: do not install this upgrade. Use
> [0.13.0-pre4](https://github.com/tarobits/label-server/releases/tag/v0.13.0-pre4)
> instead.** Pre3 can fail during the review-table migration when database
> collations differ. Pre4 fixes the migration and retry handling.

### Added

- Profile pictures and a companion user-card picker with rounded-square avatars,
  followed by PIN entry and a centered unlock button.
- A touchscreen-friendly companion dashboard with queue counts, cartridge levels,
  batch progress and a persistent main-server connection indicator. Operational
  details on the locked screen can be disabled in deployment settings.
- A searchable template picker for New label, with previews, filters, recent
  templates and pagination for larger libraries.
- Misprint reporting for previously confirmed copies, with reviewer attribution,
  requester notifications and access to the existing retry workflow. Original
  charges and recorded tape consumption remain unchanged.
- Evidence photos for batch reviews and misprint reports, with an administrator
  setting for Disabled, Optional or Required, and permission-protected history.

### Changed

- Image proportions and bounding-box proportions have independent controls.
  Images can be scaled from 0.1 to 1 inside their box, and a reset button fits a
  mismatched box to the image. Logic-driven image changes preserve the box size.
- Uploaded images, fonts and profile pictures now live in the database for both
  SQLite and MariaDB. Existing assets are imported and verified automatically;
  the old assets directory then moves into a timestamped backup folder.
- Rendering files and thumbnails use a disposable cache. Access refreshes their
  timestamps, and files expire after seven idle days by default, configurable
  with `LABEL_ASSET_CACHE_IDLE_SECONDS`.
- Database transfer and native MariaDB backup/restore preserve binary assets and
  check packet-size limits before importing or replacing data.

### Fixed

- Companions reconnect automatically when the main server becomes available,
  including when the companion starts first, without refreshing the kiosk browser.

**Migration requirements:** Keep the original asset files available for the first
main-server startup. Verified import moves them into `data/backups/assets-…` under
`LABEL_DATA_DIR`; failed imports leave them intact. Retain the archive for rollback.
Before SQLite-to-MariaDB conversion, complete asset import by starting this release once
or running `scripts/migrate_assets.py` with the service stopped. Once database assets or
review evidence are populated, rollback requires a coordinated backup restore.

**Deployment limits:** Automatic Docker updates remain SQLite-only; native updates
support MariaDB.

## [0.13.0-pre2] - 2026-11-08

### Added

- Printer retirement that preserves history, and a move-to-companion workflow that
  keeps the original printer's ownership, explicit permissions, groups and queued work.
- Location ownership, resource filters by location and owner, separate printer and
  cartridge location permissions, and location grants in the role editor.
- Explicit allow/deny permission rules, inherited-access explanations, and a
  permissions graph for individual users and resources.
- An optional companion PIN keypad with fixed, once-shuffled or per-keypress-shuffled
  digits, plus a visible inactivity-lock countdown.
- Controlled media properties on tape profiles, inherited cartridge tags, and
  design compatibility checks for continuous TZe tape and exact fixed-label sizes.

### Changed

- More specific resource rules take precedence over location rules; within a scope,
  user rules take precedence over role rules, and equally specific denies win.
  Administrator and individual printer/cartridge owner rights remain protected.
- Submit requests and Submit directly are mutually exclusive permission-editor
  choices, with inherited conflicts resolved by specificity.
- Design destination selection now lives with template settings.
- Named objects display their names alongside technical identifiers in the logic
  graph, property pickers, autocomplete and reference lists.

### Fixed

- Companion installation preserves configured environment values instead of
  appending conflicting defaults; explicit installation options still override them.
- Companion setup buttons have clearance from adjacent fields and status messages.
- Opening or reopening the PIN form no longer immediately shows missing-field errors.
- Automatic text width now includes logic-bound content and typography before
  positioning dependent objects, including text placed between images by logic.

**Migration requirements:** Complete administrator inventory migration if upgrading from
before pre1. Existing locations remain unowned, grants remain allows, and tape profiles
default to continuous TZe. Review effective permissions after upgrading.

**Rollback restriction:** Explicit deny rules and non-TZe profiles must be removed
before schema downgrade; otherwise restore a coordinated backup. Fixed-label
compatibility does not add a physical printer driver.

## [0.13.0-pre1] - 2026-11-08

### Added

- Physical locations, printer and cartridge ownership, and granular permissions
  for users, roles, individual resources, and cartridge locations.
- Cartridge notes, owner-to-requester balances, cartridge-attributed debts and
  repayments, ownership transfers, and an administrator inventory migration workflow.
- Price limits, authorized cartridge substitutions with price protection, and
  explicit free or requester-funded retries for failed labels.
- Filterable Print Activity, completed-batch packing previews, an in-app notification
  inbox, and permission-aware audit-log views.
- Lightweight companion stations with local printer configuration, a printer
  dashboard, queue controls, cartridge swaps, user PINs and optional shared-PIN mode.
  Authorized batches can finish through a temporary main-server disconnection.
- Separate main and companion frontend builds and release downloads, plus native
  installation and role-aware updates for companion stations.
- MariaDB support, a verified SQLite-to-MariaDB migration tool, and coordinated
  MariaDB backup and rollback for native updates.
- A manual deployment and acceptance checklist for this prerelease.

### Changed

- Printer and cartridge owners receive their resource permissions. Ownerless
  cartridges remain usable according to existing grants and retain their debts.
- The updater detects native or Docker installations, with an explicit mode
  override. Installation and updates show a plan and require confirmation;
  unattended use requires `--yes`.

### Security

- Resource-scoped audit access redacts information the viewer cannot access.
- Companion access and controls follow current main-server permissions; shared-PIN
  user bindings require administrator approval and station credentials are scoped.
- MariaDB ownership locking prevents multiple main servers from owning the same
  database and stops database operations after ownership is lost.

**Migration requirements:** Complete administrator inventory migration before printing
resumes. Run main and companion servers on separate machines and preserve each
companion's local journal.

**Deployment limits:** Automatic Docker updates require SQLite; native updates support
MariaDB.

## [0.12.2] - 2026-11-08

### Fixed

- Automatically sized text fields now use the rendered size of multiline text,
  keeping labels compact when text shrinks to fit the field height. Character
  spacing, line spacing, padding, and queued preview geometry stay consistent.

## [0.12.1] - 2026-11-07

### Fixed

- Show backup progress during updates, including the current stage, elapsed time,
  and archive size, so slow backups no longer appear stuck after stopping the service.

## [0.12.0] - 2026-11-07

### Added

- Installable web app for phones and tablets, with Home Screen icons, a
  server-unavailable screen, automatic reconnection, and deferrable app updates.
- Web Push notifications with per-device printer and event preferences, test
  notifications, and device removal. Personal print-completion notifications
  support per-item opt-outs; moderators can subscribe to finished printer batches.
- Conditional template logic with reusable intermediate variables, property
  inputs, and bindings for element properties, visibility, and label length.
- Number, boolean, and uploaded-image variables, with typed forms, numeric limits,
  and CSV image mappings. Queued labels preserve their resolved layout and values.
- Visual node editor with pan/zoom, click, drag, keyboard, and touch connections,
  plus distinct connector shapes for colorblind accessibility. The source editor
  provides highlighting, completion, inline errors, and shared undo/redo.
- Searchable built-in logic reference with contextual help and examples.
- Horizontal and vertical line tools with Length, Stroke, and direction controls.
- Requeue individual confirmed prints from Activity using their saved label and
  original printer.
- Edit copy counts on unstarted queued items and pending requests. Request owners
  can edit their own pending requests; approvals require reviewing the latest revision.
- View and revoke logged-in sessions, including IP address, browser, OS, device,
  user agent, first sign-in, last-seen time, and optional approximate location.
- Updater release channels (`--channel stable|beta`), exact release selection
  (`--tag`), and prebuilt frontend downloads (`--prebuilt-frontend`) for native updates.
- Automatic rollback after update or health-check failures, restoring the previous
  application, configuration, data, and dependencies. Failed recovery retains the
  backup and leaves the service stopped.

### Changed

- Property inputs follow other logic bindings and reject circular dependencies.
  Automatic text sizing runs before logic; automatically sized dimensions cannot
  be assigned. Automatic label length continues to follow the final layout.
- Rotated objects use their visible bounding box for X/Y and Width/Height in both
  Layout and logic. Lines use the visible stroke for bounds and spacing.
- Logic nodes use a shared value-type selector for related inputs and operands.
- Cartridge rechecks identify the previous cartridge and offer confirmation,
  cartridge management, or deferral. Explicitly selecting a matching cartridge
  no longer prompts again.
- Updates pause for relaunch when the updater itself changes. Printing and
  notifications remain paused while an updated installation is health-checked.

### Fixed

- Show pending print-request counts in navigation and keep mobile selection
  highlights aligned as badges and layout sizes change.
- Preserve label proportions in print-request and logic-editor previews.
- Keep rotated objects anchored when resizing, dragging, and snapping, and protect
  the correct automatically sized dimension after rotation.
- Reject incompatible logic connections, including mismatched If branches and
  equality operands, and preserve connector types through intermediate variables.
- Prevent accidental text selection on logic controls and allow dragging nodes
  from their body while preserving socket connections and editable text.
- Avoid duplicate app-update prompts for the same build and correctly track
  upgrades from prereleases to stable releases.
- Enabling print-completion notifications no longer sends historical completions.
- Distinguish denied notification permission from an unanswered prompt, and reuse
  permission that has already been granted.

### Security

- Push delivery rechecks account, printer, and session permissions, restricts
  subscription URLs to supported providers, and stops after session revocation.
- Updated frontend build dependencies to address reported glob and minimatch
  vulnerabilities.

**Compatibility:** API clients approving print requests must send the reviewed
`expected_revision`. Saving typed fields or logic upgrades templates to version 2, which
older servers cannot read; version 1 templates remain supported. Review prerelease logic
that assigns automatic dimensions or uses unrotated axes, and use `stroke` for line
thickness.

**Known limitations:** Automatic rollback cannot recover from power loss or a forcibly
terminated updater; uncertain activation leaves the service stopped. The low-severity
deepmerge build-tool advisory remains unresolved.

## [0.12.0-pre7] - 2026-11-06

### Added

- Add horizontal and vertical lines directly from the editor toolbar, with a
  Horizontal/Vertical direction selector.

### Changed

- Lines use Length and Stroke controls. Selection bounds and distance-holder
  spacing follow the visible stroke instead of an empty surrounding box.

### Fixed

- X/Y coordinates and Width/Height values follow the rotated bounding box in
  Layout and template logic. Resizing one dimension preserves the other and the
  top-left position.
- Keep rotated objects aligned during positioning, resizing, dragging, and
  snapping. Automatic text sizing protects the correct dimension after rotation.

**Compatibility:** Review logic that positions or resizes rotated objects using
unrotated axes. Use `stroke` for line thickness; assignments to a line's cross-axis
dimension are rejected. Queued prints retain their saved geometry.

## [0.12.0-pre6] - 2026-11-06

### Added

- Property inputs in template logic, available as visual nodes and source expressions.
  Reads follow other bindings, support intermediate variables, and reject circular
  dependencies. The built-in reference explains the new behavior.
- Requeue individual confirmed prints from Activity to print another exact copy
  using the saved label and original printer.

### Changed

- Automatic text widths are measured before logic runs. Automatically sized
  dimensions have disabled assignment inlets; manual bindings are preserved when
  switching sizing modes. Automatic label length still follows the final layout
  and is not available as a logic input.
- Cartridge rechecks name the previous cartridge and offer options to confirm it,
  open cartridge management, or choose later. Deliberately selecting a matching
  cartridge no longer prompts again.

### Fixed

- Keep mobile navigation highlights aligned when badges and layout sizes change.
- Preserve label proportions in print-request and logic-editor previews.
- Prevent accidental text selection on logic nodes and controls while keeping
  text fields, source, and documentation selectable.
- Avoid app-update prompts for the same frontend build and preserve deferred
  updates when the waiting service worker is replaced.

**Compatibility:** Templates using property inputs require this version or newer. Adjust
existing logic that assigns automatic text width or uses intermediate text tokens with
automatic width to the new sizing order.

## [0.12.0-pre5] - 2026-11-05

### Added

- Prebuilt frontend downloads for native updates with `--prebuilt-frontend`,
  avoiding Node/npm installation and local builds on devices such as Raspberry Pi.
  Downloads are checked against the release checksum and source commit before
  stopping the service.

### Changed

- Updates now pause when a release contains a different updater and provide a
  relaunch command before stopping the service or changing the installation.

### Security

- Updated frontend build dependencies to address the reported glob and minimatch
  vulnerabilities.

**Manual action:** Refresh older updater scripts to use `--prebuilt-frontend` and
updater handoff; see the [deployment
guide](https://github.com/tarobits/label-server/blob/v0.12.0-pre5/docs/DEPLOYMENT.md).

**Known limitation:** The low-severity deepmerge build-tool advisory remains unresolved.

## [0.12.0-pre4] - 2026-11-04

### Changed

- Configurable logic nodes now use one shared value-type selector instead of
  separate selectors for each input or operand.

### Fixed

- Reject incompatible node connections, including mismatched If branches and
  equality operands, and preserve compatible types when changing node types,
  disconnecting inputs, or removing nodes.
- Image connectors remain triangular when no image is selected, including
  connections through intermediate variables.
- Node search matches displayed names such as "Not equal".

## [0.12.0-pre3] - 2026-11-04

### Added

- Conditional template logic with reusable intermediate variables and bindings for
  element properties, visibility, and label length, alongside automatic sizing.
- Number, boolean, and uploaded-image variables with typed input forms, numeric
  limits, and CSV image mappings. Queued labels retain their resolved layout and values.
- Visual node editor with pan/zoom, click, drag, keyboard, and touch connections,
  plus distinct connector shapes for colorblind accessibility.
- IDE-style source editor with syntax highlighting, completion, hover help, and
  inline errors. Source and node edits share undo/redo and preserve matching node
  positions; invalid drafts keep the last valid preview and block saving.
- Searchable built-in reference with contextual help and copyable examples.

**Compatibility:** Typed fields or saved logic edits upgrade templates to version 2,
which older servers cannot read. Existing version 1 templates remain supported.

## [0.12.0-pre2] - 2026-11-04

### Added

- Personal notifications when all copies of a queued item are confirmed printed,
  with per-item opt-outs for labels and CSV rows, also editable in queue details.
- Per-printer batch-completion notifications for moderators and administrators.
  Both new notification types are opt-in in notification preferences.

### Fixed

- The sidebar now shows the number of pending print requests visible to you.

## [0.12.0-pre1] - 2026-11-04

### Added

- Installable web app for phones and tablets, with Home Screen icons.
- Web Push notifications with per-device printer and event preferences, test
  notifications, device removal, and automatic cleanup of expired subscriptions.
- Server-unavailable screen with retry and automatic recovery during connection
  or server outages, preserving unsaved work in an already-open editor.
- App update prompts that let users defer reloading and preserve other open windows.
- Updater release channels (`--channel stable|beta`) and exact release selection
  with `--tag`; stable remains the default.

### Fixed

- Release checks and changelog tracking support installed prereleases, including
  upgrades to the corresponding stable release.

### Security

- Push delivery rechecks account and printer permissions, stops after sign-out or
  session revocation, and restricts subscription URLs to supported push providers.

## [0.11.0] - 2026-11-03

### Added

- Sign in using a username or verified account email, ignoring case.
- Administrator username editing with a review of the old and new names,
  preserving account IDs, ownership, memberships, and existing sessions.

### Changed

- Renamed **Recovery email** to **Account email** in settings and related messages.

### Security

- Username and email sign-in share the same account rate limit.
- Email verification prevents an address from being assigned to multiple accounts.
  Sign-in rejects ambiguous email addresses already shared by older accounts;
  those accounts can continue using their usernames.

**Manual action:** Accounts sharing an email address must verify separate addresses
before using email sign-in. Username sign-in remains available.

## [0.10.0] - 2026-11-03

### Added

- Verified recovery email, single-use password reset links, and personal email
  notification subscriptions.
- SMTP email notification endpoints alongside ntfy, with per-printer event choices
  and per-printer ntfy priorities.
- Authorized printer changes for queued labels and complete CSV runs, preserving
  saved labels and recording the authorizer, reason, and destination history.
- Optional element names in the visual editor, including the element list,
  inspector, and distance-holder selector.
- Browser and home-screen icons.

### Changed

- Element duplication and deletion are available on the first inspector tab.
- Manual printing explains blocked destinations, including offline printers,
  pending reviews, tape mismatches, and incompatible saved label geometry.
- More consistent mobile headers, touch targets, form spacing, disabled controls,
  and animated settings disclosures.

### Fixed

- Saving a tape profile after clearing the reminder interval and disabling reminders.
- Keyboard focus returns to the email control after saving recovery email changes.

### Security

- Authentication validation errors omit submitted credentials and recovery tokens.

## [0.9.0] - 2026-10-30

### Added

- Cartridge renaming, archiving and restoration, with print history, usage and
  costs preserved. Archived cartridges are excluded from installation choices
  and new cost estimates.
- Permanent deletion of cartridges without print or queue history, with
  confirmation and visible explanations when removal is blocked.
- Owner names in font and image libraries for administrators.

## [0.8.0] - 2026-10-30

### Added

- Separate Activity pages for print attempts and notifications, with access to
  history beyond the latest 100 records and page selections preserved on reload.
- Administrator preview and confirmation for permanently purging duplicate
  failures where printing never started. One original remains; duplicate usage
  records and linked notifications are removed without changing tape consumption
  or account balances.
- Cartridge names and tape profiles in usage history, plus a cartridge filter for
  personal, individual-user and all-user usage. Account balances and payments
  continue to include all cartridges.

### Fixed

- Failures before printing no longer create repeated attempts on every worker
  poll. Labels remain queued and automatic printing is held for the affected
  destination, including printer groups, pending a manual retry or explicit resume.

**Manual cleanup:** Existing duplicate failures remain until an administrator previews
and confirms their removal in Activity.

## [0.7.1] - 2026-10-29

### Added

- Cartridge selection during manual review, defaulting to the cartridge recorded
  when printing began. Corrections update that attempt's tape usage and costs
  without changing the installed cartridge or its confirmation.

### Fixed

- Narrow-tape printing failures caused by rounding at the printable edge,
  including templates changed from 24 mm to 12 mm.
- False clipping warnings caused by empty space inside object bounds. Printable
  guides now match the printed area and remain visible on light and dark tape.
- Installed-cartridge confirmation popups no longer interrupt manual review;
  outstanding checks remain separate from the review's accounting.

**Manual repair:** Resubmit queued labels affected by the print-area error; existing
jobs retain their saved rasters.

## [0.7.0] - 2026-10-29

### Added

- Personal, group and global font and image libraries, with sharing controls,
  separate collaboration permissions, bulk uploads and retries for failed files.
- Cartridge mismatch confirmation for users with Full printer access, allowing
  third-party TZe tape to print using the selected width while retaining hardware
  error checks.
- A printer details window showing detected tape type, width, colors, error flags
  and the complete reported status packet.
- Cartridge verification after an observed cover opening or tape change. Printing
  waits for confirmation, including after a server restart. The check is enabled
  by default and can be disabled separately for each printer.

### Changed

- Replaced the combined asset-upload permission with independent font and image
  permissions. Group and global sharing require explicit grants for each library.

**Permission compatibility:** Roles with `assets.write` are migrated to
`images.create_personal` and `fonts.create_personal`. Integrations configuring roles
must use the new permission names; existing uploads remain personal.

## [0.6.0] - 2026-10-28

### Added

- Approximate costs before submitting individual labels or CSV runs, including
  all copies, feed, unused tape and one batch leader. Queue estimates update for
  remaining copies; missing prices and cartridge price ranges stay explicit.
- Individual user usage views and account balances, with separate permissions to
  view other users' usage and to edit accounts. Payments and corrections retain
  the operator, date and reason, and retries cannot duplicate an adjustment.

### Security

- Upgraded Pillow to 13.0.0 to address image-processing vulnerabilities, including
  Ghostscript argument injection and TIFF memory corruption.

**Permission change:** Administrators receive both account permissions; grant them
explicitly to other roles that need them.

## [0.5.0] - 2026-10-28

### Added

- Per-user tape usage and costs with cartridge purchase prices, personal usage
  history, and an administrator view across users. All allocated tape is charged
  to the original requester, including a share of the batch leader. Prices are
  preserved per attempt; unpriced tape and attempts awaiting review stay separate.
- GitHub installer for a fresh systemd deployment, including dependencies, USB
  permissions, frontend builds, database migrations, and service health checks.
- Tape breakdowns under queue and activity details: Design, Feed, Leader, and
  Unused, with saved estimates retained for each print attempt.

### Fixed

- Short-label estimates now include padding for the 10 mm template minimum and
  the PT-P710BT's 24.5 mm cutting minimum. Individual labels and CSV drafts warn
  when hand trimming is needed, and print attempts log the extra unused tape.
- New-label previews fit within the desktop viewport so warnings remain visible.
- Upgrades recognize the previously applied consumption-source migration and
  preserve existing print history.

**History limitation:** Per-user usage tracking starts with new print attempts; older
costs are not reconstructed.

## [0.4.0] - 2026-10-22

### Added

- Searchable template library with separate personal, group, and global sections,
  plus tape-width and group filters that persist when returning from the editor.
- Template revision history with previews, editor names, save dates, and the
  ability to restore a previous revision as a new revision without changing
  queued labels. Older revisions without editor or date records remain unrecorded.

### Fixed

- Template dimensions show a calculated length when inputs cannot change the
  label size, and “Variable length” when input-driven text sizing can change it.
- The label-length field clearly appears disabled when automatic length is selected.

### Security

- Updated Vite to 7.3.7 to fix five development-server vulnerabilities involving
  file access, cross-origin script execution, and editor command execution.

## [0.3.2] - 2026-10-22

### Fixed

- Account menu clicks in Safari no longer dismiss the menu before settings or
  sign-out actions can run.

## [0.3.1] - 2026-10-22

### Fixed

- Queue and activity label previews now show the selected tape profile's ink and
  tape colors, including enlarged previews, without a mismatched border.
- Label previews provide distinct hover and click feedback while respecting
  reduced-motion preferences.

## [0.3.0] - 2026-10-22

### Added

- Account settings with password changes and reduced-motion preferences that can
  follow the browser or be overridden for each browser.
- A once-per-account update dialog showing every release since the last visit,
  plus a full changelog accessible beside the version number.
- Separate role permissions for creating personal and global templates and for
  editing or deleting other users' global templates. Registration codes can grant
  independent template-group permissions.
- Editable process names and on-demand label details and previews in the print
  queue and activity history.

### Changed

- Organized the template inspector into Content, Style, and Layout tabs while
  keeping all existing settings available.
- Added connected page transitions, sliding tabs, animated disclosures, and
  smoother feedback for dialogs, lists, and editor selections.
- Moved account actions into a side-opening navigation menu that keeps the rest
  of the navigation accessible.
- Reorganized administration into focused sections with clearer access previews,
  account and group management, and notification settings.
- Permission change: Custom roles must explicitly grant template creation.
  The Member role retains personal-template creation by default.
- Accounts establish their changelog baseline on their first visit after this
  upgrade.

### Fixed

- Keyboard focus outlines remain visible in scrolling navigation, editor settings,
  and queue details. Account menus close when focus leaves and can be reopened
  immediately with the keyboard.
- Dialog focus indicators distinguish pointer interaction from keyboard navigation
  while preserving screen-reader focus and returning to the opener.
- Editor values remain intact across tab changes, interrupted gestures, and
  expanding settings. Fields stop moving when editing begins.
- Label previews load without blank flashes or unnecessary requests, and failed
  submissions and previews remain recoverable.
- Long names, form errors, and settings layouts remain usable on smaller screens.

### Removed

- The redundant Printers shortcut in the page header.

### Security

- Password changes require the current password and invalidate other sessions for
  the account while keeping the current session signed in.

## [0.2.1] - 2026-10-21

### Fixed

- Using a template automatically selects its saved tape profile for labels and
  CSV runs, while preserving explicitly chosen profiles when reopening a form.
- The template editor requires a tape profile and matches the label height to
  its tape width, replacing the separate width control and default preview tape.

## [0.2.0] - 2026-10-21

### Added

- Templates remember their preview tape and colors when reopened or duplicated.
- Template cards show label previews that are reused across visits and server
  restarts.
- Inline form validation with linked field errors and keyboard focus for
  correcting invalid input.

### Changed

- Renamed the product to Taro's Label Room, with shared branding on sign-in,
  registration, and first-run setup.
- Simplified UI copy and expanded the editor workspace when no element is selected.
- Enlarged checkbox targets for queue selection, CSV runs, and batch review.
- Improved placeholder contrast, form spacing, and disabled-button feedback.

### Fixed

- Sidebar controls remain reachable in short windows, and navigation keeps the
  current section highlighted and visible on nested pages and mobile screens.
- Long cartridge names no longer overflow mobile layouts.
- Switching between sign-in and registration clears previous validation and
  focuses the username field.

## [0.1.0] - 2026-10-21

Initial release of Label Printer Server.

### Added

- Persistent label queues, tape profiles and cartridge consumption tracking.
- USB printer management and distribution groups, with print review and durable
  holds after cancellation, interruptions and access changes.
- Visual label editor, reusable templates, image and font libraries, CSV runs,
  and print requests with approvals.
- User accounts, roles and groups, with administrator access previews.
- Administrator deletion of accounts, templates, images and fonts, including
  referenced content. Deleted content is unavailable immediately and can be
  restored for 30 days before purging. Dependent templates show missing-asset
  placeholders and affected print work remains held for review.
- Durable notifications with administrator-managed ntfy endpoints.
- Native systemd and Docker Compose deployment, plus a release updater that
  backs up data, upgrades dependencies, migrates and verifies service health.
- Version display, cached release notifications and private GitHub token support.

**Printing limitation:** Cancellation may finish the current label before stopping
subsequent labels.

[0.20.0]: https://github.com/tarobits/label-server/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/tarobits/label-server/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/tarobits/label-server/compare/v0.17.2...v0.18.0
[0.17.2]: https://github.com/tarobits/label-server/compare/v0.17.1...v0.17.2
[0.17.1]: https://github.com/tarobits/label-server/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/tarobits/label-server/compare/v0.16.1...v0.17.0
[0.16.1]: https://github.com/tarobits/label-server/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/tarobits/label-server/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/tarobits/label-server/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/tarobits/label-server/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/tarobits/label-server/compare/v0.13.0-pre5...v0.13.0
[0.13.0-pre5]: https://github.com/tarobits/label-server/compare/v0.13.0-pre4...v0.13.0-pre5
[0.13.0-pre4]: https://github.com/tarobits/label-server/compare/v0.13.0-pre3...v0.13.0-pre4
[0.13.0-pre3]: https://github.com/tarobits/label-server/compare/v0.13.0-pre2...v0.13.0-pre3
[0.13.0-pre2]: https://github.com/tarobits/label-server/compare/v0.13.0-pre1...v0.13.0-pre2
[0.13.0-pre1]: https://github.com/tarobits/label-server/compare/v0.12.2...v0.13.0-pre1
[0.12.2]: https://github.com/tarobits/label-server/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/tarobits/label-server/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/tarobits/label-server/compare/v0.11.0...v0.12.0
[0.12.0-pre7]: https://github.com/tarobits/label-server/compare/v0.12.0-pre6...v0.12.0-pre7
[0.12.0-pre6]: https://github.com/tarobits/label-server/compare/v0.12.0-pre5...v0.12.0-pre6
[0.12.0-pre5]: https://github.com/tarobits/label-server/compare/v0.12.0-pre4...v0.12.0-pre5
[0.12.0-pre4]: https://github.com/tarobits/label-server/compare/v0.12.0-pre3...v0.12.0-pre4
[0.12.0-pre3]: https://github.com/tarobits/label-server/compare/v0.12.0-pre2...v0.12.0-pre3
[0.12.0-pre2]: https://github.com/tarobits/label-server/compare/v0.12.0-pre1...v0.12.0-pre2
[0.12.0-pre1]: https://github.com/tarobits/label-server/compare/v0.11.0...v0.12.0-pre1
[0.11.0]: https://github.com/tarobits/label-server/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/tarobits/label-server/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/tarobits/label-server/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/tarobits/label-server/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/tarobits/label-server/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/tarobits/label-server/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/tarobits/label-server/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/tarobits/label-server/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/tarobits/label-server/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/tarobits/label-server/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/tarobits/label-server/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/tarobits/label-server/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/tarobits/label-server/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/tarobits/label-server/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tarobits/label-server/tree/v0.1.0
