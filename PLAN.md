# Label printer server plan

## Goal and agreed decisions

A self-hosted appliance for a USB Brother PT-P710BT on Debian in a Proxmox
LXC: submit labels, retain them across restarts, swap tape, and print efficient
batches. Vue 3 + TypeScript + Vite will provide the UI; FastAPI, SQLAlchemy,
Alembic and SQLite provide the backend. The built frontend will eventually be
served by FastAPI from the same origin. Start with polling, one printer and one
worker. No Brother protocol concerns may enter queue/domain code (AGENTS.md).

- Queue creation normally does not print immediately. Each tape profile has an
  editable positive `auto_print_threshold`, initially 10. Count physical copies,
  not job records. A manual flush includes the compatible copies queued at the
  time the request is accepted, even below threshold.
- Match the exact requested profile and physical width. Never infer tape color
  from printer status. Unknown or mismatched physical width blocks printing.
- Freeze job inputs/template revision/profile width at submission and freeze
  batch membership before printing. Editing profiles cannot silently change
  queued label dimensions. Newly arriving copies belong to a later batch.
- Serialize printer access. The API requests work; only the worker prints.
- **Automatic-print hold (TODO.md):** a persistent printer-wide switch lets the
  user accumulate a large batch beyond tape thresholds. It survives restarts and
  cartridge/threshold changes. Explicit manual flush remains available and obeys
  all width and review safeguards. Holding does not interrupt a batch already
  reserved or cancel an explicit pending manual flush. Resuming re-evaluates the
  queue immediately and can start a batch. Show the hold clearly on the dashboard
  and label-submission screen. Waiting-tape reminders retain their own controls.
- Ambiguous physical outcomes become `needs_review` and block all further
  printing. Do not automatically retry potentially printed labels. Review can
  mark individual copies printed, requeue them, or cancel them. Crash recovery
  treats in-flight physical printing as uncertain.
- Use durable notifications with an optional ntfy adapter. Configure server URL,
  topic, optional bearer token, public application URL and delivery retries.
  Notify about review requirements and printing blockers; omit label payloads.
  Success notifications are off by default. Notification failures never trigger
  printing retries or erase review state.
- Each profile has optional waiting reminders and an editable repeat interval
  (default 24 hours). Notify when its queue reaches its threshold but another
  profile is installed. Support snooze-until and silence-current-episode; reset
  an episode when the count falls below threshold. Persist timing and silence.
  Installing the profile suppresses reminders. Threshold changes are effective
  on the next worker wake, including triggering an eligible active batch.
- Track physical cartridges separately from tape profiles. Store nominal length,
  estimated remaining length, and an uncertainty flag. Reinstalling a cartridge
  preserves its estimate. Allow partly used cartridges and manual corrections.
  Account for labels, margins and batch overhead through the printer adapter;
  uncertain consumption is reconciled during review. Estimated shortage warns
  rather than blocks. Future UI displays remaining and batch-required length.
- Multiple-printer architecture is now in scope: identify printers independently
  from models and transports, describe continuous/fixed-label media and printable
  geometry through capabilities, and keep driver commands separate from USB/IP
  transport. Wi-Fi and Ethernet use network endpoints; Wi-Fi provisioning and
  discovery are future integrations. Shipping printer drivers and real network
  printing are not part of this implementation. A single active destination can use the mock or Brother USB driver; independent
  multi-printer scheduling remains future work.
- **Required physical implementation:** the Brother PT-P710BT remains in scope,
  including its USB backend, status/width detection and verified batch/cut/feed
  behavior in stages 4–5. Only additional printer models (including shipping
  printers) and Wi-Fi/Ethernet driver implementations are architecture-only for
  now. The multi-printer foundation does not replace or defer the Brother work
  beyond the agreed UI/editor-first milestone order.
- QR content is data. SVG/Jinja rendering must escape input, restrict template
  capabilities and prevent file/network access. Initial deployment is LAN-only;
  accounts and authorization belong to the approval-gated phase 8 below. Operational multi-printer
  scheduling follows the architectural foundation; it must isolate queues, locks,
  review blocks, holds, cartridge assignments and notification links per printer.
