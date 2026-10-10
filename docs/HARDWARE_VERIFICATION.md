# PT-P710BT verification record

**2026-10-04: physical printer testing validated by the user after the review fixes.**
This records user-reported hardware acceptance of the current implementation.
No new per-check measurements, device details or consumption calibration values
were supplied with this confirmation. Earlier observations below are retained as
historical results.
Initial user testing on macOS reached the first printed label, then entered review
with `Printer disconnected while reading status`. The USB reader incorrectly
treated a zero-length transfer as EOF. It now skips empty transfers within the
original timeout; real disconnect errors still require review. On 2026-10-02 the
user confirmed that the batch cleared successfully after this fix.
Record printer serial/firmware, tape SKU, host OS, settings, date and results below.
Printers support normal 180 × 180 dpi and high 180 × 360 dpi output. On 2026-10-02 the user reported
excellent visual quality from the 180 × 360 dpi comparison print. The API uses
physical widths, including 3.5 mm. The Brother adapter maps its status byte 4 to
3.5 mm; that byte never serves as a domain measurement. Native grayscale is not enabled;
tonal artwork uses 1-bit dithering.

## Compare high-resolution output

Keep automatic printing held and stop the backend. Rebuild the frontend with
`npm run build --prefix frontend` for previews with the correct physical aspect.
For this Mac USB test, start from the project directory with:

```sh
sudo .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

The temporary sudo workaround is needed on this Mac to detach its USB kernel
driver; Linux deployment uses device group permissions instead. Under **Printers & groups → Configure**, select **180 × 360 dpi**.
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

1. Back up the database and assets, upgrade migrations, and select the USB backend
   using [deployment instructions](DEPLOYMENT.md). Stop other applications that
   access the printer. Set automatic printing to held before adding labels.
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

The table records earlier individual observations. The overall validation above
supersedes the earlier pending status; unreported measurements remain blank.

| Check | Expected | Measured / result |
| --- | --- | --- |
| Orientation | Text and arrow readable; circle before shaded blocks | |
| Scale | Short rule is 10 mm; measure text/image dimensions too | User measured exactly 10 mm (2026-10-02); other dimensions not measured |
| Content band | Artwork lies within approximately 18 mm on 24 mm tape | |
| Fine text | Compare 2 mm and 3 mm text with P-touch output | User accepts missing strokes at very small sizes; Earlier comparison concern: overall blockiness versus P-touch; high-resolution output subsequently accepted |
| Curves/diagonals | Circle and diagonal retain shape without extra scaling | |
| QR | Scan all copies; decoded content is `https://example.org` | Successful scan confirmed by user (2026-10-02); decoded payload/all-copy coverage not separately reported |
| Tonal image | Three distinct dither densities; not native grayscale | Lightest block almost invisible; medium dots visible. Raster smoothing bug fixed; overall physical testing subsequently validated (2026-10-04), with no separate tonal measurement reported |
| Copies/order | Exactly 01, 02, 03, in that order | |
| Cuts | One cut per label with **Cut each label** enabled | |
| Strip mode | With false: continuous sequence and final feed/cut | |
| Batch completion | Queue clears without interruption/review | Passed per user after empty-USB-transfer fix (2026-10-02) |

The shading defect was reproduced before printing: the light block in the original
acceptance raster retained only about 0.5% black pixels in an interior sample,
instead of its intended approximately 20%. The SVG renderer was smoothing the
already-dithered bitmap, and final monochrome thresholding erased isolated dots.
Using the renderer's supported nearest-neighbor image setting preserves the dot
coverage. Regression tests cover all three gray levels at multiple placements.
Visible individual dots are still expected from this monochrome dither mode.

The small-text fixture lies inside the printable band and produces no clipping
warning. The user accepts missing fine strokes at this size; matching P-touch's
overall visual quality motivated the high-resolution comparison. The user subsequently
reported excellent high-resolution output; detailed measurements across more artwork,
tape widths and feed settings remain part of this verification record.

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
Changes apply without restarting; existing draft estimates
remain historical. Verify again before relying on cartridge estimates.

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

Physical testing was validated by the user on 2026-10-04. This acceptance comes
from the user’s hardware testing; mock or captured USB streams provide separate
software regression coverage.
