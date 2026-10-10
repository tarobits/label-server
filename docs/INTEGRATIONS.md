# REST integrations

Use the API from Home Assistant, Shortcuts, scripts, or inventory systems.

## Authentication and access

Create an account with a role granting access to the required printers or groups. Print, Moderator or Full permits direct
queue submission; Request only requires approval. A distribution-group permission
does not grant direct access to its printers. Image upload also requires the
`assets.write` application permission in a directly assigned role.

The bundled clients read `LABEL_API_USERNAME` and `LABEL_API_PASSWORD` from their
environment, sign in, retain the session cookie in memory and send the CSRF token.
Keep credentials in the integration's secret store rather than command arguments.
Copy `scripts/api_session.py` alongside the client when installing it elsewhere.
Add `--request-approval` to either submission script to create a pending request.

Other clients first POST `{"username":"…","password":"…"}` to `/api/auth/login`.
Retain the returned cookie and send the response's `csrf_token` in the
`X-CSRF-Token` header on every mutation. Sessions expire after seven days; sign in
again after a 401. Use HTTPS outside localhost. Never put credentials in a URL.

Administrator submission of another user's CSV draft can return HTTP 409 with
`detail.code: "owner_access_discrepancy"`, an explanatory `detail.message` and
`detail.override_allowed: true`. Present that discrepancy and obtain an explicit
administrator confirmation before retrying `POST /api/runs/{id}/submit` with
`{"authorization_override": true}`. The first response creates no jobs. Do not
automatically retry this response: the override uses the administrator's print
authorization and records it in the immutable print-attempt attribution.

## Template labels

Find profile and template IDs via `GET /api/tape-profiles` and `GET /api/templates`.
Preview first with `POST /api/preview` using a template ID and field data.
Pass `destination_id` when several printers are configured. Both bundled clients
accept `--destination PRINTER_OR_GROUP_ID`; omission selects the sole configured
printer. Retries with an omitted destination retain the original destination,
even if more printers are later added. Changing it with the same key returns 409.

```sh
.venv/bin/python scripts/submit_label.py \
  --server http://labels.local:8000 --profile PROFILE_ID --template text \
  --key inventory:event-123 --data '{"text":"Storage / Box 12"}'
```

This adds a job to the queue. Tape thresholds and automatic-print holds determine
when it prints.

### Retries

The client retries transient transport/server failures with the same key. `Idempotency-Key`
on `POST /api/jobs` is stored per authenticated user, persists across restarts,
and returns the original job even if its template was later changed or archived.
Changed input with the same key returns 409. Use one key per originating event;
an intentional reprint requires a new key. Without a key each call creates a job.
Do not expire keys while an integration may still retry. Label removal retains
job history and therefore its receipt. CSV preparation uses its existing
`request_key`; submitting the same saved run again cannot duplicate its jobs.

In Home Assistant, use an HTTP POST/rest_command to `/api/jobs`, JSON content type,
the authenticated cookie and CSRF token, an `Idempotency-Key` header derived from the originating event, and body fields
`template`, `tape_profile`, `copies` and `data`. In Shortcuts, use Get Contents of
URL with the same POST and headers. Retain the originating key for retries rather
than generating a new key per HTTP attempt. Inspect `/docs` for live schemas.
Automatic submission is separate from `POST /api/queue/print`; don't flush on every
label if you want threshold-based batching and reduced feed waste.

## Image labels

The standalone `scripts/submit_image.py` client uploads artwork and submits a
saved image label without creating a library template. It needs Python 3,
`api_session.py` alongside it, API credentials, access to the image file, and
connectivity to this server. PNG, JPEG, WebP, BMP, still GIF, and the server's
constrained SVG subset are accepted, up to
5 MB. Uploaded assets remain in the image library and must be included in backups.

Preview first; this uploads the asset but creates no queue items:

```sh
python3 scripts/submit_image.py label.png \
  --server http://labels.local:8000 --profile PROFILE_ID \
  --resolution high --preview label-preview.html
```

Open the HTML file to see the actual print pixels at the correct physical aspect.
Then submit with the same sizing and rendering options:

```sh
python3 scripts/submit_image.py label.png \
  --server http://labels.local:8000 --profile PROFILE_ID \
  --resolution high --key inventory:image-event-123
```

The default length fits the image to the printable tape width, with margins
provided by printer capabilities. Aspect ratio and orientation are preserved.
Use `--length 60` to fit inside a 60 mm label without cropping. Automatically
calculated lengths over 300 mm are refused; choose an explicit length to reduce
the image. `--copies`, `--mode threshold|dither` and `--threshold 128` control
copies and monochrome conversion. Resolution defaults to the printer setting;
`--resolution normal|high` overrides it. Higher output resolution cannot recover
detail missing from the original bitmap.

The REST equivalent is:

1. `POST /api/image-assets?name=Label` with the raw image bytes.
2. `POST /api/image-jobs/preview` with JSON fields `image_asset` (the returned ID),
   `tape_profile`, optional `length_mm`, `copies`, `print_resolution`, `image_mode`
   and `image_threshold`.
3. `POST /api/image-jobs` with the same JSON and an `Idempotency-Key` header.

Image jobs share the existing job-key namespace and retry rules. Upload retries
reuse the content-addressed asset. Image submissions honor automatic-print hold,
tape thresholds, selection and review just like template labels; the client does
not flush the queue. Set hold before submitting if you want manual inspection.

## HomeBox print-command bridge

The [official HomeBox configuration documentation](https://homebox.software/en/configure/)
provides `HBOX_LABEL_MAKER_PRINT_COMMAND`, substituting `{{.FileName}}` with a
rendered PNG filename. The [HomeBox print implementation](https://github.com/sysadminsmedia/homebox/blob/main/backend/pkgs/labelmaker/labelmaker.go)
creates a fresh temporary filename per invocation and removes it after the command
returns. It also supplies label attributes, but no durable submission-event ID.

Place `submit_image.py` and `api_session.py` in HomeBox's execution environment,
install Python 3, and set `LABEL_API_USERNAME` and `LABEL_API_PASSWORD` there.
Configure this command with your server URL and profile ID:

```text
HBOX_LABEL_MAKER_PRINT_COMMAND=python3 /opt/labels/submit_image.py --server http://labels:8000 --profile PROFILE_ID --resolution high --homebox {{.FileName}}
```

The script must run where it can read HomeBox's temporary PNG. For containers,
mount/copy it into the HomeBox container with a Python runtime; the server URL must
be reachable from that container. Merely installing the script on the host does
not make it available inside HomeBox. No shell wrapper is required.

`--homebox` derives the key from the full filename and image contents. Network
retries and re-running the command against the same file reuse the job. A new
HomeBox print invocation has a new filename and therefore creates a new job,
even with identical artwork. An upstream retry that regenerates a PNG is also a
new invocation; this hook cannot distinguish it from an intentional reprint.
Integrations with a durable event ID should use `--key` instead.

The bridge has automated retry tests but has not been verified in a live HomeBox
deployment. To verify configuration without queuing, temporarily add
`--preview /tmp/label-preview.html` to the command and inspect that file. A
successful submission means queued, not physically printed. For structured
editable labels, map item fields to a saved template through `/api/jobs`.

## Limits and queue controls

Label lengths are 10–300 mm across job, image, and CSV inputs. Tape widths are
physical millimetres, including 3.5 mm.

Cancel a pending manual flush with `DELETE /api/queue/flush/{id}` to release its
reservation without cancelling jobs. Automatic-print holds remain until resumed.
