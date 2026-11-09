# Access control

Roles control application and printer access. Ownership and group membership
control template, font and image sharing. These rules are implemented.

## Personal sessions

Every signed-in user can list and revoke their own login sessions in Account
settings. These endpoints are owner-only, including for administrators:
`GET /api/auth/sessions`, `DELETE /api/auth/sessions/{id}`, and
`DELETE /api/auth/sessions/others`. Deletion requires the current session's CSRF
token and same-origin checks. Listing returns separate public identifiers,
never login tokens, their hashes, or another session's CSRF token. Expired
sessions are omitted. Revocation also removes the session's push subscription.

## Roles and user groups

Roles contain permission objects and are assigned directly to users. A role can
contain application permissions and resource rules scoped to printers, distribution
groups and locations. Resource rules have **Inherit**, **Allow** or **Deny** states.
An inherited state removes the explicit rule rather than denying access. Application
permissions remain additive; resource rules use the precedence below.

Content groups share templates, fonts and images. They never assign roles or
confer printer permissions. Ownership, scope and group membership determine
which items are available. Each content type has separate collaboration rights.

## Protected Administrator role

Administrator is a protected, built-in role assigned directly to users. It grants
every permission on all existing and future resources, including printers,
distribution groups and user groups. Its users can view every template, including
templates in groups they have not joined.

The role cannot be deleted or stripped of its universal access. At least one
enabled administrator must remain. Validation and physical printer state still
apply to administrator actions.

## Template ownership and group membership

Templates have personal, group or global scope. Group membership makes that
group's templates available and has three independent settings per member:

- Create templates in the group.
- Edit templates owned by other group members.
- Delete templates owned by other group members.

Users can always edit and delete their own templates. Editing or deleting someone
else's group template requires the corresponding membership permission; creation
permission does not implicitly grant either. Administrators have all of these
permissions regardless of membership.

Roles independently grant creation of personal templates, creation of global
templates, editing other users' global templates, and deletion of other users'
global templates. The Member role includes personal template creation by default.
Custom roles must explicitly grant it. Creation permissions also govern moving
owned templates into a different scope; editing an existing owned template does
not require a creation permission. Only its owner or an administrator can change
a template's sharing scope.

Global deletion permission allows archiving and deleting global templates,
including other users' templates. Deleted templates remain recoverable by an
administrator for 30 days. Global template permissions grant no access to other
users' personal templates or to template groups.

Template readers can inspect saved revisions and the artwork referenced by that
history. Restoring requires current edit permission and creates a new revision;
it preserves the template's current owner, visibility, and group. Existing queued
labels retain their saved layout. New revisions record the editor and save date;
older revisions without that information are shown as unrecorded.

Registration codes can assign content groups with independent create, edit
others, and delete others permissions for templates, fonts and images in each
group. Membership with all permissions off grants view-only access. Older codes
retain their template permissions and grant no font or image collaboration rights.

## Font and image libraries

Uploaded fonts and images have personal, group or global scope, just like
templates. Each has its own role permissions:

| Action | Fonts | Images |
| --- | --- | --- |
| Upload personal items | `fonts.create_personal` | `images.create_personal` |
| Upload global items | `fonts.create_global` | `images.create_global` |
| Edit others' global items | `fonts.edit_global` | `images.edit_global` |
| Hide or delete others' global items | `fonts.delete_global` | `images.delete_global` |

Group membership separately controls uploading, editing others' items and deleting
others' items for each library. Restoring a hidden item requires edit permission.
Owners can manage their own existing items even after losing upload permission.
Only owners and administrators can change sharing, and moving an item requires
permission to create in the target scope. Template rights do not grant asset rights.

The Member role includes personal font and image uploads. The migration replaces
the former `assets.write` grant with both personal upload grants. Existing uploads
remain personal; no group or global grants are added. Stop the server and run
`alembic upgrade head` before restarting after this upgrade.

Readable templates, their revisions, and saved printing work also allow access to
the specific assets they reference. This preserves rendering without exposing the
asset owner's entire library. Changing an asset's scope does not revoke access
already provided by a readable saved document. Bundled fonts remain global.

