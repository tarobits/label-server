# Version 0.13.0 plan

Status: 0.13.0-pre1 candidate. Inventory, accounting, notification, Print Activity,
audit views and companion station workflows are implemented for staged evaluation.
Comprehensive audit coverage and physical deployment acceptance remain release gates.
Planning date: 2026-11-07. Prerelease preparation: 2026-11-08. Baseline: 0.12.2.

This document records the agreed scope and implementation progress, not a claim
that all acceptance criteria have passed. Use [the deployment checklist](DEPLOYMENT_CHECKLIST.md)
for manual rollout and acceptance; operational behavior is documented in
ACCESS_CONTROL.md, PRINTER_ARCHITECTURE.md and PLAN.md.

## Implementation progress

The first backend increment adds:

- A schema migration for nested locations, nullable printer/cartridge ownership
  and locations, cartridge notes, scoped user/role grants, and structured audit events.
  Existing owners are deliberately not inferred.
- An independent resource-permission resolver with direct, role, ownership, and
  ancestor-location grants, legacy-level expansion, and disabled-account handling.
  Invalid location paths fail closed; group grants do not authorize member hardware.
- Audit append/replay primitives, safe-field definitions, permission-aware field
  projection, and filtering/counting/pagination over the authorized projection.
  Audit evidence participates in the caller's transaction and is immutable through
  ordinary ORM writes.
- Focused tests for permission boundaries, redaction, replay conflicts, transaction
  rollback, and migration round trips with existing inventory.

Granular printer permissions now connect to submission, queue
operations, approvals, review, hardware controls, routing/revocation checks, and
notification scopes. The role editor supports presets and individual grants;
effective-access previews include the new permissions and detect stale ownership,
location, or direct-grant state. Existing level grants retain their old behavior.

Confirmed access changes now write global and per-printer audit entries, and
`GET /api/audit` exposes permission-filtered history with access-event recording.
The audit UI exposes permission-filtered facets and restricted details; full action
coverage is still pending. Tests cover the new
read/write boundaries, independent stop permissions, live revocation, scoped
history, and audit access.

Queue and completed-history visibility are enforced separately for individual jobs
and CSV runs, including previews. Desktop/mobile role editing and both directions
of the permission disclosure animation have browser coverage.

Resource management now supports nested locations, user/role/location grants,
ownership transfers, and stale-safe effective-access confirmation. Cartridge notes
have a separate edit permission. Installation offers moving or retaining a
cartridge's location, with permission-impact review.

The resumable administrator migration wizard bulk assigns owners, locations,
cartridge grants, and historical repayment recipients, previews pairwise balances,
and gates printing until confirmation. Ownership history preserves recipients
across transfers and reviewed cartridge corrections.

Pairwise accounts and repayments are connected to the UI. Own-cartridge usage
creates no self-debt; recipients and accounting editors can record repayments.
The notification bell supports scoped pagination and read/unread state independently
of external delivery. Desktop/mobile inbox and accounting interactions have
browser coverage.

Saved price receipts bind requester, geometry, and quantity. Per-submission charge
allocations retain actual and charged costs separately, share remaining allowances
across attempts, cap unexpected excess, and notify owners of reductions. Labels
and CSV rows expose optional maximums. Selected-copy cartridge-use overrides
retain their authorizer and recheck stale price confirmations. Focused backend
tests cover these boundaries; broader verification remains in progress.

Debts retain cartridge attribution while ownerless and are assigned to the next
owner once. Repayments default to individual charges in oldest-first order, with
editable allocations and visible unallocated credits. Migration previews include
historical payment allocations.

Print Activity filters use immutable attempt attribution. Completed-batch packing
groups consecutive copies in print order and can sort by requester. Notification
delivery history has its own administrator view.

