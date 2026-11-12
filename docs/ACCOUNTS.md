# Accounts and access

[All guides](README.md) · [Project overview](../README.md)

Your account keeps your labels and settings separate from other people’s. Administrators decide who can use each printer, approve requests or manage shared content.

## For administrators: manage access

Manage users, roles, template groups, and registration codes under
**Administration**. Registration requires a code by default. Roles are assigned
directly to users; the highest applicable permission wins.

## Sign in and recover your account

Add an **Account email** in **Account settings** and confirm the emailed link before
using **Forgot password?** on the sign-in screen. Adding, changing, or removing
the address requires your current password. Recovery links expire after 30 minutes
and work once. Resetting a password ends all sessions and invalidates outstanding
recovery links; sign in again afterward. Administrators can still set a replacement
password through the user editor when email recovery is unavailable.

Sign in with your username or verified account email. Administrators can change
usernames through the user editor; account IDs, ownership, and existing sessions
are preserved. Account emails are unique when verified. If older accounts already
share an email, use their usernames until each has a separate verified address.

## Delete or restore an account

Only administrators can delete accounts, after reviewing and confirming the impact.
Deletion ends all sessions and removes the user's templates, images and fonts from
use, including shared content. The account and content can be restored together
for 30 days. Items deleted independently beforehand stay deleted. The last enabled
administrator cannot be deleted. Print history and its saved attribution remain;
restored users must sign in again. A print already underway may finish.

## Understand printing permissions

| Destination access | Allowed actions |
| --- | --- |
| Request only | Submit labels for approval. |
| Print | Submit directly and start own queued jobs. |
| Moderator | Also manage scoped queues and approve or reject requests. |
| Full | Also configure the granted printer or distribution group. |

Group permissions apply through that group and grant no direct printer access.
Interrupted-batch review requires Moderator or Full directly on the physical
printer. Content groups share templates, fonts and images and never assign roles.
Owners can edit or delete their own content and cancel their own queued jobs after
losing printer access. Roles independently grant creation of personal or global
content and editing or deleting other users’ global content for each type. The
default Member role includes personal template creation and personal font and
image uploads. Registration codes can assign independent collaboration permissions
for each content type in each selected group.

## When printing needs approval

Pending requests do not count toward thresholds. Disabling a user or revoking the
access needed for queued work pauses those jobs for an administrator to release
or cancel. Restoring access alone does not resume them. Submitting another user's
CSV draft as an administrator requires an explicit override if the author's
access is insufficient. See [access control](ACCESS_CONTROL.md) for details.

## Manage signed-in devices

In **Account settings**, change your password, view active login sessions, or sign
out one device or all other devices. Session details show when a device signed in
and was last active. Reduced-motion preferences apply separately in each browser.

## View release changes

Select the version in the footer to open the changelog. A notice links to newer
releases. After an upgrade, each account sees the releases since its last visit
once, across browsers; the first visit establishes a baseline.
