# Remaining work

- Calibrate tape consumption with measured one-label and multi-label batches,
  including feed, leaders, and both cut settings.
- Verify simultaneous printing with two physical USB printers.
- Build and run the Docker image, including USB access in the intended LXC setup.
- Verify the HomeBox print-command bridge in a running HomeBox deployment.
- Investigate native PT-P710BT grayscale support before offering it. Current
  shading uses 1-bit dithering.

Additional printer models and Wi-Fi/Ethernet drivers are future extensions. Their
connection types are defined, but no working drivers are provided.

The editor, automatic-print holds, clipping, automatic sizing, CSV runs and
previews, font/image uploads, multi-printer routing, and account/approval workflows
are implemented. See [PLAN.md](PLAN.md) for constraints,
[access control](docs/ACCESS_CONTROL.md) for permissions, and
[hardware verification](docs/HARDWARE_VERIFICATION.md) for reported print results.