## Usage accounts

Every signed-in user can view their own tape usage, balance and adjustments.
Two independent application permissions can be granted through roles:

- `usage.view_others`: view all users or an individual user's usage, balances and
  adjustment history.
- `usage.edit_accounts`: record positive or negative account adjustments, including
  payments and corrections, with a required reason. This permission exposes the
  recipient name list but does not grant access to others' usage or balances.

Administrators have both permissions. Printer access and inventory management
grant neither. Adjustments are append-only and retain the operator, recipient,
time and reason, including after account deletion. Repeating an adjustment with
the same reference and payload does not apply it twice. Balances use settled
priced allocations; pending and unpriced tape stays separate. Viewing usage does
not grant access to batch details or printer operations.

## Printer and distribution-group access

Printer and distribution-group permissions are independent grants. The role editor
provides presets plus individual checkboxes, and previews each affected user's
combined access before saving. Existing level-based roles remain readable and
retain their previous abilities; editing them stores explicit permissions.

| Permission | Ability within the granted destination |
| --- | --- |
| View printer | Read printer status and its installed-cartridge summary. |
| Submit requests | Send labels for approval. |
| Submit directly | Queue labels without printer approval. |
| Start own prints | Manually start the user's own queued work. |
| View everyone's queue | Read other users' active work and previews. |
| Start anyone's prints | Manually start selected work from other requesters. |
| Manage everyone's queue | Edit quantities and cancel other users' work. |
| Approve print requests | Approve or reject requests without permission to edit their quantities. |
| View everyone's print activity | Read completed job and batch history and previews. |
| View audit log | Read permission-filtered audit entries for the physical printer. |
| Review interrupted batches | Read and reconcile uncertain batches on the physical printer. |
| Swap cartridges | Select installed cartridges and confirm cartridge checks. |
| Hold/resume printing | Hold or resume automatic printing. |
| Stop after current label | Request a graceful hardware stop. |
| Emergency stop | Request an emergency hardware stop. |
| Configure printer | Edit hardware configuration, including the cover-check policy. |

View permission makes the destination available in the interface; operation grants
control its actions independently. Configuration does not imply printing, swapping,
stopping, or review rights. Users retain access to their own history and can cancel
their own queued work after losing destination access.

Group-scoped access governs group-addressed work, not every job or operation on
its member printers. Changing group membership requires Configure printer on the
group and on each newly added physical printer. Swap, stop, review, and physical
printer audit permissions cannot be granted through a distribution group.

A queue reader cannot cancel work, change quantities, or authorize requests.
An activity reader cannot reconcile uncertain output. Review permission permits
reading the uncertain physical batch, including labels routed through groups the
reviewer cannot otherwise access. It does not grant general completed-batch history.

With both Review batches and View everyone's print activity, a reviewer can report
previously confirmed copies as misprinted. This records a human correction without
changing the original charges or tape consumption. Offering a paid retry still
requires Start own/anyone's prints as appropriate; a free retry additionally
requires the cartridge's Approve use permission. Reporting alone never queues work.
Review photos follow current batch access, including after permission revocation.
Administrators choose Disabled, Optional (default), or Required evidence in
Administration → Account settings. The policy applies to both uncertain-batch
reviews and later misprint reports; disabling uploads retains historical evidence.

Selecting work for manual printing only holds unselected work when the operator
has both Start anyone's prints and Hold/resume printing. Stop commands intentionally hold the printer and
cancel its pending manual requests, even when the operator lacks a separate
hold/resume grant. Saving review never clears that hold. The PT-P710BT USB adapter
still cannot guarantee a mid-label stop or perform a standalone manual cut.

Session responses include `destination_permissions`; `destination_levels` remains
for compatibility with existing clients. New role grants use
`{"kind":"destination_permissions","destination_id":"…","permissions":["printer.view","printer.swap_cartridges"]}`.
Location rules are editable in both **Locations & access** and the role editor.
Both views edit the same stored rules, with separate printer and cartridge sections.
Roles accept `location_permissions` entries with `location_id`, `permissions` and
`denied_permissions`; destination entries also accept `denied_permissions`.

