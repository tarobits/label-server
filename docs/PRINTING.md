# Printing and the queue

[All guides](README.md) · [Project overview](../README.md)

Start here to connect a printer and print a label. A queue is the list of labels waiting to print; a batch is a set printed together. If you cannot see a control mentioned below, ask your administrator to check your access.

## Set up and print

1. Add your printer under **Printers & groups**. USB serial is optional for one
   device; multiple devices require a distinct serial on each registration.
2. Create a **Tape profile** with the tape width, ink and background colors, and
   automatic-print threshold.
3. Register the physical cassette under **Cartridges** and assign it to the
   printer chosen in that page's **Printer** selector. Installed badges identify
   each cassette's printer. This selection is separate from **Design destination**;
   each cartridge keeps its remaining-length estimate across swaps.
4. Create a layout under **Templates**, then open **New label**, choose the tape
   profile and **Print destination**, fill in the fields, and submit copies.
5. Check **Overview** or **Print queue**. Compatible copies print when their
   profile threshold is reached. Use a manual print action to print them sooner.

## Why a label might wait

The automatic-print threshold is the number of waiting copies needed before
printing starts. A tape profile describes the tape width and colors you selected.

Compatibility requires the exact tape profile, a ready printer, and the correct
detected tape width. The printer detects width; you select the cartridge to
identify its colors. Different profiles do not share a threshold.

## Pause or stop printing

**Hold automatic printing** lets you accumulate a larger batch. It survives
restarts, permits manual printing, and does not interrupt a batch already started.
Resuming can immediately start a batch that has reached its threshold.

Printer cards on **Overview** also provide **Stop after current label** for direct
Moderators and **Emergency stop** for direct Full access. Both hold automatic
printing on that printer and cancel its pending manual requests. Emergency stop
is processed at the next command boundary or status check; an in-progress USB
transfer can delay it. A label already printing may finish: physical PT-P710BT
testing, including a longer-label repeat, did not interrupt the active label.
Treat this control as a cancellation request with no guaranteed mid-label stop.
Interrupted copies require review, and saving review does
not clear the hold. You can explicitly print manually or resume automatic printing.

## Review interrupted prints

In batch review, select individual uncertain copies, select all, or use **Select
from here** to include that row and all following uncertain copies. Choose
Printed, Requeue, or Cancel and apply it to the selection before saving. Confirmed
copies remain locked; total tape consumption must still be entered.

## Feed and cut tape

The PT-P710BT USB driver has no documented standalone cutter command. **Cut tape**
is disabled; while the printer is idle, double-press its physical power button to
feed and cut. Automatic cuts during printing continue to use the printer settings.

## Understand the queue

Queue thresholds count copies per destination and tape profile. A manual print
request freezes its selected copies when accepted; newly submitted copies wait
for another batch. Removing queue items cancels queued copies and retains history.
Printing and uncertain copies require batch review.

## Change quantities

Use **Change copies** on an unstarted queued item to set its quantity (1–1000).
This requires Print access to its destination and either ownership or Moderator
access. Reserved, previously attempted, partially printed, and held items cannot
be resized. Saved content and ownership remain unchanged.

Owners can also change quantities in their own pending print requests without
Print access; moderators can edit requests for their destinations. Each edit
invalidates older approval views, which must be reloaded and reviewed. Changes
apply to the selected label, including individual CSV rows.

## Print only selected labels

**Print selected** prints only the selected compatible copies. Moderator selections
also hold automatic printing for that destination so other copies stay queued;
resume from its Overview card when ready. Print-level users can select their own
copies without holding other users' work. A pending manual flush prevents cartridge
reassignment; **Cancel pending flush** releases it without cancelling the jobs.

## Use printer groups

A printer group routes work to its first ready member with the exact profile
installed. Members must have matching printable geometry and resolution
capabilities, including default resolution. Missing tapes leave work queued.
CSV runs stay on their first assigned printer to preserve order. Choose the
submission destination separately from the sidebar's **Design destination**,
which sets editor geometry. See [printer architecture](PRINTER_ARCHITECTURE.md).

## Recover after a printing problem

If printing is interrupted, that printer pauses for review. Open the pause banner
or **Activity**, inspect every uncertain copy, mark it **printed**, **queued**, or
**cancelled**, and enter the **total tape consumed by the attempt**, including
confirmed labels and waste. Confirmed copies cannot be changed. In-flight batches
also require review after a server restart; uncertain copies are never retried
automatically. Other printers can continue.

If an attempt fails before any printing starts, its labels stay queued and its
manual print request ends. Automatic printing for that destination is held until
someone retries manually or resumes it. The worker does not repeatedly retry the
failed attempt or create duplicate failure entries on every poll.

## Find previous prints

**Activity** shows saved label previews, outcomes, requester, approver, and manual
batch starter. Each attempt preserves its attribution after retries or account
changes. Older events without reliable attribution show **Not recorded**.
Print batches and notifications have separate history pages, with 25 records per
page. **Previous** and **Next** browse older records; **Latest** returns to current
activity. Reloading or using browser back preserves the selected pages.

## Remove repeated failed attempts

Administrators can use **Purge duplicates…** in Activity to preview and permanently
remove repeated failures where printing never started. Matching requires the same
label copies, printer, cartridge, error and print settings; separate manual print
requests stay separate. The oldest attempt in each group remains. The purge also
deletes redundant label-history rows, zero-use tape allocations, and notifications
explicitly linked to those attempts, including delivery records. Printed,
reviewed, unfinished, charged and unsettled attempts are excluded, so tape usage
and account balances do not change. General printer alerts without a batch link
remain. This deletion cannot be undone.

## Manage cartridges

Tape usage entries identify their cartridge and tape profile. The **Cartridge**
filter narrows usage totals and recent allocations for the selected user or all
users. Account balances and payments always include all cartridges.

Users with **Manage tape profiles and cartridges** can rename cartridges, archive
them from active inventory, and restore them using the **Archived** inventory view.
Archived cartridges are excluded from installation choices and new cost estimates;
their print history, usage and charges remain available. Remove an installed
cartridge from its printer and resolve pending prints or uncertain consumption
before archiving it. **Delete permanently** removes only cartridges without print
or queue history, after confirmation; used cartridges can be archived instead.

Cartridge lengths are estimates, not sensor measurements; calibrate feed and
leader settings and correct remaining length when the printer is idle with no
batch awaiting review.

## Check remaining tape

Before manually printing a queue or selected copies, the server compares estimated
tape use, including feed and cuts, with each chosen cartridge's remaining length.
If it exceeds the estimate, a warning shows the affected printers and lengths.
**Cancel** leaves the queue unchanged; **Print anyway** confirms the request.
Printer groups show all affected cartridges in one warning. Automatic batches
retain their shortage flag in Activity.

Automatic printing waits when the installed cartridge has an estimated **0 mm**
remaining. Its printer card explains why, and administrators receive one saved
alert per depletion, delivered through matching ntfy or email endpoints. Group
routing can use another matching printer with tape remaining; assigned CSV runs wait for their
printer. Replacing the cartridge or correcting its remaining length allows
automatic printing to resume, subject to existing holds and thresholds. Manual
printing still offers the explicit **Print anyway** override.
