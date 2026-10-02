# Label Printer Server

Persistent, tape-aware label printing for a Brother PT-P710BT. The agreed design
and staged implementation are in [PLAN.md](PLAN.md).

**Current stage: Vue visual editor, real SVG/QR rendering, and a persistent queue
with a mock physical printer.** New jobs render real text, QR codes and shapes.
Old fixture jobs keep their original checkerboard output. The Brother PT-P710BT
USB implementation remains required in the next hardware stages. Additional
printer models and Wi-Fi/Ethernet drivers currently have architecture only.

The mock's tape overhead, resolution and printable margins are development
fixtures, not verified PT-P710BT measurements.

## Run locally

Requires Python 3.12+ and Node.js 22.12+ on Linux or macOS. Developed and tested
with Python 3.14 and Node.js 22.18. Node is only needed to build/develop the UI.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000> for the Vue UI, or <http://localhost:8000/docs> for the
interactive API. The UI uses hash routes, so review links and browser refreshes
work without interfering with API 404 responses. Use **one process**;
do not set `--workers` above one. A process lock rejects another server using the
same database. SQLite is file-backed, uses WAL, and enforces foreign keys.
Migrations are explicit; the application does not silently create the schema.

When upgrading an existing checkout, stop the backend, reinstall dependencies with
`.venv/bin/python -m pip install -c requirements.lock -e '.[dev]'`, run
`.venv/bin/alembic upgrade head`, rebuild with `npm run build --prefix frontend`,
and restart. The editor/hold migration preserves existing queued jobs.

For frontend development, leave the backend running on port 8000 and run
`npm run dev --prefix frontend` in a second terminal. Open the URL Vite prints;
it proxies `/api` to FastAPI. The built UI is served from `frontend/dist` by
default; `LABEL_FRONTEND_DIST` can override that directory.

## Use the interface

1. Create a **Tape profile** with its colors, width, batch threshold and optional
   waiting reminders.
2. Register a physical cassette under **Cartridges**, then install it in the app.
   Each cassette keeps its own length estimate across swaps.
3. Use **Templates** to design a label visually, then **New label** to fill its
   variable fields and submit copies. Its smooth preview uses the same layout as printing; **Show print pixels**
   switches to the actual 1-bit raster.
4. Watch the **Overview** or **Print queue**. Compatible copies print at their
   threshold, or use **Print compatible queue now** to flush them manually.
   **Hold automatic printing** lets you collect a larger batch. This switch
   survives restarts, does not interrupt an existing batch, and still permits
   manual flushes. Resuming can immediately start an eligible batch.
5. Use **Printer & settings** to simulate disconnection, an unknown or mismatched
   tape width, or a one-time interruption after a chosen number of confirmed
   copies. Controls are runtime-only and unavailable for non-mock backends.
6. Open an interrupted batch from the pause banner or **Activity**, choose the
   outcome of every uncertain copy, enter total tape consumed, and resume.

The UI polls every 2.5 seconds. Forms keep their edits during refreshes, failures
are shown without discarding input, and printing decisions stay in the backend.
The queue can be filtered by tape profile together with copy status, before
pagination. Status filters operate on individual copy states, so a partly printed job can
appear in more than one filter. Lists use pagination for jobs and the most recent
100 batches/notifications. The settings page reports ntfy configuration; server
URLs/tokens remain environment settings and are not editable in the browser.

You can also use `/docs` to try this flow (copy returned IDs into subsequent requests):

1. `POST /api/tape-profiles`:
   ```json
   {"name":"Black on Yellow 24 mm","width_mm":24,"foreground":"#000000","background":"#ffff00","auto_print_threshold":10,"waiting_notification_enabled":true,"waiting_notification_interval_seconds":86400}
   ```
2. `POST /api/cartridges`:
   ```json
   {"profile_id":"PROFILE_ID","name":"Yellow cassette 1","nominal_length_mm":8000}
   ```
3. `PUT /api/printer/active-tape`:
   ```json
   {"cartridge_id":"CARTRIDGE_ID"}
   ```
4. `POST /api/jobs`:
   ```json
   {"template":"text","tape_profile":"PROFILE_ID","copies":9,"length_mm":40,"data":{"text":"Example label"}}
   ```
5. Inspect `/api/status`: the nine copies wait. Submit one more copy to trigger
   an automatic batch, or `POST /api/queue/print` to flush the nine now.
