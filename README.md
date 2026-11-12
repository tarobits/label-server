# Taro's Label Room

A self-hosted app for designing, sharing and printing labels with Brother
PT-P710BT USB printers.

- Reusable templates with text, images, QR codes, barcodes and optional layout rules.
- Individual labels or spreadsheet imports, with previews before printing.
- Print queues, multiple printers and companion stations on separate computers.
- User accounts, shared templates and approval requests.
- Tape estimates, print costs, repayments and shared group accounts.
- In-app notifications, email and phone alerts.

Supports normal and high-resolution printing. Other printer models and direct
Wi-Fi/Ethernet printing are not currently supported.

For everyday instructions, start with the [user guides](docs/README.md).

## License

Copyright (C) 2026 tarobits and contributors.

Licensed under **AGPL-3.0-or-later**. You may use, self-host, modify and redistribute
the application, including commercially. If you run a modified version for users
over a network, offer them its corresponding source.

See [LICENSE](LICENSE) and [license and attribution guidance](NOTICE.md).
Third-party libraries and bundled fonts retain their own licenses.

This project was designed and directed by Tarobits, with implementation assistance
from OpenAI Codex. AI-generated code has been developed under human direction and
remains subject to review and validation.

## Installation

To use someone else's installation, ask its administrator for the website address.
You can also [add it to your phone or tablet](docs/MOBILE_APP.md).

To host your own server, use a Debian 13+ computer with Python 3.12+ and Git.
Run these commands in its terminal:

```sh
git clone https://github.com/tarobits/label-server.git
cd label-server
sudo ./install.sh
```

The wizard guides you through setup. By default, it installs the latest stable
release into `/opt/labels` and makes it accessible only on that computer.
Follow the [installation and first-run guide](docs/DEPLOYMENT.md#github-installer)
to create your administrator account and configure access from other devices.

For other setups, see [Docker](docs/DEPLOYMENT.md#docker),
[companion stations](docs/COMPANION.md) or [local development](docs/DEVELOPMENT.md).
Once installed, follow [Print your first label](docs/PRINTING.md).

## Upgrading

Run the updater from the installed application's directory
(`/opt/labels` by default):

```sh
cd /opt/labels
sudo ./update.sh
```

The updater uses the default options and runs without prompts. It handles
backups, database changes and service restart. If it replaces its own updater,
rerun `update.sh` to continue.

Native updates download the prebuilt frontend by default. Use `--build-frontend`
to build it locally or `--check` to inspect the plan without making changes.
Existing environment files receive missing defaults
and comments without overwriting your settings; `--no-env-update` skips this.

See [update options and Docker instructions](docs/DEPLOYMENT.md#automated-release-updates)
and the [changelog](CHANGELOG.md) for release changes and exceptional upgrade requirements.

Made with ♥ by Tarobits
