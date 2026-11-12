# Tape, costs and payments

[All guides](README.md) · [Project overview](../README.md)

A tape profile describes the tape you want to use, such as black on white at 24 mm. A cartridge is the physical cassette in the printer. The application estimates remaining tape and costs; it cannot measure the amount left on the roll.

## Confirm the installed tape

If a third-party TZe cartridge reports an unrecognized type or a different width,
users with Full access on the printer can select **Confirm cartridge** in
**Cartridges** or **Printers & groups**. Review the selected cartridge against the
detected media and choose **Yes, I’m sure** to use the selected width for printing.
New cartridge installations show the same confirmation when needed. Hardware
faults still block printing, and an observed cartridge change requires confirmation
again. **Detected details** in **Printers & groups** shows the reported type,
width, colors, error flags and raw status packet.

By default, an observed cover opening pauses printing until a user with Full
access confirms that the selected cartridge is still installed or selects a
different one. Closing the cover alone does not resume the queue. Turn off
**Confirm cartridge after opening** on that printer in **Printers & groups** to
disable this check. Hardware faults and unconfirmed detection mismatches still
block printing.

## Check an estimated cost

Before submission, individual label previews and validated CSV drafts show an
approximate cost for all selected copies as one batch, including feed, unused
tape and one leader. The queue shows a current estimate for remaining copies.
Matching installed cartridges supply the price; when none are installed, known
cartridge prices are shown as an inventory estimate. Groups can show a range or
separate currencies. Missing prices remain unavailable. These estimates can
change with cartridge prices, routing, shared batches or retries.

## Set prices and view usage

Set the purchase price and currency when registering a cartridge, or expand
**Price** on its card. **Tape usage** shows each signed-in user's allocated tape
and cost. **View other users’ usage and balances** permits selecting **All users**
or an individual user. Different currencies stay
separate.

## How costs are shared

The **leader** is the tape fed out before the first label in a batch. **Feed** is
the tape around each label. These amounts count toward the cost, along with the
label itself and any unused tape needed for cutting.

Each attempt charges the original requester, including approved requests and
CSV runs. It includes design, feed, minimum-length padding, and a proportional
share of the batch leader and any shared strip padding. Shares follow each
requester's physical label lengths, including per-label feed and unused tape.
Cost is allocated consumption divided by the cartridge's nominal length,
multiplied by its purchase price. Cartridge remaining-length corrections do not
change historical charges.

Requester shares and prices are frozen before printing. Successful attempts use
the same consumption total deducted from the cartridge; that total may be an
estimate. Interrupted attempts remain pending until review supplies the total,
which is allocated across the frozen requester shares, including wasted tape.
Retries are separate attempts. A guaranteed failure before printing charges zero.
Changing a price affects future attempts only. Missing prices remain **Unpriced**,
not free. Print costs from before cost tracking was introduced are not
reconstructed. Costs retain millionths of currency, and requester tape
allocations retain thousandths of a millimetre, with rounding shared so totals
remain consistent.

## Understand balances and repayments

Account balances equal recorded adjustments minus settled, priced print costs,
including costs already tracked before account balances were introduced. Negative
balances are amounts owed; positive balances are credit. Pending and unpriced tape
does not affect the balance. Negative balances do not block printing.
A payer can report a payment for the recipient or an accounting editor to confirm.
The balance changes only after approval. Recipients can record repayments made to
them; accounting editors can also record corrections. Subtracting from a balance
as a correction is restricted to accounting editors. Reasons and the person who
recorded the change remain in the history.

## Share costs with a group

Group accounts let members allocate prints to a shared association account while
keeping their personal login and printing permissions. Members can wait for funding
approval, print at their own expense pending approval, or charge directly when
permitted. Earlier unpaid debts and paid-print reimbursements can also be requested.
Payment reports require receipt confirmation by the creditor or global accounting.
See [group accounts](GROUP_ACCOUNTS.md) for permissions, notifications,
setup and repayment instructions.