6. Inspect `/api/batches`, `/api/jobs` and `/api/cartridges` for results.

Profile `PUT` replaces its editable settings, including the threshold. Manual
flush returns `202` with a persistent request; it does not wait for printing.
Its membership is frozen when accepted and tied to the selected cartridge.
Another pending manual request for that cartridge returns `409`.

## Visual editor and rendering

Open **Templates → Create template**. Set tape width/label length, then add text,
QR codes, rectangles or lines. Select elements on the canvas or through its layer
buttons. Drag to position, resize using the corner handle, or enter exact millimetre
values. Numeric sizing works for rotated elements; rotation is in 90° steps.
Alignment, layer order, duplication, deletion, grid/snapping and undo/redo are
available. Navigation warns about unsaved changes.

Variable fields define names, labels, required flags, defaults and sample values.
Use `{{name}}` in text/QR content. The editor uses samples; submission uses actual
values or defaults. This is literal substitution, not executable Jinja. No raw SVG,
external URLs, scripts or server paths are accepted as rendering resources.

Saving creates a revision; concurrent edits require reloading instead of silently
overwriting a newer version. Duplicating creates a separate template. Archiving
removes it from new submissions while preserving its history and queued jobs.
The API also exposes `GET /api/templates/{id}/revisions`. Queued jobs retain their
own document and rendering settings when the template changes.

Noto Sans regular/bold is bundled under the SIL Open Font License in `app/fonts`.
The **Fonts** page accepts static TTF/OTF files up to 5 MB and 20,000 glyphs.
Select uploaded faces in the editor’s Font control; upload bold/italic faces
separately. Variable, color/bitmap, web fonts and collections are not supported.
Uploads have immutable content IDs shared by preview, CSV runs and printing.
Hide/Restore changes picker visibility without deleting files needed by saved
templates or queued jobs. Duplicate uploads reuse the existing entry.
Font assets live in `assets/fonts` beside the SQLite database (normally
`data/assets/fonts`); back up that directory together with the database. No new
database migration is needed for fonts. The API provides `GET/POST /api/font-assets`
(POST takes raw font bytes), `DELETE /api/font-assets/{id}` to hide, and
`POST /api/font-assets/{id}/restore`.

The **Images** page accepts PNG, JPEG, WebP, BMP, still GIF and constrained SVG
uploads up to 5 MB. Bitmaps are limited to 16 megapixels and 8192 pixels per side.
SVG accepts paths, basic shapes and groups with presentation attributes; text
must be converted to paths. Styles, references, embedded images, scripts, filters,
animation, entities and declarations are rejected (a standard UTF-8 XML header
is allowed). SVG markup is limited to 200 KB, 1000 elements and dimensions up to
8192. Unsupported SVGs can instead be exported as PNG.

Use **Add image** in the editor and choose an uploaded asset, or upload and use a
new image directly in the properties panel without leaving the editor. Images can be moved,
resized and rotated; aspect ratio is preserved by default. With preservation on,
width, height and corner dragging resize proportionally. Selecting artwork fits
the box to its proportions within the current dimensions. New templates enable
automatic label length and clipping of out-of-bounds objects by default; existing
templates retain their saved settings. Brightness and contrast
use 1 for unchanged artwork. Choose threshold conversion for logos or dithered
shading for tonal artwork. These are both 1-bit output; native Brother grayscale
still needs hardware verification. The selected tape colors apply to the same
ink pattern used for printing. Transparent areas preserve content behind them.
SVGs rasterize at the label's device resolution; low-resolution bitmaps cannot
gain detail by enlargement.

Original uploads and normalized assets live in `data/assets/images` (beside the
database if relocated). Include the entire `data/assets` directory in backups.
Hiding/restoring images leaves saved templates, jobs and CSV runs intact. Uploading
new content creates a separate asset. No database migration is needed.
The API is `GET/POST /api/image-assets` (raw bytes, optional `?name=...`),
`DELETE /api/image-assets/{id}` to hide and
`POST /api/image-assets/{id}/restore`.

