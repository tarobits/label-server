# Deployment checklist

Use this checklist with the [deployment guide](DEPLOYMENT.md) and
[companion guide](COMPANION.md). Release-specific changes and migration warnings
belong in the [changelog](../CHANGELOG.md); historical acceptance records remain
available in their release tags.

## Before upgrading

- [ ] Confirm the target version, deployment role and matching frontend assets.
  Read migration and rollback requirements for every release being crossed.
- [ ] Rehearse the update on an isolated copy without production printers or
  outgoing notifications. Keep one main-server process per database.
- [ ] Hold new printing, settle active batches and synchronize companion results.
  Record uncertain physical output for review before maintenance.
- [ ] Stop the relevant services and take a coordinated backup of the database,
  retained assets, configuration and matching code/environment. Confirm the
  backup can be restored; old releases may still depend on local asset files.
- [ ] Check free disk space, service ownership, USB access, proxy settings and
  release availability. Use the updater's `--check` mode to review discovery.
  Preserve existing Compose overrides and project names.
- [ ] For database changes, review [relationship repair](RELATIONSHIP_MIGRATION.md)
  and [MariaDB migration](MARIADB.md). An Alembic revision at head does not imply
  that a staged relationship repair has completed.

## Verify after upgrading

- [ ] Confirm main/companion role, version, health and logs. Finish any administrator
  repair workflow and maintenance restart before expecting normal printing.
- [ ] Verify sign-in, session revocation and restricted-user access. Review
  [security configuration](SECURITY.md), including HTTPS/cookies, request budgets
  and any companion framing allowlist on the actual embedding website.
- [ ] Check retained images, fonts, avatars, templates and saved previews. For
  legacy asset imports, retain the original source until import succeeds and
  keep the resulting archive for rollback. An empty rendering cache must be
  regenerable from the database after import.
- [ ] Check printer registration, installed cartridge, profile compatibility and
  idle reconnect/restart behavior. Print a small controlled label and reconcile
  its copies, physical output, usage and charge.
- [ ] Exercise changed queue, review, retry and CSV workflows. Verify uncertain
  attempts remain blocked for review and never replay automatically.
- [ ] Verify permissions using separate requester/operator/restricted accounts,
  including API denials. Check audit reasons, scoped history and notification
  delivery. Use [group-account checks](GROUP_ACCOUNTS.md) when shared billing is enabled.
- [ ] Test companion disconnect/reconnect around authorization and result delivery:
  unauthorized work must not start, authorized work must retain durable results,
  and reconnect must not duplicate printing or charges.
- [ ] Use the [hardware verification procedures](HARDWARE_VERIFICATION.md) for
  physical acceptance. Automated tests do not establish USB passthrough,
  multi-device behavior or native-driver recovery on the deployed host.
- [ ] Check representative load, memory use and database capacity. For MariaDB,
  ensure `max_allowed_packet` accommodates stored assets and restore/import
  requirements. Keep backup schedules working and record unresolved limitations.

## Recovery

- [ ] Rehearse failed-update recovery before production use. Restore matching
  code, dependencies, database, assets and configuration together; do not run an
  old release against an incompatible upgraded schema.
- [ ] If activation or physical output is uncertain, leave printing stopped and
  reconcile before restoring an old queue, which could otherwise repeat prints.
  Include companion journals and results when deciding what has already printed.
- [ ] After a database cutover accepts new work, its old source is stale. Use a
  current coordinated snapshot, not the pre-cutover SQLite copy.
- [ ] Retain backups until deployment acceptance is complete. A successful health
  response or published release is not evidence that physical recovery is verified.
