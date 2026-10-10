# Access control: agreed design

Implemented against the decisions confirmed on 2026-10-04. This specification
supersedes the earlier permission matrix. Integration tests, browser tests and
independent reviews cover the agreed model; verification results are below.

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
templates in groups they have not joined. Only administrators may publish global
templates.

Administrator authorization must not depend on enumerated resource grants or
group membership. Newly created resources are automatically covered, and an
administrator must never receive a permission-denied result caused by a missing
grant. Ordinary validation, missing-resource errors and physical printer state
still apply. The role is protected from deletion or loss of its universal access;
at least one active administrator must remain.

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

## Previewing access changes

Before a role or membership change takes effect, show the administrator each
affected user's effective access before and after the change. Require confirmation
before applying it. Include changes caused by overlapping role permissions, even
when a lower grant remains unchanged because a higher one applies. Recalculate
the impact if the underlying configuration changes before confirmation.

## Requests and revoked access

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

Administrator request notifications use the configured ntfy topic, restricted to
administrators. Summaries use a configurable, fixed debounce window beginning
with the first request, survive restarts, and cannot be postponed indefinitely by
continuous arrivals. Notification retries never approve or print jobs.

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

## Implementation boundaries and acceptance

Keep permission decisions in the application/service layer. Printer protocol
details remain in adapters, with no printer-specific concerns in queue/domain
logic. Authenticate and authorize every API operation, filter resource lists, and
recheck authorization after rendering outside the mutation lock.

Completed implementation stages:

1. Role permission objects, direct user-role assignments, protected Administrator,
   and per-member template-group settings; remove role inheritance from groups.
2. Scope-aware authorization for templates, printers and distribution groups,
   including owner editing/deletion and cancellation rights.
3. Administrator previews and confirmation of effective access changes.
4. Scoped moderation, physical-printer batch review, durable queued-job holds and
   administrator release/cancel decisions with dashboard notices.
5. UI, migrations and integration documentation, followed by adversarial tests,
   browser tests and independent code review.

Acceptance must cover all five printer levels; role combinations; group access
without direct printer access; adding printers to groups; physical-only batch
review; independent template membership settings; administrator access to future
resources and non-member templates; confirmation of access changes; revocation
holds; ownership rights after revocation; and retry-safe approvals/notifications.

Verification on 2026-10-04: 269 backend tests and 28 Chromium browser tests passed,
including migration upgrades/round trips, permission bypass attempts, scoped CSV
preparation, interrupted-batch review and access-change holds. Ruff, mypy, frontend
formatting and the production frontend build passed. Both Compose configurations
validated. Independent backend and UI reviews were completed and their findings
addressed; desktop and mobile access-control screens were visually inspected.
Verification used isolated databases and test printer adapters. The live database
and physical printers were not changed by this integration.

Follow-up verification on 2026-10-09: 283 backend tests and 34 Chromium browser
tests passed, including explicit delegated overrides, authorizer revocation,
per-attempt attribution and unavailable-group handling. Static checks, frontend
build/formatting and Compose validation passed. Independent review found no
remaining blockers. Tests ran against the current checkout with isolated data and
printer adapters.
