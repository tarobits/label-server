# Deployment and recovery

Run the application as a native systemd service or with Docker Compose. Both
use one server process per database and need exclusive access to each printer.
Virtual machines and containers also need USB passthrough configured by their host.

Paths such as `/opt/labels`, service accounts such as `labels`, and port 8000
below are project defaults or examples, not details of a particular installation.
Replace placeholder device paths and IDs with values discovered on your host.

## GitHub installer

Use a fresh Debian 13+ host or VM with systemd, Python 3.12+ and Git. The script
installs apt packages (including Node, Python venv and libusb), fetches the selected
GitHub version into a separate installation, builds the UI and Python environment,
applies migrations and enables the service at boot. Build and migration commands
run as the unprivileged `labels` account. Code is then owned by root, with writable
state under `data/`. It installs the bundled Brother USB rule and supplementary
`labelprinter` group.

```sh
git clone https://github.com/tarobits/label-server.git
cd label-server
python3 scripts/install.py --check
sudo python3 scripts/install.py
sudo systemctl status labels.service
```

The default version is GitHub's latest published stable release. No release or
missing repository access stops installation. To install a particular release
or the current branch, pass `--ref RELEASE_TAG` or `--ref main`. The install fetches
that ref from GitHub; local uncommitted changes are not copied. Use
`--repository OWNER/REPOSITORY` for a fork.

The default bind address is `127.0.0.1:8000`, for local access or a reverse proxy.
For HTTPS behind a reverse proxy, set the externally reachable URL:

```sh
sudo python3 scripts/install.py --public-url https://labels.example.com
```

For direct LAN access, `--host 0.0.0.0` exposes the service on all interfaces.
Restrict access at the host firewall and use HTTPS for remote access.

Options include `--install-dir /opt/labels`, `--port 8000`, `--skip-packages`
(for pre-provisioned dependencies) and `--no-start` (enable without starting).
The runtime requires Python 3.12+; the frontend build accepts Node 20.19+ on 20.x,
or Node 22.12+. Older Debian releases need compatible dependencies provisioned
separately.

For a private repository, clone using your usual GitHub authentication and pass
an absolute path to a protected token file with repository read access:

```sh
sudo python3 scripts/install.py --github-token-file /secure/path/github-token
```

The installer uses a temporary Git credential helper, stores a private copy in
`data/github-token` with mode `0600`, and references it from `.env` for later
release checks and updates. It does not put the token in Git remotes or command
arguments. Avoid putting credentials directly in a clone URL.

After startup, open the configured URL and retrieve the first-run setup token:

```sh
sudo cat /opt/labels/data/auth-setup-token
sudo journalctl -u labels.service -f
```