- **Physical print quality:** labels should have clean text, curves, QR modules
  and images without avoidable pixelation. Initial hardware tests passed QR
  scanning and the 10 mm scale check; the user reported excellent high-resolution
  quality on 2026-10-02. Broader calibration remains open. Browser preview smoothing does not
  improve the raster sent to the printer. Determine the PT-P710BT's supported
  resolution and quality modes in its adapter, render at the selected device
  resolution, and avoid unnecessary intermediate downscaling or upscaling of
  low-resolution source assets. Respect the device's physical resolution rather
  than promising resolution-independent output.
- Prioritize the Vue interface and visual template editor before physical printer
  integration. The visual editor is required for project completion, not an
  optional enhancement. Users must be able to create and edit reusable label
  layouts without writing SVG or editing server files.

## Implementation stages

1. **Backend foundation (first implementation):** project layout, migrations,
   typed models, profile/cartridge/job APIs, immutable job snapshots, mock-only
   rendering and printer, durable worker, automatic/manual batching, review and
   restart recovery, durable ntfy delivery, waiting reminders, tests and README.
   No physical USB printing or finished frontend in this stage.
2. **Vue application and mock workflow:** Vue 3, TypeScript and Vite; dashboard,
   label submission, queue, batch review, tape profiles, physical cartridges,
   reminder controls, consumption corrections and printer status. Start with
   polling and connect to the existing API. Clearly identify mock output until
   real rendering is available. Done when the complete queue/review workflow can
   be exercised through the UI, including simulated failures.
3. **Visual template editor and rendering:** implement the editor and backend
   rendering together, using a versioned structured template document that the
   backend converts into SVG and monochrome raster output. Add template CRUD,
   revisions, preview and validation APIs. Users create layouts visually, define
   variable fields and test sample values. See the editor scope and acceptance
   checks below. Done when a user can design, save, reopen, preview and queue a
   label entirely through the UI, with reproducible output and immutable queued
   revisions. This milestone is required before calling the appliance complete.
   Include the automatic-print hold from TODO.md before enabling larger editor
   workflows, with tests for persistence, manual flush and safe resumption.
   **Stage 3 extension — editor and batch authoring (new TODO.md scope):**
   complete the layout policies, CSV batch authoring/previews, font uploads and
   image assets detailed below before advancing to hardware integration. Preserve
   the existing editor milestone as completed. Layout policies, CSV authoring,
   font/image uploads and monochrome image conversion are implemented. Native
   grayscale remains pending hardware verification.
   Introduce the lightweight identity/ownership/authorization boundaries described
   below as this work touches the relevant services, without enabling phase 8.
4. **Brother adapter:** research and document USB transport, initialization,
   status/width detection, raster formats, compression, cuts and final feed.
   Implement status/width detection and single-image printing. Verify refusal on
   mismatched width and safe handling of disconnects. Keep all protocol knowledge
   inside the adapter. Verify the TODO.md claim of PT-P710BT grayscale support
   against the protocol and physical output, including any mode/media limits.
   Include a physical print-quality acceptance sheet with small text, curved and
   diagonal shapes, QR codes at several sizes, and image/tonal samples. Compare
   printed dimensions and detail with the intended layout, check QR scanning,
   and tune rasterization and supported quality modes before accepting the driver.
   An enlarged on-screen preview alone cannot satisfy this acceptance check.
   Implement native grayscale if supported; otherwise provide an explicitly named
   monochrome dithering path for tonal images. This stage follows the expanded
   usable UI and editor.
5. **Consecutive printing:** verify individual cuts, chain printing and leader
   cost once per batch on physical hardware. Calibrate consumption estimates.
   Keeping USB open alone does not establish these properties. Connect the CSV
   runs authored in stage 3 to physical chain printing, preserving row order,
   requested copies and per-copy review on interruption. Preview the planned
   chain, cuts and feed separately from each label's printable image.
6. **Deployment:** container image, Compose, persistent volumes and Debian LXC
   USB passthrough documentation with the built Vue app served by FastAPI.
   Verify restarts, printer power loss, tape exhaustion and ntfy outages. Document
   single worker operation, backups, upgrades, restores and LAN exposure.
7. **Integrations:** document REST workflows and add idempotency keys before
   integration retries can create duplicate jobs. Verify HomeBox extension points
   before implementing its specific integration; retain direct REST support for
   Home Assistant, Shortcuts and other services. Provide image upload, preview and
   frozen image-job submission, plus a standalone HomeBox print-command bridge.
   Reuse generic printable geometry, resolution and queue policies. Verify the
   bridge in the user's HomeBox deployment separately from API/client tests.

