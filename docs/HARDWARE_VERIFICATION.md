# PT-P710BT verification record

This record separates reported physical observations from automated coverage.
Results came from single-device PT-P710BT tests; they do not establish compatibility
with every host, firmware, tape, or deployment method. Device identifiers and
installation-specific logs are intentionally omitted.

Reported checks include physical printing, a 10 mm scale line, QR scanning,
high-resolution output, batch completion, and native-service recovery after reboot
and USB reconnect. Simultaneous printing on two physical devices, Docker/LXC USB
passthrough, and cancellation during raster upload remain unverified.

Normal output is 180 × 180 dpi; high output is 180 × 360 dpi. The API uses physical
widths, including 3.5 mm. Brother wire codes are translated only inside the adapter.
Tonal artwork uses 1-bit dithering; native grayscale is not enabled.

For new public test records, include the printer model, firmware version, tape
specification, OS family, print settings, and measured results. Use anonymous device
labels when comparing units; omit serial numbers, hostnames, local usernames,
network addresses, and deployment logs containing account information.

## Compare high-resolution output

Hold automatic printing before submitting test labels. If updating the software,
stop the backend, apply migrations, rebuild the frontend, and restart first.
Ensure USB access is configured as described in [deployment](DEPLOYMENT.md).
Under **Printers & groups → Configure**, select **180 × 360 dpi**.
The printer card shows the current default (across × along tape).
Alternatively, choose **High · 180 × 360 dpi** in the template's Print resolution
selector; it overrides the printer default. Create a fresh job from the same
template, or rerun the draft generator below. Existing jobs and CSV drafts
keep their original resolution, even after changing this setting. Select only the
new test labels and print manually.

Compare against the retained tapes and P-touch output, using the same font, size,
artwork and tape. Recheck the 10 mm line, QR scan, circle shape, shading and batch
completion. Vector text and shapes are rendered at the higher device resolution;
feed dots are adjusted with it. No enlargement of an old print raster is used.
Switch back to **180 × 180 dpi** in the same form if needed. No restart is required.

## Prepare without printing

1. Back up the database and assets and configure the printer using
   [deployment](DEPLOYMENT.md). Stop other applications that access it. Hold
   automatic printing before adding labels.
2. Register a 24 mm tape profile and cartridge, install it, and confirm detected
   width. Keep color selection manual: width detection does not establish color.
3. Set `LABEL_API_USERNAME` and `LABEL_API_PASSWORD` in the client environment
   for an account that can create personal templates, upload images, and use the
   destination. Prepare a persistent draft (this command does not submit or print):

   ```sh
   .venv/bin/python scripts/prepare_acceptance.py --profile PROFILE_ID --destination PRINTER_ID
   ```

4. Open the printed draft URL. Inspect the smooth and device-pixel previews and
   the planned feed/cut sequence. Submit when ready, select only these labels and
   use the manual print action. The automatic hold keeps unrelated copies queued.

## Quality and geometry

Blank results indicate measurements that have not been reported.

| Check | Expected | Measured / result |
| --- | --- | --- |
| Orientation | Text and arrow readable; circle before shaded blocks | |
| Scale | Short rule is 10 mm; measure text/image dimensions too | Reported exactly 10 mm; other dimensions not measured |
| Content band | Artwork lies within approximately 18 mm on 24 mm tape | |
| Fine text | Compare 2 mm and 3 mm text with P-touch output | Missing strokes reported at very small sizes; high-resolution quality reported satisfactory |
| Curves/diagonals | Circle and diagonal retain shape without extra scaling | |
| QR | Scan all copies; decoded content is `https://example.org` | Scan confirmed; payload and all-copy coverage not reported |
| Tonal image | Three distinct dither densities; not native grayscale | Light block initially faint; raster smoothing fixed. No separate post-fix tonal measurement reported |
| Copies/order | Exactly 01, 02, 03, in that order | |
| Cuts | One cut per label with **Cut each label** enabled | |
| Strip mode | With false: continuous sequence and final feed/cut | |
| Batch completion | Queue clears without interruption/review | Reported passed after empty-USB-transfer fix |

A raster smoothing defect initially reduced the light dither block from about
20% to 0.5% black pixels. Nearest-neighbor image sampling now preserves dot
coverage; regression tests cover three gray levels at multiple placements.
Individual dots are expected in monochrome dithering.

Duplicate the template and test QR boxes of 12 and 16 mm, longer content, a narrow
tape profile and a dense bitmap. Validation may reject a QR that would have fewer
than two device pixels per module. Do not infer physical sharpness from zoomed
screen previews. If the orientation is wrong, stop and retain the result before
changing raster ordering; do not compensate with a global template flip.

## Failure and recovery

