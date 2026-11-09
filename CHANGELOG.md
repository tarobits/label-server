# Changelog

## [0.13.0-pre4] - 2026-11-09

### Fixed

- MariaDB upgrades no longer fail when the database's default collation differs
  from the existing batch tables.
- Retrying the failed review migration preserves the existing evidence-policy
  setting instead of failing on a duplicate column.

**Migration requirements:** MariaDB users should skip pre3 and upgrade directly
to pre4. If the updater restored pre2 after a failed upgrade, retry using pre4.
Back up the database, local data directory and private configuration first; the
pre3 asset-import and rollback requirements still apply. This release corrects
the existing migration and adds no new schema revision for installations already
successfully running pre3.

Verified on MariaDB 11.8.6: all 18 integration tests passed, including upgrades
with differing database defaults and retries after partial migration. All 24
SQLite migration/review tests passed.

See [the deployment checklist](https://github.com/tarobits/label-server/blob/v0.13.0-pre4/docs/DEPLOYMENT_CHECKLIST.md)
for rollout, migration and recovery checks.

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

**Migration requirements:** back up the database, complete local data directory
and private configuration before upgrading. Pre3 adds schema migrations for review
evidence and database assets. Keep the old assets directory available for the first
main-server startup; successful import moves it to `data/backups/assets-…` (under
`LABEL_DATA_DIR` when customized). Failed imports leave the original files intact.
Keep the resulting archive for rollback. Before SQLite-to-MariaDB conversion,
complete the asset import by starting this release once or running
`scripts/migrate_assets.py` while the service is stopped. Database assets and review
evidence require a coordinated backup restore for rollback once populated.
Update both main and companion servers and refresh installed PWAs.

Review evidence defaults to **Optional**. Locked companion operational details
remain enabled by default; set
`LABEL_COMPANION_SHOW_LOCKED_DASHBOARD_DETAILS=false` to hide them.

**Known limits:** physical printer/Pi and real network-outage acceptance remain
manual. Comprehensive audit coverage still needs review, and automatic Docker
updates still require SQLite; native updates support MariaDB.

See [the deployment checklist](https://github.com/tarobits/label-server/blob/v0.13.0-pre3/docs/DEPLOYMENT_CHECKLIST.md)
for rollout, migration and recovery checks.

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

**Migration requirements:** back up the database, local assets and private
configuration before upgrading. Pre2 adds schema migrations for location ownership,
permission denials and media properties. Existing locations remain unowned, existing
resource grants remain allows, and existing tape profiles default to continuous TZe.
Review effective permissions after upgrading. Remove explicit deny rules and non-TZe
profiles before attempting a schema downgrade; use a coordinated backup restore for
rollback. Upgrading from before pre1 still requires the administrator inventory
migration before printing resumes. Update both main and companion servers.

**Known limits:** fixed-label compatibility does not add a new physical printer
driver. Physical printer/Pi and network-outage acceptance remain manual. The pre1
limitations concerning audit coverage and automatic Docker updates still apply.

See [the deployment checklist](https://github.com/tarobits/label-server/blob/v0.13.0-pre2/docs/DEPLOYMENT_CHECKLIST.md)
for rollout and acceptance checks.

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
- Project-wide Pylance/Pyright checking now includes scripts, migrations, companion
  code and tests, with deprecation diagnostics enabled.

### Security

- Resource-scoped audit access redacts information the viewer cannot access.
- Companion access and controls follow current main-server permissions; shared-PIN
  user bindings require administrator approval and station credentials are scoped.
- MariaDB ownership locking prevents multiple main servers from owning the same
  database and stops database operations after ownership is lost.

**Prerelease migration requirements:** back up the complete database, local assets
and private configuration before upgrading. Apply the schema migrations and finish
administrator inventory migration before printing resumes. Run main and companion
servers on separate machines. Preserve the companion's local journal during updates.

**Known limits:** hardware/Pi and real network-outage acceptance remain manual;
comprehensive audit coverage still needs review. Automatic Docker updates require
SQLite; native updates support MariaDB. This prerelease is for staged evaluation,
not a declaration that the entire 0.13.0 acceptance plan is complete.

See [the deployment checklist](https://github.com/tarobits/label-server/blob/v0.13.0-pre1/docs/DEPLOYMENT_CHECKLIST.md)
for rollout, validation and recovery steps. Includes the 0.12.2 text-sizing fix.

## [0.12.2] - 2026-11-08

### Fixed

- Automatically sized text fields now use the rendered size of multiline text,
  keeping labels compact when text shrinks to fit the field height. Character
  spacing, line spacing, padding, and queued preview geometry stay consistent.

No new database migrations are required when upgrading from 0.12.1.

## [0.12.1] - 2026-11-07

### Fixed

- Show backup progress during updates, including the current stage, elapsed time,
  and archive size, so slow backups no longer appear stuck after stopping the service.

No new database migrations are required when upgrading from 0.12.0. If the updater
asks you to relaunch after downloading the new script, run the command it provides.

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

Apply database migrations before starting this version, including when upgrading
from 0.12.0-pre7. API clients approving print requests must send the reviewed
`expected_revision`. Existing sessions and queued label snapshots are preserved.

Version 1 templates remain supported. Saving typed fields or logic upgrades a
template to version 2, which older servers cannot read. Review logic written for
earlier prereleases that assigns automatic dimensions or uses unrotated axes;
use `stroke` for line thickness. Back up the database before upgrading.

Push notifications require VAPID configuration and a supported browser. Offline
fallback requires a previous successful visit and does not support offline editing
or replaying print submissions. Approximate session location requires explicitly
trusted Cloudflare visitor headers; see the deployment guide.

Wait for the release frontend build to finish before using `--prebuilt-frontend`.
Automatic rollback cannot recover from power loss or a forcibly terminated updater;
uncertain activation leaves the service stopped to avoid replaying print work.

Physical checks have confirmed subtitle branches, saved layouts, rotated objects,
property sizing, number inputs, cartridge handling, Activity requeueing, Android
notifications, and native updater rollback. Tablet interactions, boolean/image
inputs, the latest iPhone node dragging fix, and Docker rollback still need physical
verification.

The known low-severity deepmerge build-tool advisory remains reported by npm audit.

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

No new database migration is required when upgrading from 0.12.0-pre6.
Review existing logic that positions or resizes rotated objects using the old
unrotated axes. Use `stroke` to change line thickness; assignments to a line's
cross-axis dimension are rejected. Existing queued prints retain their saved
rendering geometry.

Wait for the release frontend build to finish before using `--prebuilt-frontend`.
Physical phone/tablet and printer verification of these changes is still pending.

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

No new database migration is required when upgrading from 0.12.0-pre5.
Templates using property inputs require this version or newer. Existing logic
that assigns automatic text width or uses intermediate text tokens with automatic
width must be adjusted to the new sizing order; see the template logic guide.
Wait for the release frontend build to finish before using `--prebuilt-frontend`.

Physical verification of the new property inputs and the iPhone PWA fixes is
still pending. Both subtitle branches and saved-layout preservation from pre3
have been verified on a printer.

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

No new database migration is required when upgrading from 0.12.0-pre4.
Refresh older updater scripts once to use the new flag and updater handoff;
see the deployment guide. Wait for the release frontend build to finish before
using `--prebuilt-frontend`.

The low-severity deepmerge build-tool advisory remains unresolved upstream.

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

No new database migration is required when upgrading from 0.12.0-pre3.

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

Existing version 1 templates remain supported. Typed fields or saved logic edits
upgrade a template to version 2, which older servers cannot read. Back up the
database before upgrading if rollback may be needed. No new database migration is
required when upgrading from 0.12.0-pre2.

Physical verification update (2026-11-06): both conditional subtitle branches and
saved-label layout preservation after template edits were successfully printed.
Phone editing also passed, with occasional accidental text selection reported.
Tablet editing and the remaining print scenarios still need physical verification.

## [0.12.0-pre2] - 2026-11-04

### Added

- Personal notifications when all copies of a queued item are confirmed printed,
  with per-item opt-outs for labels and CSV rows, also editable in queue details.
- Per-printer batch-completion notifications for moderators and administrators.
  Both new notification types are opt-in in notification preferences.

### Fixed

- The sidebar now shows the number of pending print requests visible to you.

Apply database migrations before starting this version.

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

Apply database migrations before starting this version. Push notifications require
one-time VAPID key and contact-address configuration; see the deployment guide.
Offline use requires a previous successful visit and does not support editing or
replaying print submissions. Verify push delivery on physical devices before relying on it.

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

No database migration is required. Existing shared email addresses need separate
verified addresses before they can be used for email sign-in.

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

Stop existing servers and run `alembic upgrade head` before restarting. Existing
ntfy endpoints retain their settings; email delivery requires SMTP configuration.
Non-administrators need the `queue.change_printer` permission and Moderator access
to both destinations to change a queued job's printer.

## [0.9.0] - 2026-10-30

### Added

- Cartridge renaming, archiving and restoration, with print history, usage and
  costs preserved. Archived cartridges are excluded from installation choices
  and new cost estimates.
- Permanent deletion of cartridges without print or queue history, with
  confirmation and visible explanations when removal is blocked.
- Owner names in font and image libraries for administrators.

Stop existing servers and run `alembic upgrade head` before restarting. Existing
cartridges remain active after the upgrade.

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

No database migration is required. Existing duplicate failures remain until an
administrator previews and confirms their removal in Activity.

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

Resubmit previously queued labels affected by the print-area error after updating;
existing jobs retain their saved rasters.

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

Stop existing servers and run `alembic upgrade head` before restarting. Existing
uploads remain personal; roles with `assets.write` are migrated to
`images.create_personal` and `fonts.create_personal`. Integrations that configure
roles must use the new permission names.

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

Stop existing servers, install the updated dependencies, and run
`alembic upgrade head` before restarting. Account balances include already tracked,
settled print costs; pending and unpriced tape remain separate. Administrators
receive both account permissions; other roles must be granted them explicitly.

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

Stop existing servers and run `alembic upgrade head` before restarting. Per-user
usage tracking starts with new print attempts; older costs are not reconstructed.

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

PT-P710BT printing has been verified with one physical printer. Multiple physical
printers and HomeBox integration remain deferred. Cancellation may finish the
current label before stopping subsequent labels.

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
