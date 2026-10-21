# Deployment and recovery

The selected deployment path is the native service in a Debian VM: Python in a
virtual environment, managed by systemd, with the printer attached through a
Proxmox USB resource mapping. Docker and LXC remain alternatives. Native VM
startup, application-level USB access, physical printing, VM reboot, hold
persistence and printer disconnect/reconnect without a service restart passed
on 2026-10-17.

## Debian service in a VM, LXC or host

Install Python 3.12+, Node 22.12+ for building the UI, `libusb-1.0-0` and `usbutils`.
Node is only needed to build the UI; a deployment bundle containing the built
`frontend/dist` can run without Node installed.
Clone or copy the project to `/opt/labels`, create a `labels` service user, and create
a `labelprinter` group. From the project directory, install dependencies, configure the server,
build the frontend, and migrate:

```sh
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -c requirements.lock .
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/alembic upgrade head
```

Edit `.env` for server configuration. Configure ntfy endpoints in **Administration**. Add the
printer under **Printers & groups** in the web UI. USB serial is optional for one
Brother device and required on every device when several are used. Locate USB
devices with `lsusb -d 04f9:20af`; inspect `lsusb -v` for `iSerial`, which may differ
from the physical serial label by a prefix. All device settings are stored in the
database and edited with **Configure**, including the first printer.

Install `deploy/70-label-printer.rules` under `/etc/udev/rules.d/` on the host
owning the USB device, reload udev rules and reconnect the printer. Add the service
user to `labelprinter`. Ensure the data directory is writable by `labels`.
Install `deploy/labels.service`, adjust paths/bind address if needed, and start it
with systemd. Migrations remain an explicit stopped-service upgrade step.
Do not run P-touch Editor, CUPS or another process against the same printer.

## Proxmox VM USB access

