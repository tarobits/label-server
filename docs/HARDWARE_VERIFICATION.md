# PT-P710BT verification record

The user reported successful physical testing on 2026-10-04. No additional
per-check measurements, device details, or consumption calibration were supplied.
The table below retains earlier individual results.

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

## Consumption calibration

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

## Protocol implementation notes

[Brother raster reference v1.02](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf)
is the protocol source. USB VID/PID is `04f9:20af`. Buffered PackBits lines contain
128 head bits. The driver requests status only outside printing and waits for
completion plus return to reception. It uses FF between pages and final feed at
the end. Unsupported half-cut and cut-every-N commands are not sent. Ink outside
the printable head band is refused, including old jobs prepared with mock margins.
Reopen/re-save those templates and create fresh jobs after selecting the USB backend.