8. **Multi-user administration and request approval — low priority, approval
   required:** implement the final phase specified below only after explicit user
   approval to begin it. Planning and preparatory architectural boundaries do not
   constitute approval to implement account, role or permission behavior.

Future enhancements: reprints/history UI, QR cartridge selection, optional live
events and concrete additional printer drivers. The visual editor and the
approval-gated multi-user phase are tracked explicitly above.

## Visual template editor scope

The following is the initial implementation scope; exact editor controls can be
refined while building the UI without weakening the requirement for visual editing.

- A tape canvas with physical dimensions in millimetres, printable-area guides,
  zoom, grid/snapping and a configurable label length. Printer capabilities supply
  printable-area information; Vue and the domain do not encode Brother commands.
- Add, select, drag, resize and rotate text, QR codes, lines and rectangles.
  Provide numeric position/size controls, alignment tools, ordering, duplication,
  deletion and undo/redo. QR resizing preserves square modules and quiet zones.
- Set font, size, alignment and wrapping for text. Use the same bundled fonts
  for browser editing and backend rendering. Treat the chosen font size as a
  maximum and shrink text to fit its box, preserving alignment and wrapping. Warn when QR dimensions are too small.
- Bind text and QR content to named variables; define required fields, defaults
  and sample values. Generate the label-submission form from these definitions.
- Save, reopen, duplicate and revise templates. Existing queued jobs retain their
  original document, variables and revision. A new revision affects only newly
  submitted jobs. Protect unsaved edits from accidental navigation.
- Use a structured, validated document as the editable source of truth. SVG is
  a generated rendering format, preserving the original SVG-based pipeline.
  User-controlled values are escaped; no arbitrary template code, external file
  reads or network resources are executed during rendering. SVG image assets
  are added through the constrained import path in the extension below; arbitrary
  executable SVG and a general-purpose vector illustration suite remain excluded.
- Provide responsive local editing feedback plus a backend-generated preview
  using the selected tape colors. The authoritative preview and printable raster
  share the same rendering pipeline, layout and fonts. Current output is 1-bit;
  the image extension and Brother verification below define future tonal output.

Editor acceptance checks:

- Create a reusable asset label with variable text and a QR code without editing
  source files; save it, reload it and make further visual edits.
- Change sample data and tape preview colors, then submit multiple copies using
  the resulting form. Colors must not change which raster pixels represent ink.
- Detect missing required values and invalid/out-of-bounds layout; fit oversized
  text within its box without exceeding the chosen font size.
- Decode QR codes from the generated raster, not only from the browser canvas.
- Verify dimensions and layout between backend preview and print raster.
- Undo/redo edits and reopen saved documents without losing layout or bindings.
- Edit a template after queueing a job and verify that the queued job's rendering
  remains unchanged. Add browser tests for the core design-to-queue workflow.

## Stage 3 extension: layout, assets and CSV runs

These requirements come from the new TODO.md entries. Layout policies, automatic
sizing, CSV run authoring/previews, font/image uploads and monochrome threshold
and dithering are implemented. Native grayscale and physical chain-print
verification remain pending.

- **Ignore out-of-bounds objects:** add an explicit, saved layout policy alongside
  strict validation. Implemented behavior: clip objects to the printable area, omit
  fully outside objects from output, and keep all objects editable in the source
  document. Show clipped/omitted content in the preview. This option must not
  bypass physical printer/media limits.
- **Automatic label resizing:** add a toggle saved with the template. Fit the
  continuous label's length to the content and required margins after variable
  substitution, including different CSV rows; tape width stays tied to the stock.
  Fixed-size shipping labels cannot grow beyond their stock dimensions. Apply
  auto-sizing before the out-of-bounds policy, enforce capability/length limits,
  and freeze each resolved label size in its queued snapshot. Manual sizing stays
  available when the toggle is off.
- **CSV-driven chain authoring:** import CSV, map headers to template fields,
  choose row selection/order and copy counts, and validate all selected rows
  before submitting a run. Show row-level missing values, overflow and sizing
  errors. Preserve a stable run ID, source-row identity and ordered immutable
  label snapshots. Commit an accepted run atomically so an automatic threshold
  cannot start printing halfway through import. Existing hold/manual-flush rules
  still apply; CSV import alone does not trigger physical printing.