Inventory affordability episodes are evaluated even while printers are held or
have no cartridge installed. Dispatch rechecks authorization after rendering.
Retry offers preserve the original requester and charges; free retries are tied
to a cartridge authorization, and paid retries require requester quote acceptance.
Retrying another user's work requires Start anyone's prints; free retries also
require the funding cartridge's Approve use permission. CSV retries retain source
row identity and print order and stay pinned to the original physical printer.
Review records outcomes without silently returning failed output to the queue.
Inventory changes, cartridge selection/confirmation, printer hold/stop controls,
and batch execution/review now write transactional audit evidence. Catalogued
failed/denied inventory actions record their outcome without copying payloads or
exception messages. Role assignments include cartridge access and owner-loss
warnings. Audit coverage beyond these producers remains in progress.

Companions now have outbound authenticated batch transfer, durable go/results,
local execution journals, independent printers, error investigation blocks, and
personal or administrator-bound station PINs. Their web UI supports queue/start,
hold/resume, cartridge swaps/addition, and printer registration/configuration/
removal/restoration without environment printer entries. Registration persists
locally, and optional deployment bootstrap never overwrites web edits. Local stop
events synchronize idempotently after outages. Separate companion deployment files
and setup documentation are available in `docs/COMPANION.md`.

Native installation now selects a main or companion role, with one `labels.service`
per machine and an explicit role marker. The updater detects that role, validates
the service entry point, and selects dependencies, frontend, and database handling.
Companion updates preserve and back up the SQLite journal and keep execution paused
until startup validation succeeds. Main and companion frontend builds and release
archives are separate; companion builds exclude the main UI and its PWA.

The current backend regression suite passed 1,469 tests; the six MariaDB-specific
checks skipped in that run passed separately against MariaDB 11.8.6. All 283
project Python files passed Pylance/Pyright error and warning checks. Simulated
browser workflows cover station controls. Physical Pi/USB, two-printer operation,
and real network outage acceptance remain manual. Comprehensive audit coverage
still needs review against the catalog; 0.13.0-pre1 is not final 0.13.0 acceptance.

## Release scope

- Physical locations for printers, companions, and cartridges.
- User ownership of printers and cartridges, with granular access control.
- Cartridge-owner accounting, pairwise balances, repayments, price limits,
  authorized cartridge substitutions, and explicit retry funding.
- Filterable Print Activity, a completed-batch packing view, a comprehensive Audit
  log, and an in-app notification inbox.
- A lightweight companion with local printer execution and a small web UI.
- An administrator migration workflow that gates all printing.

No dedicated touchscreen application or cartridge scanner is required. A screen
can open the companion web UI or the main website. New printer models and direct
Wi-Fi/Ethernet printer protocols are not implied by companion support.

## Locations and ownership

Locations initially have a simple named-location interface. The data model must
support parent/child relationships, prevent cycles, and allow descendant-scoped
grants without a later redesign. Grants on a parent include its descendants.

Each companion has one location; its attached printers inherit that location.
Main-server printers can also have a physical location. A cartridge has its own
recorded location. Installing it offers to move that location to the printer's
location, with confirmation. Declining still installs it and preserves the old
recorded location. Because location changes affect access, show their permission
impact before applying them.

Printers and cartridges can be owned by individual users. Group ownership is out
of scope. Owners automatically receive every permission on their resource.

- The current cartridge owner or a user with **Edit all cartridges** can transfer
  cartridge ownership.
- The current printer owner or a user with **Edit all printers** can transfer
  printer ownership.
- Printer owners can manage direct user grants for their printer, without global
  role-management access.
- Ownership does not confer access to unrelated resources: owning a printer does
  not grant cartridge permissions, companion access, or global role management.
- Historical accounting retains the owner recorded for the print attempt.
  Later transfers never move existing debts.
- Deleting an owner leaves their printers and cartridges marked **No owner**.
  Preserve direct, role, and location grants; administrators can reassign ownership
  later. Printers may also be registered without an owner.
