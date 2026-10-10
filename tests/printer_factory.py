from mock_backend import MockPrinterBackend

from app.printer.factory import configured_printer
from app.printer.registry import MediaKind, PrinterCapabilities, PrinterDefinition


def test_printer(driver, config):
    if driver == "mock":
        return (
            PrinterDefinition(
                "main",
                "Mock printer",
                "mock",
                None,
                PrinterCapabilities(
                    MediaKind.CONTINUOUS,
                    180,
                    180,
                    (3.5, 6, 9, 12, 18, 24),
                    1,
                    resolution_modes={"normal": (180, 180), "high": (360, 180)},
                ),
            ),
            MockPrinterBackend(config.get("mock_width_mm", 24)),
        )
    return configured_printer(driver, config)


class BrowserPrinter(MockPrinterBackend):
    """Production geometry, planning and raster validation with simulated physical I/O."""

    def __init__(self, backend):
        super().__init__()
        self.production = backend

    def plan_batch(self, labels):
        return self.production.plan_batch(labels)

    def estimate_consumption(self, labels):
        return self.production.estimate_consumption(labels)

    def print_batch(self, labels):
        from app.printer.base import PrintNotStarted
        from app.printer.brother import encode_raster

        try:
            for label in labels:
                encode_raster(label)
        except ValueError as error:
            raise PrintNotStarted(str(error)) from error
        return super().print_batch(labels)


def browser_printer(driver, config):
    definition, backend = configured_printer(driver, config)
    return definition, BrowserPrinter(backend)
