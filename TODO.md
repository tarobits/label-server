# Remaining verification and extensions

Implemented features and usage are documented in [README.md](README.md).
This file tracks gaps in verification and possible extensions, rather than the
status of any individual installation.

## Physical verification still needed

- Simultaneous printing with two physical USB printers, including interruption
  and recovery on one device while the other continues.
- Docker and LXC USB passthrough, permissions, and reconnect behavior.
- Cancellation during raster upload and upgrading graceful stop to emergency stop.
- Live HomeBox bridge submission and retry behavior with an actual deployment.

Automated coverage exists for routing, recovery, stop intent, and bridge retries;
it does not substitute for these physical or integration checks.

## Known limitations

- Stop requests can finish the current label. The last output may remain uncut
  and needs inspection during review; mid-label interruption is not guaranteed.
- Feed and leader consumption remain estimates. The recorded calibration covers
  four single runs at one resolution and feed setting, not statistical repeatability.
- Only the Brother PT-P710BT USB driver is implemented. Additional printer models
  and Wi-Fi/Ethernet drivers require separate implementations and validation.
- The documented raster protocol provides binary pixels, not native grayscale.
  Tonal artwork uses dithering.

See [hardware verification](docs/HARDWARE_VERIFICATION.md) for reported results and
repeatable procedures, [deployment](docs/DEPLOYMENT.md) for setup, and
[PLAN.md](PLAN.md) for implementation constraints.
