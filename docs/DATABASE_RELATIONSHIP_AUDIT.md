# Database relationship audit

Review date: 2026-11-11. The inventory covers all 56 ORM tables in `app/models.py`,
`billing_models.py`, `job_access_models.py`, `request_models.py` and
`queue_routing_models.py`, their migrations, and the associated deletion paths.

An identifier is not always a live relationship. Current ownership and active
credentials should reference existing records. Historical attribution must often
outlive those records. Polymorphic references and JSON membership lists cannot
be protected by an ordinary single-target foreign key without schema changes.

## Constraints added

| Column(s) | Parent | Deletion behavior / reason |
| --- | --- | --- |
| `locations.owner_id`, `cartridges.owner_id`, `printers.owner_id` | `users.id` | Restrict; ownership must be released/reassigned explicitly before physical deletion. |
| `companions.bound_user_id` | `users.id` | Restrict; deleting the account must not broaden station access. Application deletion is also blocked until rebind/unbind. |
| `companion_pins.user_id`, `companion_sessions.user_id` | `users.id` | Cascade invalidated credentials when the user is physically removed. |
| `printer_state.printer_id`, `batches.printer_id`, `flush_requests.printer_id`, `print_runs.assigned_printer_id` | `printers.id` | Restrict; retirement retains the printer and its operational/history links. |
| `printer_state.empty_alert_cartridge_id` | `cartridges.id` | Set null; an alert episode marker need not retain a deleted cartridge. |
| `label_templates.group_id` | `user_groups.id` | Restrict; move templates before deleting their permission group. |
| `price_quotes.user_id`, `notification_reads.user_id` | `users.id` | Cascade ephemeral consent/read markers when the account is physically removed. |

There are 14 new constraints. Two previously unbounded user-reference columns
become bounded identifier columns to support MariaDB indexing and foreign keys.
All existing SQL foreign keys are included in the orphan scan, not just these
additions. See [the migration workflow](RELATIONSHIP_MIGRATION.md).

## Complete table inventory

The “retained / special” column records why remaining identifier-shaped values
are not blindly converted to cascading foreign keys. This is a classification,
not a declaration that every JSON reference is already perfectly maintained.

| Tables | SQL relationships retained/enforced | Retained / special references |
| --- | --- | --- |
| `access_change_confirmations`, `auth_sessions`, `recovery_tokens` | User | Credentials/confirmation ownership; repair only by revocation. |
| `asset_imports`, `auth_settings`, `request_digest` | None needed | Import markers and singleton settings. |
| `audit_events` | None | Scoped identifiers and field values are immutable historical evidence. |
| `batch_items` | Batch, label copy | Attribution/print-plan JSON is frozen evidence. |
| `batch_reviews` | Batch | Actor identifier/name survive account deletion. |
| `batches` | Printer, cartridge | Snapshot data and trigger metadata describe actual attempts. |
| `billing_accounts` | None needed | Independent account entity. |
| `billing_charges` | Account, request, batch | Requester, recipient and cartridge attribution belongs to the ledger and must survive deletion. |
| `billing_events` | Account | Actor/details are historical. |
| `billing_grants` | Account | Principal is polymorphic user/role; needs explicit lifecycle handling or normalized tables. |
| `billing_payments` | Request, charge | Receipt confirmer is historical attribution. |
| `billing_requests` | Account | Requester/decider retained; source identifies different request/debt kinds. |
| `cartridge_quote_offers` | Job, printer | Offered cartridge, requester and actor describe historical consent. |
| `cartridges` | Profile, user owner, location | Inventory entity; retirement/archive preserves referenced history. |
| `companion_batches` | Batch, companion, printer | Device execution/result journal linkage. |
| `companion_pins`, `companion_sessions` | User; session also companion | Credentials cannot be transferred by repairing their owner. |
| `companion_printers` | Printer, companion | `local_id` is a companion-side external identifier. |
| `companions` | Location, bound user | Binding is a security boundary. |
| `deleted_content` | None | Tombstones intentionally outlive originals and retain deletion/owner attribution. |
| `flush_requests` | Printer, cartridge | Destination is printer/group polymorphic; copy IDs are a captured selection. |
| `job_access_holds` | Job | Resolving actor retained as evidence. |
| `job_submissions` | Job | Owner in the idempotency key identifies the original submission after account deletion. |
| `label_copies` | Job | Individual physical output units. |
| `label_templates` | Permission group | Owner retained during account/content retention; requires ordered content purge, not cascade deletion. |
| `locations` | Parent location, owner | SQL FK guarantees existence; application additionally guards cycles. |
| `notification_deliveries` | Notification, endpoint | Delivery linkage. |
| `notification_endpoints` | None | Owner and destination lists are lifecycle-managed; endpoints are disabled/redacted on account purge. Destination IDs are polymorphic. |
| `notification_reads` | Notification, user | Read state is disposable. |
| `notifications` | Tape profile | Recipient can be an account or a logical audience such as administrators; not always a user ID. |
| `price_quotes` | User | Ephemeral price consent. |
| `print_jobs` | Profile, run | Owner retained; destination polymorphic; template ID can be synthetic (`image`) and jobs have frozen template snapshots. |
| `print_requests` | None | Owner/decision history, polymorphic destination and captured job/run references. Rejected requests can outlive removed drafts. |
| `print_runs` | Assigned printer, profile | Owner retained; requested destination polymorphic. |
| `printer_groups` | None | Live printer membership is a JSON list; normalization is needed for SQL enforcement. |
| `printer_state` | Printer, active cartridge, empty-alert cartridge | Operational state requires live targets. |
| `printers` | Owner, location | Retirement preserves the record. |
| `queue_destination_changes` | None | Job/run/copy/source/target identifiers are routing history, including deleted drafts. |
| `registration_codes` | Redeeming user | Role/group lists and per-group permissions are JSON; deletion paths maintain these lists. |
| `release_migrations` | None | Completing administrator is historical attribution. |
| `resource_grants` | None | Principal and resource scope are both polymorphic. |
| `resource_ownership` | None | Polymorphic resource plus historical owner timeline. |
| `retry_offers` | Batch, source job, retry job | Captured copy IDs and actor/requester/cartridge attribution belong to the offer. |
| `roles` | None | Permissions contain application/resource-scoped data. |
| `stored_assets` | None | Metadata JSON contains owner/group references and different asset kinds, including avatars. |
| `tape_allocations` | Batch | User/cartridge/recipient and prices are historical accounting snapshots. |
| `tape_profiles` | None needed | Profile entity. |
| `template_revisions` | Template | Editor and document fields are revision snapshots. |
| `unit_charges` | Batch, job | Charge allocation linkage. |
| `usage_adjustments` | None | Payer/recipient/actor and cartridge allocation maps preserve payment history. |
| `user_groups` | None | Live user membership and rights are JSON. |
| `users` | None | Live role membership is JSON. |