## Inheritance, ownership and overrides

For each resource permission, the resolver applies this order:

1. An individual printer/cartridge rule overrides location rules. A nested
   location overrides its ancestors.
2. At the same resource scope, a direct user rule overrides role rules.
3. At equal specificity, a deny overrides an allow from another role.
4. Without a matching allow, access is absent.

Administrator and individual printer/cartridge owner rights are protected from
resource denials. Global audit access remains protected for audit viewing.
A location owner may rename/reparent that location, transfer its ownership and
manage its user/role rules. Ownership alone does not grant rights on its contents
or on nested locations. Global **Manage locations** remains necessary to create
locations. Deleting an account leaves its locations unowned and preserves grants.

**Submit requests** and **Submit directly** are mutually exclusive editor choices.
Selecting Allow for one returns the other to Inherit. If inherited grants provide
both modes, the more specific grant determines the mode; equally specific old
grants prefer direct submission. Protected owners and administrators retain their
universal rights. Existing requests and approved labels remain valid when the
requester gains direct submission; this does not allow ordinary direct-submitters
to create new approval requests.

**Locations & access** filters by resource type, owner (including No owner) and
location (including Unassigned). Printer/cartridge location filters match their
recorded location; location rows match their parent. The **Permissions graph** can
be opened for a resource or from a user's Administration row. Choose a user,
resource/location and permission to trace applicable and overridden paths. Resource
editors show saved effective access and its origin when selecting a user. Unsaved
changes are evaluated in the existing access-impact preview before confirmation.
Graph responses contain only resources the viewer may inspect; a location owner
may inspect inheritance affecting that location's contents.

Upgrading from pre1 adds nullable location ownership and an allow/deny column.
Existing locations remain unowned, and existing grants remain allows. The migration
supports SQLite and MariaDB; back up before upgrading. Explicit denial rules must
be removed before downgrading to a version that cannot enforce them.

## Audit access and current coverage

`GET /api/audit` supports printer, cartridge, action, actor, victim, and search
filters with offset/limit pagination. Each field is redacted on the server using
current permissions before filtering and totals. Printer/cartridge View audit log
permits the relevant resource scope; **View all audit logs** also permits global
events. Global audit access does not authorize printer operations or bypass separate
accounting/private-content permissions.

Confirmed account, role, and content-group access changes currently record a global
change event and per-printer effective-permission changes. Previewing a change does
not record a successful mutation. Recording shares the mutation transaction; no
passwords or raw access-change payloads enter these events. Reading the audit API
records an access event. Application-wide action coverage and the audit UI remain
in progress; this is not yet a complete audit of every operation.

## Previewing access changes

Before a role or membership change takes effect, show the administrator each
affected user's effective access before and after the change. Require confirmation
before applying it. Include changes caused by overlapping role permissions, even
when a lower grant remains unchanged because a higher one applies. Recalculate
the impact if the underlying configuration changes before confirmation.

## Requests and revoked access

Administrators can delete accounts through the effective-access preview and
confirmation flow. Deletion immediately disables login, revokes sessions and
preview receipts, removes content-group memberships, and removes all owned
templates, images and fonts from use, including shared content. The last enabled
administrator is protected. Retained account and content data can be restored for
30 days under **Administration → Deleted accounts and content**. Account restoration
also restores its associated content and memberships in groups that still exist;
independently deleted content stays deleted. Roles removed during retention are
not recreated. Sessions are never restored.

Administrators may also delete individual images, fonts and templates regardless
of saved references. Deleted assets cannot be read, rendered for printing, or
re-enabled by the ordinary Hide/Restore controls. Dependent templates display a
notice, a file-and-question-mark image placeholder, or an Aa placeholder with a
question mark at the top right for missing fonts. Preview placeholders cannot be
printed. Global deletion permission also permits deletion of referenced assets in
that global library. Other font and image deletion operations require the asset
to be unused. All use the same 30-day retention period.