- Ownerless cartridges can accumulate debt, displayed under the cartridge name.
  The next owner receives these unassigned debts once. Charges already assigned
  to a former owner stay with that owner.

## Printer permissions

Replace cumulative printer levels with independent permissions. Grants may be
assigned directly to users or through roles, scoped to a printer or to a location
and its descendants. Applicable grants combine; removing one grant must account
for access retained through other grants or ownership.

| Permission | Ability |
| --- | --- |
| View printer | See status, location, and installed-cartridge summary. |
| Submit requests | Submit labels for printer approval. |
| Submit directly | Queue labels without printer approval. |
| Start own prints | Manually start the user's queued work. |
| View everyone's queue | See other requesters' queued labels and previews. |
| Start anyone's prints | Manually start selected work from other requesters. |
| Manage everyone's queue | Edit quantities and cancel other users' queued work. |
| Approve print requests | Approve or reject requests for the destination. |
| View everyone's print activity | See batch history and previews, including packing. |
| View audit log | Read audit entries scoped to this printer. |
| Review interrupted batches | Reconcile uncertain output and consumption. |
| Swap cartridges | Install/select cartridges and confirm cartridge checks. |
| Hold/resume printing | Hold or resume automatic printing. |
| Stop after current label | Request a graceful stop. |
| Emergency stop | Request an immediate stop within hardware capabilities. |
| Configure printer | Change hardware and printing settings. |

Configure printer does not imply the other permissions. Hold and resume remain
one permission. Users retain the ability to view and cancel their own work after
access revocation; this does not authorize new submissions or printing.

Group-scoped permissions govern group-addressed work. Physical configuration,
cartridge swaps, stop controls, and interrupted-batch review require access to the
physical printer, including access obtained through its owner or location grants.
Group permissions must not become blanket access to member printers.

Retain Request only, Print, Moderator, and Full as convenient assignment presets.
Migration must reproduce actual old access, including existing history filtering
and operational side effects, rather than assuming each old level maps to every
similarly named new permission. Preview any intentional access changes.

Application-wide creation/management permissions and protected administrator
access remain separate from per-printer grants. Define Edit all printers explicitly
in the implementation rather than silently repurposing an unrelated grant.

## Cartridge permissions and notes

Cartridge permissions are **View**, **Use**, **Approve use**, **Edit notes**,
**Edit details**, **Manage access**, and **View audit log**. Assign them directly
to users or through roles, either on a cartridge or on a location including its
descendants.

Use authorizes the requester to print with a cartridge. Cost estimates normally
include only compatible cartridges the requester may use. Submission, routing,
automatic printing, and manual printing must enforce the actual cartridge's
permissions; filtering the estimate alone is insufficient.

Approve use authorizes a specific override for selected copies as described below.
Printer-request approval alone cannot bypass cartridge permissions. Cartridge
owners receive all cartridge permissions. Ordinary Edit details excludes ownership
transfers and access changes.

Use a single editable notes field, not an authored comment thread. Edit notes can
be granted without Edit details.

Companion cartridge selection defaults to its location, with an option to show
all cartridges accessible to the unlocked user. Users with the applicable creation
permission may register cartridges there. Cartridge access and printer swap access
must both be respected.

## Costs, balances, and repayments

Retain existing consumption-based calculations, including per-copy feed, shared
leader, and other batch overhead. Record actual consumption and actual cartridge
cost separately from the amount charged to a requester.

Snapshot the cartridge owner, requester, price, currency, and relevant authorization
when a print attempt starts. Preserve ownership history so a reviewed cartridge
correction can use the owner applicable to that attempt, not an unrelated later
owner. Preserve the original and corrected audit records.

Maintain balances between pairs of users, keeping currencies separate. Printing
on one's own cartridge records consumption and cost but creates no debt to oneself.

The recipient or a user with accounting-edit permission may record repayments.
Every repayment explicitly records its parties, amount, currency, operator, time,
and reason. Corrections are auditable new entries, and retried requests must not
record duplicate payments.

