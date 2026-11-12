# Relationship repair and maintenance restart

This upgrade adds foreign keys for current ownership, companion credentials,
printer references and template permission groups. It never chooses a replacement
for an orphaned reference automatically.

## Upgrade flow

1. Back up the database and retained assets using the existing deployment backup
   procedure. Stop the main server before running Alembic; settle active printing
   and uncertain companion batches before maintenance.
2. Run the normal upgrade. A clean database receives the constraints immediately.
   If missing parents are found, Alembic records a pending repair gate and leaves
   those references unchanged. Alembic reaching `head` alone does **not** mean the
   staged integrity migration is finished.
3. Start the server. A pending gate starts the restricted migration interface:
   sign-in/setup and administrator repairs are available, while normal APIs,
   printing, polling, notifications, recovery and retention cleanup are paused.
   Other users see a maintenance message.
4. Review each relationship and affected record. Search existing replacement
   records, select the intended target and provide a reason. Optional references
   can be cleared explicitly; a group-scoped template still requires a group.
   Credentials and price consent with missing owners can only be revoked, never
   transferred. Repairs are audited.
   If no suitable resource exists, use **Create replacement**, review its details,
   then confirm creation. Select that resource and save the assignment separately.
5. When every reference is valid, select **Prepare maintenance restart**. This
   records readiness; it does not resume printing or run DDL in a web request.
6. Restart the main server using the deployment's service/container controls.
   Startup takes exclusive database ownership, validates again, installs the
   constraints and marks the gate complete. Refresh the browser after startup.

The health endpoint stays available during maintenance so the deployment remains
reachable. A healthy response means the service is reachable, not that printing
has resumed. SQLite-to-MariaDB copying is blocked until this gate is completed.

## Failure and recovery

### Creating replacement resources

The migration screen supports users, permission groups, locations, tape profiles,
cartridges, printers, companions and group billing accounts. It uses the normal
resource validation rules. Missing prerequisite tape profiles and locations can
be created within the same workflow without losing the original form.

New users have no roles, permission groups have no members, and companions have
no access grants or active API key. Configure these after maintenance. New printers
are registered on the main server with automatic printing disabled by default;
move them to a companion after maintenance if needed. New group accounts grant
their creating administrator the usual account permissions.

Creation requires a reason and a confirmation bound to the reviewed values and
database state. It is audited and never automatically reassigns the broken reference.
Historical batches, charges, payments and other records outside this resource list
must be selected from existing records or restored from backup; the interface does
not manufacture replacement history.

### Repair conflicts and restart failures

- Stale repair screens cannot overwrite another repair: the record must still
  contain the missing reference identified by the screen's token. Refresh after
  a conflict.
- Changes are explicit and transactional. No record is deleted except an invalid
  credential/consent whose revocation an administrator selected.
- Constraint installation rechecks all relationships before its first DDL
  statement. SQLite table rebuilds use an explicit transaction; foreign-key
  enforcement is restored on the isolated maintenance connection afterward.
- MariaDB DDL can commit independently. Installation checks existing constraints
  so a maintenance restart can resume after a partial DDL failure. Do not manually
  mark the gate complete to bypass a failure.
- If restart installation fails, the server logs the exception and keeps the
  migration interface active. Repair the reported cause and retry maintenance.
  Restore the verified backup if rollback is required; a schema downgrade does
  not reverse administrator-selected reassignments.

SQLite batch migration uses table reconstruction rather than unsupported native
constraint alteration. [Alembic documents its foreign-key considerations](https://alembic.sqlalchemy.org/en/latest/batch.html).

## Deletion after the upgrade

- An account bound to a companion cannot be deleted until an administrator
  rebinds or explicitly unbinds that companion.
- A permission group with templates or image/font assets cannot be deleted until
  they are assigned to another group or changed to a suitable sharing scope.
- Historical financial and audit attribution is retained rather than cascading
  away when an account is removed.

## Relationship design and coverage

An identifier is not always a live relationship. Current ownership and active
credentials need existing parents; historical attribution often outlives them.

| Relationship | Lifecycle |
| --- | --- |
| Location, cartridge and printer owners; companion account bindings | Foreign keys restrict physical user deletion until ownership/bindings are explicitly released or reassigned. |
| Printer state, batches, flush requests and assigned CSV-run printers | Foreign keys retain operational/history links; retirement preserves the printer record. |
| Template permission groups | Foreign keys restrict deletion until templates are reassigned. |
| Companion credentials, price consent and notification read markers | Disposable records cascade on physical user deletion; orphaned credentials/consent are revoked, never transferred. |
| Empty-cartridge alert marker | The reference may be cleared when its cartridge is deleted. |
| Audit, accounting and frozen print attribution | Historical identifiers and snapshots are retained; cascading or reassigning them would change recorded history. |

The orphan scan covers existing SQL foreign keys as well as the added ownership,
credential and printer constraints. Unsupported composite constraints fail
explicitly instead of being interpreted as independent references.

User-role, permission-group and printer-group memberships use JSON lists.
User/role grants and printer/group destinations are polymorphic; image/font group
ownership is asset metadata. These require application validation and deletion
lifecycle checks rather than an ordinary single-target foreign key. Role deletion
cleans billing grants, and group deletion protects asset ownership. Normalizing
memberships and grants into dedicated tables would be a separate schema change.

The repair interface does not rewrite JSON membership, polymorphic grants or
historical identifiers. Synthetic template identifiers for image jobs and retained
deletion tombstones also deliberately do not require a live template or asset.
Do not treat a completed SQL migration as a complete validation of every JSON
reference, or silently substitute current users for historical identities.
