# Taro's Label Room

A self-hosted label editor and persistent print queue for Brother PT-P710BT USB
printers. Design reusable templates, fill in variable fields, import CSV runs,
and batch labels by tape profile. Accounts and roles control printer access and
approval requests.

Supports normal 180 × 180 dpi and high 180 × 360 dpi output, multiple USB printers,
and printer groups. Shading uses monochrome dithering. Other printer models,
Wi-Fi/Ethernet printing, and native grayscale are not implemented.

## Run locally

Requires Python 3.12+, Node.js 22.12+, and system libusb for USB printing on Linux
or macOS. Node.js is needed only to build or develop the UI. See
[deployment](docs/DEPLOYMENT.md) for USB permissions and service setup.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000>. On first launch, use the setup token from the server
logs or `data/auth-setup-token` to create an administrator account. The token file
is removed after setup. New installations have no printers configured.

Run **one server process per database**. Do not use multiple Uvicorn workers.
Migrations must be applied explicitly before starting the local server.

For frontend development, keep the backend on port 8000 and run
`npm run dev --prefix frontend` in another terminal. Open the URL Vite prints;
it proxies `/api` to the backend. Production serves `frontend/dist` by default;
`LABEL_FRONTEND_DIST` overrides that path.

## Install as a Linux service

On Debian 13+ with Python 3.12+ and Git:

```sh
git clone https://github.com/tarobits/label-server.git
cd label-server
sudo python3 scripts/install.py
```