Keep debt and repayment attribution to individual cartridges as well as user pairs.
Default repayment allocation to the oldest outstanding debts; let the recorder
change the cartridges and amounts before confirmation.

Users can see their own debts and receivables. Owners can see usage charged against
their cartridges. Accounting-view permission allows viewing everyone's accounts;
accounting-edit permission remains a separate authority. Cartridge ownership alone
does not expose label artwork or grant batch access.

### Cartridge-use overrides

When an operator starts a batch using the installed cartridge, identify selected
items whose requesters lack Use on that cartridge. An operator with Approve use
can explicitly select which blocked items to authorize. Show requester, preview,
copies, and the price comparison before confirmation.

The requester pays the lower of:

1. The originally shown quote's upper end for those copies, including overhead.
2. The newly calculated cost using the actual cartridge.

A stricter user-selected maximum also applies. This is an authorization for the
selected copies and attempt, not an enduring permission grant.

The cartridge owner absorbs any reduction from actual cost. The approving operator
does not personally owe that difference. Warn before granting Approve use,
including grants through roles and locations, because it can reduce the owner's
income. Notify the owner of the actual reduction and retain the approving user,
selected copies, saved quote, actual cost, charged amount, and difference.

An override needs a meaningful saved quote in the applicable currency. Missing
prices or unrelated currencies must never silently become zero-cost consent or
an invented conversion; obtain requester acceptance of an explicit quote where
the original price cannot establish a cap.

### Requester maximums

A requester may set a maximum total price for one submitted label and all its
copies. Each CSV row and its copies is a separate pricing unit. The maximum includes
feed and allocated batch overhead, and remains binding on the final charge.
Explain this protection and how unexpected excess costs are handled before
submission. Keep the actual cost and any owner-funded excess visible in accounting.

Work waits until an eligible cartridge can meet the maximum. Check compatible,
non-archived inventory the requester may use, including stored cartridges rather
than only installed ones. An affordable stored cartridge means waiting for
installation. No eligible affordable cartridge means notifying the requester once
when entering that condition, not repeatedly while it persists.

Persist the original displayed quote and the chosen maximum at submission. Partial
batches must share the original unit's remaining allowance instead of each receiving
the whole cap. Quantity edits must not silently multiply an accepted maximum or
replace the saved quote without the necessary requester acceptance.

### Failure and retry funding

Review uncertain output before requeueing. Exclude confirmed printed copies by
default. Provide two explicit paths:

- **Retry at no additional charge:** a user with Approve use on the retry cartridge
  authorizes selected copies. Preserve the original attempt's recorded charge;
  the retry adds no requester charge. Record its consumption and actual cost,
  notify the cartridge owner, and record the authorization.
- **Ask the requester to pay:** send an actionable notification with a fresh quote.
  Requeue only after explicit acceptance, applying the selected maximum to the new
  attempt. No silent paid retries.

Review and retry authorization remain distinct from resuming a blocked printer.
Retries require batch visibility plus **Start anyone's prints** for another user's
labels, or **Start own prints** for one's own labels. **Approve use** on the selected
cartridge additionally authorizes a free retry. Review permission alone does not
authorize new printing. These permissions are rechecked before dispatch.

## Print Activity and packing

Rename Activity to **Print Activity** in navigation and page titles. Keep this
view focused on printing, rather than mixing in configuration and administrative
history. Provide combinable filters for **printer**, **cartridge**, **requester**,
and **authorizer**, applied before pagination and counts.

Requester means the user whose labels were submitted. Authorizer means a person
who approved the relevant printing, including printer-request approval,
cartridge-use overrides, and funded retry authorization. Preserve the different
authorization types and allow matching any relevant authorizer; do not confuse
them with the requester or the operator who merely started the batch. Direct and
automatic prints without a separate authorizer must remain representable.