- Disconnect before submitting: no page is sent. Reconnect and confirm status.
- Install a different width: printing must be blocked without consuming tape.
- Open cover / empty tape: a blocker appears, or an active attempt enters review.
- Disconnect or power off during an attempt: review is required; no automatic
  replay. Inspect every uncertain copy before marking printed, requeueing or
  cancelling. The immediately preceding page can remain uncertain during feed.
- Restart the server during an attempt: the durable in-flight batch becomes review.
- Interrupt ntfy or SMTP connectivity: queued alerts retry; printing state is independent.
- Repeat a REST submission with the same idempotency key: one job/copy set.

## Stop controls

Use a small batch and retain the output for review. Automated checks cover
transport, concurrency, and UI behavior. Reported physical results are:

- **Stop after current label** allowed a label to finish, left it uncut, and put
  the batch into review. A subsequent manual feed/cut used additional tape.
- **Emergency stop** allowed the active label to finish and prevented the next
  label in one reported test. A repeat using a 200 mm label also finished the
  active label. Mid-label interruption has not been demonstrated.
- Automatic-print holds persisted after cancellation review and restart, and
  after a separate requeue review. A restart after that requeue was not reported.

These are observations, not guarantees about command timing or motor behavior.
No USB trace established the reason the active label completed. Cancellation
during upload, upgrading graceful stop to emergency stop, and independent
operation of a second physical printer remain unverified.

The adapter checks stop intent between complete raster commands and during
completion waits. It ends a stopped chain with cancellation rather than the normal
final-page feed/cut, so the last label can remain uncut. Inspect it before marking
it printed; include any additional feed and waste in total consumed tape.

When reviewing a stopped batch, reconcile every uncertain copy and preserve the
automatic-print hold. **Select from here** can apply Requeue or Cancel to subsequent
uncertain copies; confirmed copies remain locked. Resume printing explicitly.
A mock transport accepting cancellation bytes does not prove a mid-label stop.

The raster reference documents `ESC @` cancellation on printed page 23. The driver
sends it from the hardware-owning thread between complete commands. It does not
open a competing USB connection or query status during printing.