Queued jobs affected by deletion enter durable holds. Deleted dependencies must
be restored before those jobs can be released; replacing a template's asset does
not rewrite a frozen job. New jobs can use the repaired template. Restoring content
or an account never silently releases an existing hold. Printing already underway
may finish. Historical jobs and attribution remain, while their asset previews
show placeholders for removed data.

Restoration is rejected at the 30-day deadline even if cleanup has not run yet.
Cleanup runs at startup and hourly while the server is running, removes retained
asset files and template revisions, and removes expired account records. Used
registration codes remain spent. Minimal deletion records remain to identify
broken references; re-uploading the same file creates a new asset identity.

New registrations require an administrator-issued code by default; administrators
can enable registration without a code. Registration never grants administration.
Request only access requires approval; Print and higher permit direct submission.

Requests freeze label content and copy counts before review. Approval rechecks
the submitter's current access and the reviewer's scope. Only approval creates
executable jobs for a request, and repeating approval must not duplicate jobs.
Pending requests do not count toward printing thresholds.

Pending request owners may change individual label quantities without Print
access; other editors need Moderator access to the request's destination.
Queued quantities require Print access plus ownership or Moderator access, and
only unstarted, unreserved items without access/content holds may change.

Request responses include a monotonically increasing `revision`. Approval now
requires JSON `{"expected_revision": REVISION}`; the server rejects an outdated
revision with 409, even if quantities were changed back to their original values.
Clients must reload and review the updated request before retrying approval.
Quantity edits use `PUT /api/requests/{id}/labels/{position}/copies` with `copies`
and `expected_revision`, or `PUT /api/jobs/{id}/copies` with `copies` and
`expected_copies` for queued items. Counts must be integers from 1 through 1000.

If an account is disabled or loses the access required for queued work, pause the
affected queued jobs and show an administrator a dashboard notice. The
administrator explicitly chooses release or cancellation. Restoring access alone
does not resolve that hold. A user can still cancel their own queued jobs. Work
already being printed remains subject to the existing physical-outcome and
interrupted-batch review rules.

## Account recovery

Users manage their **Account email** under **Account settings**. Adding, changing,
or removing it requires their current password. A new address becomes usable only
after verification; the existing verified address stays active until then.
Removing it invalidates recovery links and disables the personal email subscription.

Verification and password-reset links are single-use and expire after 30 minutes.
Only token hashes are stored. Links are bound to the account's password state;
reset links also require its current verified email. Disabled or deleted accounts
cannot use them. Changing or resetting a password invalidates outstanding tokens.
An administrator can set a replacement password when recovery is unavailable.

**Forgot password?** accepts a username and gives the same response whether or
not that account has a verified email. Completing a reset revokes every session
and does not sign the user in automatically. A signed-in password change requires
the current password and preserves only the current session. Recovery requests
are rate-limited, and emailed links use the configured public URL.

## Notifications

Administrators configure ntfy or email endpoints in Administration. Each selects
event types and printer or distribution-group scopes. Ntfy endpoints also select
severity per event type; email uses the shared SMTP configuration.
Group scopes include operational alerts from member printers as membership changes.
Select all captures only current physical printers; groups remain manually selectable.
All current and future printers is a separate,
explicit choice. With neither option nor individual selections, printer event
types are disabled and cleared. Roles and application access levels do not affect
administrator-managed endpoint routing. Notification filters do not grant access to printers or
topics: configure ntfy subscription permissions separately.

Approval summaries sent to scoped endpoints include only requests addressed to
the selected logical destinations. Without destination restrictions, they include
all pending requests. Summaries collect requests during a configurable,
fixed interval starting with the first request. The interval survives restarts;
later arrivals do not extend it. Matching endpoints receive independent deliveries
and retries. Endpoint edits, disabling or deletion cancel pending deliveries.
Notification retries never approve or print jobs.

Personal subscriptions are managed separately under **Account settings** and send
only to the user's verified recovery address. Printer alerts require current
Moderator or Full access to the destination; physical printer alerts require
direct printer access even when a selected group includes that printer.
**All printers I can moderate** follows current access. Pending-request summaries
are administrator-only. General alerts go to their intended recipient, including
administrator alerts for administrator subscribers.