Use saved attempt attribution, including the cartridge actually charged after
review, rather than current owners or permission holders. Scope the results and
filter choices to the viewer's allowed print history.

Provide a view for a specific completed batch showing every label preview,
requester, and copy count. Default to physical print order and allow sorting by
requester. Preserve meaningful sequence when identical labels occur in separate
positions. Use frozen printed content rather than the template's current state.
Access follows the relevant activity permission and does not imply print controls.
Persistent packing checkmarks are not part of the agreed scope.

## Audit log

Provide a separate **Audit log** covering all application actions, including every
permission change, setting change, ownership/location change, cartridge swap and
confirmation, submission, approval, queue operation, print execution, review,
retry, account adjustment, asset/template action, authentication/session action,
companion action, and migration action. Include viewing/access actions and denied
or failed actions as well as successful changes; do not record a failed attempt
as a completed change. Identify automated/system actions explicitly.

Audit application actions rather than dumping raw HTTP traffic: background polling
is not a new user action on every request. Reading the audit log produces a normal
access event without recursively logging the internal act of writing that event.
Inventory all action entry points during implementation so coverage includes APIs,
background workers, companion execution, and administrative tools, not only UI
buttons.

Provide combinable filters for **printer**, **cartridge**, **action**, **actor**,
and **victim**. Victim means the affected user, for example the recipient of a
permission change; actor means the person performing it. An action can affect
multiple users or no user. Store both identities independently of requester,
authorizer, and resource owner. Resource-only actions need no invented victim.

Entries retain timestamp, stable event identity, action, outcome, actor/source,
affected users, linked resources, and a useful change summary. Record safe before
and after values where relevant, plus correlation to the request, batch, or attempt.
Use immutable identity snapshots so names and attribution remain understandable
after renames or account/resource deletion.

Never store passwords, PINs, API keys, tokens, session credentials, or other secrets
in audit entries. Record that a credential was created, changed, or revoked without
its value or hash. Use explicit safe fields rather than copying arbitrary request
bodies, settings dictionaries, or exception messages. Audit access alone does not
grant access to label artwork, uploaded content, or unrelated private records.

### Audit access

- Printer **View audit log** permits entries concerning that printer.
- Cartridge **View audit log** permits entries concerning that cartridge.
- These grants follow the same direct-user, role, owner, and location inheritance
  rules as the resource's other permissions. Resource owners receive them.
- Global **View all audit logs** permits every entry, including global settings,
  global permission changes, and actions unrelated to a printer or cartridge.
  Administrators retain this permission through their universal access.
- Print Activity access and accounting access do not implicitly grant audit access.
  Audit viewing does not authorize the operations described in the log.

One event may concern multiple resources. Resource-scoped readers receive only
the authorized portion, including a relevant summary of a global role change that
affected their resource, not the entire role definition or unrelated grants.
Global audit access covers all event scopes; protected content within an event
still follows the field-level rules below. Apply authorization to event details,
filters, search, counts, and pagination, not just visible rows.

### Permission-aware redaction

Audit-entry visibility and permission to read every detail in that entry are
separate checks. Apply redaction on the server using the viewer's current effective
permissions, including ownership, roles, direct grants, and location inheritance.
Permissions held when an event occurred do not grant enduring access to it.

- Classify structured event fields by the resource and data permission needed to
  read them. Include only authorized fields in API responses; hiding values in the
  frontend is insufficient. Unclassified payload fields are omitted by default.
- Apply the same checks to before/after values, summaries, actor/affected-user
  details, resource names and IDs, links, references, and nested changes. Basic
  attribution may be visible within an authorized audit event without granting
  unrelated account/profile details. Do not expose a restricted value through an
  old name, a free-text summary, an error message, or a link target.
- Build display summaries from the authorized projection of an event. For example,
  someone who can audit a printer may see that its cartridge was swapped, while
  cartridge notes, price details, or unrelated permission changes remain redacted
  unless the relevant access also permits them.
