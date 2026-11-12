# Group accounts (Gruppenkassen)

Group accounts let members use their own logins while charging an association's
account. They are independent of permission groups. Printer, cartridge, template
and queue permissions still apply to the original requester.

## Setup and permissions

Open **Group accounts** to create an account, then open its **Permissions** section
to grant access to users or roles. Creating accounts requires administrator access
or the global **Create group billing accounts** permission. The creator receives
the account's permissions; administrators retain access.

Account permissions are independent:

| Permission | Allows |
| --- | --- |
| View balances and transactions | Read the account's charges, balances and requests |
| Request print funding | Submit approval requests, waiting or printing at personal risk |
| Charge directly | Use the account without another member's funding approval |
| Approve print funding | Accept or reject another member's print funding requests |
| Request historical transfers and reimbursements | Request funding for one's previous print costs |
| Approve historical transfers and reimbursements | Accept or reject another member's historical requests |
| Report payments for confirmation | Report a payment; receipt still requires confirmation |
| Edit and archive account | Rename or archive the account |
| Manage account permissions | Assign user and role allow/deny rules |
| View account audit log | Read the account's financial and permission-change events |

A user rule takes precedence over role rules; equally specific role denies win.
Group-account grants do not grant printer access. Approval permission includes
previews of the associated funding requests and charges described below. Requesters
can still read their own requests, and creditors can see obligations owed to them,
without receiving access to other members' transactions.

## New prints

Choose **Paying account** on New label or CSV runs. The API also accepts `billing`
on text and image submissions, print-approval requests, and CSV preparation:

```json
{"account_id": "account-id", "mode": "wait", "note": "Workshop supplies"}
```

- **Wait for approval** (`wait`): labels remain held until approved. Rejection
  leaves them held until the requester selects **Pay personally** or cancels them.
- **Print at my expense pending approval** (`risk`): printing may proceed under
  the requester's ordinary permissions. The requester owes the costs unless the
  group accepts. Costs already paid become a reimbursement payable to the member.
- **Charge the group directly** (`direct`): requires Charge directly; no approval
  request is sent to other members.

Funding approval is separate from print approval. If printer access requires a
print request, its approval creates the queued jobs and their funding requests.
For CSV runs, each row and its copies is a separate funding request.

Collapsed queue entries show the payer, including pending approval. Print Activity
shows the current payer or payers for each batch, including later approved
transfers and reimbursements; original requester and authorizer attribution stays
unchanged.

Group funding requires a current price quote with a priced eligible cartridge.
Its upper estimate and any lower requester maximum cap the charged amount. Copies
cannot be increased under an existing quote. Funding never permits a cartridge
substitution that would bypass cartridge permissions or price consent.

Members cannot approve their own funding requests, including administrators.
Use Charge directly instead. Printing with one's own cartridge creates a group
obligation payable to that member; it is not discarded as personal self-use.

Archiving an account or revoking the relevant spending/approval permission holds
approved work that has not started. Existing debts remain payable. A companion
that already received authorization for an entire batch can finish it during a
connection outage, as before. Funding checks run on the main server before that
authorization is issued.

Free retries remain free. Requester-paid retries require the existing acceptance
flow and start as personal spending; the member can request a historical transfer
afterwards. An earlier group approval does not authorize additional retry spending.

## Earlier prints and repayments

Tape usage includes group obligations in **Account balances** and **Debts by
cartridge**, with the group account identified as payer and linked to its balances.
The selected-user filter includes that user's prints and money owed to them.
**All users** includes all group debts the viewer may see; it does not bypass group
permissions. Only confirmed repayments reduce the displayed amount owed.

Use **Transfer previous print costs** to request funding for a previous settled
batch's costs attributed to you. Group approval is sufficient to take over its
outstanding debt. A member with both the historical-transfer and Charge directly
permissions can transfer costs directly.

The **Transfer previous print costs** button opens a dialog showing your own
labels in each batch. Select individual label entries; each selection includes
all copies of that label in that batch. The cost includes its recorded share of
leader and strip padding. The selected labels and amounts are frozen in the
request, and overlapping pending transfers or already funded labels cannot be
claimed again. Separate labels from the same batch can be transferred separately.
Older batches without recorded per-label costs cannot use selective transfers.

Previews can be enlarged. **View prints** on a charge and the request-details
dialog show only the associated labels, their copy counts and outcomes. Historical
transfers show the selected labels too. **View batch** opens Print Activity when
the viewer already has access to that batch; group funding permissions do not
grant access to unrelated labels in the same physical batch.