- **Chain previews:** show each row's actual rendered label with navigation and
  a whole-run overview, copies, resolved dimensions and estimated tape use.
  Once driver behavior is verified, include cuts/feed/leader estimates. Preview
  and printing must use the same frozen inputs and rendering settings. A CSV run
  is a logical group; the adapter determines physical chain-print commands.
- **Web font management:** upload fonts in the UI, inspect family/style and make
  them available in text controls. Validate supported font formats and resource
  limits. Store fonts as versioned assets shared by preview and rendering; queued
  jobs retain the exact referenced font asset even after replacement/removal.
- **Image elements:** upload bitmap images and constrained SVG assets, position,
  resize and preserve aspect ratio. Provide brightness and contrast controls and
  tonal conversion settings. Treat the profile's foreground/background as the
  printed colors; derive the colored preview from the same converted image used
  for output. Sanitize SVGs, disable scripts/external resources, and bound file,
  pixel and rendering costs. Retain original assets plus immutable processing
  settings so changing an upload cannot alter queued labels.
- **Tonal rendering:** preserve grayscale image data until the destination's
  rendering capability is applied. Keep native grayscale and 1-bit dithering as
  distinct modes and expose only modes supported by the selected adapter. The
  user reports PT-P710BT grayscale capability; verifying its actual encoding and
  physical behavior is a required stage 4 task, not an established capability of
  the current mock or renderer.

Acceptance: preview and queue mixed-length CSV rows without changing their order
or data; verify atomic submission and interrupted-run recovery; test auto-size
on/off, clipping and fixed-stock limits; verify uploaded fonts/images survive
restart and remain stable in queued jobs; compare preview with final raster for
brightness/contrast, color mapping and each supported tonal mode.

## Preparatory architecture for the later multi-user phase

Preparatory boundaries are now implemented for local-owner mode: centralized
request policy checks, explicit actor context for job preparation, stable owner /
personal-template-scope / destination references, and notification recipient
routing ahead of the delivery adapter. Migration `c52d171ca013` backfills existing
records without changing frozen documents, run manifests or copy history. Legacy
asset metadata resolves to the local owner without rewriting image/font bytes.
The current worker only reserves the `main` destination. Accounts, tenant-filtered
queries, membership checks and independent per-printer queues are not enabled.

The boundaries to extend in the gated phase are:

- Pass an actor context through application services and centralize authorization
  behind a policy interface. Initially use the existing local-owner behavior;
  do not scatter role checks through rendering, queue logic or printer drivers.
- Reserve stable owner, template-scope and destination references, with migration
  paths for existing templates/jobs to the local owner/default printer. Separate
  immutable assets/revisions from who may view, edit or submit them.
- Keep request submission/approval separate from executable print jobs, and keep
  notification recipient selection separate from the ntfy delivery adapter.
  These are extension points now; do not activate moderation or account flows.
- Plan per-printer access checks at service boundaries alongside the existing
  printer registry and future per-destination queue isolation.

## Phase 8: multi-user administration (explicit approval gate)

This is the final, low-priority implementation phase. **Do not begin its feature
implementation without explicit user approval.** The gate comes directly from
TODO.md; it does not block the preparatory architecture above.

- **Authentication and registration:** add user accounts and administrator-issued
  registration codes. Make code-required registration configurable; turning it
  off permits registration without a code. Registration must not grant admin
  privileges, and existing records need an explicit local-owner migration.
- **Roles and permissions:** administrators create roles, assign permissions and
  manage users. Enforce permissions in the backend for every relevant operation,
  with corresponding UI visibility. Define a permission matrix before coding.
- **Groups and template scope:** administrators create groups and manage their
  membership. Support personal, group-shared and global templates. Administrators
  can see all templates; only administrators may create global templates. Specify
  edit/share rights and membership-change behavior in the permission matrix.
- **Printer access:** administrators grant access to each printer to individual
  users and groups. Enforce access for submission, preview/status and applicable
  management operations; never treat a hidden UI control as authorization.
- **Approval requests:** introduce a separate durable request queue. Administrators
  approve or reject requests; only approval can create executable print jobs.
  Freeze the content being approved and make approval idempotent so retries
  cannot duplicate jobs. Decide which roles may submit directly in the permission
  matrix; pending requests do not count toward automatic printing thresholds.