- View all audit logs permits global event discovery and audit metadata, but does
  not bypass separate protections for accounting details, label content, private
  assets, or personal account data. Administrators retain their ordinary universal
  access. Secrets excluded at recording time are never recoverable through any
  audit permission.
- Where the event itself is visible, a neutral restricted-details indicator can
  explain missing content. Do not reveal hidden identities, values, resource counts,
  or even event existence when those are outside the viewer's authorized scope.
- Search, filters, suggestions, sorting, counts, pagination, and any future exports
  must use the same authorized projection. Matching hidden values must not reveal
  them indirectly through returned rows or result totals.
- Reevaluate access on every read. Prevent shared caches or stale permission caches
  from serving a less-redacted response after revocation, ownership transfer, or
  location changes. Redaction changes the response, not the underlying audit record.

Audit records are append-only through ordinary application interfaces. Commit
successful database mutations and their audit records atomically; persist remote
execution events locally and synchronize idempotently. Keep event occurrence time
and receipt time distinct for offline companion activity. Historical migration may
import existing evidence with its provenance, but must not fabricate a complete
audit history for actions that were never recorded.

## Notification inbox

Add a notification bell near the user menu, an unread indicator, an inbox, and
read/unread state. In-app notifications remain available without email or push.
Support owner cost-reduction notices, unaffordable-work notices, and retry requests
alongside other user notifications. Authorize every notification and action against
the recipient; stale actions must recheck current state and permissions.

Follow existing spacing, motion, transitions, and interaction conventions. Verify
opening and closing surfaces. Avoid explanatory copy except for non-obvious pricing,
permission consequences, and other information required for informed decisions.

## Companion behavior

The main server owns the authoritative queue, rendering, permissions, accounting,
and notifications. The companion owns local printer execution and its durable
execution record. Keep Brother/USB protocol concerns in printer adapters, outside
queue, accounting, and remote orchestration code.

Main and companion are deployed on separate machines. Native installation and
updates must distinguish their roles automatically after initial installation;
the companion can build its own frontend locally on a Pi or use its separate
prebuilt release archive. Its local SQLite journal is durable deployment state.

Companions may connect across networks to a publicly reachable main server. The
main server generates a separate revocable API key for each companion, configured
in that companion's deployment settings. The companion initiates connectivity and
need not be publicly exposed. Its API key identifies the installation, not an
unrestricted human operator. Do not expose that credential to browser clients.

The companion web UI provides:

- A dashboard of all locally attached printers and their status.
- Queue views, start-print controls, and hold/resume controls under user permissions.
- Printer configuration, cartridge swapping, and permitted cartridge creation.
- User selection and PIN unlocking, plus explicit and automatic locking.

Users create/reset personal PINs in main-server account settings. The PIN works at
companions they may access; companion access is a separate permission. Operational
permissions come from the user's current main-server access.

Deployment settings can disable the picker, bind the station to one user, and
define a shared station PIN. This station uses that user's permissions. The shared
deployment PIN is distinct from personal PIN configuration.

Configure the inactivity timeout. Locking keeps the dashboard visible and printing
running, but disables controls except for explicitly configured stop exceptions.
Deployment settings independently control availability of Emergency stop and Stop
after current label while locked or disconnected. These exceptions do not grant
other actions or imply guaranteed mid-label hardware stopping.

When disconnected, show cached information and disable queue mutations, new
cartridge assignments, and other operations needing main-server authorization.
Permitted local stop controls remain usable. Offline PIN unlocking and offline
general-purpose administration are not part of the agreed scope.

### Batch execution and recovery

Before printing, download and validate the complete rendered batch and durably
record its identity. Printing requires the server's explicit go authorization,
durably recorded before local hardware writes.

Once the entire batch and authorization have arrived, a network outage alone does
not interrupt it. The companion can finish that authorized batch independently,
recording results locally. It must synchronize before accepting further batches.
Main-server stop requests cannot reach a disconnected companion; local controls
remain subject to the configured policy.