Attach the printer's existing USB resource mapping under the VM's
**Hardware → Add → USB Device**. A VM accepts named USB resource mappings; LXC
device passthrough uses a host device path instead. See the
[Proxmox VM options](https://github.com/proxmox/pve-docs/blob/master/generated/qm.1-synopsis.adoc).

Inside the VM, install `usbutils` and confirm the printer appears with
`lsusb -d 04f9:20af`. Install the bundled udev rule and `labelprinter` group
inside the VM, where the application's USB access occurs. Verify status as the
`labels` service user before starting any print test. Seeing the printer in
`lsusb` alone does not establish application permissions or successful printing.

On 2026-10-17, a native Linux AMD64 VM running Debian 13.7 and Python 3.13.5 was
installed from the current checkout with a prebuilt frontend. The `labels`
systemd service was active and enabled at boot, running as `labels:labels` with
the supplementary `labelprinter` group. The mapped USB node was owned by
`root:labelprinter` with mode `0660`. `/api/health` returned healthy, the frontend
served built assets successfully, and administrator setup was complete. In the
authenticated application, the registered PT-P710BT reported connected with
24 mm tape and a 180 × 360 dpi default. Automatic printing was held for testing;
no cartridge was installed at that check. These checks verify native service
startup and live application USB status.

A subsequent label submission exposed `crypto.randomUUID()` being unavailable
on the plain-HTTP LAN origin. A shared UUID generator using `getRandomValues()`
when needed now covers label submission, CSV preparation and editor elements;
blank required label fields are also checked before requesting a preview. The
frontend build and six browser regression checks passed. The frontend-only update
was applied without restarting the service. The VM was verified serving the new
built assets, and the user then reported a successful physical print.

The VM was then rebooted on 2026-10-17. SSH checks confirmed a new boot session,
automatic service startup, active/enabled service state and a healthy API.
The authenticated dashboard showed the printer connected, automatic printing
still held, no pending work or review, and a completed post-reboot batch. The
user confirmed that the post-reboot physical print succeeded. The guest USB node
changed from `/dev/bus/usb/002/002` to `/dev/bus/usb/001/002` across the VM reboot,
with printing still working.

The user then confirmed successful USB disconnect/reconnect and another physical
print while the VM and service stayed running. SSH verification showed the same
service activation timestamp, a healthy API and the printer at
`/dev/bus/usb/001/003` instead of `/dev/bus/usb/001/002`. This completes the native
VM deployment acceptance checks for startup, service-user USB access, printing,
VM reboot and printer reconnect through the configured Proxmox mapping.

## Proxmox LXC USB access

The printer must be accessible on the Proxmox host first. On versions exposing
`dev[n]`, pass the specific `/dev/bus/usb/BBB/DDD` node to the stopped container,
with a writable mode and the intended in-container uid/gid. For example, adapting
container ID, node and user IDs to your installation:

```sh
pct set 123 -dev0 path=/dev/bus/usb/001/005,uid=10001,gid=10001,mode=0660
```

Confirm the option against your installed `pct help set` and the
[Proxmox container documentation](https://pve.proxmox.com/pve-docs/pct.1.html).
Start the container and verify `lsusb` and device permissions there before
starting the application. USB node numbers can change after reconnect: update
the passthrough mapping and restart affected containers. Unprivileged LXC ID
mapping must match your service user. Do not enable all-device or privileged
access merely to bypass an incorrect mapping. Older Proxmox versions require
their documented cgroup/device bind configuration instead of `dev[n]`.

## Docker

The base Compose file starts with no configured printers and exposes localhost by default:

```sh
docker compose up -d --build
```

For real USB, supply the specific node and its group in `.env` and use the explicit
override. It grants that device, not the entire USB bus:

```sh
# .env: LABEL_USB_DEVICE=/dev/bus/usb/001/005
# .env: LABEL_USB_GID=<numeric group owning the node>
docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d --build
```

The image runs as UID 10001 and includes libusb. With Docker inside LXC, both
layers need that device mapped and accessible. Recreate the service after USB
node renumbering. The image applies migrations before starting one Uvicorn worker.
Stop the old container before an upgrade; do not run a second service on the same
database and printer. Compose configuration has been checked. On 2026-10-17, the
image built successfully for Linux ARM64 using Docker Desktop on macOS. A separate
test volume verified migrations through `c91d8e5a206b`, startup as UID 10001,
`/api/health`, built frontend serving, administrator setup, authenticated API
access, image upload and raster preview generation. Login, configuration and
uploaded-artwork rendering also passed after a container restart. No labels were
queued or printed. Physical USB passthrough and the intended LXC setup remain
unverified; these checks do not establish Linux AMD64 behavior.

## Settings and exposure

Under **Printers & groups → Configure**, the page timeout bounds each completion
wait (default 120 seconds). **Cut each label** requests individual labels; disabling
it requests a strip with final feed. Feed and leader estimates can be adjusted in
the same form. Finish queued work and saved drafts before changing these settings.

Choose **180 × 360 dpi** for higher resolution along the tape, or **180 × 180 dpi**
for normal output. Templates can override the device default. Saved jobs and CSV
drafts retain their original rendering settings. Configuration changes apply
without a server restart.

The initial administrator uses the one-time `auth-setup-token` file beside the
database. For Compose, read it using
`docker compose exec labels cat /srv/labels/data/auth-setup-token`. For native
deployment, read `data/auth-setup-token` as the service owner. Enter the token in
the browser setup screen; it is removed after registration. Existing workspace
records belong to this first administrator. Subsequent users require registration
codes by default and need a directly assigned role with Request only or higher
access to a printer or distribution group before submitting approval requests.
Print skips approval; Moderator adds scoped queue/request management; Full adds
configuration. Template groups share templates and never hand out roles.
Queued labels paused before initial administrator setup stay paused until the
administrator releases or cancels them from the dashboard.

While initial setup is pending, the same token is also printed in the startup logs
as `Initial administrator setup token: …`. Use `docker compose logs labels` for
Compose, `journalctl -u labels.service` for systemd, or the native server's terminal.
Restarts reuse and log the pending token; after the first administrator is created,
startup no longer logs a setup token.

Use HTTPS through your reverse proxy for access beyond localhost. Forward the
original scheme/host only from a trusted proxy; the browser origin must match
the public server origin. Session cookies become Secure on HTTPS. Configure
users, roles, groups and approval notifications through **Administration**.
Access-changing role and membership edits require a before/after impact preview
and confirmation. Accounts disabled or deprived of required printer access leave
their queued jobs paused for an administrator release/cancel decision on the
dashboard. Restoring permissions does not automatically resume those jobs.
Set `LABEL_PUBLIC_URL` to a browser-reachable origin for notification links. ntfy
server URLs, topics, credentials and routing filters are stored in the database
and configured in **Administration**. Endpoints select event types, printers or
distribution groups, and a severity per event type. Group channels also receive
operational alerts from their members as membership changes. **Select all** snapshots
only current physical printers; groups are selected manually. **All current and
future printers** includes later additions. Empty scopes
disable and clear printer event types. Configure ntfy topic read permissions
separately; application filters do not grant or restrict topic subscriptions.
Matching endpoints each have independent durable retries. Editing, disabling or
deleting an endpoint cancels its pending deliveries without changing print state.
The notification scope migration removes role/access filters, makes formerly
unrestricted scopes explicitly include future printers, preserves selected IDs,
and cancels pending deliveries under the old configuration. Apply it with the
service stopped using `.venv/bin/alembic upgrade head`; rebuild the frontend too.
The anonymous `/api/health` healthcheck proves the server responds, not that the
printer is connected. Workspace and printer APIs require sign-in.

## Backup, restore, and upgrades

Stop the service and copy the entire data directory/volume, including database,
WAL/SHM files if present, and `assets/fonts` and `assets/images`. Preserve `.env`
separately. Do not copy only the database while uploads or printing are active.
On restore, stop every old worker, restore permissions and the complete data,
apply migrations and start a single server process. A stale lock file can remain on disk;
the operating-system lock, not file existence, prevents concurrent workers.

Back up before upgrading, stop, install dependencies, migrate and rebuild the UI,
then restart. Treat printing interrupted by any shutdown as requiring review.
Never delete a review record or reissue a job with a new retry key merely to clear
an uncertain physical result. Reconcile copies and tape consumption in the UI.

## Automated release updates

`scripts/update.py` supports both the native systemd service and the `labels`
Docker Compose service. Run it with Python 3.12+ on the deployment host. It uses
GitHub's [latest release endpoint](https://docs.github.com/en/rest/releases/releases#get-the-latest-release),
which selects a published full release. It does not fall back to `main`, draft
releases, prereleases, or unassociated Git tags. A missing/inaccessible release
aborts before the application is stopped.

### Private GitHub repository access

Create a [fine-grained personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token)
restricted to `tarobits/label-server`, with **Contents: read-only** repository
permission. Add it to the installation's `.env` (not the source checkout's `.env`
when `--install-dir` is separate):

```dotenv
LABEL_GITHUB_TOKEN=github_pat_your_token_here
```

Use an editor to enter the token so it does not enter shell history, and run
`chmod 600 .env`. For native installations the file must be owned by the `labels`
service user; root can still read it when running the updater with sudo. Docker
Compose forwards the token from this file to the application. Restart the native
service or recreate the Compose container after changing credentials.

Both the in-app release check and the updater use this setting. The updater uses
it for the GitHub API **and** Git HTTPS clone/fetch, including checkouts whose
origin uses SSH. It does not change origin, save credentials in Git configuration,
or include the token in command arguments, logs, or browser responses. Without a
token, Git continues to use its configured SSH keys or credential helper.

For native installations, a separate file containing only the raw token is also
supported via `LABEL_GITHUB_TOKEN_FILE=/etc/label-server/github-token` in `.env`.
Make that file readable by `labels` and root only (for example, owner `root`, group
`labels`, mode `640`). Relative token-file paths resolve from the installation.
The updater additionally accepts `--github-token-file /path/to/token`, useful
when keeping host credentials outside a Compose installation. To use a token file
inside Docker for the in-app check, mount it read-only with a local Compose
override and set the container's `LABEL_GITHUB_TOKEN_FILE` to its mounted path;
the base Compose setup uses the `.env` token above.

Updater precedence is `--github-token-file`, environment
`LABEL_GITHUB_TOKEN_FILE`, environment `LABEL_GITHUB_TOKEN`/`GITHUB_TOKEN`, then
the installation's `.env` (file setting before inline token). The application
uses `LABEL_GITHUB_TOKEN_FILE` or `LABEL_GITHUB_TOKEN`; it does not read the
updater-only `GITHUB_TOKEN` alias. Avoid configuring multiple credential sources.
Backups include `.env` and resolved Compose configuration, so keep the restricted
backup directory private too. Rotate the token in its original file when it
expires.

The UI footer shows the running version. A dismissible notice in the bottom right
links to a newer stable release. GitHub checks are shared by all clients and cached
for an hour; failed checks retry after 15 minutes without interrupting printing.
Dismissal lasts for the browser tab's session and applies only to that release.
Set `LABEL_CHECK_FOR_UPDATES=false` in `.env` to disable automatic checks (the
version display and manual updater still work). An inaccessible repository or no
published release leaves the version visible without an update notice.

### Running an update

The checkout must have a GitHub `origin` and no tracked or untracked local changes.
Use `.env` for deployment settings. The updater fetches the release's exact tag
and switches a local `release` branch to that commit, leaving `main` intact. If
the existing `release` branch has diverged, it refuses to discard those commits.
Finish current printing and review before scheduling an upgrade.

Preview the selected release and plan without cloning, fetching, changing files,
backing up, or managing the service:

```sh
python3 scripts/update.py --mode native --check
python3 scripts/update.py --mode docker --check
```

For a native Git installation at `/opt/labels`, run:

```sh
cd /opt/labels
sudo python3 scripts/update.py --mode native
```

The existing VM was installed from a copied bundle. Place the updater on that VM
and give it a separate, initially absent source checkout:

```sh
sudo python3 /path/to/scripts/update.py --mode native \
  --checkout /opt/labels-source --install-dir /opt/labels
```

It clones `tarobits/label-server` automatically in that case. `--repository OWNER/REPO`
selects another repository for a new checkout and must match `origin` for an
existing one. Separate source and installation directories must not be nested.
Subsequent runs can use `/opt/labels-source/scripts/update.py` once a release
includes the updater. No Git metadata is required in the copied installation.

Native prerequisites are the existing virtual environment, Git, Node 22.12+/npm,
systemd/runuser, and rsync for separate source/install directories. Run as root.
`--service` defaults to `labels.service`; its WorkingDirectory must match the
installation. The supported layout uses `.env`, `.venv`, `frontend/dist`, and a
dedicated SQLite data directory. Database/assets outside the installation are
discovered from its settings. An alternate systemd EnvironmentFile or frontend
output path requires a tailored deployment process. Existing service-unit and
udev customizations are preserved. Migrations run as the configured service user.

For Docker, run from the existing Compose checkout and keep its usual files:

```sh
python3 scripts/update.py --mode docker \
  --compose-file docker-compose.yml --compose-file docker-compose.usb.yml
```

Omit the USB override when not using it. Repeat `--compose-file` for local overrides
and provide `--project-name` if the existing deployment used one. The updater
inspects the existing container and preserves the actual project and persistent
data mount, avoiding a replacement empty volume. One volume or directory bind mount
must contain the database and its sibling assets; nested data mounts require a
separate backup strategy. Docker Engine and Compose must already work. The updater
builds the new image, runs an explicit migration with the old `.env` available,
then recreates `labels`; other Compose services are not restarted.

Both modes stop the application before copying its complete data. Backups go to
a new timestamped, restricted directory beside the installation by default
(`/opt/labels-backups` for the VM). `--backup-dir` changes the parent; it must stay
outside the source, installation and data directories. Each backup contains
`source.tar.gz`, `data.tar.gz`, `.env` as `environment.env` when present, and an
`update.json` recovery record with old/new commits and Docker image/mount details.
Backups contain credentials and should retain restricted permissions. Docker
data backups use the old image with networking disabled and a read-only data mount.
No backup or old Docker image is automatically pruned.

The default final check is `http://127.0.0.1:8000/api/health`; use `--health-url`
for a different local port and `--health-timeout` for a slower startup. This proves
application startup, without submitting or printing a label.

If backup, installation, migration or health validation fails after shutdown, the
updater stops the application and exits unsuccessfully. Inspect the reported
backup and logs, fix the cause, then rerun. There is no automatic database downgrade
or restoration that could replay uncertain print work. To roll back manually,
keep the application stopped, restore the matching source, `.env` and **complete**
data archive together, reinstall the old dependencies/rebuild the UI for native
deployments or restore the saved old image for Docker, then start one service.
For a native data archive, its `data/` prefix maps to the original `data_dir` in
`update.json`. For Docker it maps to the recorded entire data mount. Reconcile any
interrupted physical output in the application after restart.

## Multiple USB printers

The application runs one physical worker per registered device, inside one server
process. Keep one Uvicorn process and the database ownership lock. Register every printer with its own
USB serial under **Printers & groups**. Map every required USB device into
the container/LXC; the sample Compose USB override maps one device and must be
extended with the additional current device nodes. Both need the configured
udev/group permissions. A group is a routing destination, not a USB device.

## Environment configuration

Supported application variables are `LABEL_DATABASE_URL`,
`LABEL_WORKER_INTERVAL_SECONDS`, `LABEL_FRONTEND_DIST` and `LABEL_PUBLIC_URL`. Compose additionally
uses `LABEL_BIND_ADDRESS`, `LABEL_USB_DEVICE` and `LABEL_USB_GID` for deployment.
Printer connections, resolution, feed, cuts and timeout are configured in the UI.
The anonymous health check uses `/api/health` and succeeds before a printer is registered.

For an existing installation, run the migration once with its old environment
available before removing the obsolete printer entries. It imports the physical
printer's settings into its database registration and retires simulated printers.

For the notification endpoint migration, an installation with existing accounts
can import its old `LABEL_NTFY_URL`, `LABEL_NTFY_TOPIC` and optional
`LABEL_NTFY_TOKEN` once. Run the migration with its original `.env` available in
the working directory, or supply those values in the migration process's environment.
It creates an administrator endpoint covering all event types. A fresh installation
does not import a channel. These variables no longer affect delivery after migration.
Compose no longer forwards them: supply the old values to a one-off migration
container if preserving that configuration, or create the endpoint in Administration
after upgrading. Database backups now include the configured endpoint tokens.
Subsequent startups read printer configuration only from the database.

For a Compose upgrade, make the previous `.env` available to the one-off migration
before starting the new service (the normal Compose environment no longer forwards
printer variables):

```sh
docker compose stop labels
docker compose build labels
docker compose run --rm -v "$PWD/.env:/srv/labels/.env:ro" labels alembic upgrade head
docker compose up -d
```

Keep using your usual USB Compose override for commands if one is configured.
After migration, remove the old printer entries from your local `.env`.

The physical-width migration converts old 4 mm media references to 3.5 mm and
adds a revised editable template where needed. Job snapshots, historical template
revisions and saved run render documents keep their original pixels. Run the
migration with the service stopped, then rebuild the frontend. Invalid imported
printer settings remain visible on the printer card and can be repaired using
**Configure**.

For reported hardware results and calibration checks, see
[hardware verification](HARDWARE_VERIFICATION.md). The measured consumption
baseline was accepted on 2026-10-17. Docker/LXC USB passthrough remains unverified
and is outside the current native-VM deployment path.
