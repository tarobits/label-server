# Printer architecture and scope

The Brother PT-P710BT USB implementation remains a required deliverable. Its
protocol research, hardware adapter, chain printing, cutting and measured feed
behavior follow the visual-editor milestone. Nothing in this document removes
that implementation from scope.

Additional models, including shipping-label printers, and Wi-Fi/Ethernet printing
currently require architecture only. No new driver, network connection, discovery
or Wi-Fi provisioning is implemented.

## Boundaries implemented now

`app/printer/registry.py` separates:

- **PrinterDefinition:** stable device ID, human name, driver key, connection and
  media/rendering capabilities. Two identical models can have different IDs.
- **PrinterCapabilities:** continuous or fixed-label media, independent X/Y DPI,
  widths, fixed label sizes, printable margins and cutting/consecutive support.
- **UsbConnection / NetworkConnection:** transport configuration independent of
  the command language. A network endpoint can use Wi-Fi or Ethernet; its IPP,
  IPPS, raw TCP or vendor protocol is explicit. Credentials are references to
  deployment secrets, not values returned in the UI.
- **PrinterRegistry:** multiple definitions, with optional backend instances.
  A registered printer without a driver cannot be obtained as an operational
  backend. Registration never contacts a device.
- **ByteTransport:** future open/write/read/close interface used inside drivers.
  Queue/domain code sees only PrinterBackend, not transport or command bytes.

The application currently registers one operational mock named `main` and exposes
its descriptor at `GET /api/printers`. The renderer/editor derive DPI and margin
from that descriptor. The mock's 180 dpi and 1 mm margin are development values,
not verified Brother printable-area specifications. The first editor supports
continuous labels and square-pixel rendering. Capability fields for fixed media
and asymmetric DPI prepare the next drivers; they do not claim current support.

## Required before enabling multiple operational destinations

1. Persist printer definitions and scope printer state, automatic-print holds,
   jobs, flush requests, batches, review blocks and notification routes to a
   stable printer ID. Migrate existing records to `main` explicitly.
2. Run one serialized physical worker per destination with a shared transaction
   coordinator for SQLite. A printer's uncertain batch must block that printer,
   not unrelated devices. A cartridge can be installed in only one printer.
3. Add destination selection to the UI/API. Validate each job against the chosen
   printer's media kind, printable area and raster resolution. Snapshot those
   capabilities with the job; never reroute queued labels silently.
4. Add fixed-label stock profiles (width/height, gap/black-mark sensing) separately
   from continuous tape cartridges. Feed/leader and remaining-stock estimation
   belong to the relevant adapter and inventory model.
5. Implement concrete transport timeouts, reconnect, status and completion
   semantics for each driver. A socket disconnect after data transmission is an
   uncertain print outcome, just like USB. Never infer completion from write()
   succeeding.
6. Add cross-printer tests for queue isolation, concurrent devices, profile/stock
   compatibility, independent holds/reviews and destination-specific previews.

This blueprint is deliberate: the current queue remains single-printer until
these isolation guarantees are implemented and tested. Shipping-label drivers
must not inherit assumptions about Brother raster bytes, TZe tape or cutting.