## Remaining integrity work to deliberate

1. **Normalize active JSON membership.** `users.role_ids`, `user_groups.members`
   and `printer_groups.printer_ids` are candidates for junction tables with SQL
   FKs and uniqueness constraints. That is a schema/API compatibility project,
   not merely adding a constraint to an existing scalar column.
2. **Normalize or validate polymorphic grants.** Separate user/role grants and
   resource link tables, or rigorously validate each kind. In particular, role
   deletion currently removes ordinary resource grants but leaves billing grants
   for that role. Ordinary UUID generation does not reuse the deleted identity;
   the confirmed issue is stale data, not proven privilege escalation.
3. **Asset group reassignment.** Image/font group ownership is in
   `stored_assets.details`, and group deletion does not protect it as it now
   protects template groups. Include these in a future metadata-integrity screen
   or normalize the metadata before claiming database-enforced asset ownership.
4. **Preserve historical identity deliberately.** A future durable “party” table
   could replace some retained user identifiers without losing accounting
   history. Cascading financial records or replacing deleted identities with a
   current user would change history and is inappropriate.

The implemented repair screen covers all SQL FK relationships plus the 14 new
relationships. It does not rewrite historical IDs, polymorphic grants, or JSON
membership lists. Unsupported composite constraints fail explicitly rather than
being incorrectly interpreted as independent references.

## Verification boundaries

SQLite checks cover clean upgrades, downgrade/upgrade compatibility, orphan
staging, administrator repair, credential revocation, authorization, and restart
enforcement. MariaDB 11.8.6 integration checks cover old-release upgrades with
different database collations, copy/restore and schema consistency. Physical
printer operation and production-data migration still require deployment testing.

Validation for this working tree:

- Full Python run: 1,720 passed, 13 skipped and 12 failures from fixtures that
  inserted duplicate test owners or referenced missing printers. Those fixtures
  were repaired; all 50 tests in the affected suites and the relationship suite
  then passed. The complete suite was not repeated after those fixture repairs.
- MariaDB integration: 18 existing checks plus the staged orphan-repair check
  passed against a disposable MariaDB 11.8.6 instance.
- Browser repair/restart checks passed at 1280px and 390px, including reduced
  motion on mobile. Frontend production build, Ruff and Pyright passed.
- Replacement-resource creation and relationship enforcement: 32 targeted Python
  checks passed, covering all eight supported resource types, preview rollback,
  confirmation replay, invalid inputs, stale references, CSRF and administrator
  access. Browser checks also cover prerequisite creation without losing drafts.
- Targeted strict Mypy checking reaches three existing missing `tuple` type
  arguments in `app/billing.py`; no new relationship-module errors remain.