The editor defaults to an antialiased design preview rendered from the same SVG
at four times the device raster dimensions. **Show print pixels** switches to the
exact 1-bit output. Both use the same backend fonts and layout; the smooth view
does not represent a measured improvement in physical print quality. Unsupported glyphs, missing variables and out-of-bounds elements and undersized QR modules are rejected. Overlapping QR
bounding boxes produce an advisory warning; layouts can still be saved and queued. QR modules use integer device pixels with a four-module quiet zone by default.
The per-QR **Scale up to bounding box** option enlarges the code and its quiet
zone to fill the box across QR versions, allowing fractional module sizes before
rasterization. When enabled, **QR margin (mm)** sets the inset on each side:
0 fills to the edges; a blank value retains the automatic four-module border.
New elements start with a 1 mm margin. Text supports top, center and bottom
vertical alignment of the entire wrapped text block. The chosen font size is a
maximum: text automatically shrinks to the largest size that fits its box, with
wrapping and explicit newlines respected. Text that already fits keeps its size. It never relaxes the minimum of two device pixels per module.
Colored previews do not change ink placement. Lengths are currently limited to
300 mm, with 50 elements and 20 variable fields per document.

The editor now offers **Automatic label length** (10–300 mm, continuous media).
It fits the element boxes plus the printable margin, preserving tape width and
positions. Enable **Fit text box width to content** on a text element to adapt its
width to each field value; explicit newlines remain, and its height stays fixed.
Combine the options for labels whose lengths vary with their submitted text.
Turning automatic sizing off restores the saved manual dimensions.

**Ignore out-of-bounds objects** clips partial objects at the printable guides and
omits fully outside objects from the output. Warnings identify affected elements;
their source geometry stays editable through the layer list. Automatic sizing
runs before clipping. Required fields and printer/length limits still validate. Existing templates keep strict bounds and manual dimensions.
Resolved dimensions are shown in previews and frozen into queued jobs.

`POST /api/preview` accepts a template ID or an unsaved structured document,
input data, optional sample mode and tape colors. It returns the exact raster as `png`, a higher-resolution antialiased
`design_png`, SVG and device pixel sizes. `POST /api/jobs` validates the same layout before queueing it. The original
built-in text template (unmodified revision 2) retains an explicit legacy API
length/width option; omitted lengths use the saved template length. The label and
CSV submission pages always use template sizing. Edited and custom
layouts use their saved dimensions. The mock printer captures genuine raster
bytes but does not send anything to hardware.