No standalone cutter opcode is documented in the raster reference. The
[Brother User’s Guide](https://download.brother.com/welcome/docp100362/pt-p710bt_eng_ug_03.pdf)
documents double-pressing the physical power button to feed and cut (printed pages
8, 11 and 14). No blank-label cutter workaround is sent by this implementation.

## Short labels and chain printing

Short variable-length designs have been reported to produce equally long pieces
with unused tape on 12 mm tape; no measured cut length was recorded. The
[Brother Raster Command Reference, printed page 18](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf)
documents a 24.5 mm minimum fed-out length due to the cutter position, independent
of tape width.

The adapter already enables chain printing between pages in a batch, using FF
for intermediate pages and Control-Z with final feeding/cutting for the last
page (printed pages 33, 37–38). Chain printing defers the final feed; the reference
does not guarantee individually cut pieces shorter than the cutting minimum.
The adapter does not retain chain state across batches.
Sub-minimum individual cuts in chain mode remain unverified on hardware.

With **Cut each label** enabled, the plan applies the minimum to each design
plus its configured feed. Short designs retain their intended layout. New label
creation and validated CSV drafts warn that hand trimming is required and report
the estimated extra unused tape caused specifically by this minimum, excluding
normal feed and batch overhead. With it disabled, labels form a continuous strip;
the minimum is applied once to the whole strip and labels require manual separation.

CSV drafts preserve their preparation plan; individual submissions save their
plan in the template snapshot. Before transmitting any print data, each physical
attempt saves the current adapter plan, per-copy expected output, extra tape,
and trimming requirement. Activity and batch details display this saved record,
and the server logs a warning for planned minimum-cut waste. Interrupted attempts
keep the plan as an estimate, never a claim that all planned tape was consumed.
Older attempts have no recorded plan; current settings are not used to invent one.

Tape estimates now retain four exclusive categories: design, feed, leader, and
unused. Their unrounded sum equals the existing total estimate. Automatic-length
padding to 10 mm is classified as unused alongside padding from the cutting
minimum; it is not added a second time to consumption. Design remains the intended
layout extent, including its own margins, before that automatic-length padding.
Manually chosen fixed canvas lengths remain design length.

Queue Details estimates the remaining copies of an item or CSV run as one batch,
using current settings and one leader. Separate queue items can share a physical
batch, so their hypothetical leaders must not be summed as actual usage. Activity
Details uses the immutable attempt plan. The printer does not measure category
totals: estimated, backend-measured, and reviewer-reported consumption are recorded
separately. A reviewer-reported total does not rewrite the planned category split.

## Consumption calibration

For a direct bench test without running the web server, use
`scripts/calibrate_tape.py`. Stop the server and other applications using the
printer first. The helper takes the configured database's server ownership lock,
requires a ready printer with 24 mm tape, and never retries uncertain output.
It prints fixed 60 mm label bodies with a 50 mm rule, using 2 mm feed and a
24.5 mm initial leader estimate. Normal resolution is 180 × 180 dpi; pass
`--resolution high` consistently for all runs to test 180 × 360 dpi instead.

First inspect the estimate without accessing USB:

```sh
.venv/bin/python -m scripts.calibrate_tape --serial USB_SERIAL
```

Add `--print` to print one batch. On macOS, USB kernel-driver capture may require
running that command with `sudo`. Repeat with `--copies 1` and `--copies 3` for
each of `--cut each` and `--cut strip`, measuring all output after each batch.
These direct prints create no queue/history records and do not update cartridge
inventory. Record anonymized measurements and correct the cartridge's remaining
length separately after the test.

For calibration through the web UI, follow the procedure below.

Hold automatic printing and use a fixed-length template for all four runs below.
Keep tape, resolution and feed settings unchanged, and create fresh jobs after
changing **Cut each label** so each job uses the intended settings. Print each
run as one manually selected batch. Retain and measure every emitted piece,
including detached blank leaders; do not measure only the printed label bodies.

| Cut each label | Labels in batch | Label length (mm) | Estimated total (mm) | Measured total (mm) |
| --- | --- | --- | --- | --- |
| On | 1 | 60 | 88.45 | 85 (22 blank leader + 63 printed piece) |
| On | 3 | 60 each | 216.35 | 214.5 (24 blank leader + 63 + 64 + 63.5 printed pieces) |
| Off | 1 | 60 | 88.45 | 85 (one piece, blank leader attached; automatic final cut) |
| Off | 3 | 60 each | 216.35 | 212 (one continuous strip, blank leader attached; automatic final cut) |

These four single-run measurements used 24 mm tape, normal resolution
(180 × 180 dpi), 2 mm feed, and a 24.5 mm leader estimate. Firmware and tape SKU
were not recorded. Estimates exceeded measured totals by 3.45 mm in each one-label
run, 1.85 mm for three individually cut labels, and 4.35 mm for the three-label
strip. Detached leaders ranged from 22 to 24 mm. In strip mode, the labels remained
joined with the leader attached, and the strip was cut automatically at the end.

Retain the existing feed and leader defaults as conservative estimates for these
tested conditions. One run per case does not establish statistical repeatability,
other print settings, or other tape types. These observations do not turn an
estimate into a sensor measurement or set the batch plan's `calibrated` flag.

For further measurements, record anonymized device labels, firmware, tape
specification, resolution, feed, and leader settings.
The estimate difference between the one-label and three-label runs helps
distinguish per-label waste from a fixed batch leader.
If those differences disagree with the measurements, changing only the leader
cannot calibrate both runs. Check actual feed and cut behavior before adjusting
the estimate, then repeat all four runs to validate any changes.

Measure a one-label and a three-label batch, including trimmed leaders and all
feed. Repeat with the intended cut setting. Compare actual totals with estimates.
The default estimate is an initial assumption, not a measurement. It uses label
length, configured feed at both ends, a configurable batch leader, and the
minimum physical output length. Adjust **Leader estimate** for fixed waste
and **Feed** for actual desired feed under **Configure → Feed & cut settings**.
Changes apply without restarting; saved drafts keep their earlier estimates. Verify again before relying on cartridge estimates.

The protocol has no documented current-job consumed-length counter. Review asks
for total consumed tape when an attempt is uncertain. Correct the cartridge's
remaining estimate after calibration; do not count displayed estimates as sensor
measurements.

## Grayscale protocol investigation

The
[Brother Raster Command Reference v1.02](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf)
defines the documented PT-P710BT raster interface. Printed page 2 defines raster
data as binary bitmap data. Pages 19–20 map individual bits to the 128 print-head
pins; page 36 specifies 16 decompressed bytes per raster line. The command list
and mode settings on pages 22 and 31–33 expose no per-pixel gray levels. The
high-resolution setting changes dot resolution, not pixel depth.

The finding is that the documented raster interface does not support native
grayscale. This does not establish what undocumented firmware or other interfaces
could do. The adapter continues to advertise one-bit output and tonal artwork
uses dithering. The investigation is complete; enabling native grayscale would
require a supported encoding and separate physical validation.

## Protocol implementation notes

[Brother raster reference v1.02](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf)
is the protocol source. USB VID/PID is `04f9:20af`. Buffered PackBits lines contain
128 head bits. The driver requests status only outside printing and waits for
completion plus return to reception. It uses FF between pages and final feed at
the end. Unsupported half-cut and cut-every-N commands are not sent. Ink outside
the printable head band is refused, including old jobs prepared with mock margins.
Reopen/re-save those templates and create fresh jobs after selecting the USB backend.