Delivery rechecks the subscriber's account status, verified address, and current
permissions. Revoking access or disabling an account prevents further matching
personal deliveries. Confirming a new email cancels pending deliveries addressed
to the old email. Subscriptions can be disabled when SMTP is unavailable.
Saving an unchanged endpoint or subscription preserves pending deliveries.

Per-printer event overrides replace the default operational event choices for
that physical printer. They cannot add a printer outside the endpoint's selected
scope, and personal overrides require direct Moderator or Full access. A selected
group may include the printer in an administrator endpoint's scope; personal
group access alone still cannot authorize its physical alerts. Group-wide waiting
reminders use the default event choices. Empty overrides silence a printer's
operational events; removing an override restores the defaults. Access and scope
are rechecked even when a saved override exists.

Ntfy priorities can be overridden for customized printer events, or inherited from
the endpoint's defaults. Priority changes do not expand routing scope. Combined
tape-waiting reminders use only the included destinations when choosing the
highest effective priority. Email subscriptions have no ntfy priority controls.

## Printing attribution and delegated drafts

Print Activity and batch details show Requested by, Approved by and the manual batch
starter separately. A direct Print-or-higher submission records the same user as
requester and approver. Automatic starts are identified as automatic. Access-hold
releases show the releasing administrator separately. Names and authorization are
captured at the event; each batch copy freezes its attribution before printing.
Later account changes and retry decisions do not rewrite previous attempts.
Historical events without reliable evidence display Not recorded.

Review records uncertain copies as printed, failed, or cancelled. It does not
authorize another charge. **Retry labels** requires batch visibility and Start
anyone's prints for someone else's labels (Start own prints for one's own).
Free retries additionally require Approve use on the funding cartridge. Paid
retries notify the original requester and remain pending until they accept a fresh
quote and maximum. Retry jobs preserve requester and saved artwork; earlier charges
remain unchanged. Free retries record actual consumption with zero new requester
charge. Neither path resumes a held printer. The legacy per-item requeue endpoint
returns a conflict directing clients to the explicit retry funding workflow.

When an administrator submits another user's CSV draft, ownership remains with
its author and Requested by displays Author (Administrator). If that author is
disabled, unavailable or lacks Print access to the destination, submission reports
the discrepancy without creating jobs. The administrator must explicitly confirm
an override to print under their authorization. The saved approval identifies the
administrator and the override. Queued override jobs recheck the authorizing
administrator's access; revoking that access pauses them for an administrator's
release or cancellation decision.

Overview lists all accessible physical printers and distribution groups, keeping
automatic holds local to their cards. Groups with unavailable members remain
visible with their queues; new work needs at least one configured member.

## Implementation boundaries

Keep permission decisions in application services and printer protocols in
adapters. Authenticate and authorize API operations, filter resource lists, and
recheck authorization after rendering outside the mutation lock.

Automated checks cover role combinations, scoped access, template ownership,
physical-printer review, confirmed access changes, revoked-access holds,
delegated drafts, and retry-safe approvals. See [README.md](../README.md#development)
for check commands.

## Changing a queued printer

The global `queue.change_printer` permission ("Change printers for queued work")
allows printer substitutions only when the operator also has Moderator or Full
access to both the original destination and the replacement printer.
Administrators have all three permissions. Grant the global permission explicitly
through a role; existing non-administrator roles do not receive it automatically.

Select queued items and use **Change printer**. All remaining queued copies of
an item or CSV run must move together. Printing, review-required, reserved, or
access-held work cannot move. The replacement must support the saved resolution
and printable area. Tape requirements remain unchanged; normal cartridge and
readiness checks still apply. Automatic printing may start after the change.

Activity records the operator, timestamp, original destination, replacement
printer, prior CSV printer assignment, affected copies, and optional reason.
Saved names survive later renames or account deletion. Future print attempts
retain the substitution history alongside the original requester and approval.
The substitution operator authorizes the new destination; losing their required
permissions pauses the work under the existing access-hold rules. An explicit
administrator release remains an audited exception to access holds.

Stop the server and run `alembic upgrade head` before restarting after this update.
