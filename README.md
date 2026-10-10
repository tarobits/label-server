# Label Printer Server

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

## Print your first label

1. Add your printer under **Printers & groups**. USB serial is optional for one
   device; multiple devices require a distinct serial on each registration.
2. Create a **Tape profile** with the tape width, ink and background colors, and
   automatic-print threshold.
3. Register the physical cassette under **Cartridges** and assign it to the
   printer. Each cartridge keeps its remaining-length estimate across swaps.
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
  stays fixed. **Ignore out-of-bounds objects** clips partial objects and omits
  fully outside objects while keeping them editable. New templates enable both;
  existing templates retain their saved settings.
- **Show print pixels** displays the exact 1-bit raster and is enabled by default.
  Turn it off for a smooth design preview. Tape colors change the preview colors,
  not the ink pattern. Rulers, cursor guides, and object outlines do not print.

Saving creates a template revision. Concurrent edits require a reload. Archiving
hides a template from new submissions; existing jobs and saved drafts retain
their layout, values, assets, dimensions, and resolution.

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

Use **Add image** in the editor or upload directly in its properties panel. Aspect
ratio is preserved by default. Brightness and contrast use 1 for unchanged
artwork. Threshold conversion suits logos; dithering provides tonal shading.
Transparent areas preserve content behind them.

Hiding assets removes them from new selections while keeping saved labels usable.
Images can be renamed without changing their ID. Permanent deletion is allowed
only when no template, revision, job, or CSV run references the image. Back up
`data/assets` together with the database.

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

| Destination access | Allowed actions |
| --- | --- |
| Request only | Submit labels for approval. |
| Print | Submit directly and start own queued jobs. |
| Moderator | Also manage scoped queues and approve or reject requests. |
| Full | Also configure the granted printer or distribution group. |

Group permissions apply through that group and grant no direct printer access.
Interrupted-batch review requires Moderator or Full directly on the physical
printer. Template groups share templates and never assign roles. Owners can edit
or delete their own templates and cancel their own queued jobs after losing
printer access. Only administrators publish global templates.

Pending requests do not count toward thresholds. Disabling a user or revoking the
access needed for queued work pauses those jobs for an administrator to release
or cancel. Restoring access alone does not resume them. Submitting another user's
CSV draft as an administrator requires an explicit override if the author's
access is insufficient. See [access control](docs/ACCESS_CONTROL.md) for details.

## Notifications and integrations

Notifications are stored in the app even when ntfy is disabled. To enable delivery,
set these values in `.env`:

```dotenv
LABEL_NTFY_URL=https://ntfy.example.com
LABEL_NTFY_TOPIC=label-printer
LABEL_NTFY_TOKEN=
LABEL_PUBLIC_URL=http://label-server.local:8000
```

`LABEL_NTFY_URL` is the server base URL without the topic; the token is optional.
Use a topic restricted to administrators because it also carries request summaries.
Delivery retries independently of printing. A notification may be delivered more
than once after a crash; this does not duplicate a print.

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

Physical PT-P710BT testing was reported successful on 2026-10-04. Detailed
measurements and remaining hardware checks are in the
[verification record](docs/HARDWARE_VERIFICATION.md). Docker runtime, simultaneous
two-device USB printing, and a live HomeBox deployment have not been verified.

## Development

This project was designed and directed by Tarobits, with implementation assistance from OpenAI Codex.
AI-generated code has been developed under human direction and remains subject to review and validation.

The backend uses FastAPI, SQLAlchemy, Alembic, and SQLite; the frontend uses Vue 3,
TypeScript, and Vite. Printer-specific protocols stay in `app/printer`; queue and
domain code use the generic backend contract. [PLAN.md](PLAN.md) describes the
implementation constraints and [TODO.md](TODO.md) lists remaining work.

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
