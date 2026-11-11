# Deployment checklist: 0.16.0

Group billing in 0.14.0 has its own [migration and acceptance
checks](GROUP_ACCOUNTS.md#deployment-and-acceptance). Its manual deployment checks
remain pending and are separate from the historical 0.13.0 results below.

Use **0.16.0** for the current release. Historical **0.12.2** and **0.13.0** checks remain below.
The 0.13.0 upgrade includes the patch, changes the database schema, and requires
administrator inventory migration before printing resumes when upgrading from before pre1. These are manual
acceptance checks. Dated results below describe reported deployment tests;
unchecked items remain to be verified.

The operator's 2026-11-09 stable-release results are recorded by checklist ID in
[the acceptance results](V0_13_0_ACCEPTANCE.md). They include passed, partial,
and untested checks; G7 passed its operator retest, and exact tested versions still
need confirmation. Consult that record alongside the historical rollout notes below.

Record the operator, date, source version, target tag, installation role and mode,
backup location, and results. Keep credentials and private backup paths out of
public issues. Main servers and companions must run on separate machines.

## Before either update

- [ ] Verify the intended tag and release notes. Wait for the release frontend
  downloads to appear: `label-server-frontend.zip` for main servers and, from
  0.13.0-pre1, `label-companion-frontend.zip` for companions.
- [ ] Rehearse on an isolated copy of the deployment. Use simulated printers and
  disable outgoing notifications in the copy; do not connect it to production
  printers, companions, or the production database.
- [ ] Finish or hold printing. Reconnect companions and reconcile every authorized
  batch before taking a recovery snapshot. Record uncertain physical output.
- [ ] Back up the database, complete local data directory (including uploaded
  images/fonts), private configuration, code revision, and dependency environment.
  Stop the service for a coordinated snapshot. Check that the backup can be read
  and restored into an isolated deployment. Before pre3 asset import, a MariaDB backup alone omits local assets.
- [ ] Check free space for backups and frontend builds, service ownership, USB
  permissions, reverse proxy configuration, and access to GitHub release assets.
- [ ] Run the updater's read-only plan from the installation directory. Specify
  `--mode native` explicitly when using an older updater:

  ```sh
  sudo python3 scripts/update.py --mode native --check --tag v0.12.2
  # Or, for the current release:
  sudo python3 scripts/update.py --mode native --check --tag v0.16.0
  ```

- [ ] Review the selected role, tag, mode, service and backup paths. The new updater
  detects native/Docker deployments and supports explicit overrides. Older scripts
  may require `--mode` and may not provide the new confirmation prompt. If an
  updater handoff prints a replacement command, review and run that exact command;
  do not bypass the handoff by manually replacing files in a running installation.

## Upgrade from 0.15.0 to 0.16.0

- [ ] Back up and rehearse on an isolated database copy. Update the main server
  first: `sudo python3 scripts/update.py --mode native --tag v0.16.0 --prebuilt-frontend`.
  Confirm migration `20201b1c52b8` and the relationship repair gate are complete;
  Alembic `head` alone is insufficient when broken references were found.
- [ ] If repairs are required, follow the [relationship migration guide](RELATIONSHIP_MIGRATION.md).
  Verify only administrators can repair references and normal printing/background
  work stays paused. Review assignments and replacement resource creation, then
  select **Prepare maintenance restart** and restart using deployment controls.
  Confirm normal operation resumes only after constraints are installed.
- [ ] Check affected inventory, templates, print history and account attribution.
  Verify bound accounts and template-owning permission groups cannot be deleted
  until the required explicit reassignments are complete.
- [ ] In the template library and picker, verify administrators initially see
  only their own personal templates; enable **Show others’ personal templates**
  and check owner names. Verify ordinary users retain their existing access.
- [ ] Update companions to `v0.16.0`. On a PT-P710BT, open the cover, remove and
  replace the cartridge, close the cover and confirm the selection. Verify no
  persistent investigation block or false busy refusal occurs while idle.
- [ ] Verify fault messages show all reported faults and that genuine hardware
  faults and uncertain batches still require review. Inspect and explicitly clear
  false blocks retained from older versions; never clear uncertain output blindly.
- [ ] Review the [security](SECURITY_AUDIT.md) and [concurrency](CONCURRENCY_AUDIT.md)
  findings for the deployment. Their publication does not mean they are resolved.
- [ ] Record physical deployment results and retain the coordinated backup. These
  manual checks have not yet been reported as passed.

## Upgrade from 0.14.0 to 0.15.0

- [ ] Back up and rehearse the update. Update the main server first, then companions:
  `sudo python3 scripts/update.py --mode native --tag v0.15.0 --prebuilt-frontend`.
  Confirm main-server migration `19191a0b41a7` is applied. Existing printers retain
  automatic-printing support; the new manual-only setting defaults to off.
- [ ] Enable **No automatic printing** on a printer. Confirm it does not print
  automatically even when its threshold is reached or a containing group resumes.
  Check manual printing still works, Hold/Resume controls disappear, and the
  companion shows **Manual only** with **Ready** when idle. Reboot and verify the
  setting persists; disable it deliberately to restore automatic printing.
- [ ] Verify group balances follow the selected user on Tape usage, including
  permitted debts in All users. Check the payer shown in queue and Print Activity
  updates after approved transfers, and historical charge previews show only the
  requesting user's labels.
- [ ] Check the companion's latest-release notice and deployment opt-out. Retrace
  a logic connection to remove it, then verify Undo restores it.
- [ ] Confirm cartridge changes no longer create an investigation block. Inspect
  and manually clear any existing false block; verify real hardware faults still
  block printing until investigated.
- [ ] Check tape-profile names, CSV run expansion and row/run selection in the
  companion queue. Print the installed tape's eligible queue, including entries
  beyond the visible page, and verify funding/price/permission holds still apply.
- [ ] Open completed-batch packing on the companion, sort by requester and inspect
  previews/counts. Verify users without print-activity access cannot open it and
  locking the station hides private packing content.
- [ ] At 1024 × 600, check dashboard and PIN entry fit without scrolling in normal
  operation. Check footer source/license links, centered connection status and
  version/credit, including during a disconnection.
- [ ] Open batch details containing image and numeric field inputs.
- [ ] With an ordinary user, open Print Activity and Printer changes. Verify only
  their labels appear, including changes made by operators, the requester filter
  is locked to their name, and inaccessible inventory details are redacted.
- [ ] Reject an oversized profile picture, then upload a valid image. Verify
  other users and companions remain connected throughout the upload.
- [ ] At INFO, check successful HTTP requests are omitted, 4xx responses produce
  warnings and 5xx responses produce errors. Check DEBUG restores successful
  requests. Configure main and companion levels independently and restart services.
- [ ] Retain the coordinated backup and record physical deployment results. These
  new manual checks have not yet been reported as passed.

## Upgrade from 0.13.0 to 0.14.0

- [ ] Back up and rehearse the update as described above. Update both server roles
  to `v0.14.0`; native installations can run
  `sudo python3 scripts/update.py --mode native --tag v0.14.0 --prebuilt-frontend`.
- [ ] Confirm the main server reaches migration `181819fa30f6` on the deployment's
  database backend. Existing personal charges, payments and queued work must remain
  unchanged. No companion database migration is required for group billing.
- [ ] Complete the [group-account acceptance checks](GROUP_ACCOUNTS.md#deployment-and-acceptance),
  including rejection holds, permission revocation, historical reimbursements and
  creditor-confirmed payments. Do not treat automated results as physical acceptance.
- [ ] Confirm a companion cartridge and reload both interfaces; it should remain
  confirmed until a new cartridge-change event. Check that success messages expire.
- [ ] If using the companion status API, configure a distinct status key and verify
  unauthenticated requests fail and responses contain only operational information.
- [ ] Check template selection, editor help, canvas example controls, the collapsible
  example inputs, and desktop/mobile Tape usage and group-funding views.
- [ ] Verify source/license links, including the corresponding source location for
  any locally modified deployment.
- [ ] Retain the coordinated backup for rollback. Once group accounts exist, the
  schema downgrade is refused; do not run older server code against the new schema.

## Stable patch: 0.12.2

**Reported result — 2026-11-09:** all 0.12.2 checks passed in manual deployment testing.

- [x] Update the native main server after backing it up:

  ```sh
  sudo python3 scripts/update.py --mode native --tag v0.12.2 --prebuilt-frontend
  ```

  For an existing Docker deployment, use `--mode docker` without
  `--prebuilt-frontend`. The patch has no new database migrations relative to 0.12.1.
- [x] Confirm service health, login, version 0.12.2 and successful frontend loading.
  Refresh any installed PWA so its code matches the server.
- [x] Preview and print a multiline automatic-width text field whose text shrinks
  to fit a fixed height. Check width, padding, character spacing and line spacing.
  Check a single-line label and a queued preview for regression.

## Main server: 0.13.0

**Reported result — 2026-11-09:** the pre2-to-pre3 MariaDB upgrade failed in
migration `151516c70dc3` when creating the `batch_reviews` foreign key to `batches`
(error 1005 / errno 150). The updater reported successful rollback to pre2 and a
healthy service. This attempt did not validate the pre3 deployment checks below.

**Fix included in pre4 — 2026-11-09:** reproduced
the failure on MariaDB 11.8.6 with database defaults different from the baseline
tables. The review migration now explicitly matches the baseline's InnoDB engine
and `utf8mb4_nopad_bin` collation, and preserves an existing evidence-policy column
when retrying the failed migration. All 18 MariaDB integration tests and 24 SQLite
migration/review tests passed, including upgrades with different database defaults
and a partially applied migration. Deployment validation is still pending. MariaDB
users must skip pre3 and use pre4, including when retrying after rollback to pre2.

- [ ] Read [the plan and known gaps](V0_13_0_PLAN.md),
  [access control](ACCESS_CONTROL.md), and [deployment guide](DEPLOYMENT.md).
  Use a maintenance window and retain the pre-upgrade backup.
- [ ] Upgrade the native main server using the exact release tag:

  ```sh
  sudo python3 scripts/update.py --mode native --tag v0.13.0 --prebuilt-frontend
  ```

  Review and confirm the plan. Reserve `--yes` for reviewed automation. The updater
  applies schema migrations; a manual installation must run `alembic upgrade head`
  with the correct environment and service account before starting the server.
- [ ] Confirm health and version, then open the interface as an administrator.
  For upgrades from before pre1, verify printing waits until inventory migration is
  complete. Bulk-assign the appropriate owners and locations and review historical
  cartridge balances. Complete the migration deliberately; verify printing resumes.
- [ ] Confirm existing users, roles, printers, cartridges, templates, images, fonts,
  queued requests, print history and balances survived. Check desktop/mobile views
  and refresh installed PWAs.
- [ ] Check the updater's role marker and service entry point. Verify the deployment
  does not run a second main process against the same database.

### Additional checks for 0.13.0 after pre5

- [ ] Install the updated main-server dependencies. Confirm existing templates
  still preview and print; no new schema revision is added after pre5.
- [ ] Save named preview examples, browse them on the unsaved canvas, and verify
  persistence, variable renames, undo/redo, and image access permissions.
- [ ] Test minimum/maximum text lengths in the editor, New label, API and CSV runs.
- [ ] Preview and scan physical Code 128, Code 39, EAN-13, EAN-8, Data Matrix and
  Aztec labels, including variable content, captions, rotation and both resolutions.
  Check invalid EAN check digits and too-small code rejection.
- [ ] Check spacing between Permissions graph and Edit in the user table.
- [ ] Keep the pre-upgrade database backup: older code cannot read templates saved
  with new preview-example fields, text limits or code element types.

### Checks introduced in pre5

- [ ] Apply migration `171718e92fe5` on the main server. Confirm companion
  registrations, grants and last-contact records survive with initially unknown
  software versions until updated companions report them.
- [ ] Verify Online, Offline, Never connected and Key revoked states, last-contact
  times, version mismatch warnings and live refresh on the Companions page.
- [ ] Refresh an already-open companion page once to adopt the new update detector.
  During a subsequent frontend update, verify recovery after service restart and
  update validation, then automatic reload only while locked with no open dialog
  or pending control request. Retest G7 on the actual kiosk and record both versions.
- [ ] Check navigation avatars on desktop and mobile, including upload/removal,
  missing-image fallback, account switching, and opening/closing the account menu.

### Additional checks when upgrading from pre1 to pre2

- [ ] Apply both new schema migrations. Confirm existing locations remain unowned,
  grants remain allows, and tape profiles retain their width and default to TZe.
  A completed inventory migration must remain complete.
- [ ] Assign a location owner and test location/owner resource filters. Edit location
  permissions through both the location and a role, keeping printer and cartridge
  rules separate. Check inheritance explanations and the user/resource graph.
- [ ] Test resource rules overriding location rules, direct-user rules overriding
  role rules within a scope, and deny winning equal-role conflicts. Confirm owner
  and administrator rights remain protected. Test the mutually exclusive request
  and direct-submit controls and review existing effective permissions.
- [ ] Retire an unused printer and confirm its history remains available. Move an
  idle main-server printer to a companion; confirm its ID, queued work, ownership,
  groups and grants survive. Verify the cartridge physically and resume deliberately.
  Follow [the move procedure](COMPANION.md#moving-an-existing-main-server-printer).
- [ ] Verify companion installation preserves existing configuration. Test opening
  and closing PIN setup without premature errors and check button clearance.
- [ ] Test the optional PIN keypad in all three shuffle modes, keyboard input,
  manual locking and the header countdown. Restart after deployment-setting changes.
- [ ] Check media tags, rejection of fixed-label stock on TZe printers, and immutable
  media properties on used profiles. No fixed-label hardware driver is added here.
- [ ] Preview logic-bound automatic-width text between images with short, long and
  bold content. Confirm dependent image positions follow the measured width and
  existing queued previews remain unchanged. Check object names in logic controls
  and find design destination selection in template settings.

### Optional SQLite-to-MariaDB cutover

Treat the database move as a separate maintenance operation after validating the
SQLite upgrade. Follow [MARIADB.md](MARIADB.md) for exact configuration and recovery.
MariaDB 11.8.6 is the integration-tested version; support targets 10.11 and newer.

- [ ] Provision an empty dedicated database and restricted application login; use
  verified TLS where the connection crosses hosts. Keep credentials in protected
  files, never command-line arguments or Git.
- [ ] Finish/review printing and synchronize companion results. Stop the main
  service and keep it stopped throughout migration. Ensure the SQLite source is at
  this release's schema head. Complete the legacy asset import by starting this
  release once, or (while stopped) running
  `.venv/bin/python scripts/migrate_assets.py --env-file .env` as the service user.
  Back up data and configuration again.
- [ ] Run the migration readiness check as the service user:

  ```sh
  sudo -u labels .venv/bin/python -m scripts.migrate_database \
    --source data/labels.db --target-env-file /secure/path/mariadb.env
  ```

- [ ] Run the same command with `--apply --backup-dir /secure/path/migration-backups`.
  Require the **Copied and verified** result. Do not initialize the target with the
  application first or overwrite a populated target to bypass a refusal.
- [ ] Change the deployment's private database URL only after successful copying.
  Set `LABEL_DATA_DIR` to the old SQLite file's parent directory. Start the service
  and verify users, grants, debts, repayments, print history and uploaded assets.
- [ ] Verify database ownership excludes a second server and maintenance process.
  Test loss of the database connection in staging and confirm operations fail closed.
- [ ] Test native backup/restore against a disposable database, including local
  assets and configuration. Preserve the backup server's existing backup policy.
  Automatic Docker updates currently support **SQLite only**; MariaDB in Docker
  requires a coordinated manual upgrade and recovery procedure.

## Companion deployment on its own machine

Follow [COMPANION.md](COMPANION.md). Native installation targets Debian 13+; manual
builds require Python 3.12+ and Node 22.12+. Physical Pi/USB acceptance is still required.

- [ ] On the main server, create a location and companion, assign access, and copy
  its one-time API key into a protected `.env.companion` on the station. Verify
  outbound HTTPS to the main server across the intended networks. Inbound public
  access to the companion is not required.
- [ ] Install from a checkout of `v0.13.0`:

  ```sh
  sudo python3 scripts/install.py --role companion \
    --companion-config "$PWD/.env.companion"
  ```

  Review the installation plan and confirm. Check the station's service role,
  USB group/udev permissions, and local dashboard. Keep localhost binding unless
  remote access is deliberately configured with HTTPS.
- [ ] If building on the Pi, use `npm run build:companion --prefix frontend` and
  verify only the companion frontend is built. For subsequent updates, use the
  role-aware updater and `--prebuilt-frontend` to avoid a local frontend build.
- [ ] Add, edit, remove and restore printer registrations through the web UI.
  Verify they persist after restart and inherit the companion location. Confirm
  removal is refused while a batch is active or awaiting investigation.
- [ ] Set personal PINs in main-server account settings; verify the user picker
  only permits users with companion access. For shared-PIN mode, have an admin
  bind the user on the main server and configure that same ID and shared PIN in
  deployment settings. Verify it cannot select a different account.
- [ ] Test dashboard, queue, start, hold/resume and cartridge swapping with both
  privileged and restricted accounts. Default cartridge choices should be local;
  showing all must still exclude inaccessible cartridges. Test adding a cartridge
  with and without permission and both answers to the location-move confirmation.
- [ ] Test manual locking and inactivity timeout. The dashboard stays visible and
  ordinary controls are disabled. Polling must not keep a session unlocked. Test
  emergency and stop-after-label controls according to the explicit locked/offline
  deployment settings, including the default-disabled case.
- [ ] Verify the entire companion data directory, including `journal.db`, persists
  across restart and update. Back it up with the service stopped. Never delete the
  journal to clear a block: it prevents duplicate execution.

### Physical printing and outage acceptance

Use disposable labels and a small known batch. Record physical counts and compare
them with Print Activity and debts. Automated tests use simulated adapters.

- [ ] Print on each supported physical printer, including multiple connected
  printers. Verify raster output, label length, copies, cuts and print order.
- [ ] Disconnect an idle printer, reconnect it and confirm no investigation is
  required solely for that idle disconnect.
- [ ] Interrupt main-server connectivity before a batch receives authorization;
  verify the companion does not start unauthorized work.
- [ ] After the complete batch is downloaded and authorized, interrupt connectivity.
  Verify it finishes that batch, stores results locally, and synchronizes exactly
  once on reconnect without printing or charging twice. New ordinary work and
  controls must require the main-server connection.
- [ ] Cause a controlled printer error and a controlled restart during execution.
  Verify the affected printer remains blocked for investigation, including after
  reconnect/restart, while unrelated printers can continue. Review uncertain output
  before clearing the block; ready hardware status alone must not clear it.
- [ ] Rehearse companion update/rollback with settled work. Confirm health-gated
  activation and preserved registrations, journal, blocks and pending results.

## Permissions, accounting and interface acceptance

Use separate test accounts for requester, cartridge owner, printer owner,
authorizer and restricted viewer. Check API responses as well as hidden controls.

- [ ] Check direct user and role grants, location-wide cartridge grants, companion
  access, and granular printer controls. Verify owners receive all resource rights;
  test ownership transfers and unauthorized access denials. Confirm revocations
  take effect at companion controls.
- [ ] Delete a disposable account owning inventory. Verify resources become
  ownerless, previous explicit grants still apply, and historical attribution is
  retained. Assign an owner later as an administrator.
- [ ] Print with an ownerless cartridge. Verify its debt is shown under the
  cartridge, accumulates correctly, and is assigned once when an owner is chosen.
  Verify an owner's own printing does not create a debt to themselves.
- [ ] Check price estimates exclude inaccessible cartridges. Test per-row limits
  including all copies, the upper estimate cap, waiting for an affordable cartridge,
  and the notification when no matching cartridge exists.
- [ ] Test authorized use of a normally excluded cartridge with explicit selection
  and consent. Verify the requester pays no more than the agreed cap and receives
  the lower actual price when applicable. Check owner discount notification and
  the warning when granting approval authority.
- [ ] Record repayment as recipient and as an accounting-authorized user. Verify
  oldest-debt allocation by default, explicit cartridge selection, partial balances,
  and explicit audit records for each action.
- [ ] Retry someone else's failed label at no extra charge with cartridge approval
  and permission to start anyone's prints. Test a requester-funded retry requires
  notification and requester acceptance. Verify charges and copies are not duplicated.
- [ ] Filter Print Activity by printer, cartridge, requester and authorizer. Open a
  completed batch's packing screen; check previews, requester and copy counts,
  default print order and requester sorting against actual output.
- [ ] Check the notification bell, unread/read state and inbox without email or
  push configured. Check cartridge notes and edit permissions.
- [ ] Test individual printer/cartridge audit permissions and global audit access.
  Filter by printer, cartridge, action, actor and affected user. Verify redaction
  in list/detail/API responses and filter suggestions, including events referring
  to both accessible and inaccessible resources.
- [ ] Review audit coverage for permission/settings changes, ownership, cartridge
  swaps, printing, retries, repayments, companion controls and relevant denied
  actions. Comprehensive coverage remains an acceptance gate for final 0.13.0;
  report missing events rather than assuming the log is exhaustive.

## Recovery and release sign-off

- [ ] Rehearse a failed update before production use. Confirm a failed pre-activation
  update restores matching code, dependencies, database, assets and configuration.
  If activation is uncertain, leave printing stopped and investigate physical output
  before choosing recovery; restoring an old queue can repeat prints.
- [ ] Never run 0.12.2 against the upgraded 0.13 database. To roll back, stop the
  service and restore the coordinated pre-upgrade snapshot with its matching code
  and environment. Reconcile any work accepted since that snapshot first.
- [ ] Before MariaDB accepts new work, a failed cutover can return to the unchanged
  SQLite source. After it accepts work, the old SQLite copy is stale; use a current,
  coordinated recovery snapshot instead. Database restore replaces target tables.
- [ ] Verify main and companion health, role/version, logs, backup schedules,
  notification delivery and a final small print. Record unresolved issues and retain
  backups until the deployment has been accepted. Do not treat prerelease publication
  as completion of these manual checks.

### Batch review evidence and misprint corrections

- [ ] Apply migration `151516c70dc3` before starting the updated main server.
  Review records and sanitized evidence photos are stored in the database and
  included in database backups. Downgrading with retained reviews requires a
  coordinated backup restore.
- [ ] In Administration → Account settings, check **Batch review evidence** with
  Disabled, Optional, and Required. Required must block both ordinary batch reviews
  and later misprint reports without a photo; Disabled must hide the upload.
- [ ] Report a successful copy as misprinted. Confirm only selected outcomes change,
  tape use and existing charges remain unchanged, and the requester is notified.
  Check the reviewer, reason and photo in Review history.
- [ ] Check that review-only operators cannot send retry offers; an operator with
  the appropriate start-print permission can request a paid retry, and a free retry
  additionally requires cartridge Approve use. Paid retries await requester consent.
- [ ] Revoke batch-history access and verify evidence photos are no longer accessible.
  Test opening and closing the photo and report dialogs on a narrow screen.

### Database assets and idle rendering cache

- [ ] Apply migration `161617d81ed4`. Keep the original asset directory available
  for the first startup (including when `LABEL_DATA_DIR` is customized). Startup
  must finish the verified asset import before the server accepts print work.
- [ ] Check images, uploaded fonts, profile pictures, shared/hidden assets and
  retained deleted assets. Restart the service and verify the import is not repeated.
- [ ] Set `LABEL_ASSET_CACHE_IDLE_SECONDS` as desired (default 604800, minimum 60).
  Cache files under `data/cache/assets` should refresh their timestamps when used,
  expire after inactivity, and regenerate without changing printed output.
- [ ] Restore a database backup into staging with an empty rendering cache and no
  legacy asset directory. Verify previews, printing and profile pictures still work.
  Native MariaDB backup format 2 includes binary values and can still restore old
  format 1 backups. Confirm the old `assets` directory has moved to a timestamped
  `backups/assets-…` folder after the import commits. Failed imports must leave the
  source untouched. Keep this archive for rollback; cache expiration must not remove
  it. Database assets block schema downgrade; use a coordinated restore.

- [ ] For MariaDB, check that `max_allowed_packet` can accommodate the largest
  stored asset, including its source bytes and SQL escaping. Upload, import and
  migration checks report the required size if the configured limit is too small;
  restore checks it before replacing tables. See the
  [MariaDB variable reference](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables#max_allowed_packet).