Create the administrator account and configure printers and cartridges in the
web UI. Printer registration does not trigger a test print.
The installer refuses an existing destination or `labels.service`; use the
[release updater](#automated-release-updates) for existing installations. A failed install
retains its files for inspection. If startup fails its health check, the new
service is stopped and disabled. Review the error before manually retrying or
removing the partial fresh installation. Existing deployments are never replaced.

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

Edit `.env` for server configuration, including SMTP if using email recovery or
notifications. Configure ntfy or email endpoints in **Administration**. Add the
printer under **Printers & groups** in the web UI. USB serial is optional for one
Brother device and required on every device when several are used. Locate USB
devices with `lsusb -d 04f9:20af`; inspect `lsusb -v` for `iSerial`, which may differ
from the physical serial label by a prefix. All device settings are stored in the
database and edited with **Configure**, including the first printer.

Install `deploy/70-label-printer.rules` under `/etc/udev/rules.d/` on the host
owning the USB device, reload udev rules and reconnect the printer. Add the service
user to `labelprinter`. Ensure the data directory is writable by `labels`.
Install `deploy/labels.service` and adjust its paths and bind address before
starting it with systemd. Unlike the installer, the sample unit binds to
`0.0.0.0`; change that to `127.0.0.1` for a local reverse proxy. Migrations remain an explicit stopped-service upgrade step.
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

After configuring passthrough, verify the installation:

1. Check `systemctl status labels.service` and `/api/health` after startup.
2. Sign in and confirm that the application reports the printer and detected tape.
3. Hold automatic printing, register the correct cartridge, and manually print a
   test label. Inspect the physical output and reconcile any review prompt.
4. Reboot the guest and verify service startup, USB access, and hold persistence.
5. Disconnect and reconnect the printer while idle, then repeat the status and
   print checks. Device node numbers may change; repair the mapping if needed.

These checks validate that installation. A healthy HTTP endpoint or a visible
USB device alone does not establish successful physical printing.

## Proxmox LXC USB access

The printer must be accessible on the Proxmox host first. On versions exposing
`dev[n]`, pass the specific `/dev/bus/usb/BBB/DDD` node to the stopped container,
with a writable mode and the intended in-container uid/gid. For example, adapting
container ID, node and user IDs to your installation. Set `CONTAINER_ID`,
`USB_DEVICE`, `SERVICE_UID`, and `DEVICE_GID` to those values before running:

```sh
pct set "$CONTAINER_ID" -dev0 "path=$USB_DEVICE,uid=$SERVICE_UID,gid=$DEVICE_GID,mode=0660"
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
# .env: LABEL_USB_DEVICE=/dev/bus/usb/BBB/DDD (replace with the actual node)
# .env: LABEL_USB_GID=<numeric group owning the node>
docker compose -f docker-compose.yml -f docker-compose.usb.yml up -d --build
```

The image runs as UID 10001 and includes libusb. With Docker inside LXC, both
layers need that device mapped and accessible. Recreate the service after USB
node renumbering. The image applies migrations before starting one Uvicorn worker.
Stop the old container before an upgrade; do not run a second service on the same
database and printer. Image build and isolated application checks have passed;
physical USB passthrough with Docker or LXC remains unverified. Validate permissions,
reconnect behavior, and physical output on your host before relying on it.

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
configuration. Content groups share templates, fonts and images with separate
collaboration permissions, and never hand out roles.
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
Set `LABEL_PUBLIC_URL` to the external HTTPS origin for notification and recovery
links. Administrators configure ntfy or email endpoints and their event/destination
filters in **Administration**. Personal subscriptions use verified account email
addresses and recheck the subscriber's current permissions at delivery time.
Configure ntfy topic read permissions separately. See
[notification behavior](../README.md#notifications-and-integrations) and
[access boundaries](ACCESS_CONTROL.md#notifications).

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
GitHub's [latest release endpoint](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)
by default (`--channel stable`), which selects a published full release.
`--channel beta` selects the most recently published release, including
prereleases and stable releases, by publication time across all release pages.
`--tag RELEASE_TAG` selects that exact published release, including prereleases,
and overrides `--channel`. Neither option falls back to branches, draft releases,
or Git tags without a published GitHub release. A missing/inaccessible release
aborts before the application is stopped. Channel selection applies to this
invocation only; the in-app release notice continues to check stable releases.

### Private GitHub repository access

Create a [fine-grained personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token)
restricted to the repository being deployed, with **Contents: read-only** repository
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
the existing `release` branch is not an ancestor of the selected release, it
refuses to discard those commits. This also prevents downgrading to an older tag
or returning from a beta to a stable release that does not include it.
Finish current printing and review before scheduling an upgrade.

Preview the selected release and plan without cloning, fetching, changing files,
backing up, or managing the service:

```sh
python3 scripts/update.py --mode native --check
python3 scripts/update.py --mode docker --check
```

To preview the beta channel or a particular release (example tag):

```sh
python3 scripts/update.py --mode native --channel beta --check
python3 scripts/update.py --mode native --tag v0.12.0-rc.1 --check
```

Remove `--check` to perform the selected update; native updates require `sudo`.
Both options also work with `--mode docker`. Omitting `--channel` selects stable.

For a native Git installation at `/opt/labels`, run:

```sh
cd /opt/labels
sudo python3 scripts/update.py --mode native
```

For an installation copied without Git metadata, place the updater on the host
and give it a separate, initially absent source checkout:

```sh
sudo python3 /path/to/scripts/update.py --mode native \
  --checkout /opt/labels-source --install-dir /opt/labels
```

It clones `tarobits/label-server` automatically in that case. `--repository OWNER/REPO`
selects another repository for a new checkout and must match `origin` for an
existing one. Separate source and installation directories must not be nested.
Subsequent runs can use `/opt/labels-source/scripts/update.py` after the first
update. No Git metadata is required in the copied installation.

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
(`/opt/labels-backups` for the default native installation). `--backup-dir` changes the parent; it must stay
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

The application reads these variables from the process environment or `.env` in
its working directory. Environment variables take precedence. Restart the service
after changes. Start with [.env.example](../.env.example); keep credentials out of
source control and restrict the populated `.env` to the service owner.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LABEL_DATABASE_URL` | `sqlite:///./data/labels.db` | Database location; Compose sets its persistent-volume path. |
| `LABEL_WORKER_INTERVAL_SECONDS` | `2` | Worker polling interval in seconds; must be positive. |
| `LABEL_PUBLIC_URL` | `http://localhost:8000` | Browser-reachable URL for notification and recovery links; use HTTPS remotely. |
| `LABEL_FRONTEND_DIST` | `frontend/dist` beside the source tree | Built frontend directory. |
| `LABEL_CHECK_FOR_UPDATES` | `true` | Enable cached GitHub release checks. |
| `LABEL_GITHUB_TOKEN` | Unset | Optional repository-read token for release checks and updates. |
| `LABEL_GITHUB_TOKEN_FILE` | Unset | Optional file containing that token; takes precedence over the inline token. |
| `LABEL_SMTP_HOST` | Unset | SMTP server; required for email delivery. |
| `LABEL_SMTP_PORT` | `587` | SMTP port; set explicitly for your provider. |
| `LABEL_SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (implicit TLS), or `plain` (unencrypted trusted local relay only). |
| `LABEL_SMTP_USERNAME` | Unset | SMTP login name; leave empty if the relay needs no authentication. |
| `LABEL_SMTP_PASSWORD` | Unset | SMTP login password. |
| `LABEL_SMTP_FROM` | Unset | Bare sender email address; required for email delivery. |
| `LABEL_SMTP_FROM_NAME` | Empty | Optional sender display name, formatted separately from the address. |

Compose also uses `LABEL_BIND_ADDRESS` (default `127.0.0.1`), `LABEL_USB_DEVICE`,
and `LABEL_USB_GID`. The USB override requires the latter two; neither is a printer
registration. Connections, resolution, feed, cuts, timeout, and cartridge checks
are stored in the database and configured in the UI.

### Email configuration

Use `starttls` with the provider's STARTTLS port (usually 587), or `ssl` with its
implicit TLS port (usually 465). Both verify TLS certificates. STARTTLS failures
never fall back to plain transport. The `plain` option is only for a trusted
local relay. `LABEL_SMTP_FROM` accepts a bare address, not `Name <address>`;
put the display name in `LABEL_SMTP_FROM_NAME`.

```dotenv
LABEL_PUBLIC_URL=https://labels.example.com
LABEL_SMTP_HOST=smtp.example.com
LABEL_SMTP_PORT=587
LABEL_SMTP_SECURITY=starttls
LABEL_SMTP_USERNAME=label-server
LABEL_SMTP_PASSWORD=
LABEL_SMTP_FROM=labels@example.com
LABEL_SMTP_FROM_NAME="Label Server"
```

Enter the provider's password locally if authentication is required. Restart the
native service after editing `.env`. Email recovery and alerts share this transport;
recipients and event subscriptions are configured in the application.

The base Compose file forwards only its listed environment variables; the host's
`.env` is not automatically available inside the container. To enable email, create
an override outside the managed source checkout, such as
`/path/to/compose.email.yml`, with explicit SMTP forwarding:

```yaml
services:
  labels:
    environment:
      LABEL_SMTP_HOST: ${LABEL_SMTP_HOST:-}
      LABEL_SMTP_PORT: ${LABEL_SMTP_PORT:-587}
      LABEL_SMTP_SECURITY: ${LABEL_SMTP_SECURITY:-starttls}
      LABEL_SMTP_USERNAME: ${LABEL_SMTP_USERNAME:-}
      LABEL_SMTP_PASSWORD: ${LABEL_SMTP_PASSWORD:-}
      LABEL_SMTP_FROM: ${LABEL_SMTP_FROM:-}
      LABEL_SMTP_FROM_NAME: ${LABEL_SMTP_FROM_NAME:-}
```

Recreate the container with this override, adding your USB or other overrides too:

```sh
docker compose -f docker-compose.yml -f /path/to/compose.email.yml up -d
```

Keep the same files on subsequent operations, including the updater's repeatable
`--compose-file` arguments. Keeping the override outside the checkout avoids
untracked files blocking the release updater. An explicit allowlist avoids forwarding host-only paths
such as `LABEL_DATABASE_URL` into the container. This override contains no secrets;
keep its credential values in the restricted `.env`.

For a functional check, add an account email in **Account settings**, open the
verification link, and confirm the address. Then request **Forgot password?** for
that account. Verification/reset links expire in 30 minutes and are single-use;
a completed reset signs out every session. Recovery messages run after the request
returns and are not in the durable alert outbox: request another link if sending
fails. Existing alert deliveries use independent durable retries. An administrator
can set a replacement password when email recovery is unavailable.

### Legacy configuration migrations

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
baseline is limited to its recorded test conditions. Docker/LXC USB passthrough
remains unverified.

### Push notifications

Push uses the browser's Web Push service and a persistent VAPID signing key.
Set `LABEL_PUBLIC_URL` to the application's externally reachable HTTPS origin. The label server
needs outbound HTTPS access to `fcm.googleapis.com`, `*.push.apple.com`, and
`*.push.services.mozilla.com`; subscriptions to other providers are rejected.
Any authentication gateway must allow the app's normal authenticated API calls.

For a native installation, generate the key once as the service user:

```sh
cd /opt/labels
sudo -u labels .venv/bin/python -m app.push_delivery --generate-key data/vapid-private.pem
```

Set these in the deployment's `.env`, using your own administrator contact address:

```dotenv
LABEL_PUBLIC_URL=https://labels.example.com
LABEL_VAPID_PRIVATE_KEY_FILE=/opt/labels/data/vapid-private.pem
LABEL_VAPID_SUBJECT=mailto:admin@example.com
```

Then restart with `sudo systemctl restart labels.service`. The key generator creates
an owner-only file and refuses to overwrite an existing key. Keep this file in the
persistent data directory and include it in backups. Changing the key requires
removing and enabling notifications again on each device. A missing, unreadable,
or invalid key leaves push unavailable without affecting printing or email.

For Docker Compose, generate the key inside the persistent data volume:

```sh
docker compose exec labels python -m app.push_delivery --generate-key /srv/labels/data/vapid-private.pem
```

Set `LABEL_VAPID_SUBJECT` and `LABEL_PUBLIC_URL` in the host `.env`; leave
`LABEL_VAPID_PRIVATE_KEY_FILE` unset to use the Compose default inside the container.
Recreate it with `docker compose up -d`, retaining any USB or other Compose overrides.
Do not supply a host filesystem path as the container's key path.

On each device, open **Account settings → Push notifications**, name the device,
and choose **Enable notifications**. On iPhone/iPad, first install the app on the
Home Screen and launch it from there (iOS/iPadOS 16.4 or later). Permission is requested
only when you choose Enable. If denied, allow notifications in the browser/device
settings and try again. Chrome on Android also supports notifications in a browser tab.
See [WebKit's mobile Web Push requirements](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).

Use **Notification preferences** to select event categories and printers; the same
moderator/admin permissions as personal email subscriptions apply. Each device has
its own preferences, test button, and removal control. You can remove other devices
from your account. Up to 20 devices can be registered per account.

Subscriptions are tied to the sign-in that enabled them. Signing out revokes that
session's push subscriptions; expired or revoked sessions also stop delivery. After
signing in again, enable notifications again if the device is inactive. Account
disabling and permission changes are checked before delivery. A push already handed
to the browser's service can still arrive for up to five minutes; logout also attempts
to unsubscribe the local browser and close its displayed notifications.

The existing outbox retries temporary delivery failures independently per device;
a 404/410 response disables that subscription. Test messages send immediately and
are not retried. The server must be running to send new alerts. A notification tap
opens its app screen (requiring sign-in when necessary), focusing an existing window
at that exact screen if available, without navigating other open editors.

Before relying on push, verify on each supported device and browser: enable,
send a test, close the app and send a real scoped alert,
tap it, then remove the device or sign out and verify that new alerts stop. Also
simulate a connection outage and reopen the previously cached app to check the server-unavailable
screen. Automated tests exercise the API, encrypted payloads, offline worker display,
and links; they do not prove delivery through Apple's or Google's live services.
