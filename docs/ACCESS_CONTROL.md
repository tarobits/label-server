# Access control

Roles control application and printer access. Template ownership and group
membership control template sharing. These rules are implemented.

## Roles and user groups

Roles contain permission objects and are assigned directly to users. A role can
contain application permissions and access levels scoped to individual printers
or distribution groups. Multiple applicable role permissions combine by taking
the highest access level; No access does not override a higher applicable level.

User groups centralize and share templates. They never assign roles or confer
printer permissions. Roles do not grant access to specific templates. Template
ownership, scope and group membership determine which templates are available;
the membership settings below govern collaboration within a template group.

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

Registration codes can assign template groups with independent create, edit
others, and delete others permissions for each group. Selecting a group with all
three permissions off grants view-only membership. Codes issued before these
settings were available retain their original create-only membership.

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

Each permission object in a role identifies its printer or distribution-group
scope and one of these levels:

| Level | Abilities within the granted scope |
| --- | --- |
| No access | Cannot submit to this destination. |
| Request only | Preview and submit print requests for approval. |
| Print | Submit without approval and start own queued jobs. |
| Moderator | Print abilities, manage all users' queues, and approve/reject print requests. |
| Full | Moderator abilities and configuration of the scoped printer or distribution group. |

Users can always cancel their own queued jobs, including when their printer access
has been revoked. This ownership right does not authorize new submissions.

Distribution-group access permits use only through that group. It grants no
direct access to any member printer. A group Moderator manages jobs and requests
addressed to that group, rather than every job handled by its member printers.

Full access to a distribution group permits changing its settings and membership.
Adding a printer additionally requires Full access directly on that printer.
Configuring an individual printer always requires Full access directly on it.

Interrupted-batch review requires Moderator or Full directly on the physical
printer. Distribution-group permissions cannot authorize batch review. Once the
physical printer has produced an uncertain result, its authorized reviewer must
be able to reconcile that batch, including work routed through a group.

**Stop after current label** requires Moderator directly on the physical printer.
**Emergency stop** and any future standalone cutter operation require Full
directly on it. Distribution-group access never grants these hardware controls.
The PT-P710BT USB adapter currently does not support standalone manual cutting.
Stop requests are saved with the actor and time in the batch history before the
hardware worker is signaled. Stopping holds automatic printing and cancels pending
manual requests on that device; reviewing output does not remove the hold.

## Previewing access changes

Before a role or membership change takes effect, show the administrator each
affected user's effective access before and after the change. Require confirmation
before applying it. Include changes caused by overlapping role permissions, even
when a lower grant remains unchanged because a higher one applies. Recalculate
the impact if the underlying configuration changes before confirmation.

## Requests and revoked access

Administrators can delete accounts through the effective-access preview and
confirmation flow. Deletion immediately disables login, revokes sessions and
preview receipts, removes template-group memberships, and removes all owned
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
printed. Other users' permanent-image-deletion operations still require the image
to be unused and use the same 30-day retention period.

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

If an account is disabled or loses the access required for queued work, pause the
affected queued jobs and show an administrator a dashboard notice. The
administrator explicitly chooses release or cancellation. Restoring access alone
does not resolve that hold. A user can still cancel their own queued jobs. Work
already being printed remains subject to the existing physical-outcome and
interrupted-batch review rules.

Administrators configure ntfy endpoints in Administration. Each endpoint selects
event types, printer or distribution-group scopes, and severity per event type.
Group scopes include operational alerts from member printers as membership changes.
Select all captures only current physical printers; groups remain manually selectable.
All current and future printers is a separate,
explicit choice. With neither option nor individual selections, printer event
types are disabled and cleared. Roles and application access levels do not affect
endpoint routing. Notification filters do not grant users access to printers or
topics: configure ntfy subscription permissions separately.

Approval summaries sent to scoped endpoints include only requests addressed to
the selected logical destinations. Without destination restrictions, they include
all pending requests. Summaries collect requests during a configurable,
fixed interval starting with the first request. The interval survives restarts;
later arrivals do not extend it. Matching endpoints receive independent deliveries
and retries. Endpoint edits, disabling or deletion cancel pending deliveries.
Notification retries never approve or print jobs.

## Printing attribution and delegated drafts

Activity and batch details show Requested by, Approved by and the manual batch
starter separately. A direct Print-or-higher submission records the same user as
requester and approver. Automatic starts are identified as automatic. Access-hold
releases show the releasing administrator separately. Names and authorization are
captured at the event; each batch copy freezes its attribution before printing.
Later account changes and retry decisions do not rewrite previous attempts.
Historical events without reliable evidence display Not recorded.

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
