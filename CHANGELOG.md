# Changelog

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