The charge's type identifies **Print funding** or **Historical transfer**. Its
separate accounting detail identifies cartridge cost, use of one's own cartridge,
or reimbursement; these details do not describe when funding was requested.

The original charge and personal repayment records are retained. Transfers reduce
personal debt with a separate entry; paid costs create a separate reimbursement
owed by the group to the member. Partially paid prints split into these two parts.
Every entry retains its cartridge and currency. Previously funded costs cannot be
claimed again, and competing pending requests for the same costs are blocked.

Historical payments explicitly allocated to cartridges are matched oldest-first.
Within a batch, the already-paid amount covers the selected labels first, up to
their combined cost. That portion becomes a reimbursement; any unpaid remainder
becomes transferred debt. Remaining personal costs and payments stay available
for subsequent transfers without duplicating earlier claims.
Unallocated personal account credits/corrections must be reconciled with cartridge
allocations by accounting before those historical costs can be transferred. The
system does not guess which print an ambiguous payment covered.

**Record payment** defaults to the oldest outstanding group debts for the chosen
recipient and currency. Select cartridges to restrict the allocation. A member
with Report payments can submit the report, but debts are reduced only when the
creditor or a user with global accounting access confirms receipt. This also
applies to reimbursement payments. Duplicate confirmations do not settle twice;
if the selected debts were settled meanwhile, the report must be rejected and
replaced with a current one.

An ownerless cartridge can accrue group debt. Its first subsequently assigned
owner receives that debt; later ownership changes do not redirect past charges.

## Notifications and audit

Eligible approvers receive new-request notifications. Requesters receive decisions;
creditors receive payment-confirmation requests. The in-app inbox works without
external channels. Personal email, push and ntfy delivery follow existing General
notification preferences. Shared operational endpoints do not receive these private
financial messages.

Notifications link to the account request. Access is checked again when reading
or delivering an actionable notice. Resolved and withdrawn requests no longer
leave actionable approval alerts. Notifications do not include label previews or
field values. Funding decisions open in a modal with saved label previews and copy
counts. Requesters and administrators can view them, as can current approvers:
**Approve print funding** for print requests and **Approve historical transfers
and reimbursements** for historical transfers. This applies to pending and resolved
requests and their charges, even without printer queue access. Access is rechecked
on every details and preview fetch; revoking approval permission removes that
access. Balance-viewing permission alone does not expose previews.

The group funding page uses separate sections for requests, balances and charges,
payments, history, settings, permissions and audit events.
Only permitted sections are shown. Queued labels awaiting funding display
“Waiting for group approval”; rejected or otherwise held funding has its own status.

Account events cover creation, settings, grants, funding, transfers, reimbursements
and payment decisions. They are also recorded in the global audit log, with
financial identifiers subject to its existing accounting redaction rules.

## Deployment and acceptance

Available from 0.14.0. Migration `181819fa30f6` adds six
`billing_*` tables on SQLite and MariaDB. It does not assign existing prints to
groups or rewrite old payments. Back up the database before upgrading. Once group
accounts exist, schema downgrade is refused; restore a coordinated backup for
rollback. Database migration, backup and restore scripts include the new tables.

- [ ] Create an account and verify user/role allow/deny precedence.
- [ ] Verify that balance-viewing permission alone cannot view label previews or grant printing access.
- [ ] Review pending and resolved funding in its modal without queue access; verify previews stop being accessible after approval authority is revoked.
- [ ] Submit wait, risk and direct prints, including CSV rows and image API jobs.
- [ ] Reject a wait request; verify it stays held until personal payment or cancellation.
- [ ] Attempt self-approval; verify rejection even for administrators.
- [ ] Mix personal and group jobs from one requester in a physical batch.
- [ ] Print using the requester's own cartridge, then verify the group owes that member.
- [ ] Transfer unpaid, partially paid and fully paid historical costs; verify original records.
- [ ] Select some labels from a shared batch; verify their exact costs, all copies, and leader shares transfer, and unrelated labels stay private and unfunded.
- [ ] Try duplicate transfers and payment confirmations; verify no double funding or settlement.
- [ ] Report a payment as a member; verify only creditor/accounting confirmation reduces debt.
- [ ] Check oldest-debt defaults and explicit cartridge selection across currencies.
- [ ] Verify inbox and personal external notifications, including after access is revoked.
- [ ] Archive the account or revoke spending permission before dispatch, including companion go authorization.
- [ ] Exercise failed prints, free retries and separately accepted paid retries.
- [ ] Restore a backup with group balances and compare requests, charges and payment allocations.