- **Administrator notifications:** notify administrators when requests arrive via
  the existing durable notification system, preferably ntfy. Add configurable
  debounce/coalescing and summary counts/links so 50 requests can produce one
  notification. Persist pending summaries across restarts and bound postponement
  during continuous arrivals; delivery retries must never approve or print jobs.

Acceptance: test code-required and open registration, role/group access changes,
all template scopes, administrator visibility, per-user/group printer grants,
unauthorized API calls, request isolation, exactly-once approval effects, and
notification coalescing/restart behavior. Confirm the permission matrix and
registration defaults as part of approval to implement this phase.

## Protocol research already checked

Brother's PT-P710BT raster reference documents status notifications but no
current-job consumed-length counter was found. TZe status `media length` is zero.
Plan for calculated estimates; add reported measurements only if verified.
Reference: https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf

## Acceptance checks for stage 1

- Nine compatible copies wait; the tenth produces one frozen batch.
- Different profiles stay queued even when their widths match.
- Per-profile threshold changes and multiple copies work; manual flush works.
- Unknown/mismatched width prevents printing; restored status resumes work.
- Printer access and review decisions cannot cause concurrent sessions.
- Partial failure and restart require review; confirmed copies are not retried.
- Jobs, consumption, reminders and notification retries survive restarts.
- Snooze, silence, interval changes and reminder episode reset work.
- Failed notification delivery cannot duplicate physical prints.

## Scope boundary

Stage 1 uses an explicitly artificial mock renderer. Its output and consumption
estimates are development fixtures, not production label rendering or verified
PT-P710BT behavior. Physical behavior needs hardware acceptance testing.

## Implementation status

Stages 1 and 2 are implemented. The backend integration suite covers the acceptance checks above,
including real Alembic migrations, application restart and worker ownership.
The API is usable through FastAPI's `/docs`. Docker/Compose defaults to mock mode
and includes an opt-in USB override; Compose configuration was validated, but the image has not been
built or run because no Docker daemon was available in the development session.
The Vue workflow includes a responsive dashboard, submission, filtered queue,
profile/cartridge management, reminder controls, consumption corrections,
activity and copy-level review. Mock controls exercise interruption and connection
failures. A production frontend build is served by FastAPI; the Dockerfile also
builds it. Chromium tests cover the full interrupted-batch workflow, reminders,
mobile layout and error handling. The tape appearance sample is not a print preview.

Stage 3 is implemented: a visual text/QR/shape editor with drag, resize, rotation,
layer ordering, numeric geometry, undo/redo, field bindings and revisioned saves.
Backend SVG rendering produces a smooth, higher-resolution design preview and
the immutable job's 1-bit raster using bundled fonts. A Show print pixels toggle
exposes the exact raster; physical print quality remains unverified. Tests decode rendered QR codes, compare preview
pixels with print pixels and verify that edits cannot alter queued revisions.
The automatic-print hold from TODO.md persists across restarts, permits manual
flushes and preserves review safeguards. Browser coverage includes design, save,
reopen, submission and hold/resume.

Printer definitions, capabilities, USB/network connection types and a driver
registry establish extension points for multiple printers. The running queue is
still single-printer; operational destination isolation is specified in
`docs/PRINTER_ARCHITECTURE.md` before additional devices can be enabled.

The layout portion of the stage 3 extension is implemented: saved strict/clipping
policies, automatic continuous-label length and optional text width fitted to each
value. Preview and queue share layout resolution; queued sizes are frozen. Tests
cover clipping pixels, omitted objects, rotations, length limits, fixed-media
refusal and field-dependent label lengths. Existing templates default to strict
bounds and manual length; no database migration is needed for these options.

CSV authoring is implemented: bounded UTF-8 CSV import, column mapping, row
selection/order/copies, row validation and persistent frozen drafts. Each run has
an ordered overview, individual smooth/raster previews and an adapter estimate.
Submission is atomic and idempotent per run; preparation keys protect retries.
Jobs retain run/source-record identity and print order. The queue groups runs
into expandable rows without splitting them across pages. Selected-copy printing
freezes only the chosen copies and holds automatic printing for the remainder.
Unsubmitted drafts can be deleted; submitted run history is retained. Tests cover quoted and
multiline CSV, malformed/oversized inputs, rollback, restart, frozen previews,
interrupted-copy recovery and migrations preserving existing queue data. Physical
chain/cut/feed behavior remains in the Brother stages; UI previews do not imply
that hardware behavior is verified.