Renderer reference: [resvg-py API](https://resvg-py.readthedocs.io/en/latest/api.html).
Bundled font source: [Google Fonts Noto Sans](https://github.com/google/fonts/tree/main/ofl/notosans).

In **Print queue**, select queued items and choose **Remove selected** to remove
them across tape profiles, or **Print selected** to print items for the installed
tape. Each row also has a **Remove** action. Removal marks queued copies cancelled
while retaining history; printing and uncertain copies require batch review.
`POST /api/queue/remove` accepts `{"copy_ids":["COPY_ID"]}` and validates the
complete selection before changing any copies. An item selects all its remaining queued copies. The server
validates the complete selection and freezes those copy IDs in queue order.
Printing a selection also holds automatic printing, so unselected labels stay
queued; resume automatic printing from Overview when ready. Existing review,
installed-tape and pending-flush safeguards still apply. The original **Print
compatible queue now** action remains available for a full compatible flush.

CSV runs appear as expandable queue rows. Select a run as a whole or expand it
to select individual items. Filtering applies before grouping and pagination;
runs are not split across pages. Selection clears when changing page, filters or
installed tape, and polling removes copies that are no longer eligible.
`POST /api/queue/print` accepts optional `{"copy_ids":["COPY_ID"]}` for selected
printing; omit the body for the original full flush. `GET /api/queue/groups`
provides the grouped queue with status/profile filtering.

## CSV runs

Open **CSV runs** (or **Use with CSV** on a template). Upload a UTF-8 file or
paste CSV, select comma/semicolon/tab separation, then **Read CSV**. Map columns
to template fields; unmapped fields use their defaults. Select records, change
copy counts and move records up/down to set print order. Quoted delimiters and
multiline values are supported. Imports are limited to 1 MB, 250 data records,
40 columns, 2000 characters per cell and 1000 copies per run.

**Validate and preview run** reports errors by CSV record and saves a draft only
when every selected record is valid. Record numbers count logical CSV records
(including the header), not physical lines inside quoted multiline cells. The
saved run freezes field values, resolved dimensions, template revision, rendering
settings and tape-preview colors. Browse each rendered label and the ordered run
overview before submitting; drafts remain available under Recent runs after a
restart. Template edits or archival cannot change a saved draft's contents.
Use **Delete draft** in Recent runs or the draft detail view to remove an
unsubmitted draft. Submitted runs remain in history; cancel their queued items
from the queue instead. `DELETE /api/runs/{id}` enforces this distinction.

**Submit entire run** adds all jobs/copies atomically. Retries of the same run
cannot create duplicate jobs. Normal thresholds and the automatic-print hold
apply after submission; preparing a draft never prints. A changed tape width
requires a new draft. Queue entries link back to their run and source record.
Interrupted runs use the existing per-copy review and retry workflow.

Tape estimates assume one batch through the active adapter; current mock feed
values are fixtures. Other queued labels or separate attempts can alter overhead.
Actual Brother chain printing, cut/feed diagrams and calibrated consumption
remain hardware-stage work.

API: `POST /api/csv/parse`; `POST /api/runs/prepare` (mapping, ordered records,
copy counts, expected template revision and a client request key); `GET /api/runs`
(latest 100); `GET /api/runs/{id}`; `GET /api/runs/{id}/rows/{position}/preview`
(zero-based position); `POST /api/runs/{id}/submit`. Reusing a preparation key with
different input returns 409. Invalid rows return `valid: false` and per-record
errors without saving a partial run. See `/docs` for request schemas.

Existing installations: stop the service and run `.venv/bin/alembic upgrade head`
before restarting. The run migration preserves existing jobs and copies.

## Architecture and behavior

The UI follows [COLOR_SCHEME.md](COLOR_SCHEME.md) and
[FIGMA_COLOR_SCHEME.md](FIGMA_COLOR_SCHEME.md): charcoal surfaces, indigo actions,
cool gray text, and semantic red/green states. Shared CSS tokens in
`frontend/src/style.css` define the palette for all screens and the visual
editor. Tape swatches and samples use the physical tape profile's colors.

- `app/models.py`: profiles, physical cartridges, immutable job snapshots,
  individual copies, batch attempts, flush requests and notification outbox.
- `app/api.py` / `app/schemas.py`: validated HTTP inputs and API operations.
- `app/queue.py`: exact-profile compatibility, batch reservation, print outcomes
  and review. No Brother protocol bytes, feed rules or raster encoding here.
- `app/printer/base.py`: protocol-independent status, images, consumption estimate
  and batch result contract. `mock.py` captures images and simulates failures.
- `app/render.py`: validated documents → generated SVG → resvg PNG → 1-bit raster;
  colored previews are derived from that exact raster.
- `app/template_schema.py` / `app/templates.py`: bounded documents and versioned
  template persistence; queued jobs snapshot documents and rendering settings.
- `app/printer/registry.py`: device, capabilities and transport definitions. See
  [printer architecture](docs/PRINTER_ARCHITECTURE.md) for current and future scope.
- `app/notifications.py`: durable outbox, reminder episodes and ntfy adapter.
- `app/main.py`: app lifecycle and separate printer/notification worker threads.
- `migrations/`: versioned Alembic schema; tests apply real migrations.
- `frontend/src/views/`: Vue screens for the queue, tape inventory, review and
  mock controls; `workspace.ts` handles shared polling and API actions.
- `frontend/tests/`: Chromium workflows against an isolated temporary backend.

Copies count toward each profile's threshold. Printing requires the exact active
profile, a connected printer and matching known tape width. Color metadata is
never taken from the printer. Job inputs, template revision and required width
are captured at submission. Used profile widths cannot be edited; create another
profile instead. Jobs are cancelled, not physically deleted; history is retained.

The worker commits a frozen `printing` attempt before calling the adapter. API
requests may enqueue new jobs during printing; those copies wait for another
batch. One lock serializes physical sessions, while short database locks protect
reservation and mutations. Status endpoints read the worker's cached status.

The adapter can guarantee that no printing started (`PrintNotStarted`), report a
confirmed prefix plus an uncertain remainder (`PrintInterrupted`), or confirm
the whole batch. Any other exception after calling `print_batch` is uncertain.
A no-start failure returns copies to the queue for retry. An uncertain outcome
blocks all printing until review. On restart, committed in-flight attempts enter
review instead of automatically printing again.

`GET /api/batches/{id}` lists copy IDs and outcomes. Resolve a review with:

```http
POST /api/batches/BATCH_ID/review
Content-Type: application/json

{"decisions":{"UNCERTAIN_COPY_ID":"queued","OTHER_UNCERTAIN_COPY_ID":"cancelled"},"consumed_mm":85}
```

Every uncertain copy needs one decision: `printed`, `queued` or `cancelled`.
Already confirmed copies cannot be changed. `consumed_mm` is the **total** tape
used by this attempt, including confirmed labels and waste; it may itself be your
estimate. Review is applied once transactionally. Requeued copies follow the
usual threshold/manual-flush rules. A resolved batch with mixed outcomes retains
`failed` at batch level; copy outcomes are the detailed record.

Each cartridge retains its estimate through swaps. The mock deducts the sum of
requested lengths plus a fictional 20 mm overhead per batch. Shortage is recorded
as a warning and does not block. Uncertain batches leave the estimate unchanged
and mark it uncertain until reviewed. Use
`PUT /api/cartridges/{id}/remaining` with `{"remaining_mm":3200}` to correct an
estimate when no batch is printing or awaiting review.

## ntfy and waiting reminders

Notifications are stored even when ntfy is disabled, and are visible at
`GET /api/notifications`. Set these environment values to enable publishing:

```dotenv
LABEL_NTFY_URL=https://ntfy.example.com
LABEL_NTFY_TOPIC=label-printer
LABEL_NTFY_TOKEN=
LABEL_PUBLIC_URL=http://label-server.local:8000
```

URL is the ntfy **server base URL**, without the topic. Subscribe to that topic
in your ntfy client. The token is optional. Delivery runs independently of the
print worker with a 10-second HTTP timeout and exponential retry delay from
30 seconds up to one hour. Delivery is at least once: a crash after ntfy accepts
a message but before the database records success can duplicate a notification,
never a physical print. Enabling ntfy also delivers still-valid pending alerts.

Review and printing blockers produce alerts. Waiting reminders are opt-in per
profile, start when its queued copies meet its threshold while that profile is
not installed, and repeat at its configured interval (default 24 hours). The
message contains a profile name and copy count, not label content. Repeated
identical blockers are deduplicated until the blocker clears.

`PUT /api/tape-profiles/{id}/reminder` accepts:

```json
{"action":"silence"}
```
```json
{"action":"snooze","until":1791000000}
```
```json
{"action":"resume"}
```

`until` is a future UTC Unix timestamp. Silence lasts for the current waiting
episode; falling below threshold resets it. Installing the profile suppresses
reminders without resetting silence. Set `waiting_notification_enabled=false`
to disable them persistently. Stale pending reminders are checked again before
delivery. Timing and controls survive restart.

New notifications link to the Vue dashboard, settings or batch review screen.
Previously stored notifications keep their original API links.

## Verify

```sh
.venv/bin/pytest -q
.venv/bin/ruff check app tests migrations
.venv/bin/ruff format --check app tests migrations
.venv/bin/mypy app
npm run build --prefix frontend
npm run format:check --prefix frontend
```

Browser tests use a temporary database, mock hardware and no ntfy connection:

```sh
cd frontend
npx playwright install chromium
npm run test:e2e
```

Build the frontend first. The browser suite starts its own temporary backend on
port 8765 and checks the complete registration → interrupted batch → review →
manual flush workflow, reminder controls, editable forms during polling, API
errors and the mobile layout. Screenshots are written to `frontend/test-results`.

Tests cover thresholds, copies, profile separation, frozen manual flushes,
connection/width gates, serialization, partial failures, review, consumption,
restart recovery, process ownership, notification retries, ntfy request shape,
snooze/silence and schema upgrades/downgrades. Tests do not contact a real ntfy
server or printer. The pinned Starlette version emits a test-client deprecation
warning for httpx; this does not affect test results or application requests.

## Container scaffold

The multi-stage container builds Vue and serves it with the same mock-only
backend; no USB passthrough is configured.

```sh
docker compose up --build -d
```

Compose binds to localhost by default and uses a named volume for the database.
Set `LABEL_BIND_ADDRESS` to an appropriate LAN address when exposing it. Pass
ntfy settings via `.env`. There is no authentication in this stage; keep access
on your trusted LAN. Stop the service before taking a filesystem backup of the
data volume (including SQLite WAL files), or use SQLite's online backup API.

The required Brother USB backend, verified chain printing and LXC device
passthrough instructions follow in their planned milestones. Docker configuration
validates, but a running Docker daemon is still needed to build/test the image.
