# Remaining work

No active TODOs remain for the current single-printer deployment.

Consumption measurements were accepted by the user on 2026-10-17 as within the
margin of measurement error; no repeat measurements are required. The existing
conservative feed and leader defaults are retained. See the
[measurements](docs/HARDWARE_VERIFICATION.md#consumption-calibration).

Stop behavior was accepted on 2026-10-17: finishing the current label and stopping
before the next is sufficient; mid-label interruption is not a requirement.
Physical tests recorded review and automatic-print hold persistence, including
after restart. The last label can remain uncut and needs inspection during review.
Upload cancellation and stop-mode upgrade remain physically unverified, as optional
future checks. See the [stop results](docs/HARDWARE_VERIFICATION.md#stop-controls).

Simultaneous printing with two physical USB printers is deferred until a second
printer is available. Only one printer is currently available.

Native Debian VM deployment verification completed on 2026-10-17: native service
startup, application USB access, physical printing, VM reboot, hold persistence
and USB disconnect/reconnect without a service restart all passed. The HTTP UUID
compatibility fix was deployed and verified. See the
[deployment record](docs/DEPLOYMENT.md#proxmox-vm-usb-access).

Docker image build and isolated local runtime checks passed on 2026-10-17.
Docker USB passthrough remains unverified and is outside the current native-VM
deployment path.

Live HomeBox bridge verification was deferred on 2026-10-17. The current workflow
preference is to create labels manually with the native editor rather than use
HomeBox's rendered-image bridge. Revisit live integration testing when needed.

Native PT-P710BT grayscale investigation completed on 2026-10-17: Brother's
documented raster protocol provides binary pixels and no grayscale mode. Keep
1-bit dithering; revisit native grayscale only if a supported protocol is found.
See the [protocol findings](docs/HARDWARE_VERIFICATION.md#grayscale-protocol-investigation).

Additional printer models and Wi-Fi/Ethernet drivers are future extensions. Their
connection types are defined, but no working drivers are provided.

The editor, automatic-print holds, clipping, automatic sizing, CSV runs and
previews, font/image uploads, multi-printer routing, and account/approval workflows
are implemented. See [PLAN.md](PLAN.md) for constraints,
[access control](docs/ACCESS_CONTROL.md) for permissions, and
[hardware verification](docs/HARDWARE_VERIFICATION.md) for reported print results.
