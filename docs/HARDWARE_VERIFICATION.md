# PT-P710BT verification record

The user reported successful physical testing on 2026-10-04. No additional
per-check measurements, device details, or consumption calibration were supplied.
The table below retains earlier individual results.

On 2026-10-17, the user also reported a successful physical print from the native
Debian VM through its Proxmox USB mapping, after applying the frontend's HTTP UUID
compatibility fix. After a subsequent VM reboot, the service restarted
automatically, the hold persisted, and another physical print succeeded.
The user also confirmed successful USB reconnect and printing without restarting
the VM or service; SSH checks confirmed the service stayed running and healthy. See
[deployment verification](DEPLOYMENT.md#proxmox-vm-usb-access).

On 2026-10-02, the user confirmed batch completion after a USB-reader fix, an
exactly 10 mm test line, successful QR scanning, and excellent visual quality at
180 × 360 dpi. The reader now skips empty USB transfers within the original
timeout instead of treating them as disconnects.

Normal output is 180 × 180 dpi; high output is 180 × 360 dpi. The API uses physical
widths, including 3.5 mm. Brother wire codes are translated only inside the adapter.
Tonal artwork uses 1-bit dithering; native grayscale is not enabled.

For new tests, record printer serial/firmware, tape SKU, host OS, settings, date,
and measured results.

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
3. Prepare a persistent draft (this command does not submit or print):

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
| Scale | Short rule is 10 mm; measure text/image dimensions too | User measured exactly 10 mm (2026-10-02); other dimensions not measured |
| Content band | Artwork lies within approximately 18 mm on 24 mm tape | |
| Fine text | Compare 2 mm and 3 mm text with P-touch output | Missing strokes at very small sizes accepted; high-resolution comparison accepted |
| Curves/diagonals | Circle and diagonal retain shape without extra scaling | |
| QR | Scan all copies; decoded content is `https://example.org` | Scan confirmed (2026-10-02); payload and all-copy coverage not reported |
| Tonal image | Three distinct dither densities; not native grayscale | Light block initially faint; raster smoothing fixed. No separate post-fix tonal measurement reported |
| Copies/order | Exactly 01, 02, 03, in that order | |
| Cuts | One cut per label with **Cut each label** enabled | |
| Strip mode | With false: continuous sequence and final feed/cut | |
| Batch completion | Queue clears without interruption/review | Passed per user after empty-USB-transfer fix (2026-10-02) |

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
- Interrupt ntfy connectivity: alerts retry; printing state is independent.
- Repeat a REST submission with the same idempotency key: one job/copy set.

## Stop controls

Use a small batch and retain the output for review. These controls have automated
transport, concurrency and UI coverage. A first physical graceful-stop result was
reported on 2026-10-17. Hold persistence after review and a server restart was
also confirmed. An emergency-stop test prevented the following label. A repeat
with a longer label also finished the active label, so mid-label interruption
failed in the reported tests. Cancelling during upload remains unverified.

On 2026-10-17, the user accepted stopping after the current label as sufficient
and removed mid-label interruption as a requirement. Stop behavior is accepted
for the current deployment. Upload cancellation and stop-mode upgrade remain
physically unverified optional future checks, rather than acceptance blockers.

During **Stop after current label**, the user reported that one label finished
printing but was not cut, and the batch entered review. A subsequent manual
feed/cut action fed an extra 10 mm and cut the output. The method used for that
manual action, the total consumed tape, and whether any following label began
were not reported. Include the extra 10 mm in the attempt's total consumption
when saving review. The user subsequently saved the review using **Cancel** and
confirmed that automatic printing remained held after a server restart. This
verifies hold persistence through cancellation review and restart. After the
longer-label emergency-stop test, the user also confirmed that saving review
with unprinted copies requeued left automatic printing held. A restart after
that requeue review was not reported. The total consumption entered during
either review was not reported.

The current adapter ends a stopped chain with cancellation rather than the
normal final-page feed/cut. This is consistent with the observed uncut output;
graceful stopping has not established automatic delivery of a cut label. Keep
the last output uncertain until it has been inspected and reconciled.

For **Emergency stop**, the user reported on 2026-10-17 that the first label
finished printing, no other label started, review was triggered and automatic
printing remained held. This verifies prevention of a following label and the
review/hold outcome for that attempt. It does not demonstrate interruption of an
active label midway. The label length, stop-request timing, cut behavior and
total consumed tape were not reported for this test. The adapter checks emergency
intent between raster commands and during completion waits; the observation
alone does not distinguish request timing from device cancellation behavior.
The test was then repeated using the requested longer-label procedure (a fixed
200 mm label, with a request as soon as printing visibly began). The user reported
that the entire first label still printed. No new second-label, cut, review or
hold observation was supplied in the initial repeat report; hold persistence
after requeue review was subsequently confirmed as described above. Mid-label
interruption is a known limitation of the tested implementation; this result does not prove that a
different supported implementation is impossible. No USB trace or request timing
measurement has established the cause.

The raster reference's printed page 4 instructs clients to wait for completion
before sending another command; page 23 describes initialization as cancellation
but gives no guarantee about stopping a physically executing label midway.
Page 39 describes buffered printing, which this adapter uses. Keep the current
label's possible completion explicit in the UI and documentation. A mock transport
accepting cancellation bytes does not establish a physical motor-stop guarantee.

Optional future physical checks cover cancellation during upload and upgrading a
graceful stop to emergency without allowing another graceful request to undo it.
Independent operation of another printer is deferred until a second printer is
available. These checks have automated coverage but have not been physically
verified. No further mid-label interruption investigation is required for the
current scope.

When stopping a real batch, inspect the last output, including any deferred
feed/cut, and reconcile uncertain copies and consumed tape. Saving review must
preserve the hold; resume explicitly when ready. **Select from here** can apply
Requeue or Cancel to subsequent uncertain copies. Confirmed copies remain locked.

The raster reference documents `ESC @` cancellation on printed page 23. The driver
sends it from the hardware-owning thread between complete commands. It does not
open a competing USB connection or query status during printing.

No standalone cutter opcode is documented in the raster reference. The
[Brother User’s Guide](https://download.brother.com/welcome/docp100362/pt-p710bt_eng_ug_03.pdf)
documents double-pressing the physical power button to feed and cut (printed pages
8, 11 and 14). No blank-label cutter workaround is sent by this implementation.

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
inventory. Record their measurements here and correct the cartridge's remaining
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

The calibration measurements were reported by the user on 2026-10-17 after
running the direct helper: printer USB serial `000E6G210727`, detected 24 mm tape,
normal resolution (180 × 180 dpi), 2 mm feed setting and 24.5 mm leader estimate.
Firmware and tape SKU have not been reported. The estimates exceeded measured
use in all four runs: by 3.45 mm for each one-label run, 1.85 mm for three
individually cut labels and 4.35 mm for the three-label strip. Reported detached
blank leaders varied from 22 to 24 mm, and the three individually cut printed
pieces averaged 63.5 mm. The user confirmed that the three strip-mode labels
remained joined, the blank leader stayed attached in both strip-mode runs, and
each strip was cut automatically at the end.

The initial four-run baseline is complete. Retain the existing 2 mm feed setting
and 24.5 mm leader estimate as conservative estimates for these tested conditions;
do not fit new defaults to one run per case. On 2026-10-17, the user accepted the
differences as within the margin of measurement error and requested no further
repeat measurements. This closes consumption verification for the current scope;
it does not establish statistical repeatability or consumption at
other resolutions, feed settings, label lengths or tape types. They also do not
turn the estimate into a sensor measurement or set the batch plan's `calibrated`
flag. The four direct batches consumed a reported total of 596.5 mm; the helper
did not deduct that amount from cartridge inventory.

Record printer serial/firmware, tape SKU, resolution, feed and leader settings
with these measurements. The estimate difference between the one-label and
three-label runs helps distinguish per-label waste from a fixed batch leader.
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

On 2026-10-17, the
[Brother Raster Command Reference v1.02](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf)
was checked for native PT-P710BT grayscale support. Printed page 2 defines raster
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