The installer fetches the latest stable GitHub release into a fresh `/opt/labels`,
installs dependencies, builds the UI, migrates the database and enables
`labels.service`. It binds to `127.0.0.1:8000` by default. Use `--ref main` to
install the current GitHub branch instead of a published release.
See [installer options and first-run setup](docs/DEPLOYMENT.md#github-installer)
for LAN access, private repositories and updates.

## Print your first label

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

Compatibility requires the exact tape profile, a ready printer, and the correct
detected tape width. The printer detects width; you select the cartridge to
identify its colors. Different profiles do not share a threshold.

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

In batch review, select individual uncertain copies, select all, or use **Select
from here** to include that row and all following uncertain copies. Choose
Printed, Requeue, or Cancel and apply it to the selection before saving. Confirmed
copies remain locked; total tape consumption must still be entered.

The PT-P710BT USB driver has no documented standalone cutter command. **Cut tape**
is disabled; while the printer is idle, double-press its physical power button to
feed and cut. Automatic cuts during printing continue to use the printer settings.

## Tape usage and costs

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

Before submission, individual label previews and validated CSV drafts show an
approximate cost for all selected copies as one batch, including feed, unused
tape and one leader. The queue shows a current estimate for remaining copies.
Matching installed cartridges supply the price; when none are installed, known
cartridge prices are shown as an inventory estimate. Groups can show a range or
separate currencies. Missing prices remain unavailable. These estimates can
change with cartridge prices, routing, shared batches or retries.

Set the purchase price and currency when registering a cartridge, or expand
**Price** on its card. **Tape usage** shows each signed-in user's allocated tape
and cost. **View other users’ usage and balances** permits selecting **All users**
or an individual user. Different currencies stay
separate. Prices use hundredths of the selected currency in the API
(`price_minor: 1299` means `12.99`).

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
not free. Tracking starts with new attempts after this migration; older history
is not reconstructed. Costs retain millionths of currency, and requester tape
allocations retain thousandths of a millimetre, with rounding shared so totals
remain consistent.

Account balances equal recorded adjustments minus settled, priced print costs,
including costs already tracked before account balances were introduced. Negative
balances are amounts owed; positive balances are credit. Pending and unpriced tape
does not affect the balance. Negative balances do not block printing.
**Edit usage accounts** permits recording payments, adding credit, or subtracting
an amount with a required reason under **Tape usage → Adjust account**. Adjustments
retain the operator, recipient, date and reason; corrections are new entries, and
retrying the same adjustment does not record it twice. The edit permission does
not grant access to other users' usage or balances. Administrators have both
permissions; other roles must be granted each explicitly. Run `alembic upgrade head`
with the server stopped before restarting to create the adjustment ledger.

## Templates and previews

The visual editor supports text, QR codes, images, rectangles, and lines. Drag,
resize, rotate in 90° steps, or enter dimensions in millimetres. Alignment,
layer ordering, duplication, snapping, and undo/redo are available.

- Define variable fields with names, labels, defaults, and sample values. Use
  `{{name}}` in text or QR content. Samples are used in the editor; submitted
  values or defaults are used for printing.
- **Print resolution** chooses the printer default, Normal, or High. New jobs and
  CSV drafts save that choice; changing it later does not affect them.
- Text supports wrapping, alignment, padding on all four sides, and horizontal
  character and vertical line spacing in mm. Zero adds no extra spacing. Text and
  spacing shrink together to fit the box. Accents and joined characters stay
  together; right-to-left runs retain native shaping and character spacing.
- **Fit text box width to content** adapts width to each value. **Distance holder**
  keeps a fixed gap to another object's bounds. Text widths resolve first, then
  linked positions, then automatic label length. Circular links are rejected.
- **Automatic label length** fits content and margins within 10–300 mm; tape width
  stays fixed. Shorter automatic lengths are extended to 10 mm with a warning,
  which is retained in saved jobs and CSV drafts.
  **Ignore out-of-bounds objects** clips partial objects and omits
  fully outside objects while keeping them editable. New templates enable both;
  existing templates retain their saved settings.
- Individually cut PT-P710BT labels have a 24.5 mm minimum output length,
  including feed, regardless of tape width. Shorter designs need hand trimming
  and produce extra unused tape. New label previews and validated CSV drafts
  show affected copies and estimated extra tape. Activity preserves the output
  plan for each attempt, including interrupted prints. These are estimates,
  separate from normal feed and batch overhead.
- Queue **Details** and Activity **Details** show tape use split into **Design**,
  **Feed**, **Leader**, and **Unused**. Design excludes padding added by the 10 mm
  automatic-length minimum; that padding and any cutting-minimum padding belong
  to Unused. Feed covers both end margins of each label, while Leader is charged
  once per batch. Queue estimates cover remaining copies printed together;
  separate batches each need a leader. Saved attempt breakdowns remain estimates,
  even when a reviewer reports a different total consumed length.
- **Show print pixels** displays the exact 1-bit raster and is enabled by default.
  Turn it off for a smooth design preview. Tape colors change the preview colors,
  not the ink pattern. Rulers, cursor guides, and object outlines do not print.

Saving creates a template revision. Concurrent edits require a reload. Archiving
hides a template from new submissions; existing jobs and saved drafts retain
their layout, values, assets, dimensions, and resolution.

The editor's **Preview tape** choice and display colors are saved with the template.
Printing may use another compatible tape profile. Template cards load WebP
thumbnails stored under `data/assets/template-previews`, generated on first view
and reused across requests and restarts. Saving a new revision invalidates its
thumbnail; missing or restored assets also refresh it. Retention cleanup purges
derived previews with deleted content. Older templates default to black on white.

Labels support up to 50 elements and 20 variable fields. Invalid layouts, missing
required values, unsupported glyphs, and QR modules smaller than two device pixels
are rejected. QR codes have a four-module quiet zone by default. **Scale up to
bounding box** fills the box and allows an explicit **QR margin (mm)**; a blank
margin keeps the automatic quiet zone.

### Fonts and images

Noto Sans regular and bold are bundled under the SIL Open Font License. The
**Fonts** page accepts static TTF/OTF files up to 5 MB and 20,000 glyphs. Upload
bold and italic faces separately. Variable fonts, color/bitmap fonts, web fonts,
and collections are unsupported.

The **Images** page accepts PNG, JPEG, WebP, BMP, still GIF, and constrained SVG
files up to 5 MB. Bitmaps are limited to 16 megapixels and 8192 pixels per side.
SVG supports paths, basic shapes, and groups; convert text to paths. Scripts,
external resources, styles, embedded images, filters, and animation are rejected.
SVG limits are 200 KB, 1000 elements, and dimensions up to 8192. Export unsupported
SVGs as PNG.

Both libraries accept multiple files at once, with individual results and retries
for failed uploads. Choose Personal, Group or Global for the batch; an item's
**Sharing** details can change its visibility afterward. Fonts and images have
separate upload and management permissions, independent of templates. Group
members can use shared items; creating, editing others' items and deleting others'
items each require the corresponding group permission. Existing uploads remain
personal when upgrading. Run `alembic upgrade head` with the server stopped to
migrate the former asset-upload permission to personal font and image uploads.

Use **Add image** in the editor or upload directly in its properties panel. Aspect
ratio is preserved by default. Brightness and contrast use 1 for unchanged
artwork. Threshold conversion suits logos; dithering provides tonal shading.
Transparent areas preserve content behind them.

Hiding assets removes them from new selections while keeping saved labels usable.
Images can be renamed without changing their ID. Administrators can delete images,
fonts and templates even when saved work references them. Deletion removes them
from use immediately and retains their data for 30 days. Restore them under
**Administration → Deleted accounts and content** before the deadline; afterward,
maintenance permanently purges the retained data. Global deletion permissions
also permit removing referenced assets in that global library; other users may
delete only unused assets they can manage. Back up `data/assets` with the database.

Templates that reference deleted assets show a notice and placeholders: a file
with a question mark for images, or **Aa** with a question mark in the top right
for fonts. Replace the missing assets or restore them before printing. Affected
queued jobs are paused; restoration does not automatically release their holds.

## Queue, printer groups, and recovery

Queue thresholds count copies per destination and tape profile. A manual print
request freezes its selected copies when accepted; newly submitted copies wait
for another batch. Removing queue items cancels queued copies and retains history.
Printing and uncertain copies require batch review.

**Print selected** prints only the selected compatible copies. Moderator selections
also hold automatic printing for that destination so other copies stay queued;
resume from its Overview card when ready. Print-level users can select their own
copies without holding other users' work. A pending manual flush prevents cartridge
reassignment; **Cancel pending flush** releases it without cancelling the jobs.

A printer group routes work to its first ready member with the exact profile
installed. Members must have matching printable geometry and resolution
capabilities, including default resolution. Missing tapes leave work queued.
CSV runs stay on their first assigned printer to preserve order. Choose the
submission destination separately from the sidebar's **Design destination**,
which sets editor geometry. See [printer architecture](docs/PRINTER_ARCHITECTURE.md).

If printing is interrupted, that printer pauses for review. Open the pause banner
or **Activity**, inspect every uncertain copy, mark it **printed**, **queued**, or
**cancelled**, and enter the **total tape consumed by the attempt**, including
confirmed labels and waste. Confirmed copies cannot be changed. In-flight batches
also require review after a server restart; uncertain copies are never retried
automatically. Other printers can continue.

**Activity** shows saved label previews, outcomes, requester, approver, and manual
batch starter. Each attempt preserves its attribution after retries or account
changes. Older events without reliable attribution show **Not recorded**.
Cartridge lengths are estimates, not sensor measurements; calibrate feed and
leader settings and correct remaining length when the printer is idle with no
batch awaiting review.

Before manually printing a queue or selected copies, the server compares estimated
tape use, including feed and cuts, with each chosen cartridge's remaining length.
If it exceeds the estimate, a warning shows the affected printers and lengths.
**Cancel** leaves the queue unchanged; **Print anyway** confirms the request.
Printer groups show all affected cartridges in one warning. Automatic batches
retain their shortage flag in Activity.

Automatic printing waits when the installed cartridge has an estimated **0 mm**
remaining. Its printer card explains why, and administrators receive one saved
alert per depletion, delivered through ntfy when configured. Group routing can use
another matching printer with tape remaining; assigned CSV runs wait for their
printer. Replacing the cartridge or correcting its remaining length allows
automatic printing to resume, subject to existing holds and thresholds. Manual
printing still offers the explicit **Print anyway** override.

## CSV runs

Open **CSV runs** or **Use with CSV** on a template. Upload or paste UTF-8 CSV,
choose comma, semicolon, or tab separation, then **Read CSV**. Map columns to
fields, select records, set copies, and arrange print order. Quoted delimiters
and multiline values are supported.

**Validate and preview run** saves a draft only if every selected record is valid.
The draft freezes the template, values, dimensions, assets, and rendering settings.
Review individual labels and the ordered run before choosing **Submit entire run**.
Submission creates all jobs atomically; retrying the same run cannot duplicate
jobs. Preparing a draft does not print. Normal thresholds and holds apply after
submission.

Imports are limited to 1 MB, 250 data records, 40 columns, 2000 characters per cell,
and 1000 copies per run. Reported record numbers include the header and count
logical CSV records, including multiline cells. Unsubmitted drafts can be deleted;
submitted runs remain in history, with queued copies cancellable from the queue.

## Accounts and requests

Manage users, roles, template groups, and registration codes under
**Administration**. Registration requires a code by default. Roles are assigned
directly to users; the highest applicable permission wins.

Only administrators can delete accounts, after reviewing and confirming the impact.
Deletion ends all sessions and removes the user's templates, images and fonts from
use, including shared content. The account and content can be restored together
for 30 days. Items deleted independently beforehand stay deleted. The last enabled
administrator cannot be deleted. Print history and its saved attribution remain;
restored users must sign in again. A print already underway may finish.

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

Pending requests do not count toward thresholds. Disabling a user or revoking the
access needed for queued work pauses those jobs for an administrator to release
or cancel. Restoring access alone does not resume them. Submitting another user's
CSV draft as an administrator requires an explicit override if the author's
access is insufficient. See [access control](docs/ACCESS_CONTROL.md) for details.

## Notifications and integrations

Notifications are stored in the app even when no ntfy endpoint is configured.
Administrators add endpoints under **Administration**, choosing a server base URL
(for example `https://ntfy.example.com`), topic, optional access token and event types.
Tokens stay on the server; editing an endpoint can preserve, replace or clear its token.
Set `LABEL_PUBLIC_URL` to the browser-reachable server address for notification links.

Each endpoint routes by event type and printer scope. Choose specific printers or
distribution groups, use **Select all** to capture only current physical printers, or explicitly
enable **All current and future printers**. Group scopes also receive operational
alerts from their member printers as membership changes; select groups manually.
With no scope selected, printer-related event
types are disabled and cleared. General alerts remain global; pending-request
summaries are global without a scope and narrow to selected destinations otherwise.
Endpoint filters do not use application roles or access levels. Configure ntfy
topic subscription permissions separately to control who can read each topic.

Set a severity per event type on each endpoint using ntfy's
[message priorities](https://docs.ntfy.sh/publish/#message-priority): Min, Low,
Normal, High, or Urgent. Empty cartridges, blocked printers and batch reviews
default to High; general alerts, waiting tape reminders and pending requests
default to Normal.

A notification can go to several matching endpoints. Each delivery retries
independently of other endpoints and printing. Changing, disabling or deleting an
endpoint cancels its pending deliveries. Delivery may repeat after a crash; this
does not duplicate a print.

The endpoint migration imports an existing installation's old `LABEL_NTFY_URL`,
`LABEL_NTFY_TOPIC` and optional `LABEL_NTFY_TOKEN` once, when those values are
available in its environment or `.env` and accounts already exist. The imported
endpoint includes all current and future printers. The scope migration preserves
selected destinations and turns formerly unrestricted scopes into an explicit
all-printers selection. It removes permission filters and cancels pending deliveries
created under the old configuration. Fresh installations create their endpoints
in the UI; the old variables no longer configure runtime delivery.

Waiting reminders are optional per tape profile. They begin when a destination
reaches its threshold without the required tape installed and repeat at the
configured interval, defaulting to 24 hours. Snooze and silence survive restarts.
Silence lasts until the waiting episode ends; disable the profile's reminders to
turn them off persistently.

Interactive API schemas are at <http://localhost:8000/docs>. API clients sign in,
retain the session cookie, and send `X-CSRF-Token` on mutations. Use
`Idempotency-Key` for retry-safe job submissions: the same key and input return
the original job; changed input returns HTTP 409. Intentional reprints need a new
key. See [REST integrations](docs/INTEGRATIONS.md) for bundled clients and HomeBox.

## Deployment and upgrades

```sh
docker compose up --build -d
```

Compose binds to localhost and stores data in a named volume. Map USB devices as
described in [deployment and recovery](docs/DEPLOYMENT.md), then register printers
in the UI. Use HTTPS for remote access.

Before upgrading, back up the complete data directory, including assets. Stop the
server, reinstall dependencies, run `.venv/bin/alembic upgrade head`, rebuild the
frontend, and restart. For older environment-configured printers, keep the old
`.env` available during migration so their settings can be imported once.

The release updater automates these steps for native systemd and Docker Compose
installations. It selects GitHub's latest published stable release, updates a local
`release` branch, backs up code/configuration/data, installs or builds dependencies,
migrates, restarts and checks health. It refuses local changes and preserves `main`.

For the private repository, set `LABEL_GITHUB_TOKEN` in the installation's `.env`
and restrict that file with `chmod 600 .env`. Use a fine-grained GitHub token for
this repository with **Contents: read-only** permission. The token authenticates
both release lookup and Git clone/fetch, and is shared with the server's cached
update check. The footer displays the running version and opens the full changelog;
a bottom-right notice links to newer releases. After an upgrade, each account sees
the releases since its last visit once, across browsers. The first visit establishes
a baseline. Account settings provide password changes and per-browser reduced-motion
preferences. See [private repository access](docs/DEPLOYMENT.md#private-github-repository-access)
for token-file configuration and credential handling.

```sh
# Preview without changing the checkout or service:
python3 scripts/update.py --mode native --check

# Native installation in this Git checkout:
sudo python3 scripts/update.py --mode native

# Compose; keep your existing USB override/project name when applicable:
python3 scripts/update.py --mode docker \
  --compose-file docker-compose.yml --compose-file docker-compose.usb.yml
```

For the VM's copied `/opt/labels` installation, use a separate managed source
checkout: `sudo python3 /path/to/scripts/update.py --mode native
--checkout /opt/labels-source --install-dir /opt/labels`. The missing source checkout
is cloned automatically. Native updates require Git, Node/npm and, with a separate
source checkout, rsync. See [automated release updates](docs/DEPLOYMENT.md#automated-release-updates)
for prerequisites, backups and failure recovery.

Physical PT-P710BT testing was reported successful on 2026-10-04. Detailed
measurements and remaining hardware checks are in the
[verification record](docs/HARDWARE_VERIFICATION.md). Docker image build and isolated
local runtime checks passed on 2026-10-17. Native Debian VM service startup, USB
access, physical printing, VM reboot, hold persistence and printer reconnection
without a service restart were also verified that day. The user accepted the
consumption baseline and stopping after the current label; no repeat measurements
or mid-label interruption are required. Simultaneous two-device USB testing is
deferred until a second printer is available. Docker/LXC USB passthrough remains
unverified outside the current deployment path. Live HomeBox bridge verification
is deferred.

## Development

This project was designed and directed by Tarobits, with implementation assistance from OpenAI Codex.
AI-generated code has been developed under human direction and remains subject to review and validation.

The backend uses FastAPI, SQLAlchemy, Alembic, and SQLite; the frontend uses Vue 3, Pinia,
TypeScript, and Vite. Printer-specific protocols stay in `app/printer`; queue and
domain code use the generic backend contract. [PLAN.md](PLAN.md) describes the
implementation constraints and [TODO.md](TODO.md) lists remaining work.

Pinia owns shared authentication, workspace, administration and request caches.
Concurrent reads share a request; catalogs load on relevant pages and remain cached
for a minute. Live queue and printer data refresh every five seconds, with longer
intervals for summaries and session checks. One scheduler pauses polling in hidden
tabs. Successful writes invalidate affected resources before the UI reloads them;
session and permission changes clear private caches. Cached data stays in memory.

Run backend and frontend checks with the development dependencies installed:

```sh
.venv/bin/pytest -q
.venv/bin/ruff check app tests migrations
.venv/bin/ruff format --check app tests migrations
.venv/bin/mypy app
npm run build --prefix frontend
npm run format:check --prefix frontend
```

Build the frontend before running browser tests:

```sh
cd frontend
npx playwright install chromium
npm run test:e2e
```

Tests use isolated databases and simulated printer hardware, without contacting
real printers or ntfy. Browser screenshots are written to `frontend/test-results`.

Made with ♥ by Tarobits
