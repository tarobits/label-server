"""Never release process ownership while a native printer worker is still alive."""

import logging
import os
import time
from collections.abc import Iterable
from threading import Thread


def join_workers(threads: Iterable[Thread], deadline: float) -> None:
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
        if thread.is_alive():
            logging.getLogger(__name__).critical(
                "Companion shutdown deadline exceeded; unfinished printing requires review"
            )
            # No finally blocks may unlock station ownership while hardware work
            # survives. The durable running attempt is recovered on next startup.
            os._exit(1)