Use durable batch identities and idempotent messaging so lost acknowledgments,
reconnects, and server restarts cannot cause a second execution or reroute an
outstanding remote attempt. A network timeout is not proof that no label printed.

Idle printer disconnects may recover without human clearance. Local printing
errors block the affected printer for investigation and survive reconnect/restart.
Uncertain physical output requires review, never automatic replay. A process crash
cannot be treated like a harmless network outage with proven continuous execution.
Other printers may continue when one printer is blocked.

## Upgrade migration

On the administrator's first interface visit after upgrading, open a resumable
migration workflow. All printing remains paused until it completes, including
companion dispatch. Enforce the gate on the server, not just in the interface.

The workflow must support:

1. Bulk selection of cartridges and printers to assign initial owners, with
   individual exceptions and initial location assignment.
2. Bulk assignment of initial cartridge access and conversion of printer access
   to granular grants, previewing retained/lost access and deliberate changes.
3. Attribution of historical print charges to the assigned cartridge owners.
   Existing allocations link to batches and their cartridges; preserve recorded
   prices, consumption, amounts, and historical identities.
4. Explicit bulk recipient assignment for historical repayments/adjustments.
   Existing adjustments identify the affected user and recording operator, but
   not the recipient or cartridge. Never infer recipient from the operator.
5. Review of resulting balances and confirmation, with an audit record of the
   migration choices. Distinguish own-cartridge cost from debt to oneself.

Make migration resumable and idempotent. Do not manufacture charges for history
without allocations. Retain pending/uncertain attempt state, queued content,
existing holds, and frozen render geometry. Completing migration must not clear
independent holds or uncertainty blockers. Use normal stopped-server upgrade
procedures; do not cut off an already running physical batch to start migration.

## Implementation milestones

1. **Access and location foundation:** location hierarchy, ownership and transfers,
   user/role/resource/location grants, granular printer checks, access-impact
   previews, and migration gating. Review every old level check and side effect.
   Establish audit recording and scoped/global audit permissions here so later
   milestones record their actions from the start.
2. **Inventory and historical migration:** cartridge notes/access, location-aware
   selection and swapping, owner snapshots, wizard, historical owner/recipient
   assignment, and migration verification.
3. **Accounting and notifications:** actual-versus-charged ledger, pairwise balances,
   repayments, inbox, and notification delivery independent of email/push setup.
4. **Price controls and recovery:** saved quotes, per-unit limits, affordability
   routing, explicit use overrides, owner notices, and both retry funding paths.
5. **Print Activity, packing, and Audit log:** distinct views, the requested filters,
   batch-scoped previews/counts/attribution with both ordering modes, and authorized
   audit details. Verify recording coverage across every implemented action.
6. **Companion protocol and executor:** pairing/revocation, rendered batch transfer,
   durable go/result exchange, device ownership, local failures, and reconciliation.
7. **Companion web UI:** dashboard, permissions, configuration, queue and cartridge
   controls, PIN modes, lock behavior, and offline state using established UI patterns.
8. **Integration and release verification:** migration fixtures, failure injection,
   permission matrix, browser checks, and physical printer/network tests. Update
   implemented documentation and prepare release notes from actual changes.

Keep implementation commits logical and conventional. Do not bump versions,
publish, or claim features in CHANGELOG.md merely because this plan exists.

## Acceptance checks

- Existing installations cannot print before migration completion; resuming the
  wizard or replaying its submission never duplicates ledger entries.
- Direct, role, owner, and ancestor-location grants produce consistent results in
  previews, APIs, routing, companion controls, and permission-impact confirmation.
- Migration preserves old effective printer access without unintended expansion.
  Group-only grants do not leak physical printer controls or unrelated history.
- Transfers preserve historical recipients; location changes expose access impact.
  Printer owners cannot bypass cartridge or companion authorization.