Font uploads are implemented: static TTF/OTF validation, immutable content IDs,
family/style picker, and reversible hiding that preserves saved and queued labels.
The shared renderer uses the exact uploaded face for metrics and output. Assets
live beside the database and must be included in backups.

Image uploads are implemented: bounded still bitmaps and a strict SVG shapes/paths
subset, immutable originals and normalized rendering assets, reversible hiding,
and inline editor uploads. Image selection fits the box to the asset ratio;
aspect preservation locks numeric and corner resizing. New editor templates
default to automatic length and clipping. In-app confirmations use a shared
themed Vue dialog. Image elements support brightness, contrast, threshold and
Floyd–Steinberg dithering. SVGs are rasterized at the element's device resolution;
preview and print share the converted image and tape color mapping. Tests cover
rejected active SVG content, tonal controls, transparent artwork, frozen runs and
queued raster equality. Native grayscale remains unverified and is not offered.
The image library includes cached PNG thumbnails and enlarged previews, inline
renaming without changing content identity, and confirmed permanent deletion of
unused assets. Deletion checks current templates, historical revisions, job
snapshots and CSV manifests under the application lock; referenced artwork remains
available and can be hidden from new selections.

Preparatory identity, policy and recipient-routing boundaries are implemented.
Stages 4–7 software is implemented: opt-in PT-P710BT USB transport and buffered
raster commands, status/width checks, conservative interruption handling, ordered
multi-page/final-feed commands, selectable individual cuts or strip output, feed
and leader calibration settings, saved CSV cut/feed plans, USB deployment files,
and durable single-job idempotency keys with a retrying REST client. The HomeBox
PNG print-command bridge now uploads immutable images, optionally saves pixel
previews and submits frozen image jobs without adding library templates. Image
jobs reuse queue policies and durable idempotency receipts, fit printable geometry
without distortion, and retain selected resolution. Tests cover concurrent retries,
restart, a lost response after commit, access checks and preview/print equality.
Installation and verification in a running HomeBox deployment remain pending.
Normal 180 dpi monochrome and opt-in 180 × 360 dpi are
implemented, with native rendering, resolution-aware feed and saved per-job
resolution. The user reported excellent high-resolution output on 2026-10-02;
native grayscale remains deferred. On the same date the user confirmed successful
normal-resolution batch completion, QR scanning and an exactly 10 mm test line.

Template resolution selection, independent text padding on all four sides, mm
rulers with selected-object spans and cursor guides, and toggleable dashed object
boundaries are implemented. Pixel previews are the default across editor, label
submission and CSV runs. Existing documents retain zero padding and printer-default
resolution; already frozen jobs/drafts retain their captured resolution.
Editor properties use animated, keyboard-accessible expandable categories in the
sidebar (stacked on narrow screens). Add buttons use Heroicons; grid, rulers and
cursor guides remain on. Single-line inputs and selects share consistent sizing
across the UI, and disclosure animations respect reduced-motion preferences.

Distance holders are implemented as validated, acyclic relationships between
objects, with a configurable horizontal or vertical gap measured between rotated
bounds. Text fitting resolves first, then linked positions, then automatic label
length; CSV rows and jobs freeze the resulting geometry. The editor exposes target,
direction and gap controls, protects the linked coordinate, and detaches followers
when their anchor is removed. Rotation-aware dragging and corner resizing work at
all four orientations while preserving the opposite corner during resizing.
Template/profile selections, the selected editor element and preview tape, and
saved CSV preview rows persist in URLs for refresh and direct links.

Batch history and interruption review include per-copy label thumbnails with an
accessible enlarged preview. The read-only job preview endpoint uses the same
frozen raster inputs as printing, preserving CSV values, image assets and print
resolution after later template edits. Previews show physical proportions in black
and white; outcome badges remain authoritative for whether a copy was printed.

Physical USB behavior, print quality, cuts and consumption calibration still await
user verification using docs/HARDWARE_VERIFICATION.md. Container image execution
also remains unverified here because no Docker daemon was running. These are
acceptance gaps, not completed hardware checks. Backend and browser tests cover
the software paths and Compose syntax is checked. Shipping-label and other printer drivers remain
deferred; Wi-Fi/network support is architectural. Phase 8 is low priority and
requires explicit approval before implementation.
