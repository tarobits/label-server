# Changelog

## 0.2.0

- Rename the product to Taro's Label Room and add shared branding to sign-in,
  registration, and first-run setup.
- Simplify UI copy and polish forms, editor layouts, and responsive navigation.
- Add accessible inline form validation, keyboard recovery, and larger checkbox
  targets for queue selection, CSV runs, and batch review.
- Fix mobile overflow with long cartridge names, preserve navigation context on
  nested pages, and keep sidebar controls reachable in short windows.
- Improve placeholder contrast, disabled-button feedback, and authentication form
  transitions.

## 0.1.0

Initial release of Label Printer Server.

- Persistent label queues, tape profiles and cartridge consumption tracking.
- USB printer management and distribution groups, with print review and durable
  holds after cancellation, interruptions and access changes.
- Visual label editor, reusable templates, image and font libraries, CSV runs,
  and print requests with approvals.
- User accounts, roles and groups, with administrator access previews.
- Administrator deletion of accounts, templates, images and fonts, including
  referenced content. Deleted content is unavailable immediately and can be
  restored for 30 days before purging. Dependent templates show missing-asset
  placeholders and affected print work remains held for review.
- Durable notifications with administrator-managed ntfy endpoints.
- Native systemd and Docker Compose deployment, plus a release updater that
  backs up data, upgrades dependencies, migrates and verifies service health.
- Version display, cached release notifications and private GitHub token support.

PT-P710BT printing has been verified with one physical printer. Multiple physical
printers and HomeBox integration remain deferred. Cancellation may finish the
current label before stopping subsequent labels.
