# Gruppenkassen: shared billing accounts

Status: included in 0.14.0; automated verification completed. Manual
deployment acceptance remains pending.
See [Group accounts](GROUP_ACCOUNTS.md) for operation, permissions,
migration requirements and manual acceptance checks.

## Agreed behavior

- Each Gruppenkasse is an independent billing account. Users and roles receive
  account-specific permissions; an account is not tied to an existing permission group.
- Members retain their personal login, requester attribution and normal printer
  and cartridge permissions. Selecting a paying account grants no printing rights.
- A member who needs billing approval chooses between:
  - **Wait for approval:** printing cannot start until the group accepts the charge.
  - **Print at my expense:** printing can proceed under the member's existing
    permissions. The member remains liable unless the group subsequently accepts.
- A separate **Charge directly** permission permits group-funded printing without
  a billing approval request.
- Existing outstanding print debts can be transferred to a group account.
- Previously paid print costs can be reimbursed by the group. Original charges
  and payments remain in the history; a reimbursement is a separate obligation
  from the group to the member, not another payment to the cartridge owner.
- Preserve cartridge attribution, original requester, actual costs, accepted
  prices, currency and the recipient of each original charge.
- Transfers, approvals, rejections and repayments must be explicitly audited.
- Members cannot approve their own requests. Charge directly remains the separate
  permission for bypassing another person's approval.
- Group-funded printing on a member's own cartridge creates a debt from the group
  to that member at the calculated printing cost.
- Group approval is sufficient to take over outstanding personal debt; the
  cartridge owner's approval is not required.
- Notify eligible approvers about new requests and notify requesters of decisions,
  including requests for historical debt transfers and paid-print reimbursements.
- Repayment receipt must be confirmed by the creditor or someone with global
  accounting access. The group's Record payments permission allows reporting a
  payment for confirmation; it does not itself settle the obligation. This also
  applies to reimbursements payable to members.

- Rejected Wait for approval requests keep their labels on hold until the requester
  explicitly chooses personal payment or cancellation. Printing never silently
  switches to personal liability.

## Request notifications

- Cover both print-funding modes, outstanding-debt transfers and paid-print
  reimbursement requests.
- Notify active users who can approve the specific request through their current
  user or role permissions. Exclude the requester because self-approval is forbidden;
  do not broadcast requests to every account member.
- Notify the requester when a request is approved or rejected. Link directly to
  the request, where its account, decision and recorded reason can be reviewed.
- Notify the creditor when a group reports a payment requiring confirmation, and
  notify the reporting member of the resulting decision. A reported payment remains
  pending and does not reduce balances until an authorized recipient confirms it.
- Keep notifications in the in-app inbox even without external delivery channels.
  Email, push and other configured delivery channels follow the recipient's
  notification preferences.
- Recheck access before exposing request details or delivering an approver alert.
  Cancel outstanding actionable alerts when the request is resolved or withdrawn;
  keep the decision and audit history.
- Request notifications must not expose label previews, field values or unrelated
  financial history. Following a notification link must enforce current access.
- Write notifications in the same transaction as the request or decision. Retrying
  submission or approval must not create duplicate notifications, and a delivery
  failure must not roll back the billing decision or change print eligibility.

## Account permissions

Separate account-scoped rights for viewing balances/transactions, requesting
charges, charging directly, approving charges, requesting historical transfers,
approving historical transfers, recording payments, editing/archiving the account,
managing its grants, and viewing its audit log. Grant these to users and roles using
the existing allow/deny conventions. Account creation needs a global permission.

Financial access alone must not expose label previews, template inputs or
unrelated personal transactions. Current approvers explicitly receive preview access
to their pending print-funding requests, without broader printer queue access.
Existing recipient/accounting authorization for
recording receipt of a payment must not be weakened by account membership.

Payment confirmation uses creditor identity or global accounting access, not the
group's Approve charges permission. No self-approval applies to funding requests;
a member receiving a reimbursement can still acknowledge receipt as its creditor.

## Implementation structure

1. Add shared-account identity, grants and billing-request records with SQLite and
   MariaDB migrations. Existing work continues to use personal billing by default.
2. Separate the requester from the paying account in saved jobs and charge
   attribution. Preserve immutable financial history with explicit transfer and
   reimbursement entries rather than overwriting earlier transactions.
3. Add billing selection and the two approval modes to submission, including CSV
   runs and image jobs. Keep billing approval separate from permission to print.
4. Enforce pending billing approvals at every dispatch path, including automatic
   batches, explicit print actions and companion dispatch. Resolve authorization
   on the main server before granting a companion permission to execute a batch.
5. Include billing decisions in price consent, cancellation and retry handling.
   Free retries must remain free; accepting group funding must not bypass the
   existing price cap or authorize arbitrary future price increases.
6. Add group balances, charge details, transfer/reimbursement requests, approval
   views, payment recording, notifications and permission-aware audit views.
7. Test mixed personal/group billing, duplicate requests, partial repayments,
   concurrent approval/settlement, rejection, permission revocation, archived
   accounts, failed prints and both database backends. Verify request notifications
   for direct and role-based approvers, exclusion of self-approval, outcome delivery,
   revoked access, duplicate submissions and failed external delivery.

## Existing accounting constraints

- `app/usage.py` records physical usage per batch/requester in `TapeAllocation`,
  but already records per-job amounts in `UnitCharge`. A requester may submit
  personal and group-funded jobs in the same batch; funding must not be inferred
  from the batch/requester aggregate alone.
- `app/cartridge_debts.py` retains cartridge attribution and assigns repayments
  to cartridges, defaulting to oldest debts. Historical transfer calculations
  must account for these allocations and partially settled charges.
- `app/usage_accounts.py` and `app/accounting_api.py` currently assume individual
  users are the paying and receiving parties. Group balances need explicit party
  types, rather than fake user accounts or ambiguous IDs.
- Existing self-owned-cartridge accounting excludes personal self-debts. Group-funded
  use must instead create the agreed obligation from the group to the cartridge owner.
- Existing notifications use a durable outbox and a permission-filtered in-app inbox.
  Group requests need their own recipient checks throughout routing and inbox reads;
  adding a new notification category alone must not allow shared administrator
  delivery endpoints to receive private group financial information.

Historical reimbursement uses explicit cartridge payment allocations, oldest-first.
Accepted group entries prevent the same cost being transferred or reimbursed twice.
Unallocated legacy payments require accounting reconciliation before a historical
transfer; they are never guessed. Original personal charges and receipts stay intact.