- Quotes exclude unauthorized cartridges. Approved overrides affect only selected
  copies and respect saved upper bounds and stricter requester maximums.
- Split batches, edited quantities, overhead, and retries cannot reuse or silently
  increase a pricing unit's allowance. Actual cost and requester charge reconcile.
- Owners are warned about Approve use and notified of actual reductions. Repayments
  are authorized, audited, and idempotent; currencies remain separate.
- Missing/unknown prices and missing currency matches never become free printing.
  Affordable stored cartridges and nonexistent affordable inventory are distinguished.
- Retry actions require the right authorization, never replay uncertain copies,
  never silently add requester charges, and do not clear printer holds implicitly.
- Packing reproduces saved printed artwork, attribution, counts, and order while
  enforcing activity access. Deleted assets follow existing historical-access rules.
- Print Activity combines printer, cartridge, requester, and authorizer filters
  correctly across approvals, overrides, and retries, including multiple authorizers.
  Filters and totals operate across the full authorized history before pagination.
- Every application action has an audit outcome with the correct actor, affected
  users, resources, and safe change details. Verify global settings, access grants,
  swaps, failed/denied actions, viewing, background actions, and companion activity.
- Audit filters combine printer, cartridge, action, actor, and victim correctly.
  Printer/cartridge-scoped access cannot reveal global or unrelated data through
  entries, filter options, counts, or cross-resource changes. Global access includes
  global events; Print Activity access alone grants no audit access.
- Mutation rollback cannot leave a successful audit event, audit failure cannot
  silently drop a committed change's event, and companion synchronization cannot
  duplicate events. Credential changes never retain secret values or hashes.
- Verify field-level audit redaction for resource-scoped readers, global audit
  readers without accounting/content access, and administrators. Check raw API
  responses, nested before/after values, summaries, identities, and links, not just
  rendered text. Unclassified fields must not become visible by default.
- Hidden audit fields cannot be inferred through search/filter matches, options,
  sorting, totals, or pagination. Revocation, ownership transfer, and location
  changes immediately affect subsequent reads without altering stored evidence
  or leaking another viewer's cached projection.
- In-app notifications work without external delivery, cannot leak another user's
  content, and validate current permissions before executing actions.
- PINs and deployment keys remain secret, verification is rate-limited, and key
  revocation/user-access changes prevent new unauthorized actions. No companion can
  execute another companion's work or acquire arbitrary printer ownership.
- Test connection loss before transfer completion, before/after go, during printing,
  and after physical completion before acknowledgment. Prove no duplicate execution.
- Test main-server and companion restarts separately from network interruption.
  A fully authorized running batch may finish offline; uncertain restart state
  blocks for review. Idle disconnects recover without unnecessary human clearance.
- Confirm locking preserves dashboard visibility and printing, blocks ordinary
  controls, and honors each configured local stop exception. Verify both PIN modes.
- Test two physical printers independently, including one failing while the other
  continues, and validate companion behavior over a real interrupted connection.

## Implementation-time decisions

Main-server storage also supports MariaDB 10.11+; integration coverage targets the
requested MariaDB 11.8.6. SQLite remains the default and companion journals remain
local SQLite. The SQLite migration tool verifies all table contents before committing
and preserves the original database. Native installation and updates support MariaDB
with coordinated database/local-state backup and rollback. Automatic Docker updates
still require SQLite. See [MariaDB deployment and migration](MARIADB.md).

The product scope above is agreed. Protocol framing, storage schema, API names,
timeout defaults, and pagination details are engineering decisions to document
when implemented. Pi model/OS and native-service versus container packaging can
be finalized before companion deployment work. Screen dimensions do not require
a separate touchscreen application.

An administrator approves a single-user companion's identity binding on the main
server. Deployment settings select the matching user and shared PIN; the
installation key cannot authorize a different account. Companion access remains
an independent permission and current account permissions apply to every control.
